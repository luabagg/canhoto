from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
from alembic import command
from canhoto import service
from canhoto.core import breakdown, config, migrate, store
from canhoto.core.models import AgentViewConfig, LedgerTransaction, UserRule
from canhoto.core.money import to_minor
from canhoto.core.redaction import to_review_item
from canhoto.core.user_rules import match_user_rule


def _row(currency: str, amount_minor: int, **fields: object) -> LedgerTransaction:
    return LedgerTransaction.model_validate({
        "id": currency, "date": date(2026, 6, 1), "amount_minor": amount_minor,
        "currency": currency, "amount_exponent": {"JPY": 0, "KWD": 3}.get(currency, 2),
        "source_kind": "card", "month": "2026-06", **fields,
    })


@pytest.mark.parametrize(("currency", "minor", "major"), [
    ("JPY", 1250, "1250"), ("KWD", 12345, "12.345"), ("MGA", 1234, "12.34"),
])
def test_native_minor_units_survive_store_and_review(
    tmp_path: Path, currency: str, minor: int, major: str,
) -> None:
    row = _row(currency, minor)
    assert row.amount == Decimal(major)
    store.upsert_transactions([row], path=tmp_path / "ledger.db")
    saved = store.get_transaction(row.id, path=tmp_path / "ledger.db")
    assert saved is not None
    assert saved.amount == Decimal(major)
    assert to_review_item(saved, AgentViewConfig()).amount == major


def test_non_two_decimal_parser_rows_require_explicit_units() -> None:
    with pytest.raises(ValueError, match="amount_exponent"):
        LedgerTransaction(id="old-parser", date=date(2026, 6, 1), amount_minor=1250,
                          currency="JPY", source_kind="card", month="2026-06")


