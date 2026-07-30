"""Contract tests for privacy-safe agent/report domain models."""

from __future__ import annotations

from canhoto.core.models import (
    AgentViewConfig,
    AppConfig,
    MonthBreakdown,
    ParserEntry,
    ReviewItem,
    StatementType,
)

FORBIDDEN_REVIEW_FIELDS = {
    "description",
    "source_file",
    "operation_id",
    "running_balance",
    "account_id",
    "metadata",
    "merchant_raw",
}

FORBIDDEN_BREAKDOWN_FIELDS = {
    "transactions",
    "items",
    "rows",
    "ledger",
    "description",
    "source_file",
    "operation_id",
    "running_balance",
    "account_id",
    "metadata",
    "merchant_raw",
}

FORBIDDEN_APP_CONFIG_FIELDS = {
    "spreadsheet_id",
    "google_credentials",
    "google_token",
    "google_auth",
    "sheets_id",
}


def test_review_item_has_no_forbidden_fields() -> None:
    assert FORBIDDEN_REVIEW_FIELDS.isdisjoint(set(ReviewItem.model_fields))


def test_month_breakdown_has_no_forbidden_fields() -> None:
    assert FORBIDDEN_BREAKDOWN_FIELDS.isdisjoint(set(MonthBreakdown.model_fields))


def test_month_breakdown_has_no_per_transaction_list() -> None:
    for name, field in MonthBreakdown.model_fields.items():
        annotation = field.annotation
        assert annotation is not list, f"{name} must not be a bare list"
        origin = getattr(annotation, "__origin__", None)
        assert origin is not list, f"{name} must not be a list type"


def test_app_config_has_no_google_or_sheets_fields() -> None:
    assert FORBIDDEN_APP_CONFIG_FIELDS.isdisjoint(set(AppConfig.model_fields))


def test_statement_type_values() -> None:
    assert StatementType.ACCOUNT == "account"
    assert StatementType.CARD == "card"
    assert set(StatementType) == {StatementType.ACCOUNT, StatementType.CARD}


def test_agent_view_config_defaults() -> None:
    view = AgentViewConfig()
    assert view.allow_aggregates is True
    assert view.allow_review_items is True
    assert view.include_amounts_in_review is True
    assert view.include_institution is True
    assert view.max_batch_size == 25
    assert view.absolute_max_batch_size == 50
    assert view.expense_only is True
    assert view.allow_parser_writes is False
    assert view.preview_max_chars == 20_000


def test_parser_entry_defaults_disabled() -> None:
    entry = ParserEntry(id="mp-account", module="mp_account.py")
    assert entry.enabled is False


def test_app_config_defaults() -> None:
    cfg = AppConfig(data_dir="/tmp/canhoto-test")
    assert cfg.parsers_dir == "parsers"
    assert cfg.parsers == []
    assert isinstance(cfg.agent_view, AgentViewConfig)


def test_review_item_required_shape_and_currency_override() -> None:
    item = ReviewItem(
        id="tx-1",
        date="2026-07-01",
        amount="-12.34",
        merchant_display="Cafe",
        source_kind="card",
        current_category="Eating",
        current_kind="expense",
    )
    assert item.currency == "BRL"
    assert item.institution is None
    assert item.confidence == 0.0
    assert item.review_reason is None
    assert item.installment is None

    usd = item.model_copy(update={"currency": "USD", "amount": None})
    assert usd.currency == "USD"
    assert usd.amount is None


def test_month_breakdown_required_shape() -> None:
    breakdown = MonthBreakdown(
        month="2026-07",
        income="1000.00",
        expenses="250.50",
        net="749.50",
        by_category={"Eating": "50.00", "Groceries": "200.50"},
        pending_review=3,
        transaction_count=12,
        expense_count=8,
    )
    assert breakdown.by_category["Eating"] == "50.00"
    assert "transactions" not in breakdown.model_fields
