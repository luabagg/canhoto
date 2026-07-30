"""Focused review batch + category patch tests (Task 4.2)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from canhoto.cli import main as cli_main
from canhoto.core import config as core_config
from canhoto.core.models import LedgerTransaction, ReviewItem
from canhoto.core.store import ensure_schema, get_transaction, upsert_transactions


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
    needs_review: bool = True,
    is_expense: bool = True,
    kind: str = "expense",
    category: str = "",
    description: str = "SECRET DESCRIPTION LEAK",
    merchant_raw: str = "RAW MERCHANT SECRET",
    merchant_normalized: str | None = "Cafe",
) -> LedgerTransaction:
    return LedgerTransaction(
        id=tx_id,
        date=date(2026, 6, day),
        amount_minor=amount_minor,
        currency="BRL",
        description=description,
        merchant_raw=merchant_raw,
        merchant_normalized=merchant_normalized,
        source_kind="card",
        institution="Bank",
        source_file="/secret/path.pdf",
        operation_id="op-secret",
        category=category,
        kind=kind,
        is_expense=is_expense,
        needs_review=needs_review,
        confidence=0.3,
        review_reason="needs_human" if needs_review else None,
        month=month,
        metadata={"secret": True},
    )


def _seed(data_home: Path, txs: list[LedgerTransaction]) -> None:
    db = core_config.db_path(data_home)
    ensure_schema(db)
    upsert_transactions(txs, path=db, preserve_classification=False)


def test_cli_review_json_redacted(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(data_home, [_tx("tx-1", day=1), _tx("tx-2", day=2)])
    assert cli_main(["review", "--month", "2026-06", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["month"] == "2026-06"
    assert payload["count"] == 2
    allowed = set(ReviewItem.model_fields)
    for item in payload["items"]:
        assert set(item) <= allowed
        blob = json.dumps(item)
        assert "SECRET DESCRIPTION" not in blob
        assert "/secret/path.pdf" not in blob
        assert "op-secret" not in blob
        assert "RAW MERCHANT SECRET" not in blob


def test_cli_review_requires_month(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["review"])
    assert excinfo.value.code == 2


def test_cli_categorize_apply_file(
    data_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(data_home, [_tx("tx-apply", day=4)])
    patches_path = tmp_path / "patches.json"
    patches_path.write_text(
        json.dumps(
            [
                {
                    "id": "tx-apply",
                    "category": "Eating",
                    "kind": "expense",
                    "is_expense": True,
                    "needs_review": False,
                    "confidence": 0.9,
                }
            ]
        ),
        encoding="utf-8",
    )
    assert cli_main(["categorize", "apply", "--file", str(patches_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["applied"] == 1
    assert payload["missing"] == []

    stored = get_transaction("tx-apply", path=core_config.db_path(data_home))
    assert stored is not None
    assert stored.category == "Eating"
    assert stored.needs_review is False
    assert stored.confidence == 0.9
