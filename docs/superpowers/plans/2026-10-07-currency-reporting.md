# Currency Reporting Implementation Plan

> **For agentic workers:** Use executing-plans and regression tests. Keep the established current-checkout workflow. Track each task with the checkboxes below.

**Goal:** Support currency-specific precision, currency-separated monthly totals, and correctly labelled summary PDFs.

**Architecture:** Store each transaction's decimal exponent with its integer amount. New rows use ISO 4217 precision. A migration records exponent 2 for existing rows, preserving their previous numeric meaning. Reports never add amounts across currencies.

**Tech Stack:** Python, Decimal, SQLite/Alembic, Pydantic, iso4217, fpdf2, pytest.

**Spec:** The user approved all three remaining currency features. Exchange-rate conversion stays outside this scope.

## Constraints and decisions

- Use one maintained ISO registry dependency. CLDR display precision is not the accounting-unit source.
- Keep currency-code normalization separate from native-unit lookup. Legacy codes remain readable with their recorded exponent.
- Record exponent 2 on existing transactions and rules. Do not infer a different scale from their currency code.
- Reject non-two-decimal parser rows without explicit units. Old parser arithmetic must not acquire a new meaning after upgrade.
- Preserve integer amounts and running balances during migration and backup restore.
- Reject amounts that require rounding, unknown native currencies, non-finite values, and SQLite integer overflow.
- Ordinary edits preserve stored units. Amount or currency corrections use native precision and preserve major-unit value without FX.
- Duplicate identity compares major-unit amounts, not integer encodings.
- Report JSON replaces flat monetary totals with `by_currency`. Keep month-wide counts but no combined monetary total.
- Group merchant totals by currency before PDF rendering. Each currency starts its own page.
- PDF money uses explicit currency codes and English number separators. This avoids ambiguous symbols and missing font glyphs.
- New amount-bounded rules capture a currency and its exponent. Unbounded rules may match all currencies.
- Legacy bounds without a currency need user confirmation through rule removal/recreation. Never guess their denomination.
- Keep MCP allowlist and privacy limits unchanged. Extend only the existing rule tool's currency argument.
- Do not commit, push, tag, or publish this new work unless requested.

## Task 1: Exact money and persisted units

Files: `core/money.py` (new), `core/models.py`, `core/manual.py`, `core/redaction.py`, `core/store.py`, `core/migrate.py`, `migrations/versions/003_currency_units.py` (new), `service.py`, `core/config.py`, parser scaffold, `pyproject.toml`, `uv.lock`, currency/migration/manual/parser tests.

Interfaces:
- `currency_exponent(currency: str) -> int`: normalized ISO code lookup; reject undefined minor units.
- `to_minor(value: str | Decimal, currency: str) -> int`: exact major-to-native conversion.
- `major_units(value: int, exponent: int) -> Decimal` and `format_amount(value: Decimal, exponent: int) -> str`.
- `LedgerTransaction.amount_exponent: int`: explicit storage scale. Only native two-decimal currencies retain implicit exponent 2.
- `LedgerTransaction.amount`: derive from the stored scale.

Rule: a new JPY row with `amount_minor=1250` means 1250 JPY; a KWD row with `amount_minor=12345` means 12.345 KWD.
Failure: fixed hundredths silently change the recorded amount.

```python
assert LedgerTransaction(id="j", date=date(2026, 6, 1), amount_minor=1250,
                         currency="JPY", amount_exponent=0, source_kind="card", month="2026-06").amount == Decimal("1250")
```

- [x] Add failing tests for native precision and exact input rejection.
- [x] Test upgrading a revision-002 JPY row without changing its old major-unit amount.
- [x] Implement the money helpers, schema migration, store mapping, and model defaults.
- [x] Use currency precision for manual add/edit, review formatting, and scaffold conversion.
- [x] Test currency correction without conversion and duplicate equality across representations.
- [x] Run focused currency, migration, parser, manual, and backup tests.

## Task 2: Currency-safe totals and rule bounds

Files: `core/breakdown.py`, `core/models.py`, `core/user_rules.py`, `core/store.py`, `service.py`, `cli.py`, `mcp/server.py`, aggregate/rule/guardrail tests.

Interfaces:
- `CurrencyBreakdown`: income, expenses, net, category totals, stored report exponent, and counts.
- `MonthBreakdown.by_currency: dict[str, CurrencyBreakdown]`; overall counts remain.
- `compute_merchant_spend_by_currency(rows) -> dict[str, dict[str, dict[str, str]]]`.
- `UserRule.currency: str | None` and `amount_exponent: int`; bounds compare major-unit values within the declared currency.
- `rule_add(..., currency: str | None = None)` captures the explicit or configured currency when bounds exist.

Rule: 1250 JPY and 12.345 KWD never become one total or one merchant subtotal.
Failure: mixed units produce a plausible but false financial report.

- [x] Add failing mixed-currency totals, exclusion, empty-month, and merchant-isolation tests.
- [x] Replace flat monetary fields and update existing tests to select BRL explicitly.
- [x] Add native-precision rule bounds, currency matching, and legacy-bound confirmation failures.
- [x] Extend existing CLI/MCP rule inputs without adding tools.
- [x] Run aggregate, rule, and privacy contract tests.

## Task 3: PDF output and full verification

Files: `exporters/pdf_summary.py`, `core/models.py`, `service.py`, `tests/test_export_pdf.py`, `README.md`, `scripts/smoke_test.py`.

Interfaces:
- `ReportBundle.merchant_spend_by_currency` matches the currency-grouped report.
- PDF rendering takes currency and exponent explicitly through metrics, categories, and merchant continuations.

Rule: every PDF amount uses its currency's label and precision, including continuation pages.
Failure: a KWD or JPY total appears as BRL or loses fractional value.

- [x] Add failing PDF text tests for JPY/KWD/BRL in all three profiles and merchant continuations.
- [x] Render one section/page per currency, without mixed totals or rounded legacy amounts.
- [x] Update README contracts, native-unit parser examples, rule-bound confirmation, and smoke checks.
- [x] Run full pytest, Ruff, mypy, smoke checks, and diff checks.
- [x] Obtain a fresh read-only review and record the result.

## Verification and review

333 tests passed. Ruff, mypy, project smoke checks, and diff checks passed.
Installed wheel and sdist smoke checks passed outside the checkout.
Currency lookup passed with network access blocked.
Independent review approved the implementation after two fixes:

- Exact conversion now traps inexact Decimal operations, including extreme underflow.
- SQLite migrations now commit schema changes and revision together. Failure rolls back, and retry succeeds.

A real revision-002 backup/restore test preserves legacy JPY balances, unknown codes, and unlabelled rule bounds.
The user approved a local squash merge into `main`.
333 tests, Ruff, mypy, smoke checks, and staged diff checks passed on the merged tree.
Real-data validation used a private backup and a temporary restored ledger.
The migration preserved all original columns and classifications. Reports passed PDF and JSON validation.
The live ledger and configuration stayed unchanged. Backups and reports stayed outside Git.
No push, tag, version bump, or publication was made.
