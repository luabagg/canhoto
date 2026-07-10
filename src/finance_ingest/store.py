from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from finance_ingest.config import db_path
from finance_ingest.models import (
    BudgetCategory,
    ClassificationPatch,
    MonthlySummary,
    SourceKind,
    Transaction,
    TransactionKind,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY,
  source_kind TEXT NOT NULL,
  source_file TEXT NOT NULL,
  date TEXT NOT NULL,
  description TEXT NOT NULL,
  amount REAL NOT NULL,
  currency TEXT NOT NULL,
  operation_id TEXT,
  running_balance REAL,
  card_last4 TEXT,
  installment TEXT,
  international INTEGER NOT NULL DEFAULT 0,
  merchant_raw TEXT NOT NULL,
  merchant_normalized TEXT,
  category TEXT NOT NULL,
  kind TEXT NOT NULL,
  is_expense INTEGER NOT NULL DEFAULT 0,
  needs_review INTEGER NOT NULL DEFAULT 1,
  confidence REAL NOT NULL DEFAULT 0,
  review_reason TEXT,
  month TEXT NOT NULL,
  billing_cycle TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  pushed_to_sheets INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS statements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_kind TEXT NOT NULL,
  source_file TEXT NOT NULL UNIQUE,
  meta_json TEXT NOT NULL,
  ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _tx_to_row(tx: Transaction) -> tuple:
    return (
        tx.id,
        tx.source_kind.value,
        tx.source_file,
        tx.date.isoformat(),
        tx.description,
        tx.amount,
        tx.currency,
        tx.operation_id,
        tx.running_balance,
        tx.card_last4,
        tx.installment,
        1 if tx.international else 0,
        tx.merchant_raw,
        tx.merchant_normalized,
        tx.category.value,
        tx.kind.value,
        1 if tx.is_expense else 0,
        1 if tx.needs_review else 0,
        tx.confidence,
        tx.review_reason,
        tx.month,
        tx.billing_cycle,
        json.dumps(tx.metadata, ensure_ascii=False),
    )


def _row_to_tx(row: sqlite3.Row) -> Transaction:
    return Transaction(
        id=row["id"],
        source_kind=SourceKind(row["source_kind"]),
        source_file=row["source_file"],
        date=date.fromisoformat(row["date"]),
        description=row["description"],
        amount=row["amount"],
        currency=row["currency"],
        operation_id=row["operation_id"],
        running_balance=row["running_balance"],
        card_last4=row["card_last4"],
        installment=row["installment"],
        international=bool(row["international"]),
        merchant_raw=row["merchant_raw"],
        merchant_normalized=row["merchant_normalized"],
        category=BudgetCategory(row["category"]),
        kind=TransactionKind(row["kind"]),
        is_expense=bool(row["is_expense"]),
        needs_review=bool(row["needs_review"]),
        confidence=row["confidence"],
        review_reason=row["review_reason"],
        month=row["month"],
        billing_cycle=row["billing_cycle"],
        metadata=json.loads(row["metadata"] or "{}"),
    )


def upsert_transactions(txs: list[Transaction], path: Path | None = None) -> dict:
    inserted = updated = 0
    with connect(path) as conn:
        for tx in txs:
            existing = conn.execute(
                "SELECT id FROM transactions WHERE id = ?", (tx.id,)
            ).fetchone()
            row = _tx_to_row(tx)
            if existing:
                conn.execute(
                    """
                    UPDATE transactions SET
                      source_kind=?, source_file=?, date=?, description=?, amount=?,
                      currency=?, operation_id=?, running_balance=?, card_last4=?,
                      installment=?, international=?, merchant_raw=?, merchant_normalized=?,
                      category=?, kind=?, is_expense=?, needs_review=?, confidence=?,
                      review_reason=?, month=?, billing_cycle=?, metadata=?,
                      updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    row[1:] + (tx.id,),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO transactions (
                      id, source_kind, source_file, date, description, amount, currency,
                      operation_id, running_balance, card_last4, installment, international,
                      merchant_raw, merchant_normalized, category, kind, is_expense,
                      needs_review, confidence, review_reason, month, billing_cycle, metadata
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    row,
                )
                inserted += 1
    return {"inserted": inserted, "updated": updated, "total": len(txs)}


def save_statement_meta(source_kind: str, source_file: str, meta_json: str, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO statements (source_kind, source_file, meta_json)
            VALUES (?, ?, ?)
            ON CONFLICT(source_file) DO UPDATE SET meta_json=excluded.meta_json, ingested_at=CURRENT_TIMESTAMP
            """,
            (source_kind, source_file, meta_json),
        )


def list_transactions(
    month: str | None = None,
    needs_review: bool | None = None,
    source_kind: str | None = None,
    limit: int = 500,
    path: Path | None = None,
) -> list[Transaction]:
    clauses: list[str] = []
    args: list = []
    if month:
        clauses.append("month = ?")
        args.append(month)
    if needs_review is not None:
        clauses.append("needs_review = ?")
        args.append(1 if needs_review else 0)
    if source_kind:
        clauses.append("source_kind = ?")
        args.append(source_kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM transactions {where} ORDER BY date ASC, id ASC LIMIT ?"
    args.append(limit)
    with connect(path) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_tx(r) for r in rows]


def apply_classifications(patches: list[ClassificationPatch], path: Path | None = None) -> dict:
    applied = 0
    missing: list[str] = []
    with connect(path) as conn:
        for p in patches:
            row = conn.execute("SELECT * FROM transactions WHERE id = ?", (p.id,)).fetchone()
            if not row:
                missing.append(p.id)
                continue
            tx = _row_to_tx(row)
            if p.merchant_normalized is not None:
                tx.merchant_normalized = p.merchant_normalized
            if p.category is not None:
                tx.category = p.category
            if p.kind is not None:
                tx.kind = p.kind
            if p.is_expense is not None:
                tx.is_expense = p.is_expense
            if p.needs_review is not None:
                tx.needs_review = p.needs_review
            if p.confidence is not None:
                tx.confidence = p.confidence
            if p.review_reason is not None:
                tx.review_reason = p.review_reason
            conn.execute(
                """
                UPDATE transactions SET
                  merchant_normalized=?, category=?, kind=?, is_expense=?,
                  needs_review=?, confidence=?, review_reason=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    tx.merchant_normalized,
                    tx.category.value,
                    tx.kind.value,
                    1 if tx.is_expense else 0,
                    1 if tx.needs_review else 0,
                    tx.confidence,
                    tx.review_reason,
                    tx.id,
                ),
            )
            applied += 1
    return {"applied": applied, "missing": missing}


def replace_transactions(txs: list[Transaction], path: Path | None = None) -> None:
    """Full overwrite of given IDs (used after rule categorization)."""
    upsert_transactions(txs, path=path)


def mark_pushed(ids: list[str], path: Path | None = None) -> int:
    if not ids:
        return 0
    with connect(path) as conn:
        conn.executemany(
            "UPDATE transactions SET pushed_to_sheets=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [(i,) for i in ids],
        )
    return len(ids)


def monthly_summary(month: str, path: Path | None = None) -> MonthlySummary:
    txs = list_transactions(month=month, limit=10000, path=path)
    income = 0.0
    expenses = 0.0
    by_cat: dict[str, float] = {}
    transfers = 0.0
    card_payments = 0.0
    pending = 0
    for tx in txs:
        if tx.needs_review:
            pending += 1
        if tx.kind in {
            TransactionKind.INTERNAL_TRANSFER,
            TransactionKind.PIGGY_RESERVE,
            TransactionKind.SELF_TRANSFER,
        }:
            transfers += abs(tx.amount)
            continue
        if tx.kind is TransactionKind.CARD_PAYMENT:
            card_payments += abs(tx.amount)
            continue
        if tx.kind is TransactionKind.INCOME or tx.amount > 0 and not tx.is_expense:
            income += abs(tx.amount)
            continue
        if tx.is_expense or tx.amount < 0:
            amt = abs(tx.amount)
            expenses += amt
            key = tx.category.value
            by_cat[key] = by_cat.get(key, 0.0) + amt
    return MonthlySummary(
        month=month,
        income=round(income, 2),
        expenses=round(expenses, 2),
        net=round(income - expenses, 2),
        by_category={k: round(v, 2) for k, v in sorted(by_cat.items())},
        transfers_excluded=round(transfers, 2),
        card_payments_excluded=round(card_payments, 2),
        pending_review=pending,
        transaction_count=len(txs),
    )
