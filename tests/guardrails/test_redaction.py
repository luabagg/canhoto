"""Guardrail tests for transaction → ReviewItem redaction."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from canhoto.core.models import AgentViewConfig, ReviewItem
from canhoto.core.redaction import merchant_display, to_review_item

FORBIDDEN_REVIEW_FIELDS = {
    "description",
    "source_file",
    "operation_id",
    "running_balance",
    "account_id",
    "metadata",
    "merchant_raw",
}

# Unique canaries that must never appear in redacted agent output.
CANARY_DESCRIPTION = "CANARY_FULL_DESCRIPTION_LEAK_xyz"
CANARY_SOURCE_FILE = "/home/secret/CANARY_SOURCE_PATH_xyz.pdf"
CANARY_OPERATION_ID = "CANARY_OP_ID_xyz"
CANARY_RUNNING_BALANCE = "CANARY_BALANCE_999999.99"
CANARY_ACCOUNT_ID = "CANARY_ACCOUNT_ID_xyz"
CANARY_METADATA = "CANARY_METADATA_SECRET_xyz"
CANARY_MERCHANT_RAW = "CANARY_MERCHANT_RAW_xyz"


def _hostile_transaction(**overrides: object) -> SimpleNamespace:
    base = dict(
        id="tx-hostile-1",
        date=date(2026, 7, 15),
        amount=-42.5,
        currency="BRL",
        description=CANARY_DESCRIPTION,
        source_file=CANARY_SOURCE_FILE,
        operation_id=CANARY_OPERATION_ID,
        running_balance=CANARY_RUNNING_BALANCE,
        account_id=CANARY_ACCOUNT_ID,
        metadata={"note": CANARY_METADATA, "raw": CANARY_DESCRIPTION},
        merchant_raw=CANARY_MERCHANT_RAW,
        merchant_normalized="Cafe Central",
        source_kind="card",
        institution="Mercado Pago",
        category="Eating",
        kind="expense",
        confidence=0.4,
        review_reason="low_confidence",
        installment="2/12",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _serialized_blob(item: ReviewItem) -> str:
    return item.model_dump_json()


def test_merchant_display_prefers_normalized() -> None:
    tx = _hostile_transaction()
    assert merchant_display(tx) == "Cafe Central"


def test_merchant_display_falls_back_to_raw_when_normalized_missing() -> None:
    tx = _hostile_transaction(merchant_normalized=None)
    assert merchant_display(tx) == CANARY_MERCHANT_RAW


def test_to_review_item_shape_and_safe_fields() -> None:
    view = AgentViewConfig()
    item = to_review_item(_hostile_transaction(), view)

    assert isinstance(item, ReviewItem)
    assert item.id == "tx-hostile-1"
    assert item.date == "2026-07-15"
    assert item.amount == "-42.50"
    assert item.currency == "BRL"
    assert item.merchant_display == "Cafe Central"
    assert item.source_kind == "card"
    assert item.institution == "Mercado Pago"
    assert item.current_category == "Eating"
    assert item.current_kind == "expense"
    assert item.confidence == 0.4
    assert item.review_reason == "low_confidence"
    assert item.installment == "2/12"


def test_to_review_item_never_includes_forbidden_field_names() -> None:
    item = to_review_item(_hostile_transaction(), AgentViewConfig())
    assert FORBIDDEN_REVIEW_FIELDS.isdisjoint(set(item.model_dump()))


def test_to_review_item_never_leaks_hostile_strings() -> None:
    item = to_review_item(_hostile_transaction(), AgentViewConfig())
    blob = _serialized_blob(item)
    for canary in (
        CANARY_DESCRIPTION,
        CANARY_SOURCE_FILE,
        CANARY_OPERATION_ID,
        CANARY_RUNNING_BALANCE,
        CANARY_ACCOUNT_ID,
        CANARY_METADATA,
        CANARY_MERCHANT_RAW,
    ):
        assert canary not in blob, f"leaked canary into review item: {canary}"


def test_to_review_item_omits_amount_when_disabled() -> None:
    view = AgentViewConfig(include_amounts_in_review=False)
    item = to_review_item(_hostile_transaction(), view)
    assert item.amount is None
    assert "42.50" not in _serialized_blob(item)
    assert "42.5" not in _serialized_blob(item)


def test_to_review_item_omits_institution_when_disabled() -> None:
    view = AgentViewConfig(include_institution=False)
    item = to_review_item(_hostile_transaction(), view)
    assert item.institution is None
    assert "Mercado Pago" not in _serialized_blob(item)


def test_to_review_item_formats_date_string_input() -> None:
    tx = _hostile_transaction(date="2026-01-02")
    item = to_review_item(tx, AgentViewConfig())
    assert item.date == "2026-01-02"


def test_to_review_item_stringifies_enum_like_values() -> None:
    tx = _hostile_transaction(
        source_kind=SimpleNamespace(value="account"),
        category=SimpleNamespace(value="Groceries"),
        kind=SimpleNamespace(value="income"),
        institution=SimpleNamespace(value="itau"),
    )
    item = to_review_item(tx, AgentViewConfig())
    assert item.source_kind == "account"
    assert item.current_category == "Groceries"
    assert item.current_kind == "income"
    assert item.institution == "itau"
