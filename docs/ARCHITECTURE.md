# Architecture — Personal Finance Ingest Engine

**Status:** target design (2026-07-29). Supersedes Sheets-first and “built-in bank parsers only” product shape.  
**Archive of prior WIP:** branch `archive/2026-07-29-pre-engine-redesign`.

This document is the product/architecture contract. Implementation order lives in:

- `docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md`
- `AGENTS.md` (bootstrap for coding agents)

---

## 1. One-sentence product

Installable local CLI + optional MCP server: user (or Hermes) points at **extratos** (conta / cartão), agents can **author Python parsers**, engine **normalizes into SQLite**, agent **categorizes**, engine **exports a summary PDF**.

---

## 2. Non-goals (v1)

- Google Sheets in core (future **export plugin** only)
- Shipping mandatory Itaú/Mercado Pago parsers inside the package
- TUI / web UI
- Open Finance / Pluggy
- Raw SQL over MCP
- PDF with full transaction line dump (v1 = **summary only**)
- Merchant rollups for agent aggregates (v1 = category totals + counts)
- Multi-user / hosted SaaS

---

## 3. Distribution

| Artifact | Role |
|---|---|
| PyPI / `uv tool install` package | Engine only (no user money data) |
| `finance` | Human + agent CLI |
| `finance-mcp` | Optional MCP stdio server (host-spawned; user does **not** babysit a daemon) |
| `~/.finance-ingest/` or `$FINANCE_DATA_DIR` | Config, DB, user parsers, raw archives, exports |

Users must **not** need the git monorepo to run the tool. Contributors clone git; end users install the package.

```text
~/.finance-ingest/
  config.json
  finance.db
  raw/                    # content-addressed statement copies
  exports/                # PDF summaries
  parsers/                # user/agent Python plugins (option A)
  fixtures/               # redacted samples for parser tests
```

---

## 4. Pipeline

```text
Statement file (PDF/TXT)
        │
        ▼
 Text Text extract
        │
        ▼
 Parser registry (user plugins in data dir)
   sniff() → best score → parse() → ParseResult
        │
        ▼
  Normalize + stable ids
        │
        ▼
  SQLite ledger  ◄── system of record
        │
        ├─ rule categorize + optional merchant memory
        ├─ MCP/CLI review batches (redacted) + set categories
        └─ ReportBundle (aggregates)
                │
                ▼
         PDF exporter (summary template)
```

**SQLite is not optional.** It is the workspace between ingest, categorization, and export. Exports are projections, never the database.

---

## 5. Extension ports (design patterns)

### 5.1 Strategy + Registry — `StatementParser`

```python
class StatementParser(Protocol):
    id: str
    statement_type: Literal["account", "card"]
    institution: str          # free string; not a closed enum forever
    version: str

    def sniff(self, text: str) -> float:
        """0.0–1.0 confidence this parser owns the document."""

    def parse(self, text: str, source_file: str) -> ParseResult:
        """Return normalized meta + transactions; raise on hard failure."""
```

- **No required built-in bank parsers** in the distributed package.
- Package ships: Protocol, loader, scaffold, test runner, docs/example.
- Implementations live in `data_dir/parsers/*.py`, explicitly **enabled** in config.
- Option **A**: real Python plugins (max flexibility). Treat as trusted local code.

### 5.2 Strategy + Registry — `Exporter`

```python
class Exporter(Protocol):
    id: str
    def export(self, bundle: ReportBundle, dest: Path) -> ExportResult: ...
```

- v1: `pdf_summary` only.
- Later: `csv`, `sheets`, etc., without core changes.

### 5.3 Policy object — `AgentView` / guardrails

Config-driven projection of what CLI agent commands and MCP tools may return. Not a substitute for OS sandboxing; product-level least privilege.

---

## 6. Hermes / MCP happy path

MCP transport is **stdio**. Client (Hermes, Claude Code, Cursor) **spawns** `finance-mcp`; user does not pre-start a server.

Target chat:

> “Here’s `~/Downloads/fatura.pdf` — implement parser, ingest, categorize, give June breakdown.”

Tool phases:

1. **Preview** statement text (bounded)
2. **Write/test/enable** parser plugin
3. **Ingest** into SQLite
4. **Categorize** (rules + review batches + patches)
5. **Breakdown** aggregates + optional **export PDF**

