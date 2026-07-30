# Project status — Canhoto

**Canonical design:** `docs/ARCHITECTURE.md`  
**Implementation plan:** `docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md`  
**Agent bootstrap:** `AGENTS.md`  
**Legacy code map:** `docs/ARCHIVE_BRANCH.md`

## Name

| | |
|---|---|
| Product | **Canhoto** (stub/counterfoil you keep) |
| CLI | `canhoto` |
| MCP | `canhoto-mcp` |
| Data | `~/.canhoto` / `$CANHOTO_DATA_DIR` |

## Branches

| Branch | Meaning |
|---|---|
| `main` | Canhoto architecture + phased plan; legacy MVP code may still use old `finance_*` paths until redesign lands |
| `archive/2026-07-29-pre-engine-redesign` | Frozen pre-redesign WIP (Itaú parsers, Sheets OAuth, expanded tests, draft plans) |

## Direction (summary)

- Distributable CLI package + optional host-spawned MCP (`canhoto-mcp`)
- User/agent **Python statement parsers** in data dir (no required built-in banks)
- SQLite ledger; **summary PDF** export v1; Sheets deferred as future exporter plugin
- Agent loop: preview → parser → ingest → categorize → breakdown → PDF
- Guardrails first (Phase 0): redaction, batch caps, MCP allowlist, no raw SQL
- **Country-agnostic core**; locale defaults (e.g. BRL) are profile/config, not the kernel

## Legacy note

Older “personal-finance-ingest / Mercado Pago + Sheets + fat MCP” behavior may still exist in the tree on `main`. Treat it as scaffolding to replace per the plan, not as the product contract.
