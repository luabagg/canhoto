from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from finance_ingest import sheets as sheets_mod
from finance_ingest.categorize import categorize_many
from finance_ingest.config import data_dir, dump_json, load_config, update_config
from finance_ingest.models import ClassificationPatch, ParseResult
from finance_ingest.parsers import parse_path
from finance_ingest import store


def configure(
    spreadsheet_id: str | None = None,
    google_token_path: str | None = None,
    google_client_secret_path: str | None = None,
    own_name_markers: list[str] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if spreadsheet_id is not None:
        kwargs["spreadsheet_id"] = spreadsheet_id
    if google_token_path is not None:
        kwargs["google_token_path"] = google_token_path
    if google_client_secret_path is not None:
        kwargs["google_client_secret_path"] = google_client_secret_path
    if own_name_markers is not None:
        kwargs["own_name_markers"] = own_name_markers
    cfg = update_config(**kwargs)
    return cfg.model_dump()


def get_config() -> dict[str, Any]:
    return load_config().model_dump()


def parse_statement(path: str) -> dict[str, Any]:
    result = parse_path(path)
    return result.model_dump(mode="json")


def ingest_paths(paths: list[str], auto_categorize: bool = True) -> dict[str, Any]:
    cfg = load_config()
    raw_dir = data_dir() / "raw"
    results: list[dict[str, Any]] = []
    all_txs = []
    for p in paths:
        src = Path(p).expanduser().resolve()
        if not src.exists():
            results.append({"path": str(src), "error": "not_found"})
            continue
        dest = raw_dir / src.name
        if src != dest:
            shutil.copy2(src, dest)
        parsed: ParseResult = parse_path(src)
        txs = parsed.transactions
        if auto_categorize:
            txs = categorize_many(txs, own_name_markers=cfg.own_name_markers)
        stats = store.upsert_transactions(txs)
        store.save_statement_meta(
            parsed.meta.source_kind.value,
            str(src),
            parsed.meta.model_dump_json(),
        )
        all_txs.extend(txs)
        results.append(
            {
                "path": str(src),
                "source_kind": parsed.meta.source_kind.value,
                "meta": parsed.meta.model_dump(mode="json"),
                "store": stats,
            }
        )
    return {
        "ingested": results,
        "transaction_count": len(all_txs),
        "pending_review": sum(1 for t in all_txs if t.needs_review),
    }


def list_transactions(
    month: str | None = None,
    needs_review: bool | None = None,
    source_kind: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    txs = store.list_transactions(
        month=month, needs_review=needs_review, source_kind=source_kind, limit=limit
    )
    return [t.model_dump(mode="json") for t in txs]


def auto_categorize(month: str | None = None) -> dict[str, Any]:
    cfg = load_config()
    txs = store.list_transactions(month=month, limit=10000)
    updated = categorize_many(txs, own_name_markers=cfg.own_name_markers)
    store.replace_transactions(updated)
    return {
        "updated": len(updated),
        "pending_review": sum(1 for t in updated if t.needs_review),
    }


def apply_classifications(patches: list[dict[str, Any]]) -> dict[str, Any]:
    models = [ClassificationPatch.model_validate(p) for p in patches]
    return store.apply_classifications(models)


def get_pending_review(month: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return list_transactions(month=month, needs_review=True, limit=limit)


def get_monthly_summary(month: str) -> dict[str, Any]:
    return store.monthly_summary(month).model_dump(mode="json")


def sheets_setup(spreadsheet_id: str | None = None) -> dict[str, Any]:
    if spreadsheet_id:
        configure(spreadsheet_id=spreadsheet_id)
    return sheets_mod.ensure_workbook(spreadsheet_id)


def sheets_push(month: str, only_unpushed: bool = False) -> dict[str, Any]:
    txs = store.list_transactions(month=month, limit=10000)
    if not txs:
        return {"error": "no_transactions", "month": month}
    # optional filter not tracked tightly in memory; push all for month
    push = sheets_mod.push_transactions(txs)
    summary = store.monthly_summary(month)
    sum_push = sheets_mod.push_monthly_summary(summary)
    store.mark_pushed([t.id for t in txs])
    return {"transactions": push, "summary": sum_push}


def reconcile(month: str) -> dict[str, Any]:
    """Basic reconciliation helpers for the agent."""
    txs = store.list_transactions(month=month, limit=10000)
    summary = store.monthly_summary(month)
    account = [t for t in txs if t.source_kind.value == "account"]
    card = [t for t in txs if t.source_kind.value == "card"]
    card_payments = [t for t in txs if t.kind.value == "card_payment"]
    return {
        "month": month,
        "summary": summary.model_dump(mode="json"),
        "counts": {
            "account": len(account),
            "card": len(card),
            "card_payments": len(card_payments),
            "pending_review": summary.pending_review,
        },
        "notes": [
            "Card purchases are expenses; account 'Pagamento Cartão de crédito' is card_payment (excluded from expenses).",
            "Piggy reserve moves are internal transfers.",
            "Self PIX to own name is self_transfer.",
        ],
    }


def export_json(month: str) -> dict[str, Any]:
    out = data_dir() / "exports" / f"{month}.json"
    payload = {
        "month": month,
        "transactions": list_transactions(month=month, limit=10000),
        "summary": get_monthly_summary(month),
    }
    out.write_text(dump_json(payload), encoding="utf-8")
    return {"path": str(out), "count": len(payload["transactions"])}
