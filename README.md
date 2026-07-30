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

> **Implementers:** start at [`AGENTS.md`](AGENTS.md) → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) → [implementation plan](docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md).

## Status

**Dual state:** Canhoto is fully specified in docs; **runtime is still the old MVP** (`src/finance_ingest/`, CLI `finance` / `finance-mcp`). There is no `canhoto` console script until the implementation plan lands.

| | Now | Target |
|---|---|---|
| Package | `finance_ingest` | `canhoto` |
| CLI / MCP | `finance` / `finance-mcp` | `canhoto` / `canhoto-mcp` |
| Redesign | docs only | Phases 0–7 in the plan |

Implementers: **[`AGENTS.md`](AGENTS.md)** (Day-1 reality) → architecture → plan.  
Prior richer WIP: branch `archive/2026-07-29-pre-engine-redesign` ([catalog](docs/ARCHIVE_BRANCH.md)).

## Target install (after package rename)

```bash
uv tool install canhoto
# or: pipx install canhoto

canhoto init
canhoto doctor
```

### Hermes

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  canhoto:
    command: canhoto-mcp
```

Host spawns MCP over stdio — you do not keep a server running manually.

## Target workflow

```bash
# one-time / when bank layout is new
canhoto parsers scaffold --id my_bank_card --type card --institution my_bank
# agent writes parser under ~/.canhoto/parsers/
canhoto parsers test --id my_bank_card --file ~/statements/sample.pdf
canhoto parsers enable --id my_bank_card

# monthly
canhoto ingest ~/statements/*.pdf
canhoto categorize rules --month 2026-06
canhoto review --month 2026-06 --json
# agent: review_batch + set_categories via MCP
canhoto export pdf 2026-06
# → ~/.canhoto/exports/2026-06-summary.pdf
```

## Design anchors

- **Parsers:** user/agent Python plugins (Strategy + Registry), not mandatory builtins  
- **Ledger:** SQLite system of record  
- **Export v1:** summary PDF only  
- **MCP:** domain tools (preview → parser → ingest → categorize → breakdown → PDF), never raw SQL  
- **Guardrails:** redacted review batches, month required, batch caps  

Full contract: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Legacy checkout (contributors)

```bash
uv sync --extra dev
# current scripts may still be `finance` / `finance-mcp` until rename tasks
uv run pytest -q
```

## License / privacy

Local money data stays under your data dir. Never commit statements, tokens, or `~/.canhoto`.
