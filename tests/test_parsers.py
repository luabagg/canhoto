from pathlib import Path

from finance_ingest.parsers import parse_path
from finance_ingest.parsers.mercadopago_account import parse_account_text
from finance_ingest.parsers.mercadopago_card import parse_card_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_account_txt():
    text = (FIXTURES / "mercadopago-account-2026-06.txt").read_text(encoding="utf-8")
    result = parse_account_text(text, "account.txt")
    assert result.meta.period_start is not None
    assert result.meta.period_start.isoformat() == "2026-06-01"
    assert len(result.transactions) >= 15
    # first credit
    first = result.transactions[0]
    assert first.amount == 1442.69
    assert first.operation_id == "161448944237"
    # has card payment
    kinds = {t.description for t in result.transactions}
    assert any("Pagamento Cartão" in d or "Pagamento Cart" in d for d in kinds)


def test_parse_card_txt():
    text = (FIXTURES / "mercadopago-card-2026-07.txt").read_text(encoding="utf-8")
    result = parse_card_text(text, "card.txt")
    assert result.meta.due_date is not None
    assert result.meta.due_date.isoformat() == "2026-07-10"
    assert len(result.transactions) >= 20
    payments = [t for t in result.transactions if t.kind.value == "card_payment"]
    assert len(payments) >= 1
    expenses = [t for t in result.transactions if t.is_expense]
    assert len(expenses) >= 10
    cards = {t.card_last4 for t in result.transactions if t.card_last4}
    assert "1050" in cards
    assert "5753" in cards


def test_parse_path_pdf_account():
    path = FIXTURES / "mercadopago-account-2026-06.pdf"
    result = parse_path(path)
    assert result.meta.source_kind.value == "account"
    assert len(result.transactions) >= 10


def test_parse_path_pdf_card():
    path = FIXTURES / "mercadopago-card-2026-07.pdf"
    result = parse_path(path)
    assert result.meta.source_kind.value == "card"
    assert len(result.transactions) >= 15
