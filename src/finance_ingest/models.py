from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceKind(str, Enum):
    ACCOUNT = "account"
    CARD = "card"


class TransactionKind(str, Enum):
    EXPENSE = "expense"
    INCOME = "income"
    CARD_PAYMENT = "card_payment"
    INTERNAL_TRANSFER = "internal_transfer"
    PIGGY_RESERVE = "piggy_reserve"
    SELF_TRANSFER = "self_transfer"
    FEE = "fee"
    INSTALLMENT = "installment"
    UNKNOWN = "unknown"


class BudgetCategory(str, Enum):
    CAR_PAYMENT = "Car payment"
    GAS_TRAVEL = "Gas/travel"
    INVESTMENTS = "Investments"
    GROCERIES = "Groceries"
    EATING = "Eating"
    PERSONAL_CARE = "Personal care"
    ELECTRIC = "Electric"
    CONDO_FEE = "Condo Fee"
    RENT_MORTGAGE = "Rent/mortgage"
    HOUSE = "House"
    INTERNET = "Internet"
    CELL_PHONE = "Cell phone"
    ENTERTAINMENT = "Entertainment"
    PURCHASES = "Purchases"
    OTHERS = "Others"
    INCOME = "Income"
    TRANSFER = "Transfer"
    UNCATEGORIZED = "Uncategorized"


class Transaction(BaseModel):
    """Normalized ledger row ready for review / Sheets."""

    id: str
    source_kind: SourceKind
    source_file: str
    date: date
    description: str
    amount: float  # signed: expenses negative, income positive (account style)
    currency: str = "BRL"
    operation_id: str | None = None
    running_balance: float | None = None
    card_last4: str | None = None
    installment: str | None = None
    international: bool = False
    merchant_raw: str
    merchant_normalized: str | None = None
    category: BudgetCategory = BudgetCategory.UNCATEGORIZED
    kind: TransactionKind = TransactionKind.UNKNOWN
    is_expense: bool = False
    needs_review: bool = True
    confidence: float = 0.0
    review_reason: str | None = None
    month: str  # YYYY-MM (calendar month of transaction date)
    billing_cycle: str | None = None  # e.g. 2026-07 for card statement month
    metadata: dict[str, Any] = Field(default_factory=dict)

    def fingerprint(self) -> str:
        return self.id


class StatementMeta(BaseModel):
    source_kind: SourceKind
    source_file: str
    period_start: date | None = None
    period_end: date | None = None
    due_date: date | None = None
    total_amount: float | None = None
    opening_balance: float | None = None
    closing_balance: float | None = None
    entries: float | None = None
    exits: float | None = None
    raw_summary: dict[str, Any] = Field(default_factory=dict)


class ParseResult(BaseModel):
    meta: StatementMeta
    transactions: list[Transaction]


class ClassificationPatch(BaseModel):
    """Agent-provided classification for one stored transaction."""

    id: str
    merchant_normalized: str | None = None
    category: BudgetCategory | None = None
    kind: TransactionKind | None = None
    is_expense: bool | None = None
    needs_review: bool | None = None
    confidence: float | None = None
    review_reason: str | None = None


class MonthlySummary(BaseModel):
    month: str
    income: float = 0.0
    expenses: float = 0.0
    net: float = 0.0
    by_category: dict[str, float] = Field(default_factory=dict)
    transfers_excluded: float = 0.0
    card_payments_excluded: float = 0.0
    pending_review: int = 0
    transaction_count: int = 0


class AppConfig(BaseModel):
    data_dir: str
    spreadsheet_id: str | None = None
    google_token_path: str | None = None
    google_client_secret_path: str | None = None
    currency: str = "BRL"
    own_name_markers: list[str] = Field(
        default_factory=lambda: ["LUAN BAGGIO", "Luan Baggio"]
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
