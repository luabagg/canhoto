"""Merchant category memory tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from canhoto import service
from canhoto.core import categorize as core_categorize
from canhoto.core import config as core_config
from canhoto.core.models import LedgerTransaction
from canhoto.core.store import (
    ensure_schema,
    get_merchant_category,
    get_transaction,
    upsert_transactions,
)
from canhoto.core.store import (
    set_merchant_category as store_set_merchant_category,
)


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    core_config.init_data_dir(root)
    return root


def _tx(
    tx_id: str,
    *,
    description: str = "PADARIA CENTRAL",
    merchant_normalized: str | None = "PADARIA CENTRAL",
    amount_minor: int = -2500,
    month: str = "2026-06",
    day: int = 10,
    category: str = "",
    kind: str = "",
    is_expense: bool = False,
    needs_review: bool = True,
    source_kind: str = "card",
) -> LedgerTransaction:
    return LedgerTransaction(
        id=tx_id,
        date=date(2026, 6, day),
        amount_minor=amount_minor,
        currency="BRL",
        description=description,
        merchant_raw=description,
        merchant_normalized=merchant_normalized,
        source_kind=source_kind,
        institution="Example",
        source_file="/tmp/stmt.txt",
        category=category,
        kind=kind,
        is_expense=is_expense,
        needs_review=needs_review,
        confidence=0.0,
        month=month,
    )


def test_is_learnable_merchant_key_skips_person_id_like() -> None:
    assert core_categorize.is_learnable_merchant_key("PADARIA CENTRAL") is True
    assert core_categorize.is_learnable_merchant_key("cafe-do-joao") is True
    # Empty / whitespace
    assert core_categorize.is_learnable_merchant_key("") is False
    assert core_categorize.is_learnable_merchant_key("   ") is False
    # Mostly digits / CPF-like
    assert core_categorize.is_learnable_merchant_key("12345678901") is False
    assert core_categorize.is_learnable_merchant_key("123.456.789-01") is False
    assert core_categorize.is_learnable_merchant_key("CPF 12345678901") is False
    # Digit-heavy person transfer leftovers
    assert core_categorize.is_learnable_merchant_key("12345678900 JOAO") is False


def test_set_and_recall_applies_after_rules(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    ensure_schema(db)

    upsert_transactions(
        [
            _tx(
                "tx-bakery",
                description="PADARIA CENTRAL LOJA 2",
                merchant_normalized="PADARIA CENTRAL",
                day=1,
            ),
            _tx(
                "tx-already",
                description="PADARIA CENTRAL LOJA 3",
                merchant_normalized="PADARIA CENTRAL",
                day=2,
                category="groceries",
                kind="expense",
                is_expense=True,
                needs_review=False,
            ),
        ],
        path=db,
        preserve_classification=False,
    )

    set_result = service.set_merchant_category("PADARIA CENTRAL", "food")
    assert set_result["ok"] is True
    assert set_result["learned"] is True
    assert get_merchant_category("PADARIA CENTRAL", path=db) == "food"

    run = service.run_rules("2026-06")
    assert run["ok"] is True
    assert run["merchant_memory_applied"] >= 1

    recalled = get_transaction("tx-bakery", path=db)
    assert recalled is not None
    assert recalled.category == "food"
    assert recalled.kind == "expense"
    assert recalled.is_expense is True
    assert recalled.needs_review is False
    assert recalled.confidence >= 0.7

    # Already-classified row is not overwritten by memory.
    kept = get_transaction("tx-already", path=db)
    assert kept is not None
    assert kept.category == "groceries"
    assert kept.needs_review is False


def test_set_merchant_category_skips_bad_keys(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    ensure_schema(db)

    result = service.set_merchant_category("123.456.789-01", "transfer")
    assert result["ok"] is True
    assert result["learned"] is False
    assert result["skipped_reason"] == "unlearnable_merchant_key"
    assert get_merchant_category("123.456.789-01", path=db) is None


def test_run_rules_applies_memory_from_store_only(tmp_path: Path) -> None:
    """Core path: rules first, then memory for still-pending rows."""
    db = tmp_path / "canhoto.db"
    ensure_schema(db)

    upsert_transactions(
        [
            _tx(
                "tx-mem",
                description="MERCADO BOM PRECO",
                merchant_normalized="MERCADO BOM PRECO",
                day=5,
            ),
            _tx(
                "tx-pay",
                description="PAGAMENTO DA FATURA CARTAO",
                merchant_normalized="PAGAMENTO DA FATURA CARTAO",
                amount_minor=-99000,
                source_kind="account",
                day=6,
            ),
        ],
        path=db,
        preserve_classification=False,
    )
    store_set_merchant_category("MERCADO BOM PRECO", "groceries", path=db)

    result = core_categorize.run_rules_for_month("2026-06", path=db)
    assert result.applied >= 2

    mem = get_transaction("tx-mem", path=db)
    assert mem is not None
    assert mem.category == "groceries"
    assert mem.needs_review is False

    # Structural rule wins; memory must not reclassify card payments.
    pay = get_transaction("tx-pay", path=db)
    assert pay is not None
    assert pay.kind == "card_payment"
    assert pay.category == "transfer"
