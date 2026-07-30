# Engine + MCP + PDF Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.  
> **Read first:** `AGENTS.md`, `docs/ARCHITECTURE.md`.  
> **Do not** continue the Sheets-first or “ship all bank parsers in package” designs.  
> **Prior WIP snapshot:** branch `archive/2026-07-29-pre-engine-redesign` (reference only).

**Product:** Canhoto — CLI `canhoto`, MCP `canhoto-mcp`, package `canhoto`, data `~/.canhoto` / `$CANHOTO_DATA_DIR`.

**Goal:** Rebuild the product as a distributable local engine: user/agent Python statement parsers, SQLite ledger, agent-host MCP (e.g. Hermes) domain tools, summary PDF export, with guardrails enforced in code and tests.

**Architecture:** Ports-and-adapters. Core ledger + policy; `StatementParser` and `Exporter` registries; CLI + MCP as façades. No raw SQL MCP. No Sheets in core.

**Tech Stack:** Python ≥3.11, pydantic v2, SQLite, FastMCP, pymupdf (text extract), pytest/ruff/mypy. PDF render: prefer a small pure dependency (e.g. `fpdf2` or `reportlab`) added explicitly in `pyproject.toml` when Task 8 starts — do not add until needed.

## Global Constraints

- Data dir: `CANHOTO_DATA_DIR` or `~/.canhoto`.
- Package scripts are `canhoto` and `canhoto-mcp` (product **Canhoto**).
- No Google API deps on the default/non-extra install path for v1.
- No required built-in Itaú/MP parsers in the distributed runtime package.
- MCP: domain tools only; never `sql_query` / arbitrary SELECT.
- PDF v1: summary only (metrics + category totals).
- Agent aggregates v1: category totals + counts; no merchant rollups.
- Parser plugins = Option A (Python) with enable + test gates.
- Guardrail tests are mandatory before declaring a phase done.
- Prefer deleting Sheets coupling over maintaining dead code paths on `main`.
- TDD: failing test → implement → pass → commit per task.
- Do not commit secrets, real statements, or `~/.canhoto` contents.

- **Canhoto rename:** new modules use `canhoto` / `canhoto`; do not add new public `finance_*` names.
- Core remains country-agnostic; BRL/PIX-style rules belong in default locale/profile, not the kernel.

---

## Phase map (implement in order)

| Phase | Name | Outcome |
|---|---|---|
| 0 | Guardrails & contracts | Models, policy, forbidden-field tests — **before** features |
| 1 | Core engine | Config, store, pipeline skeleton, doctor/init |
| 2 | Parser port | Registry, loader, scaffold, test, enable |
| 3 | Ingest | File → extract → parse → SQLite |
| 4 | Categorize | Rules + review batches + patches + optional merchant memory |
| 5 | MCP | agent full-loop tools wired to service |
| 6 | PDF export | Summary `ReportBundle` → PDF |
| 7 | Distribution polish | Package metadata, README, example parser docs, CI |

Each phase ends with: tests green, ruff/mypy clean (as configured), commit(s).

---

## File map (target)

| Path | Responsibility |
|---|---|
| `AGENTS.md` | Agent bootstrap (already on main) |
| `docs/ARCHITECTURE.md` | Product contract |
| `src/canhoto/core/models.py` | Domain models |
| `src/canhoto/core/config.py` | Data dir + config.json |
| `src/canhoto/core/store.py` | SQLite |
| `src/canhoto/core/policy.py` | AgentView + batch clamps |
| `src/canhoto/core/redaction.py` | ReviewItem projection |
| `src/canhoto/core/pipeline.py` | Orchestration helpers |
| `src/canhoto/parsers/protocol.py` | `StatementParser` Protocol |
| `src/canhoto/parsers/loader.py` | Load/enable from data dir |
| `src/canhoto/parsers/scaffold.py` | Stub generator |
| `src/canhoto/exporters/protocol.py` | `Exporter` Protocol |
| `src/canhoto/exporters/pdf_summary.py` | v1 PDF |
| `src/canhoto/service.py` | Façade used by CLI/MCP |
| `src/canhoto/cli.py` | CLI |
| `src/canhoto/mcp/server.py` | MCP tools |
| `tests/guardrails/` | Privacy/allowlist tests |
| `examples/parsers/README.md` | How to write a parser (not imported at runtime) |

