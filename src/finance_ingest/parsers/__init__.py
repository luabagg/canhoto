from __future__ import annotations

from pathlib import Path

from finance_ingest.models import ParseResult, SourceKind
from finance_ingest.parsers.mercadopago_account import parse_account_text
from finance_ingest.parsers.mercadopago_card import parse_card_text
from finance_ingest.pdf_text import extract_pdf_text


def detect_kind(text: str) -> SourceKind:
    upper = text.upper()
    if "EXTRATO DE CONTA" in upper or "DETALHE DOS MOVIMENTOS" in upper:
        return SourceKind.ACCOUNT
    if "FATURA" in upper or "DETALHES DE CONSUMO" in upper or "CARTÃO VISA" in upper:
        return SourceKind.CARD
    raise ValueError("Could not detect statement type (account vs card)")


def parse_text(text: str, source_file: str) -> ParseResult:
    kind = detect_kind(text)
    if kind is SourceKind.ACCOUNT:
        return parse_account_text(text, source_file)
    return parse_card_text(text, source_file)


def parse_path(path: str | Path) -> ParseResult:
    path = Path(path)
    if path.suffix.lower() == ".txt":
        text = path.read_text(encoding="utf-8")
    elif path.suffix.lower() == ".pdf":
        text = extract_pdf_text(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    return parse_text(text, str(path))
