"""Guardrail tests for MCP tool allowlist integrity (fail closed)."""

from __future__ import annotations

from canhoto.mcp.allowlist import MCP_TOOL_ALLOWLIST, MCP_TOOL_DENYLIST

EXPECTED_ALLOWLIST = frozenset(
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

EXPECTED_DENYLIST = frozenset(
    {
        "sql_query",
        "list_all_transactions",
        "sheets_push",
        "sheets_setup",
        "get_config_secrets",
    }
)


def test_allowlist_matches_contract() -> None:
    assert MCP_TOOL_ALLOWLIST == EXPECTED_ALLOWLIST


def test_denylist_matches_contract() -> None:
    assert MCP_TOOL_DENYLIST == EXPECTED_DENYLIST


def test_allowlist_and_denylist_are_disjoint() -> None:
    overlap = MCP_TOOL_ALLOWLIST & MCP_TOOL_DENYLIST
    assert not overlap, f"allowlist/denylist overlap: {sorted(overlap)}"


def test_allowlist_and_denylist_are_frozensets() -> None:
    assert isinstance(MCP_TOOL_ALLOWLIST, frozenset)
    assert isinstance(MCP_TOOL_DENYLIST, frozenset)


def test_denylist_names_not_present_in_allowlist() -> None:
    for name in MCP_TOOL_DENYLIST:
        assert name not in MCP_TOOL_ALLOWLIST


def test_dangerous_tools_remain_denied() -> None:
    """Fail closed: raw SQL, full ledger dumps, Sheets, and secrets stay denied."""
    for name in (
        "sql_query",
        "list_all_transactions",
        "sheets_push",
        "sheets_setup",
        "get_config_secrets",
    ):
        assert name in MCP_TOOL_DENYLIST
        assert name not in MCP_TOOL_ALLOWLIST
