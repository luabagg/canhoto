"""Pure matching helpers for user classification rules."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from canhoto.core.models import LedgerTransaction, UserRule

_MINOR_PER_MAJOR = Decimal(100)


def match_user_rule(
    tx: LedgerTransaction, rules: Sequence[UserRule], *, text: str
) -> UserRule | None:
    """Return the first rule that matches ``tx``; ``rules`` must be in priority order."""
    return next((rule for rule in rules if _matches(rule, tx, text)), None)


def amount_bound_to_minor(value: str | None) -> int | None:
    """Convert a non-negative major-unit amount ("700", "1234.56") to minor units."""
    if value is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"amount must be a finite number: {value!r}")
    minor = amount * _MINOR_PER_MAJOR
    if amount < 0 or minor != minor.to_integral_value():
        raise ValueError(f"amount must be non-negative with at most 2 decimals: {value!r}")
    return int(minor)


def _matches(rule: UserRule, tx: LedgerTransaction, text: str) -> bool:
    if rule.source_kind is not None and rule.source_kind != tx.source_kind:
        return False
    if rule.direction == "in" and tx.amount_minor <= 0:
        return False
    if rule.direction == "out" and tx.amount_minor >= 0:
        return False
    magnitude = abs(tx.amount_minor)
    if rule.min_amount_minor is not None and magnitude < rule.min_amount_minor:
        return False
    if rule.max_amount_minor is not None and magnitude > rule.max_amount_minor:
        return False
    return re.search(rule.pattern, text, re.IGNORECASE) is not None
