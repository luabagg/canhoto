# Project status

**Canonical design (2026-07-29):** see `docs/ARCHITECTURE.md` and  
`docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md`.

**Agent bootstrap:** `AGENTS.md`.

## Branches

| Branch | Meaning |
|---|---|
| `main` | Target architecture docs + phased implementation plan; legacy MVP code still present until redesign lands |
| `archive/2026-07-29-pre-engine-redesign` | Frozen WIP before redesign (Itaú parsers, Sheets OAuth, expanded tests, draft plans) |

## Direction (summary)

- Distributable CLI package + optional host-spawned MCP (`finance-mcp`)
- User/agent **Python statement parsers** in data dir (no required built-in banks)
- SQLite ledger; **summary PDF** export v1; Sheets deferred as future exporter plugin
- Hermes loop: preview → parser → ingest → categorize → breakdown → PDF
- Guardrails first (Phase 0): redaction, batch caps, MCP allowlist, no raw SQL

## Legacy note

Older “Mercado Pago + Sheets + fat MCP” behavior may still exist in the tree on `main` from the initial commits. Treat it as scaffolding to replace per the plan, not as the product contract.