Migration note: current tree is flat (`config.py`, `store.py`, …). Either:

- **Preferred:** introduce `core/` and move modules incrementally, keeping thin re-export shims briefly, or  
- Refactor in place with the same module responsibilities if a full move blocks progress.

Do not mix Sheets code into new modules.

---

# Phase 0 — Guardrails & contracts (FIRST)

Ship types and tests that define “safe” **before** MCP or parser execution exists. Later phases must not weaken these tests.

### Task 0.1 — Domain models for plugins, policy, review, report

**Files:**
- Create or reshape: `src/canhoto/core/models.py` (or `models.py` if not moving yet)
- Test: `tests/guardrails/test_models_contracts.py`

**Models to define:**

```python
# Required shapes (names stable)

class StatementType(str, Enum):
    ACCOUNT = "account"
    CARD = "card"

class AgentViewConfig(BaseModel):
    allow_aggregates: bool = True
    allow_review_items: bool = True
    include_amounts_in_review: bool = True
    include_institution: bool = True
    max_batch_size: int = 25
    absolute_max_batch_size: int = 50
    expense_only: bool = True
    allow_parser_writes: bool = False
    preview_max_chars: int = 20_000

class ParserEntry(BaseModel):
    id: str
    module: str                    # filename under parsers_dir
    enabled: bool = False

class AppConfig(BaseModel):
    data_dir: str
    parsers_dir: str = "parsers"
    parsers: list[ParserEntry] = Field(default_factory=list)
    agent_view: AgentViewConfig = Field(default_factory=AgentViewConfig)
    # own_name_markers, currency, etc. as needed
    # NO spreadsheet_id / google_* required fields in v1 core

class ReviewItem(BaseModel):
    id: str
    date: str
    amount: str | None
    currency: str = "BRL"  # default only; core must allow override
    merchant_display: str
    source_kind: str
    institution: str | None = None
    current_category: str
    current_kind: str
    confidence: float = 0.0
    review_reason: str | None = None
    installment: str | None = None

class MonthBreakdown(BaseModel):
    month: str
    income: str
    expenses: str
    net: str
    by_category: dict[str, str]
    pending_review: int
    transaction_count: int
    expense_count: int
    # no per-transaction list
```

- [ ] **Step 1: Write failing contract tests** for `ReviewItem` / `MonthBreakdown` forbidding sensitive field names in `model_fields`.

```python
FORBIDDEN_REVIEW_FIELDS = {
    "description", "source_file", "operation_id", "running_balance",
    "account_id", "metadata", "merchant_raw",
}

def test_review_item_has_no_forbidden_fields():
    assert FORBIDDEN_REVIEW_FIELDS.isdisjoint(set(ReviewItem.model_fields))
```

- [ ] **Step 2: Implement models**
- [ ] **Step 3: Tests pass; commit**

```bash
git add src/canhoto tests/guardrails
git commit -m "feat: add core contracts for agent view and reports"
```

### Task 0.2 — Policy helpers + redaction pure functions

**Files:**
- `src/canhoto/core/policy.py`
- `src/canhoto/core/redaction.py`
- `tests/guardrails/test_policy.py`
- `tests/guardrails/test_redaction.py`

**APIs:**

```python
def assert_month(month: str) -> str: ...
def clamp_batch_size(requested: int | None, view: AgentViewConfig) -> int: ...

def merchant_display(tx: Transaction) -> str: ...
def to_review_item(tx: Transaction, view: AgentViewConfig) -> ReviewItem: ...
```

