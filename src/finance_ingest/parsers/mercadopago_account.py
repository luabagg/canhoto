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

DATE_RE = re.compile(r"^(\d{2}-\d{2}-\d{4})$")
OP_ID_RE = re.compile(r"^\d{8,}$")


def _is_amount(line: str) -> bool:
    return line.startswith("R$")


def _parse_brl(s: str) -> float:
    s = s.strip().replace("R$", "").strip()
    negative = s.startswith("-")
    s = s.lstrip("-").replace(".", "").replace(",", ".")
    value = float(s)
    return -value if negative else value


def _parse_date(s: str):
    return datetime.strptime(s, "%d-%m-%Y").date()


def _make_id(source_file: str, operation_id: str | None, date_s: str, desc: str, amount: float) -> str:
    base = operation_id or f"{date_s}|{desc}|{amount:.2f}"
    digest = hashlib.sha1(f"account|{source_file}|{base}".encode()).hexdigest()[:16]
    return f"acc_{digest}"


def parse_account_text(text: str, source_file: str) -> ParseResult:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    period_start = period_end = None
    opening = closing = entries = exits = None

    for line in lines:
        if line.startswith("De ") and " al " in line:
            m = re.search(r"De\s+(\d{2}-\d{2}-\d{4})\s+al\s+(\d{2}-\d{2}-\d{4})", line)
            if m:
                period_start = _parse_date(m.group(1))
                period_end = _parse_date(m.group(2))
        if line.startswith("Saldo inicial:"):
            opening = _parse_brl(line.split(":", 1)[1])
        if line.startswith("Entradas:"):
            entries = _parse_brl(line.split(":", 1)[1])
        if line.startswith("Saidas:") or line.startswith("Saídas:"):
            exits = _parse_brl(line.split(":", 1)[1])
        if line.startswith("Saldo final:"):
            closing = _parse_brl(line.split(":", 1)[1])

    # Rows: Date / Description(+wrap) / Operation ID / Value / Saldo
    txs: list[Transaction] = []
    i = 0
    n = len(lines)
    while i < n:
        if not DATE_RE.match(lines[i]):
            i += 1
            continue
        date_s = lines[i]
        i += 1
        desc_parts: list[str] = []
        while i < n:
            line = lines[i]
            if DATE_RE.match(line) or _is_amount(line) or OP_ID_RE.match(line):
                break
            if line in {"Data", "Descrição", "ID da operação", "Valor", "Saldo"}:
                break
            if line.startswith("Saldo final:") or line.startswith("Data de geração:"):
                break
            desc_parts.append(line)
            i += 1
        if i >= n:
            break
        op_id = None
        if i < n and OP_ID_RE.match(lines[i]):
            op_id = lines[i]
            i += 1
        if i >= n or not _is_amount(lines[i]):
            continue
        amount = _parse_brl(lines[i])
        i += 1
        balance = None
        if i < n and _is_amount(lines[i]):
            balance = _parse_brl(lines[i])
            i += 1
        description = " ".join(desc_parts).strip()
        if not description:
            continue
        d = _parse_date(date_s)
        txs.append(
            Transaction(
                id=_make_id(source_file, op_id, date_s, description, amount),
                source_kind=SourceKind.ACCOUNT,
                source_file=source_file,
                date=d,
                description=description,
                amount=amount,
                operation_id=op_id,
                running_balance=balance,
                merchant_raw=description,
                month=d.strftime("%Y-%m"),
                kind=TransactionKind.UNKNOWN,
                needs_review=True,
            )
        )

    meta = StatementMeta(
        source_kind=SourceKind.ACCOUNT,
        source_file=source_file,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening,
        closing_balance=closing,
        entries=entries,
        exits=exits,
        raw_summary={"transaction_count": len(txs)},
    )
    return ParseResult(meta=meta, transactions=txs)
