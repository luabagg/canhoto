# Writing a Canhoto statement parser

Canhoto does **not** ship bank parsers in the wheel. You (or an agent) add
Python plugins under the **data dir**:

```text
$CANHOTO_DATA_DIR/parsers/   # or ~/.canhoto/parsers/
```

This `examples/parsers/` tree is **documentation only**. Nothing here is
imported or auto-loaded at runtime.

## Contract

Each module must expose a zero-arg `register()` that returns an object
satisfying `canhoto.parsers.protocol.StatementParser`:

| Member | Role |
|--------|------|
| `id: str` | Stable parser id (matches `config.json` entry) |
| `statement_type: str` | `"account"` or `"card"` (free string; those are the usual values) |
| `institution: str` | Free-form label |
| `version: str` | Your version string |
| `sniff(text) -> float` | `0.0`–`1.0` confidence this parser owns the document |
| `parse(text, source_file) -> ParseResult` | Normalized meta + `LedgerTransaction` rows |

```python
def register():
    return MyParser()
```

A module-level `PARSER = ...` attribute is **not** supported. Discovery stays
unambiguous: only `register()`.

`parse` should return `canhoto.core.models.ParseResult` with:

- `meta`: `StatementMeta` (`statement_type`, `source_file`, optional institution/period)
- `transactions`: list of `LedgerTransaction` (money as `amount_minor` integer cents)

Leave classification defaults alone unless you truly know them (`category` /
`kind` empty, `needs_review=True`).

## Lifecycle (test before enable)

1. **Scaffold or copy** a module into the data-dir parsers folder  
   - `canhoto parsers scaffold --id my_bank_card --type card --institution "My Bank"`  
   - or copy `demo_line_parser.py` from this directory
2. **Register** it in `config.json` (scaffold does this disabled) with
   `enabled: false` until tests pass.
3. **Implement** `sniff` / `parse` against a redacted sample in `fixtures/`.
4. **Test**  
   `canhoto parsers test --id my_bank_card --file ~/.canhoto/fixtures/sample.txt`
5. **Enable** only after a successful test stamp  
   `canhoto parsers enable --id my_bank_card`
6. **Ingest** uses **enabled** parsers only; `choose_parser` picks the highest
   positive `sniff` score.

Enable is gated: if the last `parsers test` did not stamp OK, enable fails.

## Demo line parser

[`demo_line_parser.py`](./demo_line_parser.py) understands a trivial text
format used for docs and local dry-runs (not a real bank):

```text
DEMO_STATEMENT account Demo Bank
2026-07-01 -12.50 COFFEE SHOP
2026-07-02 1000.00 PAYROLL
```

Install into the data dir (example):

```bash
canhoto init   # if needed
cp examples/parsers/demo_line_parser.py ~/.canhoto/parsers/
# If not using scaffold: add a parsers[] entry in config.json
#   { "id": "demo_line", "module": "demo_line_parser.py", "enabled": false }
printf '%s\n' \
  'DEMO_STATEMENT account Demo Bank' \
  '2026-07-01 -12.50 COFFEE SHOP' \
  '2026-07-02 1000.00 PAYROLL' \
  > ~/.canhoto/fixtures/demo_statement.txt
canhoto parsers test --id demo_line --file ~/.canhoto/fixtures/demo_statement.txt
canhoto parsers enable --id demo_line
```

Or scaffold a stub and paste logic from the demo:

```bash
canhoto parsers scaffold --id demo_line --type account --institution Demo
# edit ~/.canhoto/parsers/demo_line.py
canhoto parsers test --id demo_line --file /path/to/sample.txt
canhoto parsers enable --id demo_line
```

## Security

Parser modules are **trusted local code** (same class as a script you run
yourself). Canhoto only loads modules listed under the configured parsers dir
and registered in config. Prefer timeout around parse in long-running hosts;
never auto-download parsers from the network.

## See also

- `canhoto.parsers.protocol.StatementParser`
- `canhoto.parsers.scaffold` — stub generator (`register()` only)
- `docs/ARCHITECTURE.md` — product contract for plugins and guardrails
