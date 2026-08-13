"""Guardrail tests for redacted review_batch agent output."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from canhoto import service
from canhoto.core import config as core_config
from canhoto.core.models import AgentViewConfig, LedgerTransaction, ReviewItem
from canhoto.core.store import ensure_schema, upsert_transactions

FORBIDDEN_REVIEW_FIELDS = {
    "description",
    "source_file",
    "operation_id",
    "running_balance",
    "account_id",
    "metadata",
    "merchant_raw",
}

CANARY_DESCRIPTION = "CANARY_FULL_DESCRIPTION_LEAK_xyz"
CANARY_SOURCE_FILE = "/home/secret/CANARY_SOURCE_PATH_xyz.pdf"
CANARY_OPERATION_ID = "CANARY_OP_ID_xyz"
CANARY_MERCHANT_RAW = "CANARY_MERCHANT_RAW_xyz"


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
    amount_minor: int = -1500,
    needs_review: bool = True,
    is_expense: bool = True,
    kind: str = "expense",
    category: str = "uncategorized",
    description: str = CANARY_DESCRIPTION,
    merchant_raw: str = CANARY_MERCHANT_RAW,
    merchant_normalized: str | None = "Cafe Central",
    source_file: str = CANARY_SOURCE_FILE,
    operation_id: str | None = CANARY_OPERATION_ID,
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
        institution="Example Bank",
        source_file=source_file,
        operation_id=operation_id,
        category=category,
        kind=kind,
        is_expense=is_expense,
        needs_review=needs_review,
        confidence=0.2,
        review_reason="low_confidence" if needs_review else None,
        month=month,
        metadata={"note": "secret-meta"},
    )


def _seed(data_home: Path, txs: list[LedgerTransaction]) -> Path:
    db = core_config.db_path(data_home)
    ensure_schema(db)
    upsert_transactions(txs, path=db, preserve_classification=False)
    return db


def test_review_batch_requires_month(data_home: Path) -> None:
    with pytest.raises(ValueError, match="month"):
        service.review_batch("")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="YYYY-MM"):
        service.review_batch("2026/06")


def test_review_batch_clamps_limit(data_home: Path) -> None:
    cfg = core_config.load_config(data_home)
    cfg = cfg.model_copy(
        update={
            "agent_view": AgentViewConfig(
                max_batch_size=3,
                absolute_max_batch_size=5,
                expense_only=True,
            )
        }
    )
    core_config.save_config(cfg, root=data_home)

    txs = [
        _tx(f"tx-{i:02d}", day=min(i + 1, 28), merchant_normalized=f"M{i}")
        for i in range(12)
    ]
    _seed(data_home, txs)

    defaulted = service.review_batch("2026-06")
    assert defaulted["count"] == 3
    assert len(defaulted["items"]) == 3

    capped = service.review_batch("2026-06", limit=100)
    assert capped["count"] == 5
    assert len(capped["items"]) == 5
    assert capped["limit"] == 5


def test_review_batch_json_keys_subset_of_review_item(data_home: Path) -> None:
    _seed(
        data_home,
        [
            _tx("tx-a", day=1),
            _tx(
                "tx-income",
                day=2,
                amount_minor=50000,
                is_expense=False,
                kind="income",
                category="Income",
            ),
            _tx("tx-b", day=3),
        ],
    )

    result = service.review_batch("2026-06", limit=10)
    assert result["ok"] is True
    assert "items" in result
    allowed = set(ReviewItem.model_fields)
    for item in result["items"]:
        keys = set(item)
        assert keys <= allowed, f"extra keys in review item: {keys - allowed}"
        assert FORBIDDEN_REVIEW_FIELDS.isdisjoint(keys)
        blob = str(item)
        for canary in (
            CANARY_DESCRIPTION,
            CANARY_SOURCE_FILE,
            CANARY_OPERATION_ID,
            CANARY_MERCHANT_RAW,
            "secret-meta",
        ):
            assert canary not in blob, f"leaked canary: {canary}"


def test_review_batch_expense_only_pending_default(data_home: Path) -> None:
    _seed(
        data_home,
        [
            _tx("tx-exp", day=1, is_expense=True, needs_review=True),
            _tx(
                "tx-income",
                day=2,
                amount_minor=10000,
                is_expense=False,
                kind="income",
                needs_review=True,
            ),
            _tx(
                "tx-done",
                day=3,
                is_expense=True,
                needs_review=False,
                category="Eating",
            ),
        ],
    )
    result = service.review_batch("2026-06")
    ids = [item["id"] for item in result["items"]]
    assert ids == ["tx-exp"]
    assert result["count"] == 1


def test_review_batch_cursor_pagination(data_home: Path) -> None:
    cfg = core_config.load_config(data_home)
    cfg = cfg.model_copy(
        update={
            "agent_view": AgentViewConfig(
                max_batch_size=2,
                absolute_max_batch_size=50,
            )
        }
    )
    core_config.save_config(cfg, root=data_home)
    _seed(
        data_home,
        [
            _tx("tx-01", day=1),
            _tx("tx-02", day=2),
            _tx("tx-03", day=3),
            _tx("tx-04", day=4),
        ],
    )

    page1 = service.review_batch("2026-06", limit=2)
    assert [i["id"] for i in page1["items"]] == ["tx-01", "tx-02"]
    assert page1["next_cursor"] == "tx-02"
    assert page1["count"] == 2

    page2 = service.review_batch("2026-06", cursor=page1["next_cursor"], limit=2)
    assert [i["id"] for i in page2["items"]] == ["tx-03", "tx-04"]
    assert page2.get("next_cursor") is None
    assert page2["count"] == 2


def test_set_categories_applies_patches(data_home: Path) -> None:
    _seed(data_home, [_tx("tx-patch", day=5, needs_review=True)])
    result = service.set_categories(
        [
            {
                "id": "tx-patch",
                "category": "Eating",
                "kind": "expense",
                "is_expense": True,
                "needs_review": False,
                "confidence": 0.95,
                "review_reason": None,
            },
            {"id": "missing-tx", "category": "Others"},
        ]
    )
    assert result["ok"] is True
    assert result["applied"] == 1
    assert result["missing"] == ["missing-tx"]

    # Cleared from pending expense queue.
    pending = service.review_batch("2026-06")
    assert pending["count"] == 0
    assert pending["items"] == []
