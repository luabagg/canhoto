# Project status — Canhoto

**Canonical design:** `docs/ARCHITECTURE.md`  
**Implementation plan:** `docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md`  
**Agent bootstrap:** `AGENTS.md` (**read Day-1 reality first**)  
**Legacy code map:** `docs/ARCHIVE_BRANCH.md`

## Name (target)

| | |
|---|---|
| Product | **Canhoto** (stub/counterfoil you keep) |
| CLI | `canhoto` |
| MCP | `canhoto-mcp` |
| Data | `~/.canhoto` / `$CANHOTO_DATA_DIR` |

## Dual state (important)

| | On `main` **now** |
|---|---|
| Docs | Canhoto architecture + phased plan |
| Runtime | Legacy MVP: `src/finance_ingest/`, scripts `finance` / `finance-mcp` |
| Redesign code | **Not started** (no `src/canhoto/`, no `tests/guardrails/`) |

Agents: architecture wins; legacy is scaffolding to replace. Details in `AGENTS.md`.

## Branches

| Branch | Meaning |
|---|---|
| `main` | Canhoto docs + legacy MVP source — implement redesign here |
| `archive/2026-07-29-pre-engine-redesign` | Frozen richer WIP (Itaú, Sheets OAuth, expanded tests) — reference only |

## Direction

- Distributable CLI + host-spawned MCP  
- User/agent Python statement parsers in data dir  
- SQLite ledger; summary PDF v1; Sheets later as exporter plugin  
- Agent loop: preview → parser → ingest → categorize → breakdown → PDF  
- Guardrails first (Phase 0)  
- Country-agnostic core; locale defaults are config  

## Disk path

Project directory may be `~/development/canhoto` (renamed folder). Git history may still say `personal-finance-ingest`.
