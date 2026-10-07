"""Reports contain aggregates only. Integer arithmetic preserves every stored money scale."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from canhoto.core.models import CurrencyBreakdown, LedgerTransaction, MonthBreakdown
from canhoto.core.money import format_amount, major_units, normalize_currency_code

_EXCLUDED_SPEND_KINDS = frozenset(
    {"card_payment", "self_transfer", "internal_transfer", "transfer"}
)
DEFAULT_MONTH_LIMIT = 50_000


def compute_month_breakdown(
    month: str, transactions: Iterable[LedgerTransaction],
) -> MonthBreakdown:
    groups = {
        currency: _currency_breakdown(rows)
        for currency, rows in sorted(_group_by_currency(transactions).items())
    }
    return MonthBreakdown(
        month=month,
        by_currency=groups,
        pending_review=sum(group.pending_review for group in groups.values()),
        transaction_count=sum(group.transaction_count for group in groups.values()),
        expense_count=sum(group.expense_count for group in groups.values()),
    )


def _currency_breakdown(rows: list[LedgerTransaction]) -> CurrencyBreakdown:
    exponent = max(row.amount_exponent for row in rows)
    income = expenses = expense_count = 0
    categories: dict[str, int] = defaultdict(int)
    for tx in rows:
        kind = (tx.kind or "").strip().lower()
        if kind in _EXCLUDED_SPEND_KINDS:
            continue
        amount = _aligned_minor(tx, exponent)
        if _is_expense_row(tx, kind):
            expenses += abs(amount)
            expense_count += 1
            categories[(tx.category or "").strip() or "uncategorized"] += abs(amount)
        elif kind == "income" or amount > 0:
            income += abs(amount)
    return CurrencyBreakdown(
        amount_exponent=exponent,
        income=_format_minor(income, exponent),
        expenses=_format_minor(expenses, exponent),
        net=_format_minor(income - expenses, exponent),
        by_category={
            name: _format_minor(value, exponent) for name, value in sorted(categories.items())
        },
        pending_review=sum(row.needs_review for row in rows),
        transaction_count=len(rows),
        expense_count=expense_count,
    )


def compute_merchant_spend_by_currency(
    transactions: Iterable[LedgerTransaction],
) -> dict[str, dict[str, dict[str, str]]]:
    result: dict[str, dict[str, dict[str, str]]] = {}
    for currency, rows in sorted(_group_by_currency(transactions).items()):
        exponent = max(row.amount_exponent for row in rows)
        totals: dict[str, dict[str, int]] = {}
        for tx in rows:
            kind = (tx.kind or "").strip().lower()
            if kind in _EXCLUDED_SPEND_KINDS or not _is_expense_row(tx, kind):
                continue
            category = (tx.category or "").strip() or "uncategorized"
            merchant = (tx.merchant_normalized or "").strip() or "Unidentified merchant"
            merchants = totals.setdefault(category, {})
            merchants[merchant] = merchants.get(merchant, 0) + abs(_aligned_minor(tx, exponent))
        result[currency] = {
            category: {
                name: _format_minor(value, exponent) for name, value in sorted(merchants.items())
            }
            for category, merchants in sorted(totals.items())
        }
    return result


def _group_by_currency(
    transactions: Iterable[LedgerTransaction],
) -> dict[str, list[LedgerTransaction]]:
    groups: dict[str, list[LedgerTransaction]] = defaultdict(list)
    for tx in transactions:
        groups[normalize_currency_code(tx.currency)].append(tx)
    return groups


def _aligned_minor(tx: LedgerTransaction, exponent: int) -> int:
    return tx.amount_minor * 10 ** (exponent - tx.amount_exponent)


def _format_minor(value: int, exponent: int) -> str:
    return format_amount(major_units(value, exponent), exponent)


def _is_expense_row(tx: LedgerTransaction, kind: str) -> bool:
    return tx.is_expense or kind == "expense"


__all__ = [
    "DEFAULT_MONTH_LIMIT", "compute_merchant_spend_by_currency", "compute_month_breakdown",
]
