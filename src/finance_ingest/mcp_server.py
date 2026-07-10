"""MCP server: agent-facing tools for the full finance ingest flow.

Run:
  finance-mcp
  # or: python -m finance_ingest.mcp_server

Hermes config example:
  mcp_servers:
    finance:
      command: finance-mcp
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from finance_ingest import service

mcp = FastMCP(
    name="personal-finance-ingest",
    instructions=(
        "Tools to parse Mercado Pago bank/card PDFs, store transactions, "
        "categorize (rules + agent patches), and push to Google Sheets. "
        "Typical flow: finance_ingest → finance_get_pending_review → "
        "finance_apply_classifications → finance_get_monthly_summary → "
        "finance_sheets_push. Do not invent totals; use summary tools."
    ),
)


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def finance_get_config() -> str:
    """Return current finance-ingest configuration (paths, spreadsheet id)."""
    return _j(service.get_config())


@mcp.tool()
def finance_configure(
    spreadsheet_id: str | None = None,
    google_token_path: str | None = None,
    google_client_secret_path: str | None = None,
) -> str:
    """Update config: Google spreadsheet id and credential paths."""
    return _j(
        service.configure(
            spreadsheet_id=spreadsheet_id,
            google_token_path=google_token_path,
            google_client_secret_path=google_client_secret_path,
        )
    )


@mcp.tool()
def finance_parse_statement(path: str) -> str:
    """Parse one PDF/TXT statement without writing to the database. Returns meta + transactions JSON."""
    return _j(service.parse_statement(path))


@mcp.tool()
def finance_ingest(paths: list[str], auto_categorize: bool = True) -> str:
    """Ingest one or more statement files: parse, optional rule categorization, upsert into local SQLite."""
    return _j(service.ingest_paths(paths, auto_categorize=auto_categorize))


@mcp.tool()
def finance_list_transactions(
    month: str | None = None,
    needs_review: bool | None = None,
    source_kind: str | None = None,
    limit: int = 200,
) -> str:
    """List stored transactions. month=YYYY-MM, source_kind=account|card."""
    return _j(
        service.list_transactions(
            month=month,
            needs_review=needs_review,
            source_kind=source_kind,
            limit=limit,
        )
    )


@mcp.tool()
def finance_get_pending_review(month: str | None = None, limit: int = 200) -> str:
    """List transactions still needing agent/human classification."""
    return _j(service.get_pending_review(month=month, limit=limit))


@mcp.tool()
def finance_auto_categorize(month: str | None = None) -> str:
    """Re-run deterministic categorization rules on stored transactions."""
    return _j(service.auto_categorize(month=month))


@mcp.tool()
def finance_apply_classifications(patches: list[dict[str, Any]]) -> str:
    """Apply agent classifications. Each patch: {id, merchant_normalized?, category?, kind?, is_expense?, needs_review?, confidence?, review_reason?}.

    Categories: Car payment, Gas/travel, Investments, Groceries, Eating, Personal care,
    Electric, Condo Fee, Rent/mortgage, House, Internet, Cell phone, Entertainment,
    Purchases, Others, Income, Transfer, Uncategorized.

    Kinds: expense, income, card_payment, internal_transfer, piggy_reserve, self_transfer, fee, installment, unknown.
    """
    return _j(service.apply_classifications(patches))


@mcp.tool()
def finance_get_monthly_summary(month: str) -> str:
    """Compute monthly summary from stored txs (excludes transfers and card bill payments)."""
    return _j(service.get_monthly_summary(month))


@mcp.tool()
def finance_reconcile(month: str) -> str:
    """Return reconciliation notes + counts for a month."""
    return _j(service.reconcile(month))


@mcp.tool()
def finance_sheets_setup(spreadsheet_id: str | None = None) -> str:
    """Ensure Bank Transactions / Card Transactions / Monthly Summary tabs exist."""
    return _j(service.sheets_setup(spreadsheet_id=spreadsheet_id))


@mcp.tool()
def finance_sheets_push(month: str) -> str:
    """Push month transactions + summary rows to the configured Google Spreadsheet."""
    return _j(service.sheets_push(month))


@mcp.tool()
def finance_export_json(month: str) -> str:
    """Export month transactions + summary to a local JSON file under the data dir."""
    return _j(service.export_json(month))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
