# Agent bootstrap — Canhoto

You are implementing (or extending) **Canhoto**, a local personal finance engine. Read this file completely before editing code.

**Canhoto** = the stub/counterfoil you keep (document sense). CLI is short: **`coto`**.

## Read order (mandatory)

1. This file (`AGENTS.md`)
2. `docs/ARCHITECTURE.md` — product contract, identity, ports, guardrails, locale vs core
3. `docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md` — phased tasks
4. `docs/ARCHIVE_BRANCH.md` — when (and only when) you need old reference code
5. Branch `archive/2026-07-29-pre-engine-redesign` — frozen WIP; **reference only**

Do **not** treat legacy README Sheets flow or old `STATUS.md` history as the target design.

## Identity (use these names in new work)

| Layer | Value |
|---|---|
| Product | Canhoto |
| CLI | `coto` |
| MCP binary | `coto-mcp` |
| Package import (target) | `canhoto` |
| Data dir | `~/.canhoto` / `$CANHOTO_DATA_DIR` |
| DB | `canhoto.db` |

Legacy in tree until rename tasks run: `finance_ingest`, `finance`, `finance-mcp`, `~/.finance-ingest`. **Architecture wins** — migrate toward Canhoto names; do not immortalize legacy strings in new modules.

## Mission

Build a distributable tool:

- **CLI** `coto` — init, doctor, parsers, ingest, categorize, review, export PDF  
- **MCP** `coto-mcp` — host-spawned stdio tools for full agent loop  
- **User Python parsers** in `~/.canhoto/parsers/` (no mandatory bank parsers in the package)  
- **SQLite** ledger as system of record  
- **Summary PDF** export v1  
- **Guardrails** — domain tools + redacted review/aggregates; **not** raw SQL or unbounded ledgers  
- **Country-agnostic core** — BR defaults allowed as profile; parsers work for any bank/country  

## Hard rules

| Do | Do not |
|---|---|
| Follow plan phases 0 → 7 in order | Start with MCP UI before Phase 0 contracts |
| TDD for core behavior + guardrails | Ship Sheets/Google in core v1 |
| Keep money under `CANHOTO_DATA_DIR` / `~/.canhoto` | Commit real statements, tokens, DBs |
| MCP tools ⊆ allowlist in plan | Add `sql_query` or full ledger dump tools |
| Parser enable only after test | Auto-download parsers from the network |
| PDF summary only in v1 | Full transaction listing PDF in v1 |
| Keep core locale-pluggable | Hardcode PIX/BRL/Itaú as the only path |
| Consult archive via `docs/ARCHIVE_BRANCH.md` | Merge archive branch wholesale into main |
| Use Canhoto / `coto` in new docs & APIs | Introduce new `finance_*` public names |

## Repo state you may see

- `main` — Canhoto architecture + implementation plan; **legacy MVP code** may still use `finance_ingest` until redesign tasks migrate it  
- `archive/2026-07-29-pre-engine-redesign` — frozen WIP (Itaú, Sheets, expanded tests). **Reference only**

```bash
git branch -v
# prefer path catalog:
# docs/ARCHIVE_BRANCH.md
git show archive/2026-07-29-pre-engine-redesign:src/finance_ingest/store.py | head
```

## Commands

```bash
# setup (adjust when pyproject becomes canhoto)
uv sync --locked --extra dev   # Sheets extra not required for v1

# quality gate (must pass before you stop a phase)
uv run pytest tests/guardrails -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

Target UX after rename:

```bash
coto init
coto doctor
coto parsers scaffold --id demo_card --type card --institution demo
coto ingest ~/statements/*.pdf
coto review --month 2026-06 --json
coto export pdf 2026-06
```

## Implementation pattern

1. Open the **current phase** in the plan; finish its tasks before the next phase.  
2. Phase **0 first** (contracts + guardrail tests) even if you want the agent demo soon.  
3. Each task: failing test → code → pass → commit.  
4. After each phase: run full quality gate.  
5. If architecture conflicts with legacy code, **architecture wins** — delete or quarantine legacy.  
6. Prefer package/module name `canhoto` in new layout (`src/canhoto/…`).

## Agent acceptance sketch

```text
preview statement → write parser → test → enable → ingest
→ run_rules → review_batch / set_categories → month_breakdown → export_pdf
```

## Security note (parser option A)

User/agent-written Python parsers run as trusted local code. Enforce: data-dir only, test-before-enable, MCP `parser_write` gated by `allow_parser_writes`. Prefer timeout around parse execution when you wire ingest.

## Where config lives

```text
$CANHOTO_DATA_DIR  or  ~/.canhoto/
  config.json
  canhoto.db
  parsers/
  exports/
  raw/
  fixtures/
```

## Done means

Plan **Success criteria** in `docs/ARCHITECTURE.md` §12 and plan Phase 7 exit are satisfied; guardrail checklist in the plan still green.