- [ ] **Step 1: Tests** — clamp caps at absolute max; empty month raises; redaction never includes forbidden strings from a hostile `Transaction` fixture.
- [ ] **Step 2: Implement**
- [ ] **Step 3: Commit** `feat: add agent view policy and redaction`

### Task 0.3 — MCP allowlist constant (fail closed)

**Files:**
- `src/canhoto/mcp/allowlist.py`
- `tests/guardrails/test_mcp_allowlist.py`

```python
MCP_TOOL_ALLOWLIST = frozenset({
    "statement_preview",
    "parser_list",
    "parser_scaffold",
    "parser_write",
    "parser_test",
    "parser_enable",
    "ingest",
    "run_rules",
    "review_batch",
    "set_categories",
    "set_merchant_category",
    "month_breakdown",
    "export_pdf",
    "doctor",
})

MCP_TOOL_DENYLIST = frozenset({
    "sql_query",
    "list_all_transactions",
    "sheets_push",
    "sheets_setup",
    "get_config_secrets",
})
```

- [ ] Test: allowlist and denylist disjoint; denylist names never registered when server module loads (wire fully in Phase 5; for now test constant integrity).
- [ ] Commit `test: lock MCP tool allowlist contract`

**Phase 0 exit:** contracts + guardrail tests exist and pass on CI/local.

---

# Phase 1 — Core engine shell

### Task 1.1 — Config + data dir layout

**Files:** `config.py` / `core/config.py`, `tests/test_config.py`

- `init_data_dir()` creates `parsers/`, `exports/`, `raw/`, `fixtures/`, `config.json`, empty db path.
- `load_config` / `save_config` round-trip `AgentViewConfig` + `parsers`.
- Strip required Google fields from core config.

- [ ] Tests with `tmp_path` + `CANHOTO_DATA_DIR`
- [ ] Commit `feat: init data dir and plugin-aware config`

### Task 1.2 — SQLite store (ledger only)

**Files:** `store.py`, `tests/test_store.py`

Minimum tables:

- `transactions` (normalized rows, integer minor units for money)
- `statements` (`content_hash` unique, meta_json, source_file)
- `statement_transactions`
- `merchant_category_map` (for Phase 4; can create empty now)

Keep idempotent upsert by transaction `id` and statement `content_hash`.

Reuse good ideas from archive branch store, but **do not** require `pushed_to_sheets` for v1 (optional column ok if harmless).

- [ ] Tests: upsert, list by month, apply classification patch
- [ ] Commit `feat: sqlite ledger store`

### Task 1.3 — `doctor` + `init` CLI

**Files:** `cli.py`, `service.py`, `tests/test_doctor.py`

```bash
canhoto init
canhoto doctor
```

Doctor JSON checks: data dir writable, config present, parser count enabled/disabled, db openable, pending_review total.

- [ ] Commit `feat: add canhoto init and doctor`

**Phase 1 exit:** installable module initializes a clean data dir and doctor runs without parsers.

---

# Phase 2 — Parser port (no bank parsers required)

### Task 2.1 — Protocol + loader

**Files:**
- `parsers/protocol.py`
- `parsers/loader.py`
- `tests/test_parser_loader.py`

Behavior:

- Discover modules listed in config under `{data_dir}/{parsers_dir}/`.
- Import only **enabled** entries for ingest-time registry (disabled can still be tested by id).
- Each module exposes `register() -> StatementParser` or a module-level `PARSER` object — pick one convention and document it in scaffold.

Sniff selection:

```python
def choose_parser(text: str, parsers: sequence[StatementParser]) -> StatementParser:
    ranked = sorted(((p.sniff(text), p) for p in parsers), key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] <= 0:
        raise ParserNotFoundError(...)
    return ranked[0][1]
```

- [ ] Tests with tiny in-memory fake parser classes (not real banks)
- [ ] Commit `feat: statement parser registry and loader`

### Task 2.2 — Scaffold, test, enable

**CLI:**

```bash
canhoto parsers scaffold --id demo_card --type card --institution demo
canhoto parsers test --id demo_card --file /path/to/sample.pdf
canhoto parsers enable --id demo_card
canhoto parsers list
```

