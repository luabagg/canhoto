"""StatementParser port — strategy interface for user/plugin parsers.

Implementations live in ``{data_dir}/{parsers_dir}/*.py`` and are registered in
``config.json``. The distributed package ships no bank-specific parsers.

Plugin module convention (single, required entrypoint)
------------------------------------------------------
Each parser module **must** expose a zero-arg ``register()`` callable that
returns an object satisfying ``StatementParser``::

    def register() -> StatementParser:
        return MyParser()

A module-level ``PARSER`` attribute is **not** supported — discovery expects
``register()`` only.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from canhoto.core.models import ParseResult


@runtime_checkable
class StatementParser(Protocol):
    """Strategy for sniffing and parsing one family of statements."""

    id: str
    statement_type: str  # "account" | "card" (free string; StatementType values)
    institution: str  # free string; not a closed enum
    version: str

    def sniff(self, text: str) -> float:
        """Return 0.0–1.0 confidence that this parser owns the document."""
        ...

    def parse(self, text: str, source_file: str) -> ParseResult:
        """Return normalized meta + transactions; raise on hard failure."""
        ...
