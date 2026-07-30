"""MCP server wiring tests (Task 5.1) — registry + gated tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from canhoto.core.config import init_data_dir, load_config, save_config
from canhoto.mcp.allowlist import MCP_TOOL_ALLOWLIST, MCP_TOOL_DENYLIST
from canhoto.mcp.server import create_server, registered_tool_names


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    init_data_dir(root)
    return root


def test_registered_tools_match_allowlist() -> None:
    names = registered_tool_names(create_server())
    assert names == frozenset(MCP_TOOL_ALLOWLIST)
    assert sorted(names) == sorted(MCP_TOOL_ALLOWLIST)


def test_denylist_tools_not_registered() -> None:
    names = registered_tool_names(create_server())
    for denied in MCP_TOOL_DENYLIST:
        assert denied not in names


def test_statement_preview_truncates(data_home: Path) -> None:
    cfg = load_config(data_home)
    cfg = cfg.model_copy(
        update={"agent_view": cfg.agent_view.model_copy(update={"preview_max_chars": 50})}
    )
    save_config(cfg, root=data_home)

    sample = data_home / "fixtures" / "long_statement.txt"
    sample.write_text("A" * 200, encoding="utf-8")

    server = create_server()
    result = asyncio.run(
        server.call_tool("statement_preview", {"path": str(sample)})
    )
    assert result.is_error is False
    # structured_content preferred; fall back to JSON text payload
    payload = _tool_payload(result)
    assert payload["path_basename"] == "long_statement.txt"
    assert payload["char_count"] == 200
    assert payload["truncated"] is True
    assert payload["text"] == "A" * 50
    assert "fixtures" not in payload  # no path dump beyond basename


def test_parser_write_blocked_when_allow_parser_writes_false(data_home: Path) -> None:
    from mcp.server.mcpserver.exceptions import ToolError

    from canhoto import service

    service.parser_scaffold(
        "demo_card",
        statement_type="card",
        institution="demo",
        root=data_home,
    )
    cfg = load_config(data_home)
    assert cfg.agent_view.allow_parser_writes is False

    server = create_server()
    with pytest.raises(ToolError) as exc_info:
        asyncio.run(
            server.call_tool(
                "parser_write",
                {"parser_id": "demo_card", "code": "# blocked\n"},
            )
        )
    text = str(exc_info.value).lower()
    assert "allow_parser_writes" in text or "refused" in text or "permission" in text
    # Module must remain unchanged / not enabled by a blocked write.
    entry = next(e for e in load_config(data_home).parsers if e.id == "demo_card")
    assert entry.enabled is False


def _tool_payload(result: object) -> dict:
    import json

    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict):
        return sc
    text = _tool_text(result)
    return json.loads(text)


def _tool_text(result: object) -> str:
    content = getattr(result, "content", None) or []
    parts: list[str] = []
    for item in content:
        t = getattr(item, "text", None)
        if t is not None:
            parts.append(str(t))
    return "\n".join(parts)
