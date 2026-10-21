# Agent bootstrap — Canhoto

Read this before editing code.

## Product

| Layer | Value |
|---|---|
| Product | **Canhoto** (stub/counterfoil you keep) |
| Package / import | `canhoto` |
| CLI | `canhoto` |
| MCP | `canhoto-mcp` |
| API | `canhoto-api` |
| Page | `canhoto-page` |
| Data | `~/.canhoto` / `$CANHOTO_DATA_DIR` |
| DB | `canhoto.db` |

User docs: [`README.md`](README.md).

## Layout

```text
src/canhoto/
  core/           # models, config, store, migrate, policy, redaction, categorize, …
  migrations/     # Alembic scripts (SQLite)
  parsers/        # Protocol, loader, scaffold (no bank logic)
  exporters/      # pdf_summary
  mcp/            # allowlist + Fast/MCP server → service only
  api/            # loopback JSON → service only
  page/           # loopback static page; HTTP client of the API
  service.py      # façade for CLI, MCP, and API
  cli.py
  dashboard.py    # starts the API process side and the page side
examples/parsers/ # docs-only demo (not auto-loaded)
tests/guardrails/ # privacy/allowlist contracts
```

Dependency direction: `cli` / `mcp` / `api` → `service` → `core` + ports.
`page` does not import `service`, `api`, or `core`. `dashboard` only starts the two servers.

## Hard rules

| Do | Do not |
|---|---|
| Keep money out of git | Commit statements, tokens, DB files |
| MCP tools ⊆ `MCP_TOOL_ALLOWLIST` | Add `sql_query` or full ledger dumps |
| Review via `to_review_item` + policy | Return raw `LedgerTransaction` to agents |
| Parser enable only after successful `parser_test` (non-empty txs) | Auto-download parsers; stamp OK on empty parse |
| PDF summary only | Full transaction listing PDF |
| Country-agnostic core | Hardcode one bank as the kernel |
| Prefer deleting dead code | Keep unused alternate trees |

## MCP happy path

1. `statement_preview` → `parser_scaffold` / `parser_write` → `parser_test` → `parser_enable`
2. `ingest`
3. `rule_list` → `run_rules` → `review_batch` loop → `set_categories` (and `set_merchant_category` as needed).
   Store recurring decisions with `rule_add` and a note.
   Rules never overwrite rows set by `set_categories`.
4. `month_breakdown` → `export_pdf`

`parser_write` requires `agent_view.allow_parser_writes=true`. CLI may always write local parsers.

## Data dir

```text
$CANHOTO_DATA_DIR or ~/.canhoto/
  config.json
  canhoto.db
  parsers/
  exports/
  raw/
  fixtures/
  inbox/
```

## Commands

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src/canhoto tests
uv run mypy -p canhoto
uv run canhoto --help
uv run canhoto-mcp   # stdio; host-spawned
uv run canhoto dashboard  # page :8766 and API :8765, loopback only
```

## Quality bar

- TDD for behavior changes; meaningful tests only
- No Google/Sheets in core
- Guardrails in `tests/guardrails/` must stay green

