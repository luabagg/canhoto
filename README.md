# personal-finance-ingest

Mercado Pago **account + credit-card PDF statements** → local SQLite → **Google Sheets**, with an **MCP tool proxy** so an agent (Hermes, Claude, etc.) drives the whole flow.

No LangChain. Deterministic parsers + rule categorization + optional agent classification patches. Sheets formulas/views stay agent-free after rows are written.

## Install

```bash
cd personal-finance-ingest
uv sync --extra dev --extra sheets
# or: pip install -e ".[dev,sheets]"
```

## CLI

```bash
# parse without storing
finance parse tests/fixtures/mercadopago-account-2026-06.pdf

# ingest + rule categorize
finance ingest path/to/extrato.pdf path/to/fatura.pdf

finance list --month 2026-06 --needs-review
finance summary 2026-06
finance reconcile 2026-06
finance export 2026-06

# Google Sheets (after OAuth token with Sheets scope)
finance configure --spreadsheet-id YOUR_SHEET_ID \
  --google-token ~/.hermes/google_token.json
finance sheets-setup
finance sheets-push 2026-06
```

Data dir: `~/.finance-ingest/` (override with `FINANCE_DATA_DIR`).

## MCP server (agent proxy)

Exposes tools for full agentic control:

| Tool | Role |
|------|------|
| `finance_parse_statement` | dry-run parse |
| `finance_ingest` | parse + store |
| `finance_list_transactions` | query ledger |
| `finance_get_pending_review` | rows needing labels |
| `finance_auto_categorize` | re-run rules |
| `finance_apply_classifications` | agent patches |
| `finance_get_monthly_summary` | totals |
| `finance_reconcile` | counts + notes |
| `finance_sheets_setup` / `finance_sheets_push` | Sheets |
| `finance_export_json` | local export |
| `finance_configure` / `finance_get_config` | config |

### Hermes

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  finance:
    command: uv
    args: ["run", "--directory", "/home/luanb/development/personal-finance-ingest", "finance-mcp"]
```

Or after install: `command: finance-mcp`.

Restart Hermes / new session so `finance_*` tools appear.

### Suggested agent loop

1. `finance_ingest([pdf_paths])`
2. `finance_get_pending_review(month)`
3. `finance_apply_classifications([...])` for each ambiguous merchant
4. `finance_get_monthly_summary(month)` + `finance_reconcile(month)`
5. `finance_sheets_push(month)` (only after user approval)
6. Export PDF from Sheets **Monthly Summary** (File → Download → PDF)

## Sheet layout

Dedicated spreadsheet (not the stock tracker):

- **Bank Transactions** — account ledger rows  
- **Card Transactions** — card purchases / payments  
- **Monthly Summary** — income / expenses / net + category amounts  

### Budget categories

Aligned with your existing Monthly Budget labels:

`Car payment`, `Gas/travel`, `Investments`, `Groceries`, `Eating`, `Personal care`, `Electric`, `Condo Fee`, `Rent/mortgage`, `House`, `Internet`, `Cell phone`, `Entertainment`, `Purchases`, `Others`, plus `Income` / `Transfer` / `Uncategorized`.

### Accounting rules

- Card purchases = expenses  
- Paying the card bill from the account = `card_payment` (not double-counted)  
- Piggy reserve moves = internal transfer  
- PIX to your own name = self transfer  

## Tests

```bash
uv run pytest -q
```

Fixtures use real Mercado Pago export shapes (account extrato + card fatura).

## Privacy

- Raw PDFs copied under `~/.finance-ingest/raw/`  
- Local DB before any cloud write  
- Sheets push is explicit (`finance_sheets_push`)  

## Linear

Tracks **Personal Finance Ingest Agent** (`LUA-76`…`LUA-78`).
