"""Month aggregate reports (no per-transaction lists).

Portable accounting intent (architecture §9):
- Card spend / ``is_expense`` rows count toward expenses.
- ``card_payment``, ``self_transfer``, and ``internal_transfer`` are excluded
  from spend (and are not income).
- Income is ``kind == income`` or positive non-expense account-style inflows.
- Amounts are decimal strings consistent with review redaction formatting.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from canhoto.core.models import LedgerTransaction, MonthBreakdown

# Non-spend structural moves — never roll into expenses or income.
_EXCLUDED_SPEND_KINDS = frozenset(
    {
        "card_payment",
        "self_transfer",
        "internal_transfer",
    }
)

DEFAULT_MONTH_LIMIT = 50_000
_CENT = Decimal("0.01")
_MINOR_SCALE = Decimal(100)


def compute_month_breakdown(
    month: str,
    transactions: Iterable[LedgerTransaction],
) -> MonthBreakdown:
    """Aggregate ledger rows for ``month`` into a privacy-safe breakdown.

    Does not return transaction lists or merchant rollups.
    """
    income = Decimal("0")
    expenses = Decimal("0")
    by_cat: dict[str, Decimal] = {}
    pending_review = 0
    transaction_count = 0
    expense_count = 0

    for tx in transactions:
        transaction_count += 1
        if tx.needs_review:
            pending_review += 1

        kind = (tx.kind or "").strip().lower()
        if kind in _EXCLUDED_SPEND_KINDS:
            continue

        amount = _major_units(tx.amount_minor)

        if _is_expense_row(tx, kind):
            amt = abs(amount)
            expenses += amt
            expense_count += 1
            cat = (tx.category or "").strip() or "uncategorized"
            by_cat[cat] = by_cat.get(cat, Decimal("0")) + amt
            continue

        if _is_income_row(tx, kind, amount):
            income += abs(amount)

    net = income - expenses
    return MonthBreakdown(
        month=month,
        income=_format_money(income),
        expenses=_format_money(expenses),
        net=_format_money(net),
        by_category={k: _format_money(by_cat[k]) for k in sorted(by_cat)},
        pending_review=pending_review,
        transaction_count=transaction_count,
        expense_count=expense_count,
    )


def _is_expense_row(tx: LedgerTransaction, kind: str) -> bool:
    if tx.is_expense:
        return True
    return kind == "expense"


def _is_income_row(tx: LedgerTransaction, kind: str, amount: Decimal) -> bool:
    if kind == "income":
        return True
    # Positive non-expense flows (typical account credits) count as income.
    return amount > 0 and not tx.is_expense


def _major_units(amount_minor: int) -> Decimal:
    return Decimal(amount_minor) / _MINOR_SCALE


def _format_money(value: Decimal) -> str:
    quantized = value.quantize(_CENT)
    return format(quantized, "f")


__all__ = [
    "DEFAULT_MONTH_LIMIT",
    "compute_month_breakdown",
]
