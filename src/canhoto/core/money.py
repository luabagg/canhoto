"""Money conversions retain exact values and never round input amounts."""

from __future__ import annotations

import re
from decimal import Context, Decimal, DecimalException, Inexact, localcontext

from iso4217 import Currency

MIN_SQLITE_INTEGER = -(2**63)
MAX_SQLITE_INTEGER = 2**63 - 1


def normalize_currency_code(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("currency must contain three ASCII letters")
    code = value.strip()
    if re.fullmatch(r"[A-Za-z]{3}", code) is None:
        raise ValueError("currency must contain three ASCII letters")
    return code.upper()


def currency_exponent(currency: str) -> int:
    code = normalize_currency_code(currency)
    try:
        exponent = Currency(code).exponent
    except ValueError as exc:
        raise ValueError(f"unsupported currency: {code}") from exc
    if exponent is None:
        raise ValueError(f"currency {code} has no defined decimal minor units")
    return int(exponent)


def to_minor(value: str | Decimal, currency: str) -> int:
    exponent = currency_exponent(currency)
    try:
        amount = Decimal(value)
        if not amount.is_finite():
            raise ValueError("amount must be a finite number")
        precision = max(28, len(amount.as_tuple().digits) + exponent)
        with localcontext(Context(prec=precision)) as context:
            context.traps[Inexact] = True
            minor = amount.scaleb(exponent)
            if minor != minor.to_integral_value():
                raise ValueError(f"amount has more than {exponent} decimals for {currency}")
            if not MIN_SQLITE_INTEGER <= minor <= MAX_SQLITE_INTEGER:
                raise ValueError("amount exceeds the SQLite integer range")
            return int(minor)
    except DecimalException as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc


def major_units(value: int, exponent: int) -> Decimal:
    return Decimal(f"{value}e-{exponent}")


def format_amount(value: Decimal, exponent: int) -> str:
    if not value.is_finite():
        raise ValueError("amount must be a finite number")
    formatted = format(value, f".{exponent}f")
    if Decimal(formatted) != value:
        raise ValueError("amount cannot be formatted without rounding")
    return formatted
