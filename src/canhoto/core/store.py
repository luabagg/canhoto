"""SQLite ledger store — internal system of record.

Returns full ``LedgerTransaction`` rows for service/pipeline use only.
Agent surfaces must project through redaction/policy, never serialize store rows.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from canhoto.core.config import db_path
from canhoto.core.models import (
    ClassificationPatch,
    ClassificationResult,
    LedgerTransaction,
    StatementRecord,
    StatementUpsertResult,
    UpsertResult,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  merchant_raw TEXT NOT NULL DEFAULT '',
  merchant_normalized TEXT,
  source_kind TEXT NOT NULL,
  institution TEXT,
  source_file TEXT,
  operation_id TEXT,
  running_balance_minor INTEGER,
  account_id TEXT,
  category TEXT NOT NULL,
  kind TEXT NOT NULL,
  is_expense INTEGER NOT NULL DEFAULT 0,
  needs_review INTEGER NOT NULL DEFAULT 1,
  confidence REAL NOT NULL DEFAULT 0,
  review_reason TEXT,
  installment TEXT,
  month TEXT NOT NULL,
  billing_cycle TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS statements (
  content_hash TEXT PRIMARY KEY,
  source_file TEXT NOT NULL,
  statement_type TEXT NOT NULL,
  institution TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}',
  ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS statement_transactions (
  content_hash TEXT NOT NULL,
  transaction_id TEXT NOT NULL,
  PRIMARY KEY (content_hash, transaction_id),
  FOREIGN KEY (content_hash) REFERENCES statements(content_hash),
  FOREIGN KEY (transaction_id) REFERENCES transactions(id)
);

CREATE TABLE IF NOT EXISTS merchant_category_map (
  merchant_key TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_month ON transactions(month);
CREATE INDEX IF NOT EXISTS idx_transactions_needs_review ON transactions(needs_review);
CREATE INDEX IF NOT EXISTS idx_transactions_month_review ON transactions(month, needs_review);
"""