**Service APIs** used later by MCP:

- `parser_scaffold`, `parser_write(id, code)`, `parser_test`, `parser_enable`, `parser_list`

Rules:

- `parser_enable` fails if last test not OK (store test result stamp in config or sidecar JSON).
- `parser_write` refused when `agent_view.allow_parser_writes` is false **for MCP**; CLI may allow with explicit flag `--force` or always allow local human CLI (document choice: **CLI always may write; MCP respects flag**).

- [ ] Tests for enable gate
- [ ] Commit `feat: parser scaffold test and enable flow`

### Task 2.3 — Example parser (docs only)

**Files:** `examples/parsers/README.md` + one `examples/parsers/demo_line_parser.py` that parses a trivial fixture format used in tests.

- Not auto-loaded from package.
- `canhoto parsers scaffold` may copy from example template text embedded in package resources.

- [ ] Commit `docs: add example statement parser template`

**Phase 2 exit:** fake/demo parser can be installed into data dir, tested, enabled.

---

# Phase 3 — Ingest path

### Task 3.1 — Text extract + ingest service

**Files:** `pdf_text.py`, `service.py`, `tests/test_ingest.py`

```text
ingest(paths) ->
  for each file:
    archive raw by hash
    extract text
    choose_parser
    parse
    upsert statement + transactions
```

- Fail clearly if no enabled parser claims the doc.
- Preserve classification on re-ingest when same tx id (archive branch behavior is a good reference).

- [ ] Tests with demo parser + temp PDF/TXT fixture
- [ ] Commit `feat: ingest via plugin parsers`

### Task 3.2 — CLI ingest

```bash
canhoto ingest ~/statements/*.pdf
canhoto parse ~/statements/a.pdf    # dry-run JSON summary (capped rows)
```

- [ ] Commit `feat: CLI ingest and parse dry-run`

**Phase 3 exit:** end-to-end ingest with user plugin, no built-in bank code required.

---

# Phase 4 — Categorization

### Task 4.1 — Rules engine

Port/adapt `categorize.py` rules (self-transfer markers, card payment, etc.) without Sheets assumptions.

```bash
canhoto categorize rules --month 2026-06
```

- [ ] Commit `feat: deterministic categorization rules`

### Task 4.2 — Review batch + apply patches

```python
def review_batch(month: str, cursor: str | None, limit: int | None) -> dict: ...
def set_categories(patches: list[dict]) -> dict: ...
```

Must use Phase 0 redaction + policy.

CLI:

```bash
canhoto review --month 2026-06 --json
canhoto categorize apply --file patches.json
```

- [ ] Guardrail test: review JSON keys ⊆ ReviewItem fields
- [ ] Commit `feat: redacted review batches and category patches`

### Task 4.3 — Merchant memory (optional but recommended)

- Table `merchant_category_map`
- `set_merchant_category` + apply after rules
- Skip learning keys that look like CPF-only person transfers (simple heuristic)

- [ ] Commit `feat: local merchant category memory`

### Task 4.4 — Month breakdown (aggregates only)

```python
def month_breakdown(month: str) -> MonthBreakdown: ...
```

No transaction list field.

- [ ] Commit `feat: month breakdown aggregates`

**Phase 4 exit:** categorize + safe review + breakdown without MCP.

---

# Phase 5 — MCP (agent loop)

### Task 5.1 — Server wiring

**Files:** `src/canhoto/mcp/server.py`, entrypoint `canhoto-mcp`

Register **only** `MCP_TOOL_ALLOWLIST` tools. Each tool calls `service.*`.

`parser_write` / `parser_enable` enforce `allow_parser_writes` where applicable (`enable` may stay allowed if test passed and user wants full agent autonomy — default: enable allowed, write gated).

`statement_preview(path)`:

- Resolve user path
- Extract text
- Truncate to `preview_max_chars`
- Return `{path_basename, char_count, truncated, text}` — avoid leaking unrelated filesystem listings

