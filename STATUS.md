# Project status — Personal Finance Ingest Agent

Last updated: 2026-07-10

Repo: `~/development/personal-finance-ingest`  
Linear project: **Personal Finance Ingest Agent**  
Goal: Mercado Pago PDFs → categorized ledger → **Google Sheets** (formulas for monthly summary) → user exports **monthly PDF** from Sheets.

---

## What has been done

### Product / architecture

- **Sheets-first** design: agent writes **transaction rows** only; summaries stay formula-driven in Sheets.
- **No LangChain** — fixed pipeline + optional agent classification via MCP.
- **MCP proxy layer** so Hermes (or any MCP client) controls the full flow tool-by-tool.
- Accounting rules encoded:
  - card purchases = expenses
  - account **Pagamento Cartão de crédito** = `card_payment` (excluded from spend)
  - piggy reserve moves = internal transfers
  - self PIX to own name = `self_transfer`
  - budget categories aligned with your existing **Monthly Budget** labels

### Code delivered

| Area | Status |
|------|--------|
| Mercado Pago **account** PDF/TXT parser | Done |
| Mercado Pago **credit card** PDF/TXT parser | Done |
| SQLite local store (`~/.finance-ingest/`) | Done |
| Rule-based categorization | Done |
| Agent patch API (`finance_apply_classifications`) | Done |
| Monthly summary (income / expenses / by category, exclusions) | Done |
| Reconciliation helper (counts + notes) | Done |
| Google Sheets writer (Bank / Card / Monthly Summary tabs) | Implemented (needs auth) |
| CLI (`finance` / `python -m finance_ingest`) | Done |
| MCP server — **13 tools** (`finance-mcp`) | Done |
| Hermes MCP registration (`finance` server) | Done (path under `~/development/...`) |
| Tests on fixture PDFs | **5 passed** |
| Git repo | Initialized on `main`, initial commit |

### Verified on sample data (June 2026 account + card cycle)

- ~31 account + ~39 card lines ingested from fixtures
- Pending review rows surfaced for agent classification
- June summary computed with transfers and card payments excluded

### MCP tools (agentic flow)

`finance_parse_statement`, `finance_ingest`, `finance_list_transactions`, `finance_get_pending_review`, `finance_auto_categorize`, `finance_apply_classifications`, `finance_get_monthly_summary`, `finance_reconcile`, `finance_sheets_setup`, `finance_sheets_push`, `finance_export_json`, `finance_configure`, `finance_get_config`

---

## What is missing

### Blocking / user action

| Item | Notes |
|------|--------|
| **Google OAuth** | `~/.hermes/google_token.json` not present — Sheets push blocked until `hermes google auth` (or equivalent) with Sheets scope |
| **Spreadsheet ID** | Create a **dedicated** finance Google Sheet (recommended: separate from stock workbook); set via `finance configure` or `finance_configure` |
| **End-to-end Sheets test** | No live push verified yet |
| **Monthly PDF from Sheets** | Manual export today; no automated “export PDF” command |

### Product gaps (MVP+)

| Item | Notes |
|------|--------|
| **Design spec doc** in repo | Brainstorming workflow spec not written as separate `docs/` artifact |
| **Hermes thin plugin** | MCP + CLI exist; no `plugin.yaml` wrapper in `~/.hermes/plugins` yet |
| **GitHub remote** | Local git only — no `origin` / push |
| **Category learning** | No persistence of agent labels into reusable merchant→category rules |
| **Installment / billing-cycle UX** | Parsed; no dedicated “future installments” sheet tab |
| **International / FX rows** | Parsed on card; FX normalization not validated |
| **Duplicate detection across months** | Idempotent by operation id within store; cross-month re-ingest policy not documented |
| **Privacy redaction in Sheets** | Full merchant text goes to Sheets; no optional summary-only mode |
| **Monthly Budget workbook sync** | Does not auto-fill your existing **Monthly Budget & Stock Tracking.xlsx** category grid (stock sheets untouched by design) |
| **Other banks / formats** | Mercado Pago only |
| **CI** | No GitHub Actions / pytest in CI |
| **README path** | README still references old `/home/luanb/personal-finance-ingest` in one Hermes example — update to `~/development/...` |

### Nice-to-have (post-MVP)

- Local **monthly PDF report** generator (matplotlib/reportlab) as alternative to Sheets export
- CSV export per month (partially covered by `finance_export_json`)
- Linear issue sync / status automation
- Memory-palace link doc for vault paths and category conventions

---

## Suggested next steps (order)

1. `hermes google auth` → confirm token path in `finance_get_config`
2. Create new Google Spreadsheet → `finance configure --spreadsheet-id …`
3. `finance sheets-setup` → `finance sheets-push 2026-06` (or MCP equivalents)
4. Agent loop: `finance_get_pending_review` → `finance_apply_classifications` → re-summary
5. Export **Monthly Summary** tab as PDF; confirm layout matches what you want
6. Add `docs/DESIGN.md` or fold into this file after your review
7. `git remote add` + push to GitHub when ready

---

## Quick commands

```bash
cd ~/development/personal-finance-ingest
uv venv .venv && uv pip install -e ".[dev,sheets]"
PYTHONPATH=src .venv/bin/pytest -q

finance ingest tests/fixtures/*.pdf
finance summary 2026-06
finance reconcile 2026-06
```

Hermes: new session after MCP changes; tools prefixed `finance_*`.