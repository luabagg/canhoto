"""Pure projection from ledger transactions to agent-safe ReviewItem rows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from canhoto.core.models import AgentViewConfig, ReviewItem, Transaction
from canhoto.core.money import format_amount


def merchant_display(tx: Transaction) -> str:
    """Preferred merchant label for agent review (normalized, else raw)."""
    normalized = getattr(tx, "merchant_normalized", None)
    if normalized is not None:
        text = _as_text(normalized)
        if text:
            return text
    raw = getattr(tx, "merchant_raw", None)
    if raw is not None:
        text = _as_text(raw)
        if text:
            return text
    return ""


def to_review_item(
    tx: Transaction, view: AgentViewConfig, *, rule_note: str | None = None
) -> ReviewItem:
    """Project a transaction-like object into a redacted ``ReviewItem``.

    Never copies raw description, source paths, operation ids, balances,
    account ids, or metadata bags onto the result.
    """
    amount: str | None
    if view.include_amounts_in_review:
        amount = _format_amount(
            getattr(tx, "amount", None), exponent=getattr(tx, "amount_exponent", 2)
        )
    else:
        amount = None

    institution: str | None
    if view.include_institution:
        institution = _optional_text(getattr(tx, "institution", None))
    else:
        institution = None

    return ReviewItem(
        id=_as_text(tx.id),
        date=_format_date(tx.date),
        amount=amount,
        currency=_as_text(getattr(tx, "currency", None) or "BRL"),
        merchant_display=merchant_display(tx),
        source_kind=_as_text(tx.source_kind),
        institution=institution,
        current_category=_as_text(getattr(tx, "category", "") or ""),
        current_kind=_as_text(getattr(tx, "kind", "") or ""),
        confidence=float(getattr(tx, "confidence", 0.0) or 0.0),
        review_reason=_optional_text(getattr(tx, "review_reason", None)),
        installment=_optional_text(getattr(tx, "installment", None)),
        rule_note=rule_note,
    )


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    # Enum / str-Enum / SimpleNamespace(value=...)
    inner = getattr(value, "value", None)
    if isinstance(inner, str):
        return inner
    if inner is not None and not isinstance(inner, (dict, list, tuple, set)):
        return str(inner)
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _as_text(value)
    return text if text else None


def _format_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return _as_text(value)


def _format_amount(value: Any, *, exponent: int = 2) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return format_amount(Decimal(str(value)), exponent)
    except (InvalidOperation, ValueError):
        return str(value)
