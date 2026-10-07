"""Manual transactions: ledger rows that no statement shows.

Example: a Pix sent straight from a savings reserve never appears on the
account statement. The owner adds it by hand. Only manual rows can be edited or
removed; statement rows change only through re-ingest and classification.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from canhoto.core.models import USER_RULE_KINDS, LedgerTransaction
from canhoto.core.user_rules import amount_bound_to_minor

SOURCE_KIND = "manual"


def parse_date(text: str) -> date:
    """Parse ``YYYY-MM-DD``; any other shape raises ``ValueError``."""
    return datetime.strptime(text, "%Y-%m-%d").date()


def parse_signed_amount(text: str) -> int:
    """Parse signed major units ("-3080.00" is money out) to minor units."""
    stripped = text.strip()
    magnitude = amount_bound_to_minor(stripped.removeprefix("-").removeprefix("+"))
    if not magnitude:
        raise ValueError(f"amount must not be zero: {text!r}")
    return -magnitude if stripped.startswith("-") else magnitude


def new_transaction(
    *,
    tx_date: date,
    amount_minor: int,
    description: str,
    kind: str | None,
    merchant: str | None,
    account: str | None,
    institution: str | None,
    note: str,
) -> LedgerTransaction:
    """Build an unclassified manual row with a fresh id."""
    desc = _require_text(description, "description")
    tx_kind = normalize_kind(kind) if kind is not None else _default_kind(amount_minor)
    metadata: dict[str, Any] = {"note": note.strip()} if note.strip() else {}
    if merchant is not None:
        metadata["manual_merchant"] = True
    if kind is not None:
        metadata["manual_kind"] = tx_kind
    return LedgerTransaction(
        id=f"manual-{uuid.uuid4().hex[:12]}",
        date=tx_date,
        amount_minor=amount_minor,
        currency="BRL",
        description=desc,
        merchant_raw=desc,
        merchant_normalized=merchant,
        source_kind=SOURCE_KIND,
        institution=institution,
        account_id=account,
        month=tx_date.strftime("%Y-%m"),
        kind=tx_kind,
        is_expense=tx_kind == "expense",
        metadata=metadata,
    )


def classify_by_hand(tx: LedgerTransaction, category: str) -> LedgerTransaction:
    return tx.model_copy(
        update={
            "category": _require_text(category, "category"),
            "needs_review": False,
            "review_reason": None,
            "confidence": 1.0,
            "classification_source": "manual",
            "user_rule_id": None,
        }
    )


def is_same_entry(a: LedgerTransaction, b: LedgerTransaction) -> bool:
    """Same date, amount, description, and account: a second add is a mistake."""
    return (a.date, a.amount_minor, a.description, a.account_id) == (
        b.date,
        b.amount_minor,
        b.description,
        b.account_id,
    )


def edit_transaction(
    tx: LedgerTransaction,
    *,
    tx_date: date | None,
    amount_minor: int | None,
    description: str | None,
    kind: str | None,
    merchant: str | None,
    account: str | None,
    note: str | None,
) -> LedgerTransaction:
    """Return ``tx`` with the given facts replaced. ``None`` keeps a field."""
    update: dict[str, Any] = {}
    metadata = dict(tx.metadata)
    if tx_date is not None:
        update["date"] = tx_date
        update["month"] = tx_date.strftime("%Y-%m")
    if amount_minor is not None:
        update["amount_minor"] = amount_minor
        if kind is None and "manual_kind" not in metadata:
            update["kind"] = _default_kind(amount_minor)
            update["is_expense"] = update["kind"] == "expense"
    if description is not None:
        desc = _require_text(description, "description")
        update["description"] = desc
        update["merchant_raw"] = desc
        if desc != tx.description and not metadata.get("manual_merchant"):
            update["merchant_normalized"] = None
    if kind is not None:
        update["kind"] = normalize_kind(kind)
        update["is_expense"] = update["kind"] == "expense"
        metadata["manual_kind"] = update["kind"]
    if merchant is not None:
        update["merchant_normalized"] = merchant
        metadata["manual_merchant"] = True
    if account is not None:
        update["account_id"] = account
    if note is not None:
        metadata["note"] = note.strip()
    edited = tx.model_copy(update={**update, "metadata": metadata})
    facts_changed = any(getattr(tx, field) != value for field, value in update.items())
    if facts_changed and tx.classification_source != "manual":
        return _reset_classification(edited)
    return edited


def _reset_classification(tx: LedgerTransaction) -> LedgerTransaction:
    kind = tx.metadata.get("manual_kind", _default_kind(tx.amount_minor))
    return tx.model_copy(
        update={
            "category": "",
            "kind": kind,
            "is_expense": kind == "expense",
            "needs_review": True,
            "confidence": 0.0,
            "review_reason": None,
            "classification_source": "parser",
            "user_rule_id": None,
        }
    )


def require_manual(tx: LedgerTransaction | None, tx_id: str) -> LedgerTransaction:
    if tx is None:
        raise ValueError(f"no transaction with id {tx_id!r}")
    if tx.source_kind != SOURCE_KIND:
        raise ValueError(
            f"{tx_id!r} is not a manual transaction; statement rows change only by re-ingest"
        )
    return tx


def _default_kind(amount_minor: int) -> str:
    return "expense" if amount_minor < 0 else "income"


def normalize_kind(value: str) -> str:
    kind = value.strip().lower()
    if kind not in USER_RULE_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(USER_RULE_KINDS))}")
    return kind


def _require_text(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


__all__ = [
    "SOURCE_KIND",
    "classify_by_hand",
    "edit_transaction",
    "is_same_entry",
    "new_transaction",
    "normalize_kind",
    "parse_date",
    "parse_signed_amount",
    "require_manual",
]
