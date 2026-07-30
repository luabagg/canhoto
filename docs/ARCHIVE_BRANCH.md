# Archive branch reference

**Branch:** `archive/2026-07-29-pre-engine-redesign`  
**Commit (creation):** `a445715` — full WIP snapshot before Canhoto engine redesign docs.

## When to open this branch

Only when implementing something that already existed and you need algorithms, fixtures, or tests:

- SQLite upsert / integer cents / statement `content_hash`
- Categorization heuristics worth porting into **locale rule packs**
- Example bank parse logic to turn into **user data-dir parsers** (not package builtins)
- Sheets writer ideas for a **future exporter plugin**

## When not to

- Defining product behavior (use `docs/ARCHITECTURE.md`)
- Naming, CLI, MCP allowlist, guardrails (use plan + ARCHITECTURE)
- “How do we support any bank?” → parser port, not archive merge
- Restoring Google Sheets as core

**Do not** `git checkout` the archive branch as your implementation branch for new Canhoto work. Prefer `git show` / `git grep` from `main`.

## How to read without switching branches

```bash
git fetch . archive/2026-07-29-pre-engine-redesign   # if needed locally
git log archive/2026-07-29-pre-engine-redesign -n 5 --oneline

git show archive/2026-07-29-pre-engine-redesign:src/finance_ingest/store.py | less
git show archive/2026-07-29-pre-engine-redesign:src/finance_ingest/categorize.py | less
git grep -n "def " archive/2026-07-29-pre-engine-redesign -- src/finance_ingest/store.py
```

## Path catalog (archive tree)

Paths below are on the **archive** branch (package still named `finance_ingest` there).

| Need | Archive path |
|---|---|
| SQLite ledger, migrations, upsert | `src/finance_ingest/store.py` |
| Config / data dir helpers | `src/finance_ingest/config.py` |
| Domain models (old) | `src/finance_ingest/models.py` |
| Rule categorization | `src/finance_ingest/categorize.py` |
| Service façade | `src/finance_ingest/service.py` |
| Fat MCP (do **not** copy tool surface) | `src/finance_ingest/mcp_server.py` |
| PDF text extract | `src/finance_ingest/pdf_text.py` |
| Parser dispatch (old hardcoded) | `src/finance_ingest/parsers/__init__.py` |
| Mercado Pago account/card | `src/finance_ingest/parsers/mercadopago_*.py` |
| Itaú account/card | `src/finance_ingest/parsers/itau_*.py` |
| Sheets + OAuth (future plugin only) | `src/finance_ingest/sheets.py`, `google_auth.py` |
| CLI (old command names) | `src/finance_ingest/cli.py` |
| Fixtures | `tests/fixtures/` |
| Expanded tests | `tests/test_*.py` |
| Old ops docs | `docs/setup.md`, `docs/remaining-work.md`, `docs/analysis.md` |
| Superseded draft plan | `docs/superpowers/plans/2026-07-29-categorization-only-mcp-and-pdf-adapters.md` |

## Porting rules

1. **Architecture wins** over archive behavior.  
2. Bank parsers → `examples/parsers/` or user `~/.canhoto/parsers/`, not required wheel contents.  
3. BR-specific regex (PIX, etc.) → locale/rules config, not eternal core.  
4. Sheets/OAuth → optional exporter later; no Google deps on default install.  
5. Rename while porting: `finance_ingest` → `canhoto`, CLI → `canhoto`.  
6. Keep guardrail tests green; never reintroduce unbounded ledger MCP tools “because archive had them.”

## Relationship to Canhoto

Archive = **pre-Canhoto laboratory**.  
Canhoto = **product name + redesign contract** on `main`.
