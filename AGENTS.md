# Agent bootstrap — Canhoto

You are implementing **Canhoto**, a local personal finance engine. Read this file completely before editing code.

**Canhoto** = the stub/counterfoil you keep (document sense). Target CLI/MCP: **`canhoto`** / **`canhoto-mcp`**.

---

## STOP — Day-1 reality (read before anything else)

**Canhoto runtime is the product.** Primary code lives in `src/canhoto/` with console scripts `canhoto` / `canhoto-mcp`.

| Layer | On `main` now |
|---|---|
| Product / package | **Canhoto** / `canhoto` |
| CLI / MCP | `canhoto` / `canhoto-mcp` |
| Data dir | `~/.canhoto` / `$CANHOTO_DATA_DIR` |
| Parsers | User/agent plugins in data dir (see `examples/parsers/`) |
| Guardrails | `tests/guardrails/` |
| PDF | Summary exporter (`export pdf`) |
| Legacy | `src/finance_ingest/` may remain as **reference only** — not shipped |

**Source of truth:** `docs/ARCHITECTURE.md` + plan. Prefer deleting leftover legacy modules over dual-maintaining them.

Repo path on disk may be `~/development/canhoto` while git history still mentions `personal-finance-ingest`. Fine.

```text
docs/ARCHITECTURE + plan  ──►  WHAT TO BUILD (wins on conflict)
src/finance_ingest        ──►  OLD MVP (reference / delete / port)
archive/* branch          ──►  RICHER OLD WIP (Itaú, Sheets tests) — see docs/ARCHIVE_BRANCH.md
```

---

## Read order (mandatory)

1. This file (`AGENTS.md`) — especially **Day-1 reality** above  
2. `docs/ARCHITECTURE.md` — product contract  
3. `docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md` — phased tasks  
4. `docs/ARCHIVE_BRANCH.md` — only when porting algorithms/fixtures from old WIP  
5. Branch `archive/2026-07-29-pre-engine-redesign` — **reference only**, never implement on it  

Do **not** treat Sheets-centric flows in legacy modules as the product contract.

---

## Identity (target — use in **new** code and docs)

| Layer | Value |
|---|---|
| Product | Canhoto |
| CLI | `canhoto` |
| MCP binary | `canhoto-mcp` |
| Import package | `canhoto` |
| Data dir | `~/.canhoto` / `$CANHOTO_DATA_DIR` |
| DB | `canhoto.db` |

Do **not** add new public `finance_*` names. While migrating, temporary shims are OK only if the plan task says so; prefer clean cut.

---

## Mission

Build a distributable tool:

- **CLI** `canhoto` — init, doctor, parsers, ingest, categorize, review, export PDF  
- **MCP** `canhoto-mcp` — host-spawned stdio domain tools  
- **User Python parsers** in `~/.canhoto/parsers/` (no mandatory bank parsers in the wheel)  
- **SQLite** ledger as system of record  
- **Summary PDF** export v1  
- **Guardrails** — redacted review + aggregates; never raw SQL / unbounded ledger dumps  
- **Country-agnostic core** — locale defaults (e.g. BRL) are config/profile, not the kernel  

---

## Hard rules

| Do | Do not |
|---|---|
| Follow plan phases **0 → 7** in order | “Just rename files” and call the redesign done |
| Start at **Phase 0** (contracts + guardrail tests) | Start by polishing Sheets or fat MCP |
| Treat architecture/plan as winning | Copy legacy MCP tool list or Sheets into core |
| Keep money out of git | Commit statements, tokens, DB files |
| MCP tools ⊆ plan allowlist | Add `sql_query` or full ledger dump tools |
| Parser enable only after test | Auto-download parsers from the network |
| PDF summary only in v1 | Full transaction listing PDF in v1 |
| Locale-pluggable rules | Hardcode PIX/BRL/Itaú as the only path |
| Use `docs/ARCHIVE_BRANCH.md` to port | `git checkout` archive and develop there |
| Delete or quarantine dead legacy | Leave two competing products in `src/` forever |

---

## What is actually in the tree right now

### Present (legacy MVP)

```text
src/finance_ingest/
  cli.py, config.py, models.py, categorize.py, service.py, store.py
  pdf_text.py, mcp_server.py, sheets.py
  parsers/mercadopago_account.py, mercadopago_card.py, __init__.py
tests/test_parsers.py, test_service_store.py, fixtures/mercadopago-*
pyproject.toml  → name personal-finance-ingest, scripts finance / finance-mcp
```

### Present (Canhoto docs — implement against these)

```text
AGENTS.md
docs/ARCHITECTURE.md
docs/ARCHIVE_BRANCH.md
docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md
STATUS.md
README.md   # target UX; not proof runtime exists
```

### Absent until you build them

- `src/canhoto/`
- `tests/guardrails/`
- Plugin parser loader / scaffold / enable flow  
- Summary PDF exporter  
- `canhoto` / `canhoto-mcp` console scripts  

### Archive branch (not checked out)

Richer pre-redesign WIP (Itaú parsers, google_auth, more tests). Catalog: `docs/ARCHIVE_BRANCH.md`.

---

## Branches

| Branch | Role |
|---|---|
| `main` | Canhoto **docs** + legacy **MVP code** — implement here |
| `archive/2026-07-29-pre-engine-redesign` | Frozen lab snapshot — read via `git show`, don’t develop on it |

```bash
git branch -v
git show archive/2026-07-29-pre-engine-redesign:src/finance_ingest/store.py | head
```

---

## Commands

### Today (legacy package still installed that way)

```bash
cd ~/development/canhoto   # or your clone path
uv sync --extra dev        # lockfile may be incomplete on main; unlock/sync as needed
uv run pytest -q
uv run ruff check .
uv run mypy src
# legacy entrypoints still:
#   uv run finance --help
#   uv run finance-mcp
```

### After rename tasks (target)

```bash
uv run pytest tests/guardrails -q
uv run pytest -q
uv run canhoto --help
uv run canhoto-mcp
```

`tests/guardrails` will **fail/missing until Phase 0** — creating that suite *is* Phase 0.

---

## Implementation pattern

1. Open the **current phase** in the plan; finish it before the next.  
2. **Phase 0 first** — models/policy/redaction/allowlist tests even if Hermes demo feels urgent.  
3. Each task: failing test → code → pass → commit.  
4. When legacy conflicts with architecture, **delete or move legacy**, don’t dual-maintain forever.  
5. Prefer greenfield `src/canhoto/` + thin deprecation of `finance_ingest`, or in-place migrate with rename in Phase 1 — pick one approach early and stick to it (plan allows either; don’t half-do both).  
6. Port useful bits from archive (store cents, categorize ideas, fixtures) using `docs/ARCHIVE_BRANCH.md`.  

---

## Agent acceptance sketch (end state)

```text
preview statement → write parser → test → enable → ingest
→ run_rules → review_batch / set_categories → month_breakdown → export_pdf
```

---

## Security note (parser option A)

User/agent-written Python parsers are trusted local code. Enforce: data-dir only, test-before-enable, MCP `parser_write` gated by `allow_parser_writes`. Prefer timeout around parse execution.

---

## Config location (target)

```text
$CANHOTO_DATA_DIR  or  ~/.canhoto/
  config.json
  canhoto.db
  parsers/
  exports/
  raw/
  fixtures/
```

---

## Done means

`docs/ARCHITECTURE.md` success criteria + plan Phase 7 exit are met, and **runtime** entrypoints are `canhoto` / `canhoto-mcp` with guardrail tests green — not merely docs updated.
