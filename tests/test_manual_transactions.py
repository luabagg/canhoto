"""Manual transactions: rows no statement shows, added and kept by hand."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from canhoto import service
from canhoto.cli import main as cli_main
from canhoto.core import config as core_config
from canhoto.core.models import LedgerTransaction
from canhoto.core.store import ensure_schema, get_transaction, upsert_transactions


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "canhoto-home"
    core_config.init_data_dir(path)
    return path


def _add_ipva(root: Path, **overrides: str) -> str:
    fields = {
        "date": "2026-09-17",
        "amount": "-3080.00",
        "description": "Pix enviado Example Tax Office",
        "category": "Taxes",
        "merchant": "IPVA",
        "account": "cofrinho",
        "note": "Paid from the cofrinho",
    }
    fields.update(overrides)
    result = service.manual_add(root=root, **fields)
    return str(result["transaction"]["id"])


def _seed_statement_row(root: Path) -> None:
    db = core_config.db_path(root)
    ensure_schema(db)
    upsert_transactions(
        [
            LedgerTransaction(
                id="card-1",
                date=date(2026, 9, 5),
                amount_minor=-1000,
                description="Cafe",
                source_kind="card",
                category="Restaurants",
                kind="expense",
                is_expense=True,
                needs_review=False,
                month="2026-09",
            )
        ],
        path=db,
    )


def test_add_with_category_counts_in_its_month(root: Path) -> None:
    tx_id = _add_ipva(root)

    tx = get_transaction(tx_id, path=core_config.db_path(root))
    assert tx is not None
    assert tx.amount_minor == -308000
    assert tx.source_kind == "manual"
    assert tx.classification_source == "manual"
    assert tx.needs_review is False
    assert (tx.category, tx.kind, tx.is_expense) == ("Taxes", "expense", True)
    assert tx.merchant_normalized == "IPVA"
    assert tx.metadata == {"note": "Paid from the cofrinho", "manual_merchant": True}
    breakdown = service.month_breakdown("2026-09", root=root)["breakdown"]
    assert breakdown["by_category"] == {"Taxes": "3080.00"}


def test_add_without_category_runs_user_rules(root: Path) -> None:
    service.rule_add(
        pattern="PIX ENVIADO LANDLORD", category="Housing", kind="expense", root=root
    )

    result = service.manual_add(
        date="2026-09-05", amount="-715", description="Pix enviado Landlord", root=root
    )

    assert result["transaction"]["category"] == "Housing"
    assert result["transaction"]["needs_review"] is False


def test_add_without_category_or_matching_rule_waits_for_review(root: Path) -> None:
    service.manual_add(
        date="2026-09-05", amount="-12.50", description="Feira do bairro", root=root
    )

    assert service.review_batch("2026-09", root=root)["count"] == 1


def test_manual_add_resolves_and_persists_currency(root: Path) -> None:
    core_config.set_config_value("currency", "EUR", global_scope=True)
    global_row = service.manual_add(
        date="2026-09-05", amount="-12.50", description="Global default", category="Food", root=root
    )["transaction"]
    core_config.set_config_value("currency", "USD", root=root)
    local_row = service.manual_add(
        date="2026-09-05", amount="-12.50", description="Local override", category="Food", root=root
    )["transaction"]
    explicit_row = service.manual_add(
        date="2026-09-05", amount="-12.50", description="Explicit currency", category="Food",
        currency=" brl ", root=root,
    )["transaction"]

    currencies = [row["currency"] for row in (global_row, local_row, explicit_row)]
    assert currencies == ["EUR", "USD", "BRL"]
    rows = service.manual_list(root=root)["transactions"]
    assert {row["id"]: row["currency"] for row in rows} == {
        global_row["id"]: "EUR", local_row["id"]: "USD", explicit_row["id"]: "BRL",
    }
    stored = get_transaction(global_row["id"], path=core_config.db_path(root))
    assert stored is not None
    assert (stored.currency, stored.amount_minor) == ("EUR", -1250)


def test_config_changes_do_not_reinterpret_existing_manual_currency(root: Path) -> None:
    core_config.set_config_value("currency", "EUR", global_scope=True)
    tx_id = _add_ipva(root)
    core_config.set_config_value("currency", "USD", global_scope=True)
    core_config.set_config_value("currency", "BRL", root=root)

    row = service.manual_edit(tx_id, amount="-3100", root=root)["transaction"]

    assert (row["currency"], row["amount"]) == ("EUR", "-3100.00")
    stored = get_transaction(tx_id, path=core_config.db_path(root))
    assert stored is not None
    assert stored.currency == "EUR"


def test_explicit_currency_edit_corrects_code_without_converting_amount(root: Path) -> None:
    tx_id = _add_ipva(root, currency="EUR")

    row = service.manual_edit(tx_id, currency=" usd ", root=root)["transaction"]

    assert (row["currency"], row["amount"], row["category"]) == ("USD", "-3080.00", "Taxes")


def test_manual_duplicates_include_currency(root: Path) -> None:
    _add_ipva(root, currency="EUR")
    _add_ipva(root, currency="USD")

    with pytest.raises(ValueError, match="already exists"):
        _add_ipva(root, currency="eur")

    assert service.manual_list(root=root)["count"] == 2


def test_invalid_manual_currency_does_not_create_or_change_a_row(root: Path) -> None:
    with pytest.raises(ValueError, match="currency"):
        _add_ipva(root, currency="EURO")
    assert service.manual_list(root=root)["count"] == 0
    tx_id = _add_ipva(root, currency="EUR")
    before = get_transaction(tx_id, path=core_config.db_path(root))
    with pytest.raises(ValueError, match="currency"):
        service.manual_edit(tx_id, amount="-999", currency="12A", root=root)
    assert get_transaction(tx_id, path=core_config.db_path(root)) == before


def test_cli_manual_currency_add_edit_and_list(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    assert cli_main([
        "manual", "add", "--date", "2026-09-05", "--amount", "-10",
        "--description", "Example purchase", "--category", "Food", "--currency", "eur",
    ]) == 0
    original = json.loads(capsys.readouterr().out)["transaction"]
    assert original["currency"] == "EUR"
    assert cli_main(["manual", "edit", "--id", original["id"], "--currency", "USD"]) == 0
    assert json.loads(capsys.readouterr().out)["transaction"]["currency"] == "USD"
    assert cli_main(["manual", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["transactions"][0]["currency"] == "USD"


def test_positive_amount_is_income(root: Path) -> None:
    result = service.manual_add(
        date="2026-09-05", amount="150", description="Cash gift", category="Income", root=root
    )

    assert result["transaction"]["kind"] == "income"
    assert result["transaction"]["is_expense"] is False


def test_adding_the_same_entry_twice_is_refused(root: Path) -> None:
    _add_ipva(root)

    with pytest.raises(ValueError, match="already exists"):
        _add_ipva(root)


@pytest.mark.parametrize(
    ("day", "amount"),
    [("2026-13-01", "-10"), ("17/09/2026", "-10"), ("2026-09-17", "0"), ("2026-09-17", "1.234")],
)
def test_invalid_date_or_amount_is_refused(root: Path, day: str, amount: str) -> None:
    with pytest.raises(ValueError):
        service.manual_add(date=day, amount=amount, description="x", root=root)


@pytest.mark.parametrize("kind", ["expnese", ""])
def test_invalid_kind_on_add_does_not_create_a_row(root: Path, kind: str) -> None:
    with pytest.raises(ValueError, match="kind"):
        _add_ipva(root, kind=kind)

    assert service.manual_list(root=root)["count"] == 0


def test_invalid_kind_on_edit_does_not_change_the_row(root: Path) -> None:
    tx_id = _add_ipva(root)
    before = get_transaction(tx_id, path=core_config.db_path(root))

    with pytest.raises(ValueError, match="kind"):
        service.manual_edit(tx_id, kind="expnese", amount="-999", root=root)

    assert get_transaction(tx_id, path=core_config.db_path(root)) == before


def test_explicit_kind_is_normalized_and_counts_as_spending(root: Path) -> None:
    tx_id = _add_ipva(root, kind=" Expense ")
    service.manual_edit(tx_id, kind=" EXPENSE ", root=root)

    row = service.manual_list(root=root)["transactions"][0]
    assert (row["kind"], row["is_expense"]) == ("expense", True)
    assert service.month_breakdown("2026-09", root=root)["breakdown"]["expenses"] == "3080.00"


def test_list_shows_only_manual_rows(root: Path) -> None:
    _seed_statement_row(root)
    tx_id = _add_ipva(root)
    _add_ipva(root, date="2026-10-02", description="Other", amount="-5")

    september = service.manual_list(month="2026-09", root=root)["transactions"]
    everything = service.manual_list(root=root)["transactions"]

    assert [tx["id"] for tx in september] == [tx_id]
    assert september[0]["note"] == "Paid from the cofrinho"
    assert len(everything) == 2


def test_edit_changes_facts_and_keeps_the_id(root: Path) -> None:
    tx_id = _add_ipva(root)

    service.manual_edit(tx_id, date="2026-10-01", amount="-3100", category="Transport", root=root)

    tx = get_transaction(tx_id, path=core_config.db_path(root))
    assert tx is not None
    assert (tx.date, tx.month, tx.amount_minor) == (date(2026, 10, 1), "2026-10", -310000)
    assert tx.category == "Transport"
    assert tx.merchant_normalized == "IPVA"
    assert tx.metadata == {"note": "Paid from the cofrinho", "manual_merchant": True}


def test_edit_outside_old_rule_returns_to_review(root: Path) -> None:
    service.rule_add(
        pattern="LANDLORD", category="Housing", kind="expense",
        min_amount="5", max_amount="15", root=root,
    )
    original = service.manual_add(
        date="2026-09-05", amount="-10", description="LANDLORD", root=root
    )["transaction"]

    row = service.manual_edit(
        original["id"], amount="-100", description="OTHER", root=root
    )["transaction"]

    assert row["category"] == "uncategorized"
    assert row["needs_review"] is True
    assert row["merchant"] == "OTHER"
    tx = get_transaction(row["id"], path=core_config.db_path(root))
    assert tx is not None
    assert tx.user_rule_id is None
    assert tx.classification_source == "parser"
    assert service.review_batch("2026-09", root=root)["count"] == 1


def test_edit_applies_a_new_rule_instead_of_old_classification(root: Path) -> None:
    service.rule_add(pattern="LANDLORD", category="Housing", kind="expense", root=root)
    service.rule_add(pattern="SALARY", category="Pay", kind="income", direction="in", root=root)
    original = service.manual_add(
        date="2026-09-05", amount="-10", description="LANDLORD", root=root
    )["transaction"]

    row = service.manual_edit(
        original["id"], amount="100", description="SALARY", root=root
    )["transaction"]

    assert (row["category"], row["kind"], row["is_expense"]) == ("Pay", "income", False)
    assert row["merchant"] == "SALARY"
    assert row["needs_review"] is False


def test_edit_replaces_an_old_builtin_classification(root: Path) -> None:
    original = service.manual_add(
        date="2026-09-05", amount="-10", description="COFRINHO", root=root
    )["transaction"]
    assert original["kind"] == "internal_transfer"

    row = service.manual_edit(
        original["id"], description="PAGAMENTO FATURA", root=root
    )["transaction"]

    assert (row["kind"], row["is_expense"], row["needs_review"]) == ("card_payment", False, False)
    assert row["merchant"] == "PAGAMENTO FATURA"


def test_edit_keeps_explicit_transfer_kind_when_no_rule_matches(root: Path) -> None:
    original = service.manual_add(
        date="2026-09-05", amount="-10", description="COFRINHO", kind="transfer", root=root
    )["transaction"]

    row = service.manual_edit(original["id"], description="OTHER", root=root)["transaction"]

    assert row["kind"] == "transfer"
    assert row["is_expense"] is False
    assert row["needs_review"] is True
    assert service.month_breakdown("2026-09", root=root)["breakdown"]["expenses"] == "0.00"


def test_edit_preserves_human_category_and_explicit_merchant(root: Path) -> None:
    tx_id = _add_ipva(root)

    row = service.manual_edit(tx_id, description="Corrected payment", root=root)["transaction"]

    assert (row["category"], row["merchant"], row["needs_review"]) == ("Taxes", "IPVA", False)


def test_edit_preserves_explicit_merchant_on_automatically_classified_row(root: Path) -> None:
    service.rule_add(pattern="LANDLORD", category="Housing", kind="expense", root=root)
    original = service.manual_add(
        date="2026-09-05", amount="-10", description="LANDLORD", merchant="Building", root=root
    )["transaction"]

    row = service.manual_edit(original["id"], description="OTHER", root=root)["transaction"]

    assert row["merchant"] == "Building"
    assert row["category"] == "uncategorized"
    assert row["needs_review"] is True


@pytest.mark.parametrize(
    ("amount", "edited_amount", "kind", "income", "expenses"),
    [("-10", "10", "income", "10.00", "0.00"), ("10", "-10", "expense", "0.00", "10.00")],
)
def test_implicit_kind_follows_amount_sign_without_changing_human_category(
    root: Path, amount: str, edited_amount: str, kind: str, income: str, expenses: str
) -> None:
    original = service.manual_add(
        date="2026-09-05", amount=amount, description="Example payment", category="Misc", root=root
    )["transaction"]

    row = service.manual_edit(original["id"], amount=edited_amount, root=root)["transaction"]

    assert row["category"] == "Misc"
    assert row["kind"] == kind
    assert row["is_expense"] == (kind == "expense")
    breakdown = service.month_breakdown("2026-09", root=root)["breakdown"]
    assert (breakdown["income"], breakdown["expenses"]) == (income, expenses)


def test_explicit_kind_and_merchant_from_review_survive_fact_edits(root: Path) -> None:
    original = service.manual_add(
        date="2026-09-05", amount="-10", description="Example payment", root=root
    )["transaction"]
    service.set_categories(
        [{"id": original["id"], "category": "Reserve", "kind": "transfer", "is_expense": False,
          "merchant_normalized": "Reserve", "needs_review": False}],
        root=root,
    )

    row = service.manual_edit(
        original["id"], amount="10", description="Changed payment", root=root
    )["transaction"]

    assert (row["category"], row["kind"], row["merchant"]) == ("Reserve", "transfer", "Reserve")
    assert row["is_expense"] is False


def test_note_edit_does_not_reclassify_a_row(root: Path) -> None:
    rule = service.rule_add(pattern="LANDLORD", category="Housing", kind="expense", root=root)
    original = service.manual_add(
        date="2026-09-05", amount="-10", description="LANDLORD", root=root
    )["transaction"]
    service.rule_remove(rule["rule"]["id"], root=root)

    row = service.manual_edit(original["id"], note="Updated note", root=root)["transaction"]

    assert row == {**original, "note": "Updated note"}


def test_edit_without_changes_is_refused(root: Path) -> None:
    tx_id = _add_ipva(root)

    with pytest.raises(ValueError, match="nothing to change"):
        service.manual_edit(tx_id, root=root)


def test_remove_deletes_the_row(root: Path) -> None:
    tx_id = _add_ipva(root)

    service.manual_remove(tx_id, root=root)

    assert get_transaction(tx_id, path=core_config.db_path(root)) is None
    assert service.month_breakdown("2026-09", root=root)["breakdown"]["expenses"] == "0.00"


@pytest.mark.parametrize("action", ["edit", "remove"])
def test_statement_rows_cannot_be_edited_or_removed(root: Path, action: str) -> None:
    _seed_statement_row(root)

    with pytest.raises(ValueError, match="not a manual transaction"):
        if action == "edit":
            service.manual_edit("card-1", category="Other", root=root)
        else:
            service.manual_remove("card-1", root=root)
    assert get_transaction("card-1", path=core_config.db_path(root)) is not None


def test_unknown_id_is_refused(root: Path) -> None:
    with pytest.raises(ValueError, match="no transaction"):
        service.manual_remove("manual-missing", root=root)


def test_cli_crud(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    base = ["--date", "2026-09-17", "--description", "Pix enviado Example Tax Office"]

    assert cli_main(["manual", "add", *base, "--amount", "-3080.00", "--category", "Taxes"]) == 0
    tx_id = service.manual_list(root=root)["transactions"][0]["id"]
    assert cli_main(["manual", "list", "--month", "2026-09"]) == 0
    assert cli_main(["manual", "edit", "--id", tx_id, "--amount", "-3000"]) == 0
    assert service.month_breakdown("2026-09", root=root)["breakdown"]["expenses"] == "3000.00"
    assert cli_main(["manual", "remove", "--id", tx_id]) == 0
    assert service.manual_list(root=root)["transactions"] == []
