# Canhoto

**The stub you keep.** Local statement → ledger → categorize → summary PDF.

Installable CLI + optional MCP server. Point at bank/card statements, author Python parsers, store a normalized SQLite ledger, categorize, export a monthly **summary** PDF.

| | |
|---|---|
| Package | `canhoto` |
| CLI | `canhoto` |
| MCP | `canhoto-mcp` |
| Data | `~/.canhoto` or `$CANHOTO_DATA_DIR` |

## Install

```bash
uv tool install canhoto
# or from this checkout:
uv sync
uv run canhoto --help
```

```bash
canhoto init
canhoto doctor
```

### MCP host (e.g. Hermes)

```yaml
mcp_servers:
  canhoto:
    command: canhoto-mcp
```

For agent-authored parsers, set in `~/.canhoto/config.json`:

```json
{ "agent_view": { "allow_parser_writes": true } }
```

## Workflow

```bash
# author a parser (or let an agent do it via MCP)
canhoto parsers scaffold --id my_bank_card --type card --institution my_bank
# edit ~/.canhoto/parsers/my_bank_card.py  (must implement register())
canhoto parsers test --id my_bank_card --file ~/statements/sample.pdf
canhoto parsers enable --id my_bank_card

# monthly
canhoto ingest ~/statements/*.pdf
canhoto categorize rules --month 2026-06
canhoto review --month 2026-06 --json
canhoto breakdown --month 2026-06
canhoto export pdf 2026-06
# → ~/.canhoto/exports/2026-06-summary.pdf
```

Demo parser (not shipped into runtime): [`examples/parsers/`](examples/parsers/).

## Design

- **Parsers:** user plugins under the data dir — no required bank parsers in the package
- **Ledger:** SQLite (`canhoto.db`) is system of record
- **MCP:** domain tools only (preview → parser → ingest → categorize → breakdown → PDF). No raw SQL
- **Guardrails:** redacted review batches, month required, batch caps; summary PDF has no full tx dump
- **Core:** country-agnostic; currency/locale defaults are config

## CLI surface

```text
canhoto init | doctor
canhoto parsers scaffold|test|enable|list
canhoto ingest <files...>
canhoto categorize rules --month YYYY-MM
canhoto categorize apply --file patches.json
canhoto categorize merchant --key KEY --category CAT
canhoto review --month YYYY-MM [--cursor] [--limit]
canhoto breakdown --month YYYY-MM
canhoto export pdf YYYY-MM
```

Parser dry-run before enable is `parsers test` (not a separate `parse` command). MCP agents use `statement_preview` for text, not full ledger dumps.

## Develop

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src/canhoto tests
uv run mypy -p canhoto
```

Agent bootstrap: [`AGENTS.md`](AGENTS.md).

## Privacy

Money data stays under your data dir. Never commit statements, tokens, or `~/.canhoto`.
