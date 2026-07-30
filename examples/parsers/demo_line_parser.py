"""Demo line-oriented statement parser (docs/example only).

This module is **not** imported or auto-loaded by the Canhoto package.
Copy it into ``$CANHOTO_DATA_DIR/parsers/`` (or ``~/.canhoto/parsers/``),
register it in config, then test and enable::

    cp examples/parsers/demo_line_parser.py ~/.canhoto/parsers/
    # register in config.json as id=demo_line, module=demo_line_parser.py, enabled=false
    canhoto parsers test --id demo_line --file examples/parsers/fixtures/demo_statement.txt
    canhoto parsers enable --id demo_line

Fixture format (UTF-8 text)
---------------------------
Line 1 must be a header::

    DEMO_STATEMENT account|card <Institution Name>

Then zero or more transaction lines::

    YYYY-MM-DD <amount_major> <merchant...>

``amount_major`` is a decimal in major units (e.g. ``-12.34``). Negative
amounts are debits/expenses in the usual sense; sign is preserved as minor
units (cents). Blank lines and lines starting with ``#`` are ignored.

Example::

    DEMO_STATEMENT account Demo Bank
    2026-07-01 -12.50 COFFEE SHOP
    2026-07-02 1000.00 PAYROLL
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from canhoto.core.models import LedgerTransaction, ParseResult, StatementMeta

_HEADER_PREFIX = "DEMO_STATEMENT"
_MINOR_SCALE = 100


class DemoLineParser:
    """Trivial line-oriented parser for docs, tests, and local dry-runs."""

    id = "demo_line"
    statement_type = "account"
    institution = "Demo"
    version = "0.1.0"

    def sniff(self, text: str) -> float:
        """Return high confidence when the demo header marker is present."""
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.upper().startswith(_HEADER_PREFIX):
                return 0.95
            # First non-empty content line is not our header.
            return 0.0
        return 0.0

    def parse(self, text: str, source_file: str) -> ParseResult:
        """Parse demo header + transaction lines into a ParseResult."""
        statement_type = self.statement_type
        institution = self.institution
        transactions: list[LedgerTransaction] = []
        header_seen = False
        tx_index = 0

        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            if not header_seen:
                statement_type, institution = _parse_header(line, lineno)
                header_seen = True
                continue

            tx_index += 1
            transactions.append(
                _parse_tx_line(
                    line,
                    lineno=lineno,
                    tx_index=tx_index,
                    statement_type=statement_type,
                    institution=institution,
                    source_file=source_file,
                )
            )

        if not header_seen:
            raise ValueError(
                f"demo_line_parser: missing {_HEADER_PREFIX} header in {source_file!r}"
            )

        return ParseResult(
            meta=StatementMeta(
                statement_type=statement_type,
                source_file=source_file,
                institution=institution,
            ),
            transactions=transactions,
        )


def _parse_header(line: str, lineno: int) -> tuple[str, str]:
    parts = line.split(None, 2)
    if len(parts) < 2 or parts[0].upper() != _HEADER_PREFIX:
        raise ValueError(
            f"demo_line_parser: line {lineno}: expected "
            f"'{_HEADER_PREFIX} <account|card> <institution>'"
        )
    statement_type = parts[1].lower()
    if statement_type not in {"account", "card"}:
        raise ValueError(
            f"demo_line_parser: line {lineno}: statement type must be "
            f"'account' or 'card', got {parts[1]!r}"
        )
    institution = parts[2].strip() if len(parts) > 2 else "Demo"
    if not institution:
        institution = "Demo"
    return statement_type, institution


def _parse_tx_line(
    line: str,
    *,
    lineno: int,
    tx_index: int,
    statement_type: str,
    institution: str,
    source_file: str,
) -> LedgerTransaction:
    parts = line.split(None, 2)
    if len(parts) < 2:
        raise ValueError(
            f"demo_line_parser: line {lineno}: expected "
            f"'YYYY-MM-DD <amount> <merchant>'"
        )
    try:
        tx_date = date.fromisoformat(parts[0])
    except ValueError as exc:
        raise ValueError(
            f"demo_line_parser: line {lineno}: invalid date {parts[0]!r}"
        ) from exc
    try:
        amount_major = Decimal(parts[1])
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(
            f"demo_line_parser: line {lineno}: invalid amount {parts[1]!r}"
        ) from exc

    amount_minor = int(amount_major * _MINOR_SCALE)
    merchant = parts[2].strip() if len(parts) > 2 else ""
    month = tx_date.strftime("%Y-%m")
    tx_id = f"demo_line-{tx_date.isoformat()}-{tx_index:04d}"

    return LedgerTransaction(
        id=tx_id,
        date=tx_date,
        amount_minor=amount_minor,
        currency="BRL",
        description=merchant,
        merchant_raw=merchant,
        source_kind=statement_type,
        institution=institution,
        source_file=source_file,
        month=month,
        is_expense=amount_minor < 0,
    )


def register():
    """Required plugin entrypoint — returns a StatementParser instance."""
    return DemoLineParser()
