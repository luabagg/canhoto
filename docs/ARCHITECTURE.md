# Architecture — Canhoto

**Status:** target design (2026-07-29). Supersedes Sheets-first and “built-in bank parsers only” product shape.  
**Archive of prior WIP:** branch `archive/2026-07-29-pre-engine-redesign` (see `docs/ARCHIVE_BRANCH.md`).

**Name:** *Canhoto* — the stub/counterfoil you keep (comprovante que fica com você). Not “left-handed.”

**Dual state:** On `main`, this document is the contract; runtime code may still be legacy `src/finance_ingest/` until the implementation plan replaces it. See `AGENTS.md` § Day-1 reality. Do not treat existing `finance` CLI behavior as the product.

This document is the product/architecture contract. Implementation order lives in:

- `docs/superpowers/plans/2026-07-29-engine-mcp-pdf-redesign.md`
- `AGENTS.md` (bootstrap for coding agents)

---

## 0. Product identity

| Layer | Value |
|---|---|
| Product name | **Canhoto** |
| PyPI / project | `canhoto` |
| Import package | `canhoto` |
| CLI | `canhoto` |
| MCP server binary | `canhoto-mcp` |
| MCP server label (hosts) | `canhoto` |
| Data dir | `~/.canhoto` or `$CANHOTO_DATA_DIR` |
| DB file | `canhoto.db` |
| Legacy names | `personal-finance-ingest`, `finance`, `finance_ingest`, `~/.finance-ingest` — **do not** use in new code/docs |

Repo folder may still be `personal-finance-ingest` until renamed on disk; product name is Canhoto regardless.

---

## 1. One-sentence product

Installable local CLI + optional MCP server: user (or agent host) points at **bank/card statements**, agents can **author Python parsers**, engine **normalizes into SQLite**, agent **categorizes**, engine **exports a summary PDF**.

---

## 2. Non-goals (v1)

- Google Sheets in core (future **export plugin** only)
- Shipping mandatory country- or bank-specific parsers inside the package
- TUI / web UI
- Open Finance / Pluggy (or any hosted bank API) as a dependency
- Raw SQL over MCP
- PDF with full transaction line dump (v1 = **summary only**)
- Merchant rollups for agent aggregates (v1 = category totals + counts)
- Multi-user / hosted SaaS

---

## 3. Distribution

| Artifact | Role |
|---|---|
| PyPI / `uv tool install canhoto` | Engine only (no user money data) |
| `canhoto` | Human + agent CLI |
| `canhoto-mcp` | Optional MCP stdio server (host-spawned; user does **not** babysit a daemon) |
| `~/.canhoto/` or `$CANHOTO_DATA_DIR` | Config, DB, user parsers, raw archives, exports |

Users must **not** need the git monorepo to run the tool. Contributors clone git; end users install the package.

```text
~/.canhoto/
  config.json
  canhoto.db
  raw/                    # content-addressed statement copies
  exports/                # PDF summaries
  parsers/                # user/agent Python plugins (option A)
  fixtures/               # redacted samples for parser tests
```

Hermes / MCP host example:

```yaml
mcp_servers:
  canhoto:
    command: canhoto-mcp
```

---

## 4. Core vs locale (not Brazil-only)

The **engine is country-agnostic**. Brazil may be the first *profile* and doc language, not the kernel.

### Portable spine

| Concept | Meaning |
|---|---|
| `statement_type=account` | Deposit/checking-style period activity (“month report”) |
| `statement_type=card` | Credit-card cycle statement (“C.C. report”) |
| Ledger + month breakdown + summary PDF | Universal reporting |
| User/agent parsers | Any bank, any country, any file layout |

Any country works when someone authors a parser and maps rows into the normalized model.

### Locale / profile (config or optional packs — not hardwired forever)

| Concern | Default may be BR-flavored | Must be overridable |
|---|---|---|
| Currency | `BRL` | `config.currency` |
| Category labels | household budget set | custom taxonomy later |
| Rule strings | PIX, fatura, etc. | rule packs / user rules |
| ID heuristics | CPF-like | locale pack or off |
| Docs examples | extrato/fatura paths | examples only |

### Core must not require

- Closed `Institution` enum of Brazilian banks  
- PIX-only self-transfer detection as the only path  
- Portuguese-only category enums without escape hatch  
- Built-in Itaú/Mercado Pago (or any bank) parsers in the wheel  

