"""Privacy-safe domain contracts for plugins, agent policy, review, and reports.

These models are the stable surface later CLI/MCP layers must use. Review and
report shapes intentionally omit raw ledger fields (full description, source
paths, operation ids, balances, account ids, metadata bags).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator


class StatementType(str, Enum):
    ACCOUNT = "account"
    CARD = "card"


class Transaction(Protocol):
    """Structural ledger row shape consumed by agent-view redaction.

    Not a concrete SQLite/store model. Attributes match exactly what
    ``merchant_display`` / ``to_review_item`` read; concrete ledger types
    land in later core/store work and should satisfy this protocol.
    """

    id: Any
    date: date | datetime | str | Any
    amount: Decimal | int | float | str | None | Any
    currency: str | None | Any
    merchant_normalized: str | None | Any
    merchant_raw: str | None | Any
    source_kind: Any
    institution: str | None | Any
    category: str | None | Any
    kind: str | None | Any
    confidence: float | int | None | Any
    review_reason: str | None | Any
    installment: str | None | Any


class AgentViewConfig(BaseModel):
    """Policy knobs controlling what agents may see and mutate."""

    allow_aggregates: bool = True
    allow_review_items: bool = True
    include_amounts_in_review: bool = True
    include_institution: bool = True
    max_batch_size: int = 25
    absolute_max_batch_size: int = 50
    expense_only: bool = True
    allow_parser_writes: bool = False
    preview_max_chars: int = 20_000

    @field_validator("max_batch_size", "absolute_max_batch_size")
    @classmethod
    def _batch_caps_must_be_positive(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("batch size caps must be positive integers")
        return value


class ParserEntry(BaseModel):
    """Registered user/plugin parser under the data-dir parsers folder."""

    id: str
    module: str  # filename under parsers_dir
    enabled: bool = False


class AppConfig(BaseModel):
    """Application configuration. No Google/Sheets fields in v1 core."""

    data_dir: str
    parsers_dir: str = "parsers"
    parsers: list[ParserEntry] = Field(default_factory=list)
    agent_view: AgentViewConfig = Field(default_factory=AgentViewConfig)


class ReviewItem(BaseModel):
    """Redacted transaction row safe for agent review batches."""

    id: str
    date: str
    amount: str | None
    currency: str = "BRL"  # default only; core must allow override
    merchant_display: str
    source_kind: str
    institution: str | None = None
    current_category: str
    current_kind: str
    confidence: float = 0.0
    review_reason: str | None = None
    installment: str | None = None


class MonthBreakdown(BaseModel):
    """Aggregate month report. No per-transaction list."""

    month: str
    income: str
    expenses: str
    net: str
    by_category: dict[str, str]
    pending_review: int
    transaction_count: int
    expense_count: int
