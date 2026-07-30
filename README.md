# Canhoto

**The stub you keep.** Local statement → ledger → categorize → summary PDF.

Canhoto is a personal finance **engine**: drop bank/card statements, let an agent (or you) author parsers, store a normalized ledger in SQLite, categorize expenses, export a **monthly summary PDF**. Optional MCP (`canhoto-mcp`) for hosts like Hermes.

- **Not** a hosted bank connection (no Pluggy/Open Finance required)
- **Not** Google Sheets–centric (Sheets may return later as an export plugin)
- **Country-agnostic core** — any bank that can be parsed; locale defaults are config

| | |
|---|---|
| CLI | `canhoto` |
| MCP | `canhoto-mcp` |
| Data | `~/.canhoto` (`CANHOTO_DATA_DIR`) |
| Package | `canhoto` |

> **Implementers:** [`AGENTS.md`](AGENTS.md) → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) → [plan](docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md).  
> **Status:** [`STATUS.md`](STATUS.md). **Migration from archive parsers:** [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Install

```bash
uv tool install canhoto
# or from a checkout:
uv sync
uv run canhoto --help
```

```bash
canhoto init
canhoto doctor
```

### Hermes / MCP hosts

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  canhoto:
    command: canhoto-mcp
```

Host spawns MCP over stdio — you do not keep a server running manually.

For full agent parser authoring, set in `~/.canhoto/config.json`:

```json
{
  "agent_view": { "allow_parser_writes": true }
}
```

## Workflow

```bash
# one-time / when bank layout is new
canhoto parsers scaffold --id my_bank_card --type card --institution my_bank
# agent or you writes parser under ~/.canhoto/parsers/
canhoto parsers test --id my_bank_card --file ~/statements/sample.pdf
canhoto parsers enable --id my_bank_card

# monthly
canhoto ingest ~/statements/*.pdf
canhoto categorize rules --month 2026-06
canhoto review --month 2026-06 --json
# agent: review_batch + set_categories via MCP
canhoto breakdown --month 2026-06
canhoto export pdf 2026-06
# → ~/.canhoto/exports/2026-06-summary.pdf
```

Example parser template (not auto-loaded): [`examples/parsers/`](examples/parsers/).

## Design anchors

- **Parsers:** user/agent Python plugins (Strategy + Registry), not mandatory builtins  
- **Ledger:** SQLite system of record  
- **Export v1:** summary PDF only  
- **MCP:** domain tools (preview → parser → ingest → categorize → breakdown → PDF), never raw SQL  
- **Guardrails:** redacted review batches, month required, batch caps  

Full contract: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Develop

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run canhoto doctor
```

## Privacy

Local money data stays under your data dir. Never commit statements, tokens, or `~/.canhoto`.
