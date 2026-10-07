# Canhoto

Canhoto keeps your bank and card statements on your computer. It parses
statements, categorizes spending, asks you about uncertain items, and exports a
monthly PDF summary.

> **Using an AI agent?** Connect `canhoto-mcp`. The agent gets a bounded set of
> tools to parse statements, review and categorize transactions, read monthly
> totals, and export reports. It never gets SQL access or a full ledger dump.
> The CLI gives you the same workflow by hand.

| | |
|---|---|
| Package | `canhoto` |
| CLI | `canhoto` |
| MCP | `canhoto-mcp` |
| Data | `~/.canhoto` or `$CANHOTO_DATA_DIR` |

## Install

Install the CLI and the MCP server from PyPI:

```bash
uv tool install canhoto
```

Or install from a checkout of this repository:

```bash
uv tool install .
```

Or run it in place:

```bash
uv sync
uv run canhoto --help
```

Then create the data directory and check it:

```bash
canhoto init
canhoto doctor
```

## How it works

```mermaid
flowchart TD
  A[Statement PDF or text] --> B[Parser]
  B --> C[Ingest]
  C --> D[(Local SQLite ledger)]
  D --> E[Your rules, built-in rules, merchant memory]
  E --> F[Review uncertain items]
  F --> G[Apply categories]
  G --> H[Monthly breakdown]
  H --> I[Summary PDF]
```

Parsers only read statement rows. Canhoto handles categories, rules, merchant
memory, reports, and exports.

## Create a parser

Canhoto does not ship bank-specific parsers. A parser is one small Python file
in `~/.canhoto/parsers/`. It reads the text of a statement and returns its rows.
You do not need this repository to write one.

1. Create the parser file:

   ```bash
   canhoto parsers scaffold --id my_bank_card --type card --institution my_bank
   ```

2. See the text the parser receives. This is the extracted text, not the PDF
   layout:

   ```bash
   canhoto parsers preview --file ~/statements/sample.pdf > sample.txt
   ```

3. Edit `~/.canhoto/parsers/my_bank_card.py`. The file already reads rows such
   as `2026-06-02  ACME STORE  -12.34`, and its comments list the rules.
   Change three things:
   - `sniff()`: return a score above 0 only for text unique to this statement.
   - `_ROW` and `parse()`: match the row format you saw in step 2.
   - `_CURRENCY`: your ISO 4217 currency code.

4. Test the parser, then enable it:

   ```bash
   canhoto parsers test --id my_bank_card --file ~/statements/sample.pdf
   canhoto parsers enable --id my_bank_card
   ```

The test passes only when `parse()` returns at least one transaction and
`sniff()` claims the sample. A failed test disables the parser until it passes
again.

Keep transaction ids stable: build them from the bank's operation id, or from
the date, amount, and description. Never use the row position, because then
two statements can overwrite each other's rows. Leave `category` and `kind`
empty. Your rules and review set them.

