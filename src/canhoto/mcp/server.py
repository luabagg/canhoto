"""Canhoto MCP stdio server — allowlist-gated domain tools only.

Register exactly ``MCP_TOOL_ALLOWLIST``. Each tool delegates to
``canhoto.service.*``. No SQL, Sheets, or full ledger dump tools.
"""

from __future__ import annotations

from typing import Any

from canhoto import service
from canhoto.mcp.allowlist import MCP_TOOL_ALLOWLIST, MCP_TOOL_DENYLIST
from mcp.server import MCPServer

_SERVER_NAME = "canhoto"
_INSTRUCTIONS = (
    "Canhoto personal finance engine — domain tools only. "
    "No SQL, no Sheets, no unbounded ledger dumps. "
    "\n\n"
    "Happy path for agents:\n"
    "1. statement_preview → parser_scaffold / parser_write → parser_test → parser_enable\n"
    "2. ingest\n"
    "3. run_rules → review_batch loop → set_categories (and set_merchant_category as needed)\n"
    "4. month_breakdown → export_pdf\n"
    "\n"
    "Constraints:\n"
    "- parser_write requires agent_view.allow_parser_writes=true.\n"
    "- parser_enable only after a successful parser_test stamp.\n"
    "- review_batch returns redacted, capped pending items — never raw full rows.\n"
    "- export_pdf is summary-only (aggregates) when available; not a full transaction listing.\n"
    "- Prefer doctor for data-dir health; do not invent off-allowlist tools."
)


def create_server() -> MCPServer[Any]:
    """Build an MCP server with exactly the allowlisted tools registered."""
    server: MCPServer[Any] = MCPServer(
        name=_SERVER_NAME,
        instructions=_INSTRUCTIONS,
    )
    _register_tools(server)

    names = registered_tool_names(server)
    if names != frozenset(MCP_TOOL_ALLOWLIST):
        missing = sorted(frozenset(MCP_TOOL_ALLOWLIST) - names)
        extra = sorted(names - frozenset(MCP_TOOL_ALLOWLIST))
        raise RuntimeError(
            f"MCP tool registry drift: missing={missing!r} extra={extra!r}"
        )
    denied = names & frozenset(MCP_TOOL_DENYLIST)
    if denied:
        raise RuntimeError(f"MCP denylist tools registered: {sorted(denied)!r}")
    return server


def registered_tool_names(server: MCPServer[Any] | None = None) -> frozenset[str]:
    """Return the set of tool names currently registered on ``server``."""
    srv = server if server is not None else create_server()
    return frozenset(t.name for t in srv._tool_manager.list_tools())


def _register_tools(server: MCPServer[Any]) -> None:
    @server.tool()
    def statement_preview(path: str) -> dict[str, Any]:
        """Extract and truncate statement text for agent inspection (basename only)."""
        return service.statement_preview(path)

    @server.tool()
    def parser_list() -> dict[str, Any]:
        """List registered parsers and enable/test status."""
        return service.parser_list()

    @server.tool()
    def parser_scaffold(
        parser_id: str,
        statement_type: str,
        institution: str,
    ) -> dict[str, Any]:
        """Create a stub parser module and register it disabled."""
        return service.parser_scaffold(
            parser_id,
            statement_type=statement_type,
            institution=institution,
        )

    @server.tool()
    def parser_write(parser_id: str, code: str) -> dict[str, Any]:
        """Overwrite a registered parser module (requires allow_parser_writes)."""
        return service.parser_write(parser_id, code, source="mcp")

    @server.tool()
    def parser_test(parser_id: str, file: str) -> dict[str, Any]:
        """Run parser against a sample file and stamp last_test_* on config."""
        return service.parser_test(parser_id, file)

    @server.tool()
    def parser_enable(parser_id: str) -> dict[str, Any]:
        """Enable a parser only after a successful parser_test stamp."""
        return service.parser_enable(parser_id)

    @server.tool()
    def ingest(paths: list[str]) -> dict[str, Any]:
        """Archive, parse, and upsert one or more statement files."""
        return service.ingest(paths)

    @server.tool()
    def run_rules(month: str) -> dict[str, Any]:
        """Apply deterministic categorization rules for a YYYY-MM month."""
        return service.run_rules(month)

    @server.tool()
    def review_batch(
        month: str,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return a capped, redacted pending-review batch for a month."""
        return service.review_batch(month, cursor=cursor, limit=limit)

    @server.tool()
    def set_categories(patches: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply classification patches (id + category fields)."""
        return service.set_categories(patches)

    @server.tool()
    def set_merchant_category(merchant_key: str, category: str) -> dict[str, Any]:
        """Remember merchant_key → category for later rule runs."""
        return service.set_merchant_category(merchant_key, category)

    @server.tool()
    def month_breakdown(month: str) -> dict[str, Any]:
        """Return aggregate month report (no transaction list)."""
        return service.month_breakdown(month)

    @server.tool()
    def export_pdf(month: str) -> dict[str, Any]:
        """Export month summary PDF (metrics + category totals only)."""
        return service.export_pdf(month)

    @server.tool()
    def doctor() -> dict[str, Any]:
        """Return data-dir health report (no ledger rows)."""
        return service.doctor()


def main() -> None:
    """Run the Canhoto MCP server on stdio (host-spawned)."""
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
