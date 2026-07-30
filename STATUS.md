# Project status — Canhoto

**Canonical design:** `docs/ARCHITECTURE.md`  
**Implementation plan:** `docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md`  
**Agent bootstrap:** `AGENTS.md`  
**Migration / archive:** `docs/MIGRATION.md`, `docs/ARCHIVE_BRANCH.md`

## Name

| | |
|---|---|
| Product | **Canhoto** (stub/counterfoil you keep) |
| Package | `canhoto` |
| CLI | `canhoto` |
| MCP | `canhoto-mcp` |
| Data | `~/.canhoto` / `$CANHOTO_DATA_DIR` |

## Runtime status

**Canhoto runtime is implemented** under `src/canhoto/` with guardrails, plugin parsers, SQLite ledger, categorization, MCP domain tools, and summary PDF export.

| Layer | Status |
|---|---|
| Phase 0 guardrails / contracts | Done (`tests/guardrails/`) |
| Phase 1 config / store / init / doctor | Done |
| Phase 2 parser port (scaffold/test/enable) | Done |
| Phase 3 ingest + CLI parse dry-run | Done |
| Phase 4 categorize / review / breakdown | Done |
| Phase 5 MCP allowlisted tools | Done |
| Phase 6 summary PDF | Done |
| Phase 7 package scripts + CI + docs | Done |

Legacy `src/finance_ingest/` may remain in-tree as reference only — **not** shipped by the `canhoto` wheel. Prefer archive branch + data-dir plugins for bank parsers.

## Branches

| Branch | Meaning |
|---|---|
| `main` | Canhoto product |
| `archive/2026-07-29-pre-engine-redesign` | Frozen richer WIP — reference only |

## Verify

```bash
uv sync --extra dev
uv run pytest -q
uv run canhoto --help
uv run canhoto-mcp --help  # or: python -m canhoto.mcp
```