# Classification columns preserved on same-id re-ingest (facts-only refresh).
_CLASSIFICATION_COLS = (
    "category",
    "kind",
    "is_expense",
    "needs_review",
    "confidence",
    "review_reason",
)


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open canhoto.db, ensure schema, yield a Row-factory connection."""
    p = path if path is not None else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript(SCHEMA)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def ensure_schema(path: Path | None = None) -> None:
    """Create tables/indexes if missing."""
    with connect(path):
        pass


def _tx_to_params(tx: LedgerTransaction) -> dict[str, object]:
    return {
        "id": tx.id,
        "date": tx.date.isoformat(),
        "amount_minor": tx.amount_minor,
        "currency": tx.currency,
        "description": tx.description,
        "merchant_raw": tx.merchant_raw,
        "merchant_normalized": tx.merchant_normalized,
        "source_kind": tx.source_kind,
        "institution": tx.institution,
        "source_file": tx.source_file,
        "operation_id": tx.operation_id,
        "running_balance_minor": tx.running_balance_minor,
        "account_id": tx.account_id,
        "category": tx.category,
        "kind": tx.kind,
        "is_expense": 1 if tx.is_expense else 0,
        "needs_review": 1 if tx.needs_review else 0,
        "confidence": tx.confidence,
        "review_reason": tx.review_reason,
        "installment": tx.installment,
        "month": tx.month,
        "billing_cycle": tx.billing_cycle,
        "metadata": json.dumps(tx.metadata, ensure_ascii=False),
    }


def _row_to_tx(row: sqlite3.Row) -> LedgerTransaction:
    meta_raw = row["metadata"] or "{}"
    metadata = json.loads(meta_raw) if isinstance(meta_raw, str) else dict(meta_raw)
    return LedgerTransaction(
        id=row["id"],
        date=date.fromisoformat(row["date"]),
        amount_minor=int(row["amount_minor"]),
        currency=row["currency"],
        description=row["description"] or "",
        merchant_raw=row["merchant_raw"] or "",
        merchant_normalized=row["merchant_normalized"],
        source_kind=row["source_kind"],
        institution=row["institution"],
        source_file=row["source_file"],
        operation_id=row["operation_id"],
        running_balance_minor=(
            int(row["running_balance_minor"])
            if row["running_balance_minor"] is not None
            else None
        ),
        account_id=row["account_id"],
        category=row["category"] or "",
        kind=row["kind"] or "",
        is_expense=bool(row["is_expense"]),
        needs_review=bool(row["needs_review"]),
        confidence=float(row["confidence"] or 0.0),
        review_reason=row["review_reason"],
        installment=row["installment"],
        month=row["month"],
        billing_cycle=row["billing_cycle"],
        metadata=metadata,
    )


def upsert_transactions(
    txs: list[LedgerTransaction],
    *,
    path: Path | None = None,
    preserve_classification: bool = True,
) -> UpsertResult:
    """Insert or update ledger rows by stable transaction id.

    On conflict, always refreshes parser/normalized facts. When
    ``preserve_classification`` is True (default), existing classification
    columns are left unchanged so re-ingest does not wipe reviews.
    """
    with connect(path) as conn:
        return _upsert_transactions(
            conn, txs, preserve_classification=preserve_classification
        )


def _upsert_transactions(
    conn: sqlite3.Connection,
    txs: list[LedgerTransaction],
    *,
    preserve_classification: bool,
) -> UpsertResult:
    inserted = 0
    updated = 0
    for tx in txs:
        existing = conn.execute(
            "SELECT id FROM transactions WHERE id = ?", (tx.id,)
        ).fetchone()
        params = _tx_to_params(tx)
        if existing is None:
            conn.execute(
                """
                INSERT INTO transactions (
                  id, date, amount_minor, currency, description,
                  merchant_raw, merchant_normalized, source_kind, institution,
                  source_file, operation_id, running_balance_minor, account_id,
                  category, kind, is_expense, needs_review, confidence,
                  review_reason, installment, month, billing_cycle, metadata
                ) VALUES (
                  :id, :date, :amount_minor, :currency, :description,
                  :merchant_raw, :merchant_normalized, :source_kind, :institution,
                  :source_file, :operation_id, :running_balance_minor, :account_id,
                  :category, :kind, :is_expense, :needs_review, :confidence,
                  :review_reason, :installment, :month, :billing_cycle, :metadata
                )
                """,
                params,
            )
            inserted += 1
            continue

        if preserve_classification:
            conn.execute(
                """
                UPDATE transactions SET
                  date = :date,
                  amount_minor = :amount_minor,
                  currency = :currency,
                  description = :description,
                  merchant_raw = :merchant_raw,
                  merchant_normalized = :merchant_normalized,
                  source_kind = :source_kind,
                  institution = :institution,
                  source_file = :source_file,
                  operation_id = :operation_id,
                  running_balance_minor = :running_balance_minor,
                  account_id = :account_id,
                  installment = :installment,
                  month = :month,
                  billing_cycle = :billing_cycle,
                  metadata = :metadata,
                  updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """,
                params,
            )
        else:
            conn.execute(
                """
                UPDATE transactions SET
                  date = :date,
                  amount_minor = :amount_minor,
                  currency = :currency,
                  description = :description,
                  merchant_raw = :merchant_raw,
                  merchant_normalized = :merchant_normalized,
                  source_kind = :source_kind,
                  institution = :institution,
                  source_file = :source_file,
                  operation_id = :operation_id,
                  running_balance_minor = :running_balance_minor,
                  account_id = :account_id,
                  category = :category,
                  kind = :kind,
                  is_expense = :is_expense,
                  needs_review = :needs_review,
                  confidence = :confidence,
                  review_reason = :review_reason,
                  installment = :installment,
                  month = :month,
                  billing_cycle = :billing_cycle,
                  metadata = :metadata,
                  updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """,
                params,
            )
        updated += 1
    return UpsertResult(inserted=inserted, updated=updated, total=len(txs))


def upsert_statement(
    statement: StatementRecord,
    *,
    path: Path | None = None,
) -> StatementUpsertResult:
    """Idempotent statement upsert keyed by ``content_hash``."""
    with connect(path) as conn:
        return _upsert_statement(conn, statement)


def _upsert_statement(
    conn: sqlite3.Connection, statement: StatementRecord
) -> StatementUpsertResult:
    existing = conn.execute(
        "SELECT content_hash FROM statements WHERE content_hash = ?",
        (statement.content_hash,),
    ).fetchone()
    meta_json = json.dumps(statement.meta_json, ensure_ascii=False)
    if existing is None:
        conn.execute(
            """
            INSERT INTO statements (
              content_hash, source_file, statement_type, institution, meta_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                statement.content_hash,
                statement.source_file,
                statement.statement_type,
                statement.institution,
                meta_json,
            ),
        )
        return StatementUpsertResult(
            created=True, content_hash=statement.content_hash, linked=0
        )

    conn.execute(
        """
        UPDATE statements SET
          source_file = ?,
          statement_type = ?,
          institution = ?,
          meta_json = ?,
          ingested_at = CURRENT_TIMESTAMP
        WHERE content_hash = ?
        """,
        (
            statement.source_file,
            statement.statement_type,
            statement.institution,
            meta_json,
            statement.content_hash,
        ),
    )
    return StatementUpsertResult(
        created=False, content_hash=statement.content_hash, linked=0
    )


def link_statement_transactions(
    content_hash: str,
    tx_ids: list[str],
    *,
    path: Path | None = None,
) -> int:
    """Link statement ↔ transactions; INSERT OR IGNORE (idempotent). Returns new links."""
    with connect(path) as conn:
        return _link_statement_transactions(conn, content_hash, tx_ids)


