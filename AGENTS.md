# Agent bootstrap — Canhoto

Read this before editing code.

## Product

| Layer | Value |
|---|---|
| Product | **Canhoto** (stub/counterfoil you keep) |
| Package / import | `canhoto` |
| CLI | `canhoto` |
| MCP | `canhoto-mcp` |
| Data | `~/.canhoto` / `$CANHOTO_DATA_DIR` |
| DB | `canhoto.db` |

User docs: [`README.md`](README.md).

## Layout

```text
src/canhoto/
  core/           # models, config, store, policy, redaction, categorize, breakdown, pdf_text
  parsers/        # Protocol, loader, scaffold (no bank logic)
  exporters/      # pdf_summary
  mcp/            # allowlist + Fast/MCP server → service only
  service.py      # façade for CLI + MCP
  cli.py
examples/parsers/ # docs-only demo (not auto-loaded)
tests/guardrails/ # privacy/allowlist contracts
```

Dependency direction: `cli` / `mcp` → `service` → `core` + ports.

## Hard rules

| Do | Do not |
|---|---|
| Keep money out of git | Commit statements, tokens, DB files |
| MCP tools ⊆ `MCP_TOOL_ALLOWLIST` | Add `sql_query` or full ledger dumps |
| Review via `to_review_item` + policy | Return raw `LedgerTransaction` to agents |
| Parser enable only after successful `parser_test` (non-empty txs) | Auto-download parsers; stamp OK on empty parse |
| PDF summary only | Full transaction listing PDF |
| Country-agnostic core | Hardcode one bank as the kernel |
| Prefer deleting dead code | Dual-maintain a second product tree |

## MCP happy path

1. `statement_preview` → `parser_write` / `parser_test` → `parser_enable`  
2. `ingest`  
3. `run_rules` → `review_batch` loop → `set_categories`  
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
```

## Commands

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src/canhoto tests
uv run mypy -p canhoto
uv run canhoto --help
uv run canhoto-mcp   # stdio; host-spawned
```

## Quality bar

- TDD for behavior changes; meaningful tests only  
- No Google/Sheets in core  
- No public `finance_*` names  
- Guardrails in `tests/guardrails/` must stay green  