- [ ] Test: loading server, tool names == allowlist
- [ ] Test: denylist names absent
- [ ] Commit `feat: Canhoto MCP domain tools`

### Task 5.2 — Instructions string

MCP server instructions must describe the happy path:

1. preview → write parser → test → enable  
2. ingest  
3. run_rules → review_batch loop → set_categories  
4. month_breakdown → export_pdf  

- [ ] Commit `docs: MCP agent instructions for full loop`

**Phase 5 exit:** manual or automated smoke: tools list matches allowlist; review_batch redacts.

---

# Phase 6 — PDF summary export

### Task 6.1 — ReportBundle + pdf exporter

```python
@dataclass
class ReportBundle:
    breakdown: MonthBreakdown
    generated_at: str
    title: str
```

```bash
canhoto export pdf 2026-06
# → $CANHOTO_DATA_DIR/exports/2026-06-summary.pdf
```

MCP: `export_pdf(month) -> {path, bytes or size}`

- [ ] Test: export creates non-empty PDF; content path only under exports dir
- [ ] Commit `feat: summary PDF exporter`

**Phase 6 exit:** breakdown PDF generated from ledger.

---

# Phase 7 — Distribution polish

### Task 7.1 — Package & README

- README: install via `uv tool install canhoto` / `pipx`, data dir, MCP host snippet (`canhoto-mcp`), parser authoring pointer, privacy notes.
- `pyproject.toml`: description, scripts, deps; Sheets extra **removed or clearly legacy-not-installed**.
- Point STATUS.md at ARCHITECTURE.md.

### Task 7.2 — CI

- ruff, mypy, pytest including `tests/guardrails/`.
- No real credentials.

### Task 7.3 — Migration note from archive branch

Short `docs/MIGRATION.md`: how to copy old Itaú/MP parsers from archive branch into `~/.canhoto/parsers/` if desired.

- [ ] Commit `docs: distribution and migration notes`

**Phase 7 exit:** clean clone path for agents + users documented; CI green.

---

## Suggested agent demo script (acceptance)

```text
1. canhoto init
2. config agent_view.allow_parser_writes=true (for full agent profile)
3. Agent: preview sample fixture
4. Agent: write demo parser / real user parser
5. Agent: test + enable
6. Agent: ingest fixture
7. Agent: run_rules + review/set_categories
8. Agent: month_breakdown
9. Agent: export_pdf
10. User opens PDF from exports/
```

---

## Guardrail regression checklist (run every phase)

```bash
uv run pytest tests/guardrails -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

Must remain true:

1. `ReviewItem` fields never grow forbidden names without explicit architecture change.  
2. MCP registered tools ⊆ allowlist.  
3. `review_batch` requires month and respects max batch.  
4. `month_breakdown` has no transaction list.  
5. Parsers disabled by default until enable.  
6. MCP `parser_write` blocked when `allow_parser_writes` is false.

---

## Out of scope reminders

- Sheets exporter plugin (v2+)  
- Declarative non-Python parsers (possible later safer mode)  
- TUI  
- Merchant rollups  
- OCR / password-protected PDFs  

---

## Self-review

| Requirement | Phase |
|---|---|
| Distributable package, config in data dir | 1, 7 |
| No built-in bank parsers required | 2, 3 |
| Option A Python parsers + enable/test | 2 |
| SQLite ledger | 1, 3 |
| Agent MCP full loop | 5 |
| Domain tools not raw SQL | 0, 5 |
| Summary PDF only | 6 |
| Guardrails before features | 0 |
| Category aggregates, no merchant rollups v1 | 4 |
| Sheets out of core | global + delete/quarantine during 1–7 |

---

## Execution

Work **phase by phase**. Do not start Phase 5 before Phase 0–4 guardrails and APIs exist.  
Prefer one PR/commit series per task.  
When stuck on old behavior, consult `archive/2026-07-29-pre-engine-redesign` instead of resurrecting Sheets into core.