MCP exposes **domain tools over the ledger**, not raw SQLite (`query("SELECT …")` is forbidden).

### Suggested tool groups

| Group | Examples |
|---|---|
| Parsers | `statement_preview`, `parser_scaffold`, `parser_write`, `parser_test`, `parser_enable`, `parser_list` |
| Ingest | `ingest`, `doctor` / source status |
| Categorize | `run_rules`, `review_batch`, `set_categories`, `set_merchant_category` |
| Breakdown | `month_breakdown`, `export_pdf` |

Optional config profiles later: `full` (default for personal Hermes) vs `categorize_only`.

---

## 7. Privacy & guardrails (product rules)

### 7.1 Always

- Money data only under data dir; never commit.
- Raw statements archived content-addressed under `raw/`.
- No network required for core parse/categorize/export path.
- Parsers must not be auto-downloaded from the internet.

### 7.2 Parser option A (Python) risks

Agent-written Python runs with engine privileges → full local trust.

**Required mitigations:**

1. Plugins only under configured parsers dir  
2. Explicit `enable` after `parser_test` succeeds  
3. Default: human/CLI enable; MCP `parser_write` allowed only when `allow_parser_writes: true` (Hermes full profile may set true)  
4. Prefer subprocess parse with timeout (and no inherited secrets env if feasible)  
5. Document parsers as trusted code equal to user shell scripts  

### 7.3 Ledger exposure

| Allowed | Denied |
|---|---|
| Capped redacted review items | Unbounded full ledger dump |
| Month breakdown aggregates | Raw SQL |
| Capped parse preview rows | Shipping absolute secret paths in tool output when avoidable |
| Export PDF path | Sheets push in v1 |

Review item projection (illustrative):  
`id, date, amount?, currency, merchant_display, source_kind, institution?, current_category, current_kind, confidence, review_reason, installment?`  

Strip: raw multi-line description dumps, `source_file`, `account_id`, `operation_id`, `running_balance`, full `metadata`.

Defaults: `max_batch_size=25`, hard max `50`, **month required**, expense-oriented pending queue.

### 7.4 Breakdown / PDF v1

- **Aggregates:** category totals, expense/income/net per accounting rules, counts, pending_review count.  
- **Not v1:** merchant rollups, full tx tables in PDF.  
- PDF = summary template only.

---

## 8. Accounting rules (unchanged intent)

- Card purchases count as expenses  
- Paying the card from account = `card_payment` (excluded from spend)  
- Piggy/internal moves = transfers  
- PIX to own-name markers = `self_transfer`  
- Budget categories stay aligned with existing Monthly Budget labels unless config later allows custom taxonomy  

---

## 9. Layering (target package layout)

```text
src/finance_ingest/
  core/           # models, config, store, pipeline, policy, redaction
  parsers/        # Protocol, loader, scaffold helpers (no bank logic required)
  exporters/      # pdf_summary (+ future plugins)
  mcp/            # FastMCP tools → service only
  cli.py
  service.py      # orchestration façade
```

Dependency direction: `cli` / `mcp` → `service` → `core` + ports. Exporters/parsers do not import CLI/MCP.

---

## 10. Relationship to old code

| Old | New |
|---|---|
| Hardcoded MP/Itaú detect+parse in package | User parser plugins; old parsers may be copied into examples or personal data dir from archive branch |
| Sheets + Google OAuth in core | Dropped from core; future exporter |
| Fat MCP (parse/list/sheets/config) | Domain MCP for Hermes full loop; still no raw SQL |
| `export` JSON only | PDF summary primary; JSON optional debug |

Reference implementation details (Itaú, Sheets tests, etc.):  
`git show archive/2026-07-29-pre-engine-redesign:…` or checkout that branch.

---

## 11. Success criteria (v1 done)

1. Fresh install exposes `finance` and `finance-mcp` without repo checkout.  
2. Empty parsers dir → clear doctor errors; after agent adds parser → ingest works.  
3. Hermes can complete preview → parser → ingest → categorize → breakdown → PDF path.  
4. No Google dependency on default install.  
5. Guardrail tests prove review batches and breakdown cannot return forbidden fields.  
6. `finance doctor` reports data dir, parsers, pending counts, export readiness.
