"""Month index: aggregates only, and no database until one exists."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from canhoto import service
from canhoto.core.config import db_path, init_data_dir
from canhoto.core.models import LedgerTransaction
from canhoto.core.store import ensure_schema, list_months, upsert_transactions


def test_list_months_groups_counts(tmp_path: Path) -> None:
    path = tmp_path / "canhoto.db"
    ensure_schema(path)
    upsert_transactions(
        [
            _tx("a", month="2026-07", needs_review=True),
            _tx("b", month="2026-07", needs_review=False),
            _tx("c", month="2026-06", needs_review=True),
        ],
        path=path,
    )

    rows = list_months(path=path)

    assert rows == [
        {"month": "2026-07", "transaction_count": 2, "pending_review": 1},
        {"month": "2026-06", "transaction_count": 1, "pending_review": 1},
    ]


def test_service_list_months_does_not_create_db(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    init_data_dir(root)

    payload = service.list_months()

    assert payload["months"] == []
    assert not db_path(root).exists()


def _tx(tx_id: str, *, month: str, needs_review: bool) -> LedgerTransaction:
    year, month_num = (int(part) for part in month.split("-"))
    return LedgerTransaction(
        id=tx_id,
        date=date(year, month_num, 2),
        amount_minor=-100,
        currency="BRL",
        description="x",
        merchant_raw="Shop",
        source_kind="card",
        category="",
        kind="expense",
        is_expense=True,
        needs_review=needs_review,
        month=month,
    )
