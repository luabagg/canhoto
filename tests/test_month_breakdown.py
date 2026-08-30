"""Month breakdown aggregate tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from canhoto import service
from canhoto.cli import main as cli_main
from canhoto.core import config as core_config
from canhoto.core.models import LedgerTransaction, MonthBreakdown
from canhoto.core.store import ensure_schema, upsert_transactions


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    core_config.init_data_dir(root)
    return root


def _tx(
    tx_id: str,
    *,
    month: str = "2026-06",
    day: int = 10,
    amount_minor: int = -2500,
    needs_review: bool = False,
    is_expense: bool = True,
    kind: str = "expense",
    category: str = "Eating",
    source_kind: str = "card",
    description: str = "Cafe",
) -> LedgerTransaction:
    return LedgerTransaction(
        id=tx_id,
        date=date(2026, 6, day),
        amount_minor=amount_minor,
        currency="BRL",
        description=description,
        merchant_raw=description,
        merchant_normalized=description,
        source_kind=source_kind,
        institution="Bank",
        source_file="/secret/path.pdf",
        operation_id="op-secret",
        category=category,
        kind=kind,
        is_expense=is_expense,
        needs_review=needs_review,
        confidence=0.9,
        review_reason="needs_human" if needs_review else None,
        month=month,
        metadata={"secret": True},
    )


def _seed(data_home: Path, txs: list[LedgerTransaction]) -> None:
    db = core_config.db_path(data_home)
    ensure_schema(db)
    upsert_transactions(txs, path=db, preserve_classification=False)


def test_month_breakdown_aggregates_only(data_home: Path) -> None:
    _seed(
        data_home,
        [
            # Card spend — counts as expense
            _tx(
                "e1",
                day=1,
                amount_minor=-5000,
                category="Eating",
                kind="expense",
                is_expense=True,
            ),
            _tx(
                "e2",
                day=2,
                amount_minor=-20050,
                category="Groceries",
                kind="expense",
                is_expense=True,
            ),
            # Income
            _tx(
                "i1",
                day=3,
                amount_minor=100000,
                category="income",
                kind="income",
                is_expense=False,
                source_kind="account",
            ),
            # Excluded from spend
            _tx(
                "cp",
                day=4,
                amount_minor=-150000,
                category="transfer",
                kind="card_payment",
                is_expense=False,
                source_kind="account",
            ),
            _tx(
                "st",
                day=5,
                amount_minor=-20000,
                category="transfer",
                kind="self_transfer",
                is_expense=False,
                source_kind="account",
            ),
            _tx(
                "it",
                day=6,
                amount_minor=-10000,
                category="transfer",
                kind="internal_transfer",
                is_expense=False,
                source_kind="account",
            ),
            # Generic transfers, including positive wallet/account movements,
            # must not be treated as income.
            _tx(
                "transfer",
                day=6,
                amount_minor=250000,
                category="transfer",
                kind="transfer",
                is_expense=False,
                source_kind="account",
            ),
            # Pending review expense
            _tx(
                "pr",
                day=7,
                amount_minor=-1000,
                category="uncategorized",
                kind="expense",
                is_expense=True,
                needs_review=True,
            ),
            # Other month — ignored
            _tx("other", month="2026-05", day=1, amount_minor=-99999, category="Eating"),
        ],
    )

    result = service.month_breakdown("2026-06")
    assert result["ok"] is True
    assert set(result["breakdown"].keys()) == set(MonthBreakdown.model_fields)
    assert "transactions" not in result["breakdown"]
    assert "items" not in result["breakdown"]
    assert "rows" not in result["breakdown"]

    bd = MonthBreakdown.model_validate(result["breakdown"])
    assert bd.month == "2026-06"
    assert bd.income == "1000.00"
    # 50.00 + 200.50 + 10.00 (pending uncategorized) = 260.50
    assert bd.expenses == "260.50"
    assert bd.net == "739.50"
    assert bd.by_category == {
        "Eating": "50.00",
        "Groceries": "200.50",
        "uncategorized": "10.00",
    }
    assert bd.pending_review == 1
    assert bd.transaction_count == 8
    assert bd.expense_count == 3

    # No merchant rollups, no secret leakage in the aggregate payload.
    blob = json.dumps(result)
    assert "merchant" not in blob.lower() or "by_merchant" not in blob
    assert "/secret/path.pdf" not in blob
    assert "op-secret" not in blob


def test_month_breakdown_card_spend_counts_even_if_kind_empty(data_home: Path) -> None:
    """Card purchases with is_expense true count; positive account inflow counts as income."""
    _seed(
        data_home,
        [
            _tx(
                "card1",
                amount_minor=-1234,
                category="Shopping",
                kind="",
                is_expense=True,
                source_kind="card",
            ),
            _tx(
                "inc",
                amount_minor=5000,
                category="",
                kind="",
                is_expense=False,
                source_kind="account",
                description="SALARIO",
            ),
        ],
    )
    result = service.month_breakdown("2026-06")
    bd = MonthBreakdown.model_validate(result["breakdown"])
    assert bd.expenses == "12.34"
    assert bd.income == "50.00"
    assert bd.net == "37.66"
    assert bd.by_category == {"Shopping": "12.34"}
    assert bd.expense_count == 1
    assert bd.transaction_count == 2


def test_month_breakdown_requires_valid_month(data_home: Path) -> None:
    with pytest.raises(ValueError, match="month"):
        service.month_breakdown("2026-13")
    with pytest.raises(ValueError, match="month"):
        service.month_breakdown("")


def test_month_breakdown_respects_allow_aggregates(data_home: Path) -> None:
    cfg = core_config.load_config(data_home)
    cfg = cfg.model_copy(
        update={
            "agent_view": cfg.agent_view.model_copy(update={"allow_aggregates": False}),
        }
    )
    core_config.save_config(cfg, root=data_home)
    with pytest.raises(PermissionError, match="allow_aggregates"):
        service.month_breakdown("2026-06")


def test_cli_breakdown_json(data_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(
        data_home,
        [
            _tx("e1", amount_minor=-1000, category="Eating"),
            _tx(
                "i1",
                amount_minor=50000,
                category="income",
                kind="income",
                is_expense=False,
                source_kind="account",
            ),
        ],
    )
    assert cli_main(["breakdown", "--month", "2026-06"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert set(payload["breakdown"].keys()) == set(MonthBreakdown.model_fields)
    assert "transactions" not in payload["breakdown"]
    bd = payload["breakdown"]
    assert bd["month"] == "2026-06"
    assert bd["income"] == "500.00"
    assert bd["expenses"] == "10.00"
    assert bd["net"] == "490.00"
    assert bd["by_category"] == {"Eating": "10.00"}
    assert bd["transaction_count"] == 2
    assert bd["expense_count"] == 1


def test_cli_breakdown_requires_month(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["breakdown"])
    assert excinfo.value.code == 2