Accounting *ideas* that travel: card spend is expense; paying the card from cash account is `card_payment` (no double count); internal/self transfers excluded from spend. **How** those are detected is locale/parser/rules.

---

## 5. Pipeline

```text
Statement file (PDF/TXT/…)
        │
        ▼
      Text extract
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

## 6. Extension ports (design patterns)

### 6.1 Strategy + Registry — `StatementParser`

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

### 6.2 Strategy + Registry — `Exporter`

```python
class Exporter(Protocol):
    id: str
    def export(self, bundle: ReportBundle, dest: Path) -> ExportResult: ...
```

- v1: `pdf_summary` only.
- Later: `csv`, `sheets`, etc., without core changes.

### 6.3 Policy object — `AgentView` / guardrails

Config-driven projection of what CLI agent commands and MCP tools may return. Not a substitute for OS sandboxing; product-level least privilege.

---

## 7. MCP happy path (e.g. Hermes)

MCP transport is **stdio**. Client (Hermes, Claude Code, Cursor) **spawns** `canhoto-mcp`; user does not pre-start a server.

Target chat:

> “Here’s `~/Downloads/card-statement.pdf` — implement parser, ingest, categorize, give June breakdown.”

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

Optional config profiles later: `full` (default for personal agent hosts) vs `categorize_only`.

---

## 8. Privacy & guardrails (product rules)

### 8.1 Always

- Money data only under data dir; never commit.
- Raw statements archived content-addressed under `raw/`.
- No network required for core parse/categorize/export path.
- Parsers must not be auto-downloaded from the internet.

### 8.2 Parser option A (Python) risks

Agent-written Python runs with engine privileges → full local trust.

**Required mitigations:**

1. Plugins only under configured parsers dir  
2. Explicit `enable` after `parser_test` succeeds  
3. Default: human/CLI enable; MCP `parser_write` allowed only when `allow_parser_writes: true` (full agent profile may set true)  
4. Prefer subprocess parse with timeout (and no inherited secrets env if feasible)  
5. Document parsers as trusted code equal to user shell scripts  

### 8.3 Ledger exposure

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

### 8.4 Breakdown / PDF v1

- **Aggregates:** category totals, expense/income/net per accounting rules, counts, pending_review count.  
- **Not v1:** merchant rollups, full tx tables in PDF.  
- PDF = summary template only.

---

## 9. Accounting rules (portable intent)

- Card purchases count as expenses  
- Paying the card from account = `card_payment` (excluded from spend)  
- Internal reserve / pocket moves = transfers  
- Transfers to self (own-name markers or locale rules) = `self_transfer`  
- Default category labels may match a household budget set; custom taxonomy is a later config concern  

---

## 10. Layering (target package layout)

```text
src/canhoto/
  core/           # models, config, store, pipeline, policy, redaction
  parsers/        # Protocol, loader, scaffold helpers (no bank logic required)
  exporters/      # pdf_summary (+ future plugins)
  mcp/            # FastMCP tools → service only
  cli.py
  service.py      # orchestration façade
```

Dependency direction: `cli` / `mcp` → `service` → `core` + ports. Exporters/parsers do not import CLI/MCP.

Until the code rename lands, the tree may still be `src/finance_ingest/`; treat that as legacy path to migrate in Phase 1.

---

## 11. Relationship to old code

| Old | New |
|---|---|
| Name `personal-finance-ingest` / `finance` | **Canhoto** / `canhoto` |
| Hardcoded MP/Itaú detect+parse in package | User parser plugins; copy from archive into data dir if desired |
| Sheets + Google OAuth in core | Dropped from core; future exporter |
| Fat MCP (parse/list/sheets/config) | Domain MCP for full agent loop; still no raw SQL |
| `export` JSON only | PDF summary primary; JSON optional debug |

Reference implementation details: `docs/ARCHIVE_BRANCH.md`.

---

## 12. Success criteria (v1 done)

1. Fresh install exposes `canhoto` and `canhoto-mcp` without repo checkout.  
2. Empty parsers dir → clear doctor errors; after agent adds parser → ingest works.  
3. Agent host can complete preview → parser → ingest → categorize → breakdown → PDF path.  
4. No Google dependency on default install.  
5. Guardrail tests prove review batches and breakdown cannot return forbidden fields.  
6. `canhoto doctor` reports data dir, parsers, pending counts, export readiness.  
7. Core accepts non-BRL currency and non-BR institution strings without code changes.  
