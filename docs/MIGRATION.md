# Migration notes — archive → Canhoto data-dir parsers

**Product runtime is Canhoto** (`canhoto` / `canhoto-mcp`, package `canhoto`, data `~/.canhoto`).

Legacy package code may still exist under `src/finance_ingest/` for reference during transition, but it is **not** the install target. Prefer deleting it once you no longer need snippets.

## From archive branch parsers

Richer pre-redesign WIP (Itaú, Mercado Pago, etc.) lives on:

```text
archive/2026-07-29-pre-engine-redesign
```

Catalog: [`ARCHIVE_BRANCH.md`](ARCHIVE_BRANCH.md).

### Copy a parser into your data dir (example)

```bash
# inspect without checking out the archive branch
git show archive/2026-07-29-pre-engine-redesign:src/finance_ingest/parsers/mercadopago_card.py | head

# materialize into Canhoto plugins dir
mkdir -p "${CANHOTO_DATA_DIR:-$HOME/.canhoto}/parsers"
git show archive/2026-07-29-pre-engine-redesign:src/finance_ingest/parsers/mercadopago_card.py \
  > "${CANHOTO_DATA_DIR:-$HOME/.canhoto}/parsers/mercadopago_card.py"
```

Then adapt the module to the Canhoto contract:

1. Expose `register() -> StatementParser` (see `examples/parsers/demo_line_parser.py`).
2. Implement `sniff(text) -> float` and `parse(text, source_file) -> ParseResult`.
3. Emit `LedgerTransaction` rows (integer `amount_minor`, free-string institution/category/kind).
4. Register + test + enable:

```bash
canhoto init
# edit config.json parsers entry or use scaffold then overwrite
canhoto parsers test --id mercadopago_card --file ~/statements/sample.pdf
canhoto parsers enable --id mercadopago_card
canhoto ingest ~/statements/sample.pdf
```

### Sheets / Google OAuth

Removed from core. Do not port OAuth into Canhoto v1. If you need Sheets later, implement a separate **exporter plugin** outside the default install.

### Config / data dir rename

| Legacy | Canhoto |
|---|---|
| `~/.finance-ingest` / `FINANCE_DATA_DIR` | `~/.canhoto` / `CANHOTO_DATA_DIR` |
| `finance` / `finance-mcp` | `canhoto` / `canhoto-mcp` |

There is no automatic DB migrator in v1. Start fresh with `canhoto init` and re-ingest statements, or hand-copy SQLite only if you understand the new schema (`amount_minor`, `content_hash`, no required Sheets columns).
