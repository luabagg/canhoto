from __future__ import annotations

import hashlib
import re
from datetime import datetime

from finance_ingest.models import (
    ParseResult,
    SourceKind,
    StatementMeta,
    Transaction,
    TransactionKind,
)

DATE_DM = re.compile(r"^(\d{2}/\d{2})$")
DATE_DMY = re.compile(r"^(\d{2}/\d{2}/\d{4})$")
amount_re = re.compile(r"^R\$\s*(-?[\d.]+,\d{2})$")
card_re = re.compile(r"Cartão Visa \[(\*+)(\d{4})\]", re.IGNORECASE)


def _parse_brl(s: str) -> float:
    s = s.strip().replace("R$", "").strip()
    negative = s.startswith("-")
    s = s.lstrip("-").replace(".", "").replace(",", ".")
    value = float(s)
    return -value if negative else value


def _parse_dmy(s: str):
    return datetime.strptime(s, "%d/%m/%Y").date()


def _year_for_md(md: str, cycle_end) -> int:
    """Map DD/MM onto the statement cycle year (cycle end year, or previous if after end)."""
    day, month = map(int, md.split("/"))
    year = cycle_end.year
    candidate = datetime(year, month, day).date()
    # if date is after cycle end, it belongs to previous year? Usually not.
    # if date is way after cycle end month, use previous year for early-year wrap.
    if candidate > cycle_end and month > cycle_end.month:
        return year - 1
    # purchases before cycle start may be prior months installments
    if candidate.month > cycle_end.month and candidate.year == cycle_end.year:
        return year - 1
    return year


def _make_id(source_file: str, card: str | None, date_s: str, desc: str, amount: float, installment: str | None) -> str:
    base = f"{card or '-'}|{date_s}|{desc}|{amount:.2f}|{installment or ''}"
    digest = hashlib.sha1(f"card|{source_file}|{base}".encode()).hexdigest()[:16]
    return f"card_{digest}"


def parse_card_text(text: str, source_file: str) -> ParseResult:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    due_date = None
    total_amount = None
    period_start = period_end = None
    cycle_label = None

    for i, line in enumerate(lines):
        if line.startswith("Vence em") and i + 1 < len(lines) and DATE_DMY.match(lines[i + 1]):
            due_date = _parse_dmy(lines[i + 1])
        if line.startswith("Vencimento:") and DATE_DMY.search(line):
            due_date = _parse_dmy(DATE_DMY.search(line).group(1))
        if line == "Total a pagar" and i + 1 < len(lines) and amount_re.match(lines[i + 1]):
            total_amount = _parse_brl(lines[i + 1])
        if line.startswith("Consumos de "):
            m = re.search(r"Consumos de\s+(\d{2}/\d{2})\s+a\s+(\d{2}/\d{2})", line)
            if m and due_date:
                # infer full dates from due year
                y = due_date.year
                # e.g. 06/06 a 05/07 with due 10/07/2026
                start = datetime.strptime(f"{m.group(1)}/{y}", "%d/%m/%Y").date()
                end = datetime.strptime(f"{m.group(2)}/{y}", "%d/%m/%Y").date()
                if end < start:
                    start = datetime.strptime(f"{m.group(1)}/{y - 1}", "%d/%m/%Y").date()
                period_start, period_end = start, end
                cycle_label = end.strftime("%Y-%m")

    if not period_end and due_date:
        period_end = due_date
        cycle_label = due_date.strftime("%Y-%m")

    # Card purchases sections + statement-level payments
    txs: list[Transaction] = []
    current_card: str | None = None
    in_movements = False
    i = 0
    while i < len(lines):
        line = lines[i]
        mcard = card_re.search(line)
        if mcard:
            current_card = mcard.group(2)
            in_movements = True
            i += 1
            continue
        if line in {"Movimentações na fatura", "Detalhes de consumo"}:
            in_movements = True
            current_card = None if line == "Movimentações na fatura" else current_card
            i += 1
            continue
        if line.startswith("Parcele a fatura") or line.startswith("Seu cartão de crédito"):
            in_movements = False
            i += 1
            continue
        if line == "Total" and i + 1 < len(lines) and amount_re.match(lines[i + 1]):
            i += 2
            continue

        if not in_movements or not DATE_DM.match(line):
            i += 1
            continue

        md = line
        i += 1
        if i >= len(lines):
            break
        desc = lines[i]
        i += 1
        installment = None
        international = False
        # optional installment line
        if i < len(lines) and lines[i].lower().startswith("parcela "):
            installment = lines[i]
            i += 1
        # skip international conversion noise lines until amount
        while i < len(lines) and not amount_re.match(lines[i]) and not DATE_DM.match(lines[i]):
            if "internacional" in desc.lower() or lines[i].startswith("BRL"):
                international = True
            if lines[i].startswith("Compra internacional"):
                # rare: description split
                desc = lines[i]
                international = True
            i += 1
            if i >= len(lines):
                break
        if i >= len(lines) or not amount_re.match(lines[i]):
            continue
        amount_abs = _parse_brl(lines[i])
        i += 1

        # card purchases are expenses (negative); payments on statement are credits (positive)
        is_payment = "pagamento da fatura" in desc.lower()
        amount = amount_abs if is_payment else -abs(amount_abs)

        year = period_end.year if period_end else (due_date.year if due_date else datetime.now().year)
        try:
            d = datetime.strptime(f"{md}/{year}", "%d/%m/%Y").date()
            if period_end and d > period_end and d.month > period_end.month:
                d = datetime.strptime(f"{md}/{year - 1}", "%d/%m/%Y").date()
            # installments from earlier months
            if period_start and d > period_end:
                d = datetime.strptime(f"{md}/{year - 1}", "%d/%m/%Y").date()
        except ValueError:
            d = datetime.strptime(f"{md}/{year}", "%d/%m/%Y").date()

        kind = TransactionKind.CARD_PAYMENT if is_payment else TransactionKind.EXPENSE
        txs.append(
            Transaction(
                id=_make_id(source_file, current_card, md, desc, amount, installment),
                source_kind=SourceKind.CARD,
                source_file=source_file,
                date=d,
                description=desc,
                amount=amount,
                card_last4=current_card,
                installment=installment,
                international=international or "internacional" in desc.lower(),
                merchant_raw=desc,
                month=d.strftime("%Y-%m"),
                billing_cycle=cycle_label,
                kind=kind,
                is_expense=not is_payment,
                needs_review=not is_payment,
                confidence=0.9 if is_payment else 0.0,
                review_reason=None if is_payment else "needs_category",
            )
        )

    meta = StatementMeta(
        source_kind=SourceKind.CARD,
        source_file=source_file,
        period_start=period_start,
        period_end=period_end,
        due_date=due_date,
        total_amount=total_amount,
        raw_summary={"transaction_count": len(txs), "billing_cycle": cycle_label},
    )
    return ParseResult(meta=meta, transactions=txs)
