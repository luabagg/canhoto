"""Pure matching helpers for user classification rules."""

from __future__ import annotations

import re
from collections.abc import Sequence

from canhoto.core.models import LedgerTransaction, UserRule
from canhoto.core.money import major_units, normalize_currency_code, to_minor


def match_user_rule(
    tx: LedgerTransaction, rules: Sequence[UserRule], *, text: str
) -> UserRule | None:
    """Return the first rule that matches ``tx``; ``rules`` must be in priority order."""
    validate_rule_currencies(rules)
    return next((rule for rule in rules if _matches(rule, tx, text)), None)


def amount_bound_to_minor(value: str | None, currency: str = "BRL") -> int | None:
    if value is None:
        return None
    minor = to_minor(value, currency)
    if minor < 0:
        raise ValueError("amount bound must be non-negative")
    return minor


def validate_rule_currencies(rules: Sequence[UserRule]) -> None:
    for rule in rules:
        bounded = rule.min_amount_minor is not None or rule.max_amount_minor is not None
        if bounded and rule.currency is None:
            raise ValueError(
                f"rule {rule.id} has amount bounds without currency; "
                "remove and recreate it with an explicit currency"
            )


def _matches(rule: UserRule, tx: LedgerTransaction, text: str) -> bool:
    if rule.currency is not None and rule.currency != normalize_currency_code(tx.currency):
        return False
    if rule.source_kind is not None and rule.source_kind != tx.source_kind:
        return False
    if rule.direction == "in" and tx.amount_minor <= 0:
        return False
    if rule.direction == "out" and tx.amount_minor >= 0:
        return False
    magnitude = tx.amount.copy_abs()
    if rule.min_amount_minor is not None and magnitude < major_units(
        rule.min_amount_minor, rule.amount_exponent
    ):
        return False
    if rule.max_amount_minor is not None and magnitude > major_units(
        rule.max_amount_minor, rule.amount_exponent
    ):
        return False
    return re.search(rule.pattern, text, re.IGNORECASE) is not None
