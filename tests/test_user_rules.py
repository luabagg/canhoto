"""User classification rules: model, matching, store, categorize, service."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from canhoto import service
from canhoto.core import config as core_config
from canhoto.core import store as core_store
from canhoto.core.breakdown import _EXCLUDED_SPEND_KINDS
from canhoto.core.categorize import apply_rules, run_rules_for_month
from canhoto.core.models import (
    USER_RULE_KINDS,
    ClassificationPatch,
    ClassificationSource,
    LedgerTransaction,
    UserRule,
)
from canhoto.core.store import (
    apply_classifications,
    connect,
    get_transaction,
    upsert_transactions,
)
from canhoto.core.user_rules import amount_bound_to_minor, match_user_rule
from pydantic import ValidationError


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    core_config.init_data_dir(root)
    return root


def _tx(
    tx_id: str,
    *,
    description: str = "PIX RECEBIDO ACME LTDA",
    amount_minor: int = 123456,
    source_kind: str = "account",
    category: str = "Transfers",
    kind: str = "transfer",
    is_expense: bool = False,
    needs_review: bool = False,
    classification_source: ClassificationSource = "parser",
) -> LedgerTransaction:
    return LedgerTransaction(
        id=tx_id,
        date=date(2026, 6, 10),
        amount_minor=amount_minor,
        currency="BRL",
        description=description,
        merchant_raw=description,
        source_kind=source_kind,
        category=category,
        kind=kind,
        is_expense=is_expense,
        needs_review=needs_review,
        month="2026-06",
        classification_source=classification_source,
    )


def test_new_rows_default_to_parser_source(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.classification_source == "parser"
    assert stored.user_rule_id is None


def test_reingest_with_preserve_keeps_provenance(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    apply_classifications(
        [ClassificationPatch(id="a1", category="Income", classification_source="manual")],
        path=db,
    )
    upsert_transactions([_tx("a1")], path=db, preserve_classification=True)
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.classification_source == "manual"


def _insert_rule(db: Path) -> int:
    with connect(db) as conn:
        cur = conn.execute(
            "INSERT INTO user_rules (pattern, category, kind) VALUES ('ACME', 'Income', 'income')"
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


def test_patch_with_source_rewrites_rule_link(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    rule_id = _insert_rule(db)
    apply_classifications(
        [
            ClassificationPatch(
                id="a1", category="Income", classification_source="user_rule", user_rule_id=rule_id
            )
        ],
        path=db,
    )
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.classification_source == "user_rule"
    assert stored.user_rule_id == rule_id

    apply_classifications(
        [ClassificationPatch(id="a1", category="Food", classification_source="manual")],
        path=db,
    )
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.category == "Food"
    assert stored.classification_source == "manual"
    assert stored.user_rule_id is None


def test_link_only_patch_keeps_source(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1", classification_source="user_rule")], path=db)
    rule_id = _insert_rule(db)
    apply_classifications([ClassificationPatch(id="a1", user_rule_id=rule_id)], path=db)
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.user_rule_id == rule_id
    assert stored.classification_source == "user_rule"


def _rule(**overrides: object) -> UserRule:
    values: dict[str, object] = {
        "pattern": r"PIX RECEBIDO ACME LTDA",
        "direction": "in",
        "category": "Income",
        "kind": "income",
        "currency": "BRL",
    }
    values.update(overrides)
    return UserRule.model_validate(values)


def test_rule_kinds_match_what_breakdown_understands() -> None:
    assert USER_RULE_KINDS == _EXCLUDED_SPEND_KINDS | {"expense", "income"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"pattern": "("},
        {"pattern": "   "},
        {"category": " "},
        {"kind": "transfers"},
        {"direction": "sideways"},
        {"min_amount_minor": 500, "max_amount_minor": 100},
        {"min_amount_minor": -1},
        {"pattern": "a" * 201},
        {"kind": "income", "direction": "out"},
        {"kind": "expense", "direction": "in"},
    ],
)
def test_invalid_rules_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _rule(**overrides)


@pytest.mark.parametrize(
    ("raw", "expected"), [("Card", "card"), ("  ACCOUNT ", "account"), ("  ", None), (None, None)]
)
def test_source_kind_is_normalized(raw: str | None, expected: str | None) -> None:
    assert _rule(source_kind=raw).source_kind == expected


def test_pattern_of_max_length_is_accepted() -> None:
    assert len(_rule(pattern="a" * 200).pattern) == 200


def test_expense_kind_derives_is_expense() -> None:
    assert _rule(kind="expense", direction="out").is_expense is True
    assert _rule().is_expense is False


def test_match_respects_direction_amount_and_source() -> None:
    salary = _rule(min_amount_minor=120000, max_amount_minor=130000, source_kind="account")
    tx = _tx("a1", amount_minor=123456)
    text = tx.description
    assert match_user_rule(tx, [salary], text=text) == salary
    assert match_user_rule(_tx("a2", amount_minor=-123456), [salary], text=text) is None
    assert match_user_rule(_tx("a3", amount_minor=800000), [salary], text=text) is None
    assert match_user_rule(_tx("a4", source_kind="card"), [salary], text=text) is None


def test_amount_bounds_are_inclusive() -> None:
    rule = _rule(min_amount_minor=1000, max_amount_minor=2000)
    for amount, expected in [(999, False), (1000, True), (2000, True), (2001, False)]:
        tx = _tx("a1", amount_minor=amount)
        assert (match_user_rule(tx, [rule], text=tx.description) is not None) is expected


def test_direction_out_matches_only_negative_amounts() -> None:
    rule = _rule(direction="out", kind="expense")
    debit, credit = _tx("a1", amount_minor=-500), _tx("a2", amount_minor=500)
    assert match_user_rule(debit, [rule], text=debit.description) == rule
    assert match_user_rule(credit, [rule], text=credit.description) is None


def test_direction_any_matches_both_signs() -> None:
    rule = _rule(direction="any")
    for amount in (-500, 500):
        tx = _tx("a1", amount_minor=amount)
        assert match_user_rule(tx, [rule], text=tx.description) == rule


def test_first_rule_in_given_order_wins() -> None:
    narrow = _rule(id=1, category="Income", min_amount_minor=120000, max_amount_minor=130000)
    broad = _rule(id=2, category="Transfers", kind="transfer")
    tx = _tx("a1")
    assert match_user_rule(tx, [narrow, broad], text=tx.description) == narrow


def test_pattern_is_case_insensitive() -> None:
    tx = _tx("a1", description="Pix recebido Acme Ltda")
    assert match_user_rule(tx, [_rule()], text=tx.description) is not None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("700", 70000), ("1234.56", 123456), ("0.5", 50)],
)
def test_amount_bound_to_minor(value: str | None, expected: int | None) -> None:
    assert amount_bound_to_minor(value) == expected


@pytest.mark.parametrize("value", ["-1", "abc", "1.001", "NaN", "sNaN", "Infinity"])
def test_amount_bound_rejects_bad_values(value: str) -> None:
    with pytest.raises(ValueError):
        amount_bound_to_minor(value)


def test_store_round_trip_orders_by_priority(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    late = core_store.add_user_rule(_rule(priority=50, note="second"), path=db)
    early = core_store.add_user_rule(_rule(priority=10, note="first"), path=db)
    rules = core_store.list_user_rules(path=db)
    assert [r.id for r in rules] == [early.id, late.id]
    assert core_store.user_rule_notes([late.id or 0], path=db) == {late.id: "second"}
    assert core_store.delete_user_rule(early.id or 0, path=db) is True
    assert core_store.delete_user_rule(early.id or 0, path=db) is False


def test_deleting_a_rule_unlinks_rows(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    rule = core_store.add_user_rule(_rule(), path=db)
    upsert_transactions([_tx("a1")], path=db)
    apply_classifications(
        [
            ClassificationPatch(
                id="a1",
                category="Income",
                classification_source="user_rule",
                user_rule_id=rule.id,
            )
        ],
        path=db,
    )
    core_store.delete_user_rule(rule.id or 0, path=db)
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.user_rule_id is None
    assert stored.category == "Income"


def test_user_rule_reclassifies_settled_parser_row() -> None:
    rule = _rule(id=7, note="company pay")
    out = apply_rules(_tx("a1"), user_rules=[rule])
    assert (out.category, out.kind, out.is_expense) == ("Income", "income", False)
    assert out.classification_source == "user_rule"
    assert out.user_rule_id == 7
    assert out.needs_review is False


def test_user_rule_never_overwrites_manual_rows() -> None:
    manual = _tx("a1", category="Gifts", kind="expense", classification_source="manual")
    out = apply_rules(manual, user_rules=[_rule(id=7)])
    assert out == manual


def test_user_rule_runs_before_builtin_rules() -> None:
    card_payment = _tx(
        "a1",
        description="PAGAMENTO DE FATURA ACME",
        amount_minor=-5000,
        needs_review=True,
        category="",
        kind="",
    )
    rule = _rule(id=3, pattern="ACME", direction="out", category="Loans", kind="transfer")
    out = apply_rules(card_payment, user_rules=[rule])
    assert out.category == "Loans"


def test_confirm_rule_keeps_row_in_review() -> None:
    out = apply_rules(_tx("a1"), user_rules=[_rule(id=9, needs_review=True)])
    assert out.needs_review is True
    assert out.review_reason == "user_rule_confirm"


def test_builtin_rule_tags_its_source() -> None:
    pending = _tx(
        "a1",
        description="PAGAMENTO DA FATURA CARTAO",
        amount_minor=-5000,
        needs_review=True,
        category="",
        kind="",
    )
    assert apply_rules(pending).classification_source == "builtin_rule"


def test_run_rules_applies_stored_rules_and_is_idempotent(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    core_store.add_user_rule(_rule(), path=db)
    upsert_transactions([_tx("a1"), _tx("a2", classification_source="manual")], path=db)

    first = run_rules_for_month("2026-06", path=db)
    second = run_rules_for_month("2026-06", path=db)

    assert first.user_rule_applied == 1
    assert second.applied == 0
    applied_row = get_transaction("a1", path=db)
    manual_row = get_transaction("a2", path=db)
    assert applied_row is not None
    assert manual_row is not None
    assert applied_row.category == "Income"
    assert manual_row.category == "Transfers"


def test_higher_priority_rule_takes_over_rule_owned_row(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    core_store.add_user_rule(_rule(priority=50), path=db)
    upsert_transactions([_tx("a1")], path=db)
    run_rules_for_month("2026-06", path=db)

    newer = core_store.add_user_rule(_rule(priority=10), path=db)
    second = run_rules_for_month("2026-06", path=db)

    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.user_rule_id == newer.id
    assert second.user_rule_applied == 1


def test_builtin_rules_skip_pending_manual_rows() -> None:
    manual = _tx(
        "a1",
        description="PAGAMENTO DA FATURA CARTAO",
        amount_minor=-5000,
        needs_review=True,
        category="uncategorized",
        kind="",
        classification_source="manual",
    )
    assert apply_rules(manual) == manual


def test_merchant_memory_skips_pending_manual_rows(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    manual = _tx(
        "a1",
        description="PADARIA CENTRAL",
        amount_minor=-5000,
        needs_review=True,
        category="",
        kind="",
        classification_source="manual",
    )
    upsert_transactions([manual], path=db)
    core_store.set_merchant_category("PADARIA CENTRAL", "food", path=db)

    result = run_rules_for_month("2026-06", path=db)

    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert result.applied == 0
    assert stored.category == ""
    assert stored.classification_source == "manual"


def test_service_rule_lifecycle(data_home: Path) -> None:
    added = service.rule_add(
        "PIX RECEBIDO ACME",
        "Income",
        "income",
        direction="in",
        min_amount="1200",
        max_amount="1300",
        note="company pay",
    )
    rule_id = added["rule"]["id"]
    listed = service.rule_list()
    assert listed["count"] == 1
    assert listed["rules"][0]["note"] == "company pay"
    assert listed["rules"][0]["min_amount_minor"] == 120000
    assert service.rule_remove(rule_id)["removed"] is True
    assert service.rule_list()["count"] == 0


def test_service_rule_add_rejects_unknown_kind(data_home: Path) -> None:
    with pytest.raises(ValueError):
        service.rule_add("ACME", "Transfers", "transfers")


def test_run_rules_reports_user_rule_count(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    service.rule_add("PIX RECEBIDO ACME", "Income", "income", direction="in")
    assert service.run_rules("2026-06")["user_rule_applied"] == 1


def test_set_categories_marks_rows_manual_and_ignores_spoofed_source(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    service.set_categories(
        [{"id": "a1", "category": "Gifts", "classification_source": "user_rule", "user_rule_id": 4}]
    )
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.classification_source == "manual"
    assert stored.user_rule_id is None


def test_review_batch_shows_rule_note_for_flagged_income(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1", amount_minor=900000)], path=db)
    service.rule_add(
        "PIX RECEBIDO ACME",
        "Income",
        "income",
        direction="in",
        min_amount="5000",
        needs_review=True,
        note="usually profit share; confirm",
    )
    service.run_rules("2026-06")
    items = service.review_batch("2026-06")["items"]
    assert [item["id"] for item in items] == ["a1"]
    assert items[0]["rule_note"] == "usually profit share; confirm"


def test_confirm_rule_beats_merchant_memory_and_is_stable(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    pending = _tx(
        "a1",
        description="PADARIA CENTRAL",
        amount_minor=-5000,
        source_kind="card",
        needs_review=True,
        category="",
        kind="",
        is_expense=True,
    ).model_copy(update={"merchant_normalized": "PADARIA CENTRAL"})
    upsert_transactions([pending], path=db)
    core_store.set_merchant_category("PADARIA CENTRAL", "food", path=db)
    service.rule_add(
        "PADARIA CENTRAL", "Groceries", "expense", direction="out", needs_review=True
    )

    first = run_rules_for_month("2026-06", path=db)
    stored = get_transaction("a1", path=db)
    assert first.applied == 1
    assert stored is not None
    assert stored.classification_source == "user_rule"
    assert stored.needs_review is True
    assert stored.review_reason == "user_rule_confirm"
    assert stored.category == "Groceries"

    assert run_rules_for_month("2026-06", path=db).applied == 0


def test_partial_patch_keeps_flagged_row_in_review_until_confirmed(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1", amount_minor=900000)], path=db)
    service.rule_add(
        "PIX RECEBIDO ACME", "Income", "income", direction="in", needs_review=True
    )
    service.run_rules("2026-06")

    service.set_categories([{"id": "a1", "category": "Income", "kind": "income"}])
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.classification_source == "manual"
    assert stored.needs_review is True
    assert [i["id"] for i in service.review_batch("2026-06")["items"]] == ["a1"]

    service.set_categories(
        [{"id": "a1", "needs_review": False, "review_reason": None}]
    )
    assert service.review_batch("2026-06")["items"] == []


def test_user_rule_fills_normalized_merchant_name() -> None:
    out = apply_rules(_tx("a1"), user_rules=[_rule(id=7)])
    assert out.merchant_normalized == "ACME LTDA"
