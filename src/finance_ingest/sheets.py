from __future__ import annotations

from typing import Any

from finance_ingest.config import load_config
from finance_ingest.models import MonthlySummary, Transaction

BANK_HEADERS = [
    "id",
    "date",
    "description",
    "merchant_normalized",
    "amount",
    "category",
    "kind",
    "is_expense",
    "operation_id",
    "month",
    "source_file",
    "confidence",
    "needs_review",
]

CARD_HEADERS = [
    "id",
    "date",
    "description",
    "merchant_normalized",
    "amount",
    "category",
    "kind",
    "is_expense",
    "card_last4",
    "installment",
    "international",
    "billing_cycle",
    "month",
    "source_file",
    "confidence",
    "needs_review",
]


def _get_creds(token_path: str | None, client_secret_path: str | None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import json
    from pathlib import Path

    if not token_path or not Path(token_path).exists():
        raise RuntimeError(
            "Google token not found. Set google_token_path in config or FINANCE_GOOGLE_TOKEN. "
            "You can reuse ~/.hermes/google_token.json after authorizing Sheets scope."
        )
    data = json.loads(Path(token_path).read_text(encoding="utf-8"))
    # Hermes token format may be raw token dict
    if "token" in data and "refresh_token" in data:
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes"),
        )
    else:
        creds = Credentials.from_authorized_user_info(data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _service(spreadsheet_id: str | None = None):
    from googleapiclient.discovery import build

    cfg = load_config()
    sid = spreadsheet_id or cfg.spreadsheet_id
    if not sid:
        raise RuntimeError("spreadsheet_id not configured. Call finance_sheets_configure first.")
    creds = _get_creds(cfg.google_token_path, cfg.google_client_secret_path)
    return build("sheets", "v4", credentials=creds, cache_discovery=False), sid


def ensure_workbook(spreadsheet_id: str | None = None) -> dict[str, Any]:
    service, sid = _service(spreadsheet_id)
    meta = service.spreadsheets().get(spreadsheetId=sid).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    wanted = ["Bank Transactions", "Card Transactions", "Monthly Summary"]
    requests = []
    for title in wanted:
        if title not in existing:
            requests.append({"addSheet": {"properties": {"title": title}}})
    if requests:
        service.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": requests}).execute()
    # headers
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range="Bank Transactions!A1",
        valueInputOption="RAW",
        body={"values": [BANK_HEADERS]},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range="Card Transactions!A1",
        valueInputOption="RAW",
        body={"values": [CARD_HEADERS]},
    ).execute()
    summary_headers = [
        ["month", "income", "expenses", "net", "pending_review", "transaction_count"],
        ["category", "amount"],
    ]
    service.spreadsheets().values().update(
        spreadsheetId=sid,
        range="Monthly Summary!A1",
        valueInputOption="RAW",
        body={"values": [summary_headers[0]]},
    ).execute()
    return {"spreadsheet_id": sid, "sheets": wanted}


def _bank_row(tx: Transaction) -> list:
    return [
        tx.id,
        tx.date.isoformat(),
        tx.description,
        tx.merchant_normalized or "",
        tx.amount,
        tx.category.value,
        tx.kind.value,
        tx.is_expense,
        tx.operation_id or "",
        tx.month,
        tx.source_file,
        tx.confidence,
        tx.needs_review,
    ]


def _card_row(tx: Transaction) -> list:
    return [
        tx.id,
        tx.date.isoformat(),
        tx.description,
        tx.merchant_normalized or "",
        tx.amount,
        tx.category.value,
        tx.kind.value,
        tx.is_expense,
        tx.card_last4 or "",
        tx.installment or "",
        tx.international,
        tx.billing_cycle or "",
        tx.month,
        tx.source_file,
        tx.confidence,
        tx.needs_review,
    ]


def push_transactions(txs: list[Transaction], spreadsheet_id: str | None = None) -> dict[str, Any]:
    service, sid = _service(spreadsheet_id)
    ensure_workbook(sid)
    bank = [t for t in txs if t.source_kind.value == "account"]
    card = [t for t in txs if t.source_kind.value == "card"]
    if bank:
        service.spreadsheets().values().append(
            spreadsheetId=sid,
            range="Bank Transactions!A2",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [_bank_row(t) for t in bank]},
        ).execute()
    if card:
        service.spreadsheets().values().append(
            spreadsheetId=sid,
            range="Card Transactions!A2",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [_card_row(t) for t in card]},
        ).execute()
    return {
        "spreadsheet_id": sid,
        "bank_rows": len(bank),
        "card_rows": len(card),
    }


def push_monthly_summary(summary: MonthlySummary, spreadsheet_id: str | None = None) -> dict[str, Any]:
    service, sid = _service(spreadsheet_id)
    ensure_workbook(sid)
    # append one summary row + category block below a marker
    service.spreadsheets().values().append(
        spreadsheetId=sid,
        range="Monthly Summary!A2",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={
            "values": [
                [
                    summary.month,
                    summary.income,
                    summary.expenses,
                    summary.net,
                    summary.pending_review,
                    summary.transaction_count,
                ]
            ]
        },
    ).execute()
    cat_rows = [[k, v] for k, v in summary.by_category.items()]
    if cat_rows:
        service.spreadsheets().values().append(
            spreadsheetId=sid,
            range="Monthly Summary!H1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [["month", "category", "amount"]] + [[summary.month, k, v] for k, v in summary.by_category.items()]},
        ).execute()
    return {"spreadsheet_id": sid, "month": summary.month, "categories": len(cat_rows)}