def _link_statement_transactions(
    conn: sqlite3.Connection, content_hash: str, tx_ids: list[str]
) -> int:
    linked = 0
    for tx_id in tx_ids:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO statement_transactions (content_hash, transaction_id)
            VALUES (?, ?)
            """,
            (content_hash, tx_id),
        )
        linked += cur.rowcount
    return linked


def save_statement_with_transactions(
    statement: StatementRecord,
    txs: list[LedgerTransaction],
    *,
    path: Path | None = None,
    preserve_classification: bool = True,
) -> tuple[UpsertResult, StatementUpsertResult]:
    """Atomic convenience: upsert txs, upsert statement, link ids."""
    with connect(path) as conn:
        upsert = _upsert_transactions(
            conn, txs, preserve_classification=preserve_classification
        )
        stmt_result = _upsert_statement(conn, statement)
        linked = _link_statement_transactions(
            conn, statement.content_hash, [tx.id for tx in txs]
        )
        stmt_result = StatementUpsertResult(
            created=stmt_result.created,
            content_hash=stmt_result.content_hash,
            linked=linked,
        )
        return upsert, stmt_result


def list_transactions(
    *,
    month: str | None = None,
    needs_review: bool | None = None,
    source_kind: str | None = None,
    limit: int = 500,
    path: Path | None = None,
) -> list[LedgerTransaction]:
    """List ledger rows with optional filters. Always ordered and limited."""
    if limit <= 0:
        raise ValueError("limit must be a positive integer")
    clauses: list[str] = []
    args: list[object] = []
    if month is not None:
        clauses.append("month = ?")
        args.append(month)
    if needs_review is not None:
        clauses.append("needs_review = ?")
        args.append(1 if needs_review else 0)
    if source_kind is not None:
        clauses.append("source_kind = ?")
        args.append(source_kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM transactions {where} ORDER BY date ASC, id ASC LIMIT ?"
    args.append(limit)
    with connect(path) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_tx(r) for r in rows]


def get_transaction(tx_id: str, *, path: Path | None = None) -> LedgerTransaction | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (tx_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_tx(row)


def apply_classifications(
    patches: list[ClassificationPatch],
    *,
    path: Path | None = None,
) -> ClassificationResult:
    """Apply classification-only updates. Unknown ids are reported in ``missing``."""
    applied = 0
    missing: list[str] = []
    with connect(path) as conn:
        for patch in patches:
            row = conn.execute(
                "SELECT * FROM transactions WHERE id = ?", (patch.id,)
            ).fetchone()
            if row is None:
                missing.append(patch.id)
                continue
            updates: list[str] = []
            params: list[object] = []
            if patch.category is not None:
                updates.append("category = ?")
                params.append(patch.category)
            if patch.kind is not None:
                updates.append("kind = ?")
                params.append(patch.kind)
            if patch.is_expense is not None:
                updates.append("is_expense = ?")
                params.append(1 if patch.is_expense else 0)
            if patch.needs_review is not None:
                updates.append("needs_review = ?")
                params.append(1 if patch.needs_review else 0)
            if patch.confidence is not None:
                updates.append("confidence = ?")
                params.append(patch.confidence)
            if patch.review_reason is not None:
                updates.append("review_reason = ?")
                params.append(patch.review_reason)
            if patch.merchant_normalized is not None:
                updates.append("merchant_normalized = ?")
                params.append(patch.merchant_normalized)
            if not updates:
                applied += 1
                continue
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(patch.id)
            conn.execute(
                f"UPDATE transactions SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            applied += 1
    return ClassificationResult(applied=applied, missing=missing)


def count_pending_review(
    month: str | None = None, *, path: Path | None = None
) -> int:
    clauses = ["needs_review = 1"]
    args: list[object] = []
    if month is not None:
        clauses.append("month = ?")
        args.append(month)
    sql = f"SELECT COUNT(*) AS n FROM transactions WHERE {' AND '.join(clauses)}"
    with connect(path) as conn:
        row = conn.execute(sql, args).fetchone()
    return int(row["n"])


def get_merchant_category(
    merchant_key: str, *, path: Path | None = None
) -> str | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT category FROM merchant_category_map WHERE merchant_key = ?",
            (merchant_key,),
        ).fetchone()
    if row is None:
        return None
    return str(row["category"])


def set_merchant_category(
    merchant_key: str, category: str, *, path: Path | None = None
) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO merchant_category_map (merchant_key, category, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(merchant_key) DO UPDATE SET
              category = excluded.category,
              updated_at = CURRENT_TIMESTAMP
            """,
            (merchant_key, category),
        )


__all__ = [
    "SCHEMA",
    "apply_classifications",
    "connect",
    "count_pending_review",
    "ensure_schema",
    "get_merchant_category",
    "get_transaction",
    "link_statement_transactions",
    "list_transactions",
    "save_statement_with_transactions",
    "set_merchant_category",
    "upsert_statement",
    "upsert_transactions",
]
