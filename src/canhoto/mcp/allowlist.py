"""MCP tool allowlist contract — fail closed.

Only tools in ``MCP_TOOL_ALLOWLIST`` may be registered.
``MCP_TOOL_DENYLIST`` names must never be exposed.
"""

from __future__ import annotations

MCP_TOOL_ALLOWLIST = frozenset(
    {
        "statement_preview",
        "parser_list",
        "parser_scaffold",
        "parser_write",
        "parser_test",
        "parser_enable",
        "ingest",
        "run_rules",
        "review_batch",
        "set_categories",
        "set_merchant_category",
        "month_breakdown",
        "export_pdf",
        "doctor",
    }
)

MCP_TOOL_DENYLIST = frozenset(
    {
        "sql_query",
        "list_all_transactions",
        "sheets_push",
        "sheets_setup",
        "get_config_secrets",
    }
)
