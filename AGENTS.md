# Agent bootstrap — personal-finance-ingest

You are implementing (or extending) a **local personal finance engine**. Read this file completely before editing code.

## Read order (mandatory)

1. This file (`AGENTS.md`)
2. `docs/ARCHITECTURE.md` — product contract, ports, guardrails, Hermes flow
3. `docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md` — phased tasks
4. Only if you need old reference code: branch `archive/2026-07-29-pre-engine-redesign`

Do **not** treat `STATUS.md` or older Sheets-centric docs as the target design unless they point here.

## Mission

Build a distributable tool:

- **CLI** `finance` — init, doctor, parsers, ingest, categorize, review, export PDF  
- **MCP** `finance-mcp` — host-spawned stdio tools for Hermes full loop  
- **User Python parsers** in `~/.finance-ingest/parsers/` (not mandatory bank parsers in the package)  
- **SQLite** ledger as system of record  
- **Summary PDF** export v1  
- **Guardrails** so agents get domain tools + redacted review/aggregates, **not** raw SQL or unbounded ledgers  

## Hard rules

| Do | Do not |
|---|---|
| Follow plan phases 0 → 7 in order | Start with MCP UI before Phase 0 contracts |
| TDD for core behavior + guardrails | Ship Sheets/Google in core v1 |
| Keep money under `FINANCE_DATA_DIR` / `~/.finance-ingest` | Commit real extratos, tokens, DBs |
| MCP tools ⊆ allowlist in plan | Add `sql_query` or full ledger dump tools |
| Parser enable only after test | Auto-download parsers from the network |
| PDF summary only in v1 | Full transaction listing PDF in v1 |
| Consult archive branch for old parsers/tests | Copy Sheets OAuth back into default install |

## Repo state you may see

- `main` — architecture + implementation plan + **legacy early code** from initial MVP (MP parsers, fat MCP, Sheets). Expect to **reshape or replace** toward the plan; do not assume legacy API is sacred.
- `archive/2026-07-29-pre-engine-redesign` — frozen WIP (Itaú, Sheets, expanded tests). **Reference only.**

```bash
git branch -v
git show archive/2026-07-29-pre-engine-redesign:src/finance_ingest/store.py | head
```

## Commands

```bash
# setup
uv sync --locked --extra dev   # adjust when pyproject changes; Sheets extra not required for v1

# quality gate (must pass before you stop a phase)
uv run pytest tests/guardrails -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## Implementation pattern

1. Open the **current phase** in the plan; finish its tasks before the next phase.  
2. Phase **0 first** (contracts + guardrail tests) even if you want Hermes demo soon.  
3. Each task: failing test → code → pass → commit.  
4. After each phase: run full quality gate.  
5. If architecture conflicts with legacy code, **architecture wins** — delete or quarantine legacy.

## Hermes acceptance sketch

```text
preview statement → write parser → test → enable → ingest
→ run_rules → review_batch / set_categories → month_breakdown → export_pdf
```

## Security note (parser option A)

User/agent-written Python parsers run as trusted local code. Enforce: data-dir only, test-before-enable, MCP `parser_write` gated by `allow_parser_writes`. Prefer timeout around parse execution when you wire ingest.

## Where config lives

```text
$FINANCE_DATA_DIR  or  ~/.finance-ingest/
  config.json
  finance.db
  parsers/
  exports/
  raw/
  fixtures/
```

## Done means

Plan **Success criteria** in `docs/ARCHITECTURE.md` §11 and plan Phase 7 exit are satisfied; guardrail checklist in the plan still green.
`
