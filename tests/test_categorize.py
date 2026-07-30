"""Focused deterministic categorization rules tests (Task 4.1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from canhoto.core.categorize import apply_rules, run_rules_for_month
from canhoto.core.models import LedgerTransaction
from canhoto.core.store import ensure_schema, get_transaction, upsert_transactions


def _tx(
    *,
    tx_id: str = "tx-1",
    description: str = "UNKNOWN MERCHANT",
    amount_minor: int = -5000,
    source_kind: str = "account",
    month: str = "2026-06",
    day: int = 10,
    category: str = "",
    kind: str = "",
    is_expense: bool = False,
    needs_review: bool = True,
    confidence: float = 0.0,
    merchant_normalized: str | None = None,
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
        confidence=confidence,
        month=month,
    )


def test_card_payment_is_not_expense() -> None:
    tx = _tx(
        description="PAGAMENTO FATURA CARTAO FINAL 1234",
        amount_minor=-150000,
        source_kind="account",
    )
    out = apply_rules(tx)
    assert out.kind == "card_payment"
    assert out.is_expense is False
    assert out.needs_review is False
    assert out.category == "transfer"


def test_self_transfer_when_marker_matches() -> None:
    tx = _tx(
        description="PIX ENVIADO JOAO DA SILVA",
        amount_minor=-20000,
        source_kind="account",
    )
    out = apply_rules(tx, own_name_markers=["JOAO DA SILVA"])
    assert out.kind == "self_transfer"
    assert out.is_expense is False
    assert out.category == "transfer"
    assert out.needs_review is False


def test_self_transfer_without_marker_is_not_auto_self() -> None:
    tx = _tx(
        description="PIX ENVIADO JOAO DA SILVA",
        amount_minor=-20000,
        source_kind="account",
    )
    out = apply_rules(tx, own_name_markers=[])
    assert out.kind != "self_transfer"
    assert out.needs_review is True


def test_unknown_expense_still_needs_review() -> None:
    tx = _tx(
        description="LOJA ALEATORIA XYZ 99",
        amount_minor=-4250,
        source_kind="card",
    )
    out = apply_rules(tx)
    assert out.is_expense is True
    assert out.kind == "expense"
    assert out.needs_review is True
    assert out.review_reason is not None
    assert out.category in ("", "uncategorized")


def test_run_rules_updates_store_for_month(tmp_path: Path) -> None:
    db = tmp_path / "canhoto.db"
    ensure_schema(db)

    card_pay = _tx(
        tx_id="tx-card-pay",
        description="PAGAMENTO DA FATURA CARTAO",
        amount_minor=-99000,
        source_kind="account",
        day=1,
    )
    unknown = _tx(
        tx_id="tx-unknown",
        description="CAFE DESCONHECIDO",
        amount_minor=-1500,
        source_kind="card",
        day=2,
    )
    other_month = _tx(
        tx_id="tx-other-month",
        description="PAGAMENTO DA FATURA CARTAO",
        amount_minor=-1000,
        source_kind="account",
        month="2026-05",
        day=3,
    )
    upsert_transactions([card_pay, unknown, other_month], path=db)

    result = run_rules_for_month(
        "2026-06",
        path=db,
        own_name_markers=[],
    )
    assert result.applied >= 1
    assert result.missing == []

    stored_pay = get_transaction("tx-card-pay", path=db)
    assert stored_pay is not None
    assert stored_pay.kind == "card_payment"
    assert stored_pay.is_expense is False
    assert stored_pay.needs_review is False

    stored_unknown = get_transaction("tx-unknown", path=db)
    assert stored_unknown is not None
    assert stored_unknown.is_expense is True
    assert stored_unknown.needs_review is True

    # Other month untouched by this run.
    stored_other = get_transaction("tx-other-month", path=db)
    assert stored_other is not None
    assert stored_other.kind == ""
    assert stored_other.needs_review is True
