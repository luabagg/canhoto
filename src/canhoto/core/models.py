"""Privacy-safe domain contracts for plugins, agent policy, review, and reports.

Stable surface for CLI/MCP. Review and report shapes omit raw ledger fields
(full description, source paths, operation ids, balances, account ids,
metadata bags).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

# Who set a row's classification. User rules never overwrite "manual".
ClassificationSource = Literal["parser", "builtin_rule", "user_rule", "merchant_memory", "manual"]

# Kinds a user rule may set. Must equal breakdown._EXCLUDED_SPEND_KINDS plus
# expense and income; a test locks this, because an unknown non-expense kind
# is counted as income.
USER_RULE_KINDS = frozenset(
    {"expense", "income", "transfer", "internal_transfer", "self_transfer", "card_payment"}
)
_MAX_PATTERN_LENGTH = 200


class UserRule(BaseModel):
    """User-defined classification rule stored in ``user_rules``."""

    id: int | None = None
    pattern: str
    direction: Literal["in", "out", "any"] = "any"
    min_amount_minor: int | None = Field(default=None, ge=0)
    max_amount_minor: int | None = Field(default=None, ge=0)
    source_kind: str | None = None
    category: str
    kind: str
    needs_review: bool = False
    note: str = ""
    priority: int = 100

    @field_validator("pattern")
    @classmethod
    def _pattern_must_compile(cls, value: str) -> str:
        pattern = value.strip()
        if not pattern or len(pattern) > _MAX_PATTERN_LENGTH:
            raise ValueError(f"pattern must have 1 to {_MAX_PATTERN_LENGTH} characters")
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"pattern is not a valid regex: {exc}") from exc
        return pattern

    @field_validator("category")
    @classmethod
    def _category_must_be_set(cls, value: str) -> str:
        category = value.strip()
        if not category:
            raise ValueError("category must be a non-empty string")
        return category

    @field_validator("kind")
    @classmethod
    def _kind_must_be_known(cls, value: str) -> str:
        kind = value.strip()
        if kind not in USER_RULE_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(USER_RULE_KINDS))}")
        return kind

    @field_validator("source_kind")
    @classmethod
    def _normalize_source_kind(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower() or None

    @model_validator(mode="after")
    def _bounds_must_be_ordered(self) -> UserRule:
        low, high = self.min_amount_minor, self.max_amount_minor
        if low is not None and high is not None and low > high:
            raise ValueError("min amount must not exceed max amount")
        return self

    @model_validator(mode="after")
    def _kind_must_fit_direction(self) -> UserRule:
        if self.kind == "income" and self.direction == "out":
            raise ValueError("income kind cannot use direction out")
        if self.kind == "expense" and self.direction == "in":
            raise ValueError("expense kind cannot use direction in")
        return self

    @property
    def is_expense(self) -> bool:
        return self.kind == "expense"


class StatementType(StrEnum):
    ACCOUNT = "account"
    CARD = "card"


class Transaction(Protocol):
    """Structural ledger row shape consumed by agent-view redaction.

    Not a concrete SQLite/store model. Attributes match exactly what
    ``merchant_display`` / ``to_review_item`` read. Members are typed ``Any``
    (read via getattr) so concrete ledger rows with required ``str``/``float``
    fields and a read-only ``amount`` property remain structurally compatible.
    """

    id: Any
    date: Any
    currency: Any
    merchant_normalized: Any
    merchant_raw: Any
    source_kind: Any
    institution: Any
    category: Any
    kind: Any
    confidence: Any
    review_reason: Any
    installment: Any

    @property
    def amount(self) -> Any: ...


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
    # Last parser_test stamp (config field; not a sidecar). None = never tested.
    last_test_ok: bool | None = None
    last_test_at: str | None = None  # ISO-8601 UTC timestamp
    last_test_error: str | None = None


class AppConfig(BaseModel):
    """Application configuration. No Google/Sheets fields in v1 core."""

    data_dir: str
    parsers_dir: str = "parsers"
    parsers: list[ParserEntry] = Field(default_factory=list)
    agent_view: AgentViewConfig = Field(default_factory=AgentViewConfig)
    # User-local markers for self-transfer detection. Package default is empty
    # (no personal names shipped in the wheel).
    own_name_markers: list[str] = Field(default_factory=list)


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
    # Reason from the user rule that classified this row, if any.
    rule_note: str | None = None


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


class ReportBundle(BaseModel):
    """In-memory aggregate payload for local summary exporters only."""

    breakdown: MonthBreakdown
    merchant_spend_by_category: dict[str, dict[str, str]] = Field(default_factory=dict)
    generated_at: str
    title: str


# --- Concrete ledger / store DTOs (internal; not agent projections) ---

_DEFAULT_MINOR_EXPONENT = 2
_MINOR_SCALE = 10**_DEFAULT_MINOR_EXPONENT


class LedgerTransaction(BaseModel):
    """Concrete ledger row stored in SQLite.

    Money is recorded as ``amount_minor`` (integer minor units). The ``amount``
    property projects major units for redaction / ``Transaction`` protocol use.
    Classification fields are free strings (no closed bank/category enums).
    """

    id: str
    date: date
    amount_minor: int
    currency: str = "BRL"
    description: str = ""
    merchant_raw: str = ""
    merchant_normalized: str | None = None
    source_kind: str
    institution: str | None = None
    source_file: str | None = None
    operation_id: str | None = None
    running_balance_minor: int | None = None
    account_id: str | None = None
    category: str = ""
    kind: str = ""
    is_expense: bool = False
    needs_review: bool = True
    confidence: float = 0.0
    review_reason: str | None = None
    installment: str | None = None
    classification_source: ClassificationSource = "parser"
    user_rule_id: int | None = None
    month: str  # YYYY-MM
    billing_cycle: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def amount(self) -> Decimal:
        """Major-unit amount for protocol/redaction compatibility."""
        return Decimal(self.amount_minor) / Decimal(_MINOR_SCALE)


class StatementMeta(BaseModel):
    """Normalized statement-level metadata produced by a parser.

    Free-form enough for any institution; no bank-specific required fields.
    Extra keys may live in ``raw_summary``.
    """

    statement_type: StatementType | str
    source_file: str
    institution: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    due_date: date | None = None
    currency: str | None = None
    raw_summary: dict[str, Any] = Field(default_factory=dict)


class ParseResult(BaseModel):
    """Output of ``StatementParser.parse`` — meta + ledger-ready rows.

    ``transactions`` use ``LedgerTransaction`` so the ingest path can upsert
    without a second mapping layer. Parsers should leave classification fields
    at defaults (empty category/kind, needs_review=True) unless they truly know.
    """

    meta: StatementMeta
    transactions: list[LedgerTransaction] = Field(default_factory=list)


class StatementRecord(BaseModel):
    """Statement identity and metadata keyed by content hash."""

    content_hash: str
    source_file: str
    statement_type: str
    institution: str | None = None
    meta_json: dict[str, Any] = Field(default_factory=dict)


class ClassificationPatch(BaseModel):
    """Partial classification update for an existing ledger row."""

    id: str
    category: str | None = None
    kind: str | None = None
    is_expense: bool | None = None
    needs_review: bool | None = None
    confidence: float | None = None
    review_reason: str | None = None
    merchant_normalized: str | None = None
    # When set, apply_classifications also rewrites user_rule_id.
    classification_source: ClassificationSource | None = None
    user_rule_id: int | None = None


class UpsertResult(BaseModel):
    inserted: int
    updated: int
    total: int


class ClassificationResult(BaseModel):
    applied: int
    missing: list[str] = Field(default_factory=list)
    # Rows classified via merchant_category_map after the rule pack.
    merchant_memory_applied: int = 0
    # Rows classified by a user rule in this run.
    user_rule_applied: int = 0


class StatementUpsertResult(BaseModel):
    created: bool
    content_hash: str
    linked: int = 0
