"""Focused SQLite ledger store tests (Task 1.2)."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from canhoto.core.models import (
    AgentViewConfig,
    ClassificationPatch,
    LedgerTransaction,
    StatementRecord,
)
from canhoto.core.redaction import to_review_item
from canhoto.core.store import (
    apply_classifications,
    ensure_schema,
    get_transaction,
    link_statement_transactions,
    list_transactions,
    upsert_statement,
    upsert_transactions,
)

REQUIRED_TABLES = {
    "transactions",
    "statements",
    "statement_transactions",
    "merchant_category_map",
}


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "canhoto.db"
    ensure_schema(path)
    return path


def _tx(
    tx_id: str = "tx-1",
    *,
    month: str = "2026-07",
    amount_minor: int = -4250,
    category: str = "uncategorized",
    kind: str = "expense",
    needs_review: bool = True,
    confidence: float = 0.1,
    description: str = "Cafe Central SP",
    merchant_raw: str = "CAFE CENTRAL",
    merchant_normalized: str | None = "Cafe Central",
    day: int = 15,
) -> LedgerTransaction:
    return LedgerTransaction(
        id=tx_id,
        date=date(2026, 7, day),
        amount_minor=amount_minor,
        currency="BRL",
        description=description,
        merchant_raw=merchant_raw,
        merchant_normalized=merchant_normalized,
        source_kind="card",
        institution="Example Bank",
        source_file="/tmp/stmt.pdf",
        operation_id="op-1",
        category=category,
        kind=kind,
        is_expense=True,
        needs_review=needs_review,
        confidence=confidence,
        review_reason="low_confidence" if needs_review else None,
        month=month,
        metadata={"parser": "fixture"},
    )


def test_schema_creates_four_tables(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with sqlite3.connect(path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert REQUIRED_TABLES <= names


def test_upsert_preserves_classification_on_reingest(tmp_path: Path) -> None:
    path = _db(tmp_path)
    first = _tx(category="uncategorized", kind="expense", needs_review=True, confidence=0.1)
    result = upsert_transactions([first], path=path)
    assert result.inserted == 1
    assert result.updated == 0
    assert result.total == 1

    apply_classifications(
        [
            ClassificationPatch(
                id="tx-1",
                category="Eating",
                kind="expense",
                is_expense=True,
                needs_review=False,
                confidence=0.95,
                review_reason="agent",
                merchant_normalized="CAFE",
            )
        ],
        path=path,
    )

    reingest = _tx(
        description="Cafe Central updated OCR",
        amount_minor=-4300,
        category="SHOULD_NOT_WIN",
        kind="transfer",
        needs_review=True,
        confidence=0.0,
        merchant_raw="CAFE CENTRAL LTD",
        merchant_normalized="SHOULD_NOT_OVERWRITE",
    )
    result2 = upsert_transactions([reingest], path=path)
    assert result2.inserted == 0
    assert result2.updated == 1

    stored = get_transaction("tx-1", path=path)
    assert stored is not None
    assert stored.description == "Cafe Central updated OCR"
    assert stored.amount_minor == -4300
    assert stored.merchant_raw == "CAFE CENTRAL LTD"
    # classification + normalized merchant preserved
    assert stored.category == "Eating"
    assert stored.kind == "expense"
    assert stored.needs_review is False
    assert stored.confidence == 0.95
    assert stored.merchant_normalized == "CAFE"
    assert stored.review_reason == "agent"

    # Explicit null clears review_reason
    apply_classifications(
        [ClassificationPatch(id="tx-1", review_reason=None)],
        path=path,
    )
    cleared = get_transaction("tx-1", path=path)
    assert cleared is not None
    assert cleared.review_reason is None


def test_statement_upsert_and_link_idempotent(tmp_path: Path) -> None:
    path = _db(tmp_path)
    upsert_transactions([_tx("tx-a"), _tx("tx-b", day=16)], path=path)

    stmt = StatementRecord(
        content_hash="hash-abc",
        source_file="/tmp/july.pdf",
        statement_type="card",
        institution="Example Bank",
        meta_json={"period": "2026-07"},
    )
    r1 = upsert_statement(stmt, path=path)
    assert r1.created is True
    assert r1.content_hash == "hash-abc"

    r2 = upsert_statement(
        stmt.model_copy(
            update={
                "source_file": "/moved/july.pdf",
                "meta_json": {"period": "2026-07", "pages": 3},
            }
        ),
        path=path,
    )
    assert r2.created is False

    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT content_hash, source_file, meta_json FROM statements"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "hash-abc"
        assert rows[0][1] == "/moved/july.pdf"
        assert '"pages": 3' in rows[0][2]

    linked1 = link_statement_transactions("hash-abc", ["tx-a", "tx-b"], path=path)
    linked2 = link_statement_transactions("hash-abc", ["tx-a", "tx-b"], path=path)
    assert linked1 == 2
    assert linked2 == 0

    with sqlite3.connect(path) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM statement_transactions WHERE content_hash = ?",
            ("hash-abc",),
        ).fetchone()[0]
    assert n == 2


def test_list_by_month_and_limit(tmp_path: Path) -> None:
    path = _db(tmp_path)
    txs = [
        _tx("a", month="2026-07", day=1),
        _tx("b", month="2026-07", day=2),
        _tx("c", month="2026-08", day=1),
        _tx("d", month="2026-07", day=3),
    ]
    upsert_transactions(txs, path=path)

    july = list_transactions(month="2026-07", path=path)
    assert [t.id for t in july] == ["a", "b", "d"]

    limited = list_transactions(month="2026-07", limit=2, path=path)
    assert [t.id for t in limited] == ["a", "b"]


def test_apply_classifications_reports_missing(tmp_path: Path) -> None:
    path = _db(tmp_path)
    upsert_transactions([_tx("tx-1"), _tx("tx-2", day=16)], path=path)

    result = apply_classifications(
        [
            ClassificationPatch(id="tx-1", category="Transport", needs_review=False),
            ClassificationPatch(id="missing-id", category="Ghost"),
            ClassificationPatch(id="tx-2", kind="income", is_expense=False),
        ],
        path=path,
    )
    assert result.applied == 2
    assert result.missing == ["missing-id"]

    t1 = get_transaction("tx-1", path=path)
    t2 = get_transaction("tx-2", path=path)
    assert t1 is not None and t1.category == "Transport" and t1.needs_review is False
    assert t2 is not None and t2.kind == "income" and t2.is_expense is False


def test_amount_minor_round_trip_and_redaction_compat(tmp_path: Path) -> None:
    path = _db(tmp_path)
    upsert_transactions([_tx(amount_minor=-4250)], path=path)
    stored = get_transaction("tx-1", path=path)
    assert stored is not None
    assert stored.amount_minor == -4250
    assert stored.amount == Decimal("-42.50")

    item = to_review_item(stored, AgentViewConfig())
    assert item.amount == "-42.50"
    assert item.merchant_display == "Cafe Central"
    dumped = item.model_dump()
    for forbidden in (
        "description",
        "source_file",
        "operation_id",
        "metadata",
        "merchant_raw",
        "account_id",
        "amount_minor",
    ):
        assert forbidden not in dumped