def test_migration_keeps_old_currency_amounts_and_balances(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    command.upgrade(migrate.alembic_config(db), "002_user_rules")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO transactions (id,date,amount_minor,currency,source_kind,month,"
            "running_balance_minor,category,kind) VALUES ('legacy','2026-06-01',123,'JPY','manual',"
            "'2026-06',456,'','')"
        )
    migrate.upgrade_to_head(db)
    row = store.get_transaction("legacy", path=db)
    assert row is not None
    assert (row.amount_minor, row.running_balance_minor, row.amount_exponent) == (123, 456, 2)
    assert row.amount == Decimal("1.23")
    assert to_review_item(row, AgentViewConfig()).amount == "1.23"


def test_revision_two_backup_restore_preserves_legacy_units_and_unlabelled_rules(
    tmp_path: Path,
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    config.init_data_dir(source)
    db = config.db_path(source)
    command.upgrade(migrate.alembic_config(db), "002_user_rules")
    with sqlite3.connect(db) as connection:
        for code, amount, balance in [("JPY", 123, 456), ("ZZZ", 789, 1011)]:
            connection.execute(
                "INSERT INTO transactions (id,date,amount_minor,currency,source_kind,month,"
                "running_balance_minor,category,kind) VALUES (?, '2026-06-01', ?, ?, 'card',"
                "'2026-06', ?, '', '')", (code, amount, code, balance),
            )
        connection.execute(
            "INSERT INTO user_rules (pattern,category,kind,min_amount_minor,note) "
            "VALUES ('PAY','Food','expense',100,'legacy owner note')"
        )
    archive = tmp_path / "old.canhoto"
    result = service.backup(output=archive, root=source)
    assert result["schema_revision"] == "002_user_rules"
    assert migrate.current_revision(db) == "002_user_rules"
    service.restore(archive, root=target)
    for code, amount, balance in [("JPY", 123, 456), ("ZZZ", 789, 1011)]:
        row = store.get_transaction(code, path=config.db_path(target))
        assert row is not None
        assert (row.currency, row.amount_minor, row.running_balance_minor, row.amount_exponent) == (
            code, amount, balance, 2,
        )
        assert row.amount == Decimal(amount) / 100
    rule = store.list_user_rules(path=config.db_path(target))[0]
    assert (rule.currency, rule.min_amount_minor, rule.amount_exponent, rule.note) == (
        None, 100, 2, "legacy owner note",
    )
    with pytest.raises(ValueError, match="currency"):
        service.run_rules("2026-06", root=target)
    report = service.month_breakdown("2026-06", root=target)["breakdown"]
    assert set(report["by_currency"]) == {"JPY", "ZZZ"}


@pytest.mark.parametrize(("currency", "amount"), [("JPY", "-1250"), ("KWD", "-12.345")])
def test_manual_add_uses_native_precision(tmp_path: Path, currency: str, amount: str) -> None:
    root = tmp_path / "ledger"
    result = service.manual_add(date="2026-06-01", amount=amount, currency=currency,
                                description="Purchase", category="Food", root=root)
    assert result["transaction"]["amount"] == amount
    assert result["transaction"]["currency"] == currency


@pytest.mark.parametrize(("currency", "amount"), [
    ("JPY", "1.25"), ("KWD", "1.2345"), ("USD", "NaN"), ("USD", "Infinity"),
    ("ZZZ", "1"), ("USD", "92233720368547758.08"),
    ("USD", "1.000000000000000000000000000001"),
])
def test_invalid_money_does_not_create_a_ledger(
    tmp_path: Path, currency: str, amount: str,
) -> None:
    root = tmp_path / "ledger"
    with pytest.raises(ValueError):
        service.manual_add(date="2026-06-01", amount=amount, currency=currency,
                           description="Purchase", category="Food", root=root)
    assert not root.exists()


def test_currency_correction_preserves_major_value_without_fx(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    row = service.manual_add(date="2026-06-01", amount="-12.34", currency="EUR",
                             description="Purchase", category="Food", root=root)["transaction"]
    corrected = service.manual_edit(row["id"], currency="KWD", root=root)["transaction"]
    assert corrected["amount"] == "-12.340"
    saved = store.get_transaction(row["id"], path=config.db_path(root))
    assert saved is not None
    assert (saved.amount_minor, saved.amount_exponent) == (-12340, 3)
    with pytest.raises(ValueError):
        service.manual_edit(row["id"], currency="JPY", root=root)
    assert store.get_transaction(row["id"], path=config.db_path(root)) == saved


def test_reports_and_merchant_totals_never_add_different_currencies(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    config.init_data_dir(root)
    rows = [
        _row("JPY", -1250, id="j-spend", kind="expense", is_expense=True,
             category="Food", merchant_normalized="SHARED"),
        _row("JPY", 3000, id="j-income", kind="income", is_expense=False),
        _row("JPY", 10000, id="j-transfer", kind="transfer", is_expense=False),
        _row("KWD", -12345, id="k-spend", kind="expense", is_expense=True,
             category="Food", merchant_normalized="SHARED"),
        _row("KWD", -3210, id="k-spend2", kind="expense", is_expense=True,
             category="Travel", merchant_normalized="SHARED"),
    ]
    store.upsert_transactions(rows, path=config.db_path(root))
    report = service.month_breakdown("2026-06", root=root)["breakdown"]
    assert not {"income", "expenses", "net", "by_category", "transactions"} & report.keys()
    assert (report["transaction_count"], report["expense_count"]) == (5, 3)
    groups = report["by_currency"]
    assert set(groups) == {"JPY", "KWD"}
    assert (groups["JPY"]["income"], groups["JPY"]["expenses"], groups["JPY"]["net"]) == (
        "3000", "1250", "1750",
    )
    assert (groups["KWD"]["income"], groups["KWD"]["expenses"], groups["KWD"]["net"]) == (
        "0.000", "15.555", "-15.555",
    )
    assert groups["KWD"]["by_category"] == {"Food": "12.345", "Travel": "3.210"}
    assert breakdown.compute_merchant_spend_by_currency(rows) == {
        "JPY": {"Food": {"SHARED": "1250"}},
        "KWD": {"Food": {"SHARED": "12.345"}, "Travel": {"SHARED": "3.210"}},
    }


def test_currency_group_preserves_legacy_fractional_value() -> None:
    rows = [_row("JPY", -100, id="native", kind="expense", is_expense=True),
            _row("JPY", -125, id="legacy", amount_exponent=2,
                 kind="expense", is_expense=True)]
    group = breakdown.compute_month_breakdown("2026-06", rows).by_currency["JPY"]
    assert (group.expenses, group.amount_exponent) == ("101.25", 2)


def test_empty_month_has_no_invented_currency_or_combined_money() -> None:
    report = breakdown.compute_month_breakdown("2026-06", [])
    assert report.by_currency == {}
    assert (report.transaction_count, report.expense_count, report.pending_review) == (0, 0, 0)


def test_rule_bounds_use_declared_currency_and_native_precision(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    stored = service.rule_add("PAY", "Food", "expense", direction="out", currency="KWD",
                              min_amount="12.340", max_amount="12.350", root=root)["rule"]
    assert (stored["currency"], stored["amount_exponent"], stored["min_amount_minor"]) == (
        "KWD", 3, 12340,
    )
    rule = store.list_user_rules(path=config.db_path(root))[0]
    kwd = _row("KWD", -12345, description="PAY")
    usd = _row("USD", -1234, description="PAY")
    assert match_user_rule(kwd, [rule], text="PAY") == rule
    assert match_user_rule(usd, [rule], text="PAY") is None


def test_new_bounded_rule_captures_default_currency_once(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    config.set_config_value("currency", "KWD", root=root)
    service.rule_add("PAY", "Food", "expense", min_amount="1.001", root=root)
    config.set_config_value("currency", "JPY", root=root)
    rule = store.list_user_rules(path=config.db_path(root))[0]
    assert (rule.currency, rule.amount_exponent, rule.min_amount_minor) == ("KWD", 3, 1001)


def test_legacy_bounds_need_currency_confirmation_not_a_guessed_unit() -> None:
    rule = UserRule(pattern="PAY", category="Food", kind="expense", min_amount_minor=100)
    with pytest.raises(ValueError, match="currency"):
        match_user_rule(_row("BRL", -100, description="PAY"), [rule], text="PAY")
    assert (rule.currency, rule.min_amount_minor, rule.amount_exponent) == (None, 100, 2)


@pytest.mark.parametrize("operation", ["breakdown", "pdf"])
def test_report_refuses_partial_months_at_the_row_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    root = tmp_path / "ledger"
    config.init_data_dir(root)
    store.upsert_transactions([_row("BRL", -100, id=f"row-{index}") for index in range(3)],
                              path=config.db_path(root))
    monkeypatch.setattr(breakdown, "DEFAULT_MONTH_LIMIT", 2)
    with pytest.raises(ValueError, match="limit"):
        if operation == "breakdown":
            service.month_breakdown("2026-06", root=root)
        else:
            service.export_pdf("2026-06", root=root)
    assert not list((root / "exports").glob("*.pdf"))


@pytest.mark.parametrize(("amount", "currency"), [
    ("1e-1000100", "USD"), ("-1e-1000100", "JPY"),
])
def test_tiny_nonzero_amounts_never_underflow_to_zero(amount: str, currency: str) -> None:
    with pytest.raises(ValueError):
        to_minor(amount, currency)


def test_tiny_rule_bound_is_rejected_without_creating_a_ledger(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    with pytest.raises(ValueError):
        service.rule_add("PAY", "Food", "expense", min_amount="1e-1000100",
                         currency="USD", root=root)
    assert not root.exists()


def test_money_values_ignore_ambient_decimal_rounding_context() -> None:
    with localcontext() as context:
        context.prec = 2
        row = _row("KWD", -12345, kind="expense", is_expense=True)
        assert row.amount == Decimal("-12.345")
        assert to_minor("12.345", "KWD") == 12345
        report = breakdown.compute_month_breakdown("2026-06", [row, row])
        assert report.by_currency["KWD"].expenses == "24.690"


def test_store_rejects_invalid_money_copies_without_partial_batch_writes(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    valid = _row("BRL", 100)
    invalid = valid.model_copy(update={"id": "invalid", "amount_minor": 1.5})
    with pytest.raises(ValueError):
        store.upsert_transactions([valid, invalid], path=path)
    assert store.list_transactions(path=path) == []


def test_manual_duplicate_checks_compare_values_not_encodings(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    config.init_data_dir(root)
    store.upsert_transactions([_row("JPY", -100, id="legacy", source_kind="manual",
                                   description="Purchase", amount_exponent=2)],
                              path=config.db_path(root))
    with pytest.raises(ValueError, match="already exists"):
        service.manual_add(date="2026-06-01", amount="-1", currency="JPY",
                           description="Purchase", category="Food", root=root)