For password-protected PDFs, pass `--pdf-password` or set
`CANHOTO_PDF_PASSWORD`. For a complete example, see
[`examples/parsers/`](https://github.com/luabagg/canhoto/tree/main/examples/parsers).
An agent connected to `canhoto-mcp` can also write the parser for you. See
the MCP section below.

## Process a month

```bash
# Read statements into the ledger.
canhoto ingest ~/statements/*.pdf

# Apply your rules, the built-in rules, and merchant memory.
canhoto categorize rules --month 2026-06

# List the items that still need a decision.
canhoto review --month 2026-06

# Apply your decisions.
canhoto categorize apply --file patches.json

# See income, expenses, and category totals.
canhoto breakdown --month 2026-06

# Write the PDF summary.
canhoto export pdf 2026-06
```

`patches.json` is a list of changes, one per transaction id from `review`:

```json
[
  { "id": "my_bank_card-2026-06-02-0001", "category": "Groceries",
    "kind": "expense", "is_expense": true, "needs_review": false }
]
```

Canhoto marks every row you change this way as `manual`. No automatic rule
changes a manual row again.

The PDF goes to `~/.canhoto/exports/2026-06-summary.pdf` by default. It shows
totals by category and the top merchants in each category. It never contains a
transaction list or raw statement descriptions.

### Keep manual transactions

Some money moves outside every statement you can export, for example a Pix sent
straight from a savings reserve. Keep those rows yourself:

```bash
canhoto manual add --date 2026-09-17 --amount -3080.00 \
  --description "Pix enviado Example Tax Office" --category Taxes \
  --merchant IPVA --account cofrinho --note "Car tax, paid from the reserve"
canhoto manual list [--month 2026-09]
canhoto manual edit --id manual-... --amount -3100.00 --category Taxes
canhoto manual remove --id manual-...
```

A negative amount is money out. With `--category`, the row is set by hand.
Without it, your rules classify the row, or it waits in `review`. Canhoto
refuses to add the same date, amount, description, and account twice. An edit
keeps the id. `edit` and `remove` refuse statement rows: those change only when
you ingest the statement again.

### Teach Canhoto your rules

When a counterparty always means the same thing, store a rule. `categorize
rules` applies it to every future statement.

```bash
canhoto rules add --pattern "PIX RECEBIDO ACME LTDA" --direction in \
  --min 1200 --max 1300 --category Income --kind income \
  --note "Monthly pay from my company"
canhoto rules list
canhoto rules remove --id 3
```

| Option | Meaning |
|---|---|
| `--pattern` | Regular expression, case-insensitive, matched against the description. |
| `--direction` | `in` (money received), `out` (money sent), or `any`. |
| `--min`, `--max` | Amount range, inclusive, without the sign. Both are optional. |
| `--source-kind` | Match only `account` or `card` rows. |
| `--category` | The category to set. |
| `--kind` | `expense`, `income`, `transfer`, `internal_transfer`, `self_transfer`, or `card_payment`. Transfers do not count as income or spending. |
| `--review` | Set the category, but keep the row in the review queue. Use this when an amount range cannot separate two cases. |
| `--note` | Why the rule exists. Agents read it during review. Do not put secrets in it. |
| `--priority` | Lower numbers run first. The first matching rule wins. |

Your rules run before the built-in rules. They never change manual rows. When
you upgrade to the version with rules, Canhoto marks your existing reviewed
rows as manual.

To remember one merchant without a full rule, use merchant memory:

```bash
canhoto categorize merchant --key CURSOR --category Subscriptions
```

### PDF profiles

Choose a built-in style:

```bash
canhoto export pdf 2026-06 --profile canhoto
canhoto export pdf 2026-06 --profile modern --output ~/Documents/2026-06.pdf
canhoto export pdf 2026-06 --profile minimal
```

- `canhoto`: receipt-style report with a category chart.
- `modern`: clean report with metric cards and a category chart.
- `minimal`: text-only report without a chart.

## Back up and restore

Write your ledger, rules, merchant memory, config, and parsers to one file:

```bash
canhoto backup                        # ./canhoto-YYYY-MM-DD.canhoto
canhoto backup --output ~/backups/home.canhoto
```

Restore it into a new or empty data directory. Do not run `canhoto init` there first:

```bash
CANHOTO_DATA_DIR=~/.canhoto-new canhoto restore ~/backups/home.canhoto
```

A `.canhoto` file is a zip archive. Open it with any unzip tool:

| File | Content |
|---|---|
| `manifest.json` | Format version, Canhoto version, schema revision, row counts, SHA-256 of each file |
| `canhoto.sql` | Plain SQL dump of `canhoto.db`: schema and rows. `sqlite3 new.db < canhoto.sql` rebuilds it. |
| `config.json` | Settings and the parser registry |
| `parsers/*.py` | Your parser modules |

The backup does not include raw statements. A restored ledger cannot re-parse
old statements until you ingest them again.

Restore checks every checksum and the schema revision before it writes. It
prepares and migrates the ledger in a private temporary directory. It installs
the full restore only after all files are ready. A failed restore permits a
retry. Restore refuses non-empty directories and directory links. It keeps
parser modules in the restored directory's `parsers/` folder, even when the
backup used a custom parser location.

Restore only backups you trust. Checksums do not authenticate the sender. The
backup includes executable parser modules and holds your full ledger in plain
text, so keep the file private. `backup` and `restore` are CLI only: the MCP
server never gives an agent a full ledger dump.

## MCP

The CLI and the MCP server use the same service layer. For agent-assisted use,
start the MCP server. The agent follows this flow:

`statement_preview` -> `parser_*` -> `ingest` -> `rule_list` -> `run_rules` ->
`review_batch` -> `set_categories` -> `month_breakdown` -> `export_pdf`

When you explain a recurring counterparty to the agent, it can store it with
`rule_add`. The MCP server exposes only domain tools. It does not give SQL
access or full ledger dumps.

To let an agent write parsers, add this to `~/.canhoto/config.json`:

```json
{ "agent_view": { "allow_parser_writes": true } }
```

Example MCP host configuration:

```yaml
mcp_servers:
  canhoto:
    command: canhoto-mcp
```

## CLI commands

```text
canhoto init | doctor
canhoto parsers scaffold|preview|test|enable|list
canhoto ingest <files...> [--pdf-password PASSWORD]
canhoto categorize rules --month YYYY-MM
canhoto categorize apply --file patches.json
canhoto categorize merchant --key KEY --category CAT
canhoto rules add|list|remove
canhoto review --month YYYY-MM [--cursor ID] [--limit N]
canhoto breakdown --month YYYY-MM
canhoto export pdf YYYY-MM [--profile canhoto|modern|minimal] [--output PATH]
canhoto manual add --date YYYY-MM-DD --amount SIGNED --description TEXT [--category CAT]
canhoto manual list [--month YYYY-MM] | edit --id ID [fields] | remove --id ID
canhoto backup [--output PATH]
canhoto restore PATH
```

## Develop

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src/canhoto tests
uv run mypy -p canhoto
```

Or use the [`justfile`](https://github.com/luabagg/canhoto/blob/main/justfile) with [Just](https://just.systems/).

### Release

Pushing a version tag publishes to PyPI through
[`.github/workflows/release.yml`](https://github.com/luabagg/canhoto/blob/main/.github/workflows/release.yml). The workflow
tests, builds, smoke-tests the wheel and the source distribution, and publishes
with PyPI Trusted Publishing. The tag must match the version in
`pyproject.toml`.

```bash
uv version --bump patch   # or minor / major
git commit -am "chore: release v$(uv version --short)"
git tag -a "v$(uv version --short)" -m "v$(uv version --short)"
git push origin main --tags
```

## Privacy

Your statements and database stay in the data directory. Do not commit
statements, tokens, database files, backups, or `~/.canhoto`. Run
`canhoto backup` before you upgrade: the database holds your ledger and your
rules.
