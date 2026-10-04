# User Classification Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user (or an agent, on the user's instruction) store durable classification rules with a written reason, so that `run_rules` classifies future statements the same way for every agent, CLI or MCP.

**Architecture:** A new SQLite table `user_rules` holds rules: a description regex, a direction, an amount range, an optional source kind, the classification to apply, a "confirm" flag, and a `note` that says why the rule exists. Two new columns on `transactions` record provenance: `classification_source` (who set the classification) and `user_rule_id` (which rule). User rules run first in `run_rules`, and they may reclassify any row that a human did not set (`classification_source != 'manual'`). `review_batch` shows the rule note on rows that a rule flagged for confirmation.

**Tech Stack:** Python 3.13, SQLite, Alembic, Pydantic v2, argparse, FastMCP, pytest, ruff, mypy.

**Spec:** This plan is the spec. The design section below records the decisions.

## Global Constraints

- Keep money out of git. Tests, docs, and this plan use only invented names ("ACME LTDA", "JANE DOE", "EXAMPLE BANK"). Never write the owner's real counterparties or amounts into the repository.
- MCP tools must stay a subset of `MCP_TOOL_ALLOWLIST`. The new tools are `rule_list`, `rule_add`, `rule_remove`.
- Agents receive rows only through `to_review_item`. Never return raw `LedgerTransaction` objects.
- Country-agnostic core. No bank names or currencies in rule logic.
- Dependency direction: `cli` / `mcp` → `service` → `core`.
- TDD for every behavior change. Guardrails in `tests/guardrails/` must stay green, and each contract edit below must be deliberate.
- Commands: `uv run pytest -q`, `uv run ruff check src/canhoto tests`, `uv run mypy -p canhoto`.
- Technical prose uses ASD-STE100 style. Do not use em dashes.

## Design

### Why a rule table, not a "context" column on transactions

A free-text context column on a transaction row does not help next month. Next month's rows are new rows, and nothing copies the text to them. The context must live where the system can apply it again: on the rule. Each rule has a `note` ("company pro-labore; company has the owner's name"). Each row records which rule classified it (`user_rule_id`). That gives every agent the reason, and it lets a human audit a row.

### Why SQLite, not `config.json`

Rules contain counterparty names. That is ledger data, so it belongs with the ledger, in `canhoto.db`, next to `merchant_category_map`. `config.json` holds settings. The trade-off: `migrate.wipe_and_upgrade` deletes rules together with the ledger. A future parser re-ingest must delete only the affected transaction rows, not the database.

### Why provenance is required

The Mercado Pago account parser (a local plugin, not in this repo) sets `category` and `kind` itself, and it sets `needs_review=False` on transfers and income. The built-in rules only touch pending rows, so a user rule with the same limit can never reach a self-transfer or a company payment. Provenance fixes this:

| `classification_source` | Set by | User rules may overwrite |
|---|---|---|
| `parser` | ingest (new rows) | yes |
| `builtin_rule` | built-in rule pack, own-name markers | yes |
| `merchant_memory` | merchant memory | yes |
| `user_rule` | a user rule | yes (re-evaluated on each run) |
| `manual` | `set_categories` (human or agent patch) | **no** |

Migration 002 sets every existing row to `manual`. This protects the corrections the user already made. Pending pre-upgrade rows become `parser`, because they were never human decisions. The built-in rules and merchant memory touch only pending rows that are not manual. Merchant memory also skips rows a user rule owns. (Rulings made during execution.)

### Matching

- `pattern`: Python regex, case-insensitive, searched in the same text as built-in rules (`description + merchant_raw + merchant_normalized`). It is validated when the rule is added. Maximum 200 characters.
- `direction`: `in` (amount > 0), `out` (amount < 0), or `any`.
- `min_amount_minor` / `max_amount_minor`: inclusive bounds on the absolute amount, in minor units. Both are optional.
- `source_kind`: optional exact match (`account`, `card`).
- Order: `priority` ascending, then `id` ascending. The first match wins.

### Outcome

- `category`: non-empty free string.
- `kind`: one of `expense`, `income`, `transfer`, `internal_transfer`, `self_transfer`, `card_payment`. `is_expense` is derived (`kind == "expense"`). The kind set is closed on purpose: `breakdown._is_income_row` counts any positive non-expense row as income unless its kind is in `_EXCLUDED_SPEND_KINDS`. A typo such as `transfers` would silently turn a transfer into income. A test locks the set to `_EXCLUDED_SPEND_KINDS | {"expense", "income"}`.
- `needs_review`: when true, the rule classifies the row but leaves it in the review queue with `review_reason="user_rule_confirm"`. Use this when an amount range cannot fully separate two cases.
- `note`: the reason for the rule. `review_batch` returns it as `rule_note` on rows that the rule classified.

### Review queue change (deliberate policy edit)

`review_batch` filters to expense rows when `agent_view.expense_only` is true (the default). A row that a user rule flagged for confirmation can be income or a transfer. Such rows are included even when `expense_only` is true, because the user asked to confirm them. Rule-flagged rows are selected by `review_reason = 'user_rule_confirm'`. Rows that a parser classified as income or transfer stay excluded, as before.

### Known limits (accepted)

- If a rule is edited or removed, rows it classified keep their classification until a rule matches them again.
- `set_categories` always marks rows as `manual`. A later user rule cannot change them. To let rules manage a row again, a future command can reset its source. That command is out of scope.
- MCP agents may add and remove rules without a config gate, the same as `set_merchant_category`. Rules only reclassify non-manual rows.

### Out of scope

- The Mercado Pago card parser fix (installment ids and dates, duplicated names).
- The `parser_test` side effect that disables a parser on a failed probe.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/canhoto/migrations/versions/002_user_rules.py` | create | `user_rules` table, provenance columns, backfill |
| `src/canhoto/core/migrate.py` | modify | `HEAD_REVISION = "002_user_rules"` |
| `src/canhoto/core/models.py` | modify | `ClassificationSource`, `USER_RULE_KINDS`, `UserRule`, new fields on `LedgerTransaction`, `ClassificationPatch`, `ClassificationResult`, `ReviewItem` |
| `src/canhoto/core/store.py` | modify | persist provenance; `add_user_rule`, `list_user_rules`, `delete_user_rule`, `user_rule_notes`; review filter |
| `src/canhoto/core/user_rules.py` | create | `match_user_rule`, `amount_bound_to_minor` (pure functions) |
| `src/canhoto/core/categorize.py` | modify | user rules first; tag provenance on every classification |
| `src/canhoto/core/redaction.py` | modify | `to_review_item(..., rule_note=...)` |
| `src/canhoto/service.py` | modify | `rule_add`, `rule_list`, `rule_remove`; `set_categories` marks `manual`; `review_batch` notes and filter; `run_rules` count |
| `src/canhoto/cli.py` | modify | `canhoto rules add|list|remove` |
| `src/canhoto/mcp/server.py`, `src/canhoto/mcp/allowlist.py` | modify | three tools, instructions |
| `tests/test_user_rules.py` | create | model, matching, store, categorize, service |
| `tests/test_migrate.py`, `tests/guardrails/test_mcp_allowlist.py`, `tests/guardrails/test_review_batch.py`, `tests/test_mcp_server.py`, `tests/test_cli_ingest.py` | modify | contract updates |
| `README.md`, `AGENTS.md` | modify | rules workflow |

## Preconditions

- [ ] The pending exporter and card-payment fixes on `fix/card-payment-rule-and-pdf-summary` are committed (ask the user first).
- [ ] Create the branch: `git checkout -b feat/user-classification-rules`.
- [ ] Back up the live database before any run against it: `cp ~/.canhoto/canhoto.db ~/.canhoto/canhoto.db.bak-pre-002`.

---

### Task 1: Schema, provenance fields, and their persistence

**Files:**
- Create: `src/canhoto/migrations/versions/002_user_rules.py`
- Modify: `src/canhoto/core/migrate.py:15`, `src/canhoto/core/models.py`, `src/canhoto/core/store.py` (`_tx_to_params`, `_row_to_tx`, `_upsert_transactions`, `apply_classifications`)
- Test: `tests/test_migrate.py`, `tests/test_user_rules.py`

**Interfaces:**
- Produces: `ClassificationSource` (Literal), `LedgerTransaction.classification_source: ClassificationSource = "parser"`, `LedgerTransaction.user_rule_id: int | None = None`, `ClassificationPatch.classification_source: ClassificationSource | None = None`, `ClassificationPatch.user_rule_id: int | None = None`. Rule: when a patch sets `classification_source`, `apply_classifications` writes both columns. When a patch sets only `user_rule_id` (explicitly, so it is in `model_fields_set`), it writes only the link.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrate.py`:

```python
def test_upgrade_adds_user_rules_and_provenance(tmp_path: Path) -> None:
    db = tmp_path / "canhoto.db"
    migrate.upgrade_to_head(db)
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
    assert "user_rules" in tables
    assert {"classification_source", "user_rule_id"} <= columns


def test_upgrade_marks_existing_rows_manual(tmp_path: Path) -> None:
    from alembic import command

    db = tmp_path / "canhoto.db"
    cfg = migrate.alembic_config(db)
    command.upgrade(cfg, "001_initial")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO transactions (id, date, amount_minor, currency, source_kind,"
            " category, kind, month) VALUES ('t1', '2026-06-01', -100, 'XXX', 'card',"
            " 'Food', 'expense', '2026-06')"
        )
        conn.commit()
    migrate.upgrade_to_head(db)
    with sqlite3.connect(db) as conn:
        source = conn.execute(
            "SELECT classification_source FROM transactions WHERE id = 't1'"
        ).fetchone()[0]
    assert source == "manual"
```

Create `tests/test_user_rules.py`:

```python
"""User classification rules: model, matching, store, categorize, service."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from canhoto.core import config as core_config
from canhoto.core.models import ClassificationPatch, LedgerTransaction
from canhoto.core.store import apply_classifications, get_transaction, upsert_transactions


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    core_config.init_data_dir(root)
    return root


def _tx(
    tx_id: str,
    *,
    description: str = "PIX RECEBIDO ACME LTDA",
    amount_minor: int = 123456,
    source_kind: str = "account",
    category: str = "Transfers",
    kind: str = "transfer",
    is_expense: bool = False,
    needs_review: bool = False,
    classification_source: str = "parser",
) -> LedgerTransaction:
    return LedgerTransaction(
        id=tx_id,
        date=date(2026, 6, 10),
        amount_minor=amount_minor,
        currency="XXX",
        description=description,
        merchant_raw=description,
        source_kind=source_kind,
        category=category,
        kind=kind,
        is_expense=is_expense,
        needs_review=needs_review,
        month="2026-06",
        classification_source=classification_source,  # type: ignore[arg-type]
    )


def test_new_rows_default_to_parser_source(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.classification_source == "parser"
    assert stored.user_rule_id is None


def test_reingest_with_preserve_keeps_provenance(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    apply_classifications(
        [ClassificationPatch(id="a1", category="Income", classification_source="manual")],
        path=db,
    )
    upsert_transactions([_tx("a1")], path=db, preserve_classification=True)
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.classification_source == "manual"


def test_patch_with_source_rewrites_rule_link(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    apply_classifications(
        [ClassificationPatch(id="a1", category="Income", classification_source="manual")],
        path=db,
    )
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.category == "Income"
    assert stored.classification_source == "manual"
    assert stored.user_rule_id is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/test_migrate.py tests/test_user_rules.py`
Expected: FAIL (`user_rules` table missing; `LedgerTransaction` has no `classification_source`).

- [ ] **Step 3: Write the migration**

Create `src/canhoto/migrations/versions/002_user_rules.py`:

```python
"""User classification rules and classification provenance.

Revision ID: 002_user_rules
Revises: 001_initial
Create Date: 2026-10-03
"""

from __future__ import annotations

from alembic import op

revision: str = "002_user_rules"
down_revision: str | None = "001_initial"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_rules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          pattern TEXT NOT NULL,
          direction TEXT NOT NULL DEFAULT 'any'
            CHECK (direction IN ('in', 'out', 'any')),
          min_amount_minor INTEGER CHECK (min_amount_minor IS NULL OR min_amount_minor >= 0),
          max_amount_minor INTEGER CHECK (max_amount_minor IS NULL OR max_amount_minor >= 0),
          source_kind TEXT,
          category TEXT NOT NULL,
          kind TEXT NOT NULL,
          needs_review INTEGER NOT NULL DEFAULT 0,
          note TEXT NOT NULL DEFAULT '',
          priority INTEGER NOT NULL DEFAULT 100,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          CHECK (
            min_amount_minor IS NULL OR max_amount_minor IS NULL
            OR min_amount_minor <= max_amount_minor
          )
        )
        """
    )
    # Existing rows were reviewed by a human: protect them from user rules.
    op.execute(
        "ALTER TABLE transactions ADD COLUMN classification_source TEXT NOT NULL DEFAULT 'manual'"
    )
    op.execute(
        "ALTER TABLE transactions ADD COLUMN user_rule_id INTEGER"
        " REFERENCES user_rules(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    # SQLite cannot DROP COLUMN on a foreign-key column; batch mode rebuilds the table.
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("user_rule_id")
        batch.drop_column("classification_source")
    op.execute("DROP TABLE IF EXISTS user_rules")
```

In `src/canhoto/core/migrate.py`, change `HEAD_REVISION = "001_initial"` to `HEAD_REVISION = "002_user_rules"`.

- [ ] **Step 4: Add the model fields**

In `src/canhoto/core/models.py`, change `from typing import Any, Protocol` to `from typing import Any, Literal, Protocol` and add after the imports:

```python
# Who set a row's classification. User rules never overwrite "manual".
ClassificationSource = Literal[
    "parser", "builtin_rule", "user_rule", "merchant_memory", "manual"
]
```

Add to `LedgerTransaction` (after `installment`):

```python
    classification_source: ClassificationSource = "parser"
    user_rule_id: int | None = None
```

Add to `ClassificationPatch` (after `merchant_normalized`):

```python
    # When set, apply_classifications also rewrites user_rule_id.
    classification_source: ClassificationSource | None = None
    user_rule_id: int | None = None
```

- [ ] **Step 5: Persist the fields in the store**

In `src/canhoto/core/store.py`:

1. `_tx_to_params`: add `"classification_source": tx.classification_source,` and `"user_rule_id": tx.user_rule_id,`.
2. `_row_to_tx`: add `classification_source=row["classification_source"],` and `user_rule_id=row["user_rule_id"],`.
3. `_upsert_transactions` INSERT: add `classification_source, user_rule_id` to the column list and `:classification_source, :user_rule_id` to the values.
4. `_upsert_transactions` non-preserve UPDATE: add `classification_source = :classification_source,` and `user_rule_id = :user_rule_id,`. Do not change the preserve UPDATE.
5. `apply_classifications`: before `if not updates:` add:

```python
            if patch.classification_source is not None:
                updates.append("classification_source = ?")
                params.append(patch.classification_source)
            # A new source always rewrites the link; a rule-to-rule change sets it alone.
            if patch.classification_source is not None or "user_rule_id" in patch.model_fields_set:
                updates.append("user_rule_id = ?")
                params.append(patch.user_rule_id)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -q`
Expected: all pass. `test_upgrade_creates_versioned_schema` still passes because it compares with `migrate.HEAD_REVISION`.

- [ ] **Step 7: Commit**

```bash
git add src/canhoto/migrations/versions/002_user_rules.py src/canhoto/core/migrate.py src/canhoto/core/models.py src/canhoto/core/store.py tests/test_migrate.py tests/test_user_rules.py
git commit -m "feat(db): add user_rules table and classification provenance"
```

### Task 2: `UserRule` model, rule store, and matching

**Files:**
- Modify: `src/canhoto/core/models.py`, `src/canhoto/core/store.py`
- Create: `src/canhoto/core/user_rules.py`
- Test: `tests/test_user_rules.py`

**Interfaces:**
- Consumes: Task 1 schema.
- Produces:
  - `USER_RULE_KINDS: frozenset[str]` and `class UserRule(BaseModel)` with fields `id: int | None`, `pattern: str`, `direction: Literal["in", "out", "any"]`, `min_amount_minor: int | None`, `max_amount_minor: int | None`, `source_kind: str | None`, `category: str`, `kind: str`, `needs_review: bool`, `note: str`, `priority: int`, and property `is_expense: bool`.
  - `store.add_user_rule(rule: UserRule, *, path: Path | None = None) -> UserRule` (returns the rule with `id`).
  - `store.list_user_rules(*, path: Path | None = None) -> list[UserRule]` (priority, then id).
  - `store.delete_user_rule(rule_id: int, *, path: Path | None = None) -> bool`.
  - `store.user_rule_notes(rule_ids: Iterable[int], *, path: Path | None = None) -> dict[int, str]`.
  - `user_rules.match_user_rule(tx: LedgerTransaction, rules: Sequence[UserRule], *, text: str) -> UserRule | None`.
  - `user_rules.amount_bound_to_minor(value: str | None) -> int | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_rules.py`:

```python
from canhoto.core import store as core_store
from canhoto.core.breakdown import _EXCLUDED_SPEND_KINDS
from canhoto.core.models import USER_RULE_KINDS, UserRule
from canhoto.core.user_rules import amount_bound_to_minor, match_user_rule
from pydantic import ValidationError


def _rule(**overrides: object) -> UserRule:
    values: dict[str, object] = {
        "pattern": r"PIX RECEBIDO ACME LTDA",
        "direction": "in",
        "category": "Income",
        "kind": "income",
    }
    values.update(overrides)
    return UserRule.model_validate(values)


def test_rule_kinds_match_what_breakdown_understands() -> None:
    assert USER_RULE_KINDS == _EXCLUDED_SPEND_KINDS | {"expense", "income"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"pattern": "("},
        {"pattern": "   "},
        {"category": " "},
        {"kind": "transfers"},
        {"direction": "sideways"},
        {"min_amount_minor": 500, "max_amount_minor": 100},
        {"min_amount_minor": -1},
    ],
)
def test_invalid_rules_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _rule(**overrides)


def test_expense_kind_derives_is_expense() -> None:
    assert _rule(kind="expense", direction="out").is_expense is True
    assert _rule().is_expense is False


def test_match_respects_direction_amount_and_source() -> None:
    salary = _rule(min_amount_minor=120000, max_amount_minor=130000, source_kind="account")
    tx = _tx("a1", amount_minor=123456)
    text = tx.description
    assert match_user_rule(tx, [salary], text=text) == salary
    assert match_user_rule(_tx("a2", amount_minor=-123456), [salary], text=text) is None
    assert match_user_rule(_tx("a3", amount_minor=800000), [salary], text=text) is None
    assert match_user_rule(_tx("a4", source_kind="card"), [salary], text=text) is None


def test_first_rule_in_given_order_wins() -> None:
    narrow = _rule(id=1, category="Income", min_amount_minor=120000, max_amount_minor=130000)
    broad = _rule(id=2, category="Transfers", kind="transfer")
    tx = _tx("a1")
    assert match_user_rule(tx, [narrow, broad], text=tx.description) == narrow


def test_pattern_is_case_insensitive() -> None:
    tx = _tx("a1", description="Pix recebido Acme Ltda")
    assert match_user_rule(tx, [_rule()], text=tx.description) is not None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("700", 70000), ("1234.56", 123456), ("0.5", 50)],
)
def test_amount_bound_to_minor(value: str | None, expected: int | None) -> None:
    assert amount_bound_to_minor(value) == expected


@pytest.mark.parametrize("value", ["-1", "abc", "1.001"])
def test_amount_bound_rejects_bad_values(value: str) -> None:
    with pytest.raises(ValueError):
        amount_bound_to_minor(value)


def test_store_round_trip_orders_by_priority(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    late = core_store.add_user_rule(_rule(priority=50, note="second"), path=db)
    early = core_store.add_user_rule(_rule(priority=10, note="first"), path=db)
    rules = core_store.list_user_rules(path=db)
    assert [r.id for r in rules] == [early.id, late.id]
    assert core_store.user_rule_notes([late.id or 0], path=db) == {late.id: "second"}
    assert core_store.delete_user_rule(early.id or 0, path=db) is True
    assert core_store.delete_user_rule(early.id or 0, path=db) is False


def test_deleting_a_rule_unlinks_rows(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    rule = core_store.add_user_rule(_rule(), path=db)
    upsert_transactions([_tx("a1")], path=db)
    apply_classifications(
        [
            ClassificationPatch(
                id="a1", category="Income", classification_source="user_rule",
                user_rule_id=rule.id,
            )
        ],
        path=db,
    )
    core_store.delete_user_rule(rule.id or 0, path=db)
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.user_rule_id is None
    assert stored.category == "Income"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/test_user_rules.py`
Expected: FAIL with `ImportError` for `USER_RULE_KINDS` and `canhoto.core.user_rules`.

- [ ] **Step 3: Add the model**

In `src/canhoto/core/models.py`, add `import re` to the imports and `model_validator` to the pydantic import. Add after `ClassificationSource`:

```python
# Kinds a user rule may set. Must equal breakdown._EXCLUDED_SPEND_KINDS plus
# expense and income; a test locks this, because an unknown non-expense kind
# is counted as income.
USER_RULE_KINDS = frozenset(
    {"expense", "income", "transfer", "internal_transfer", "self_transfer", "card_payment"}
)
_MAX_PATTERN_LENGTH = 200


class UserRule(BaseModel):
    """User-defined classification rule stored in ``user_rules``."""

    id: int | None = None
    pattern: str
    direction: Literal["in", "out", "any"] = "any"
    min_amount_minor: int | None = Field(default=None, ge=0)
    max_amount_minor: int | None = Field(default=None, ge=0)
    source_kind: str | None = None
    category: str
    kind: str
    needs_review: bool = False
    note: str = ""
    priority: int = 100

    @field_validator("pattern")
    @classmethod
    def _pattern_must_compile(cls, value: str) -> str:
        pattern = value.strip()
        if not pattern or len(pattern) > _MAX_PATTERN_LENGTH:
            raise ValueError(f"pattern must have 1 to {_MAX_PATTERN_LENGTH} characters")
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"pattern is not a valid regex: {exc}") from exc
        return pattern

    @field_validator("category")
    @classmethod
    def _category_must_be_set(cls, value: str) -> str:
        category = value.strip()
        if not category:
            raise ValueError("category must be a non-empty string")
        return category

    @field_validator("kind")
    @classmethod
    def _kind_must_be_known(cls, value: str) -> str:
        kind = value.strip()
        if kind not in USER_RULE_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(USER_RULE_KINDS))}")
        return kind

    @model_validator(mode="after")
    def _bounds_must_be_ordered(self) -> UserRule:
        low, high = self.min_amount_minor, self.max_amount_minor
        if low is not None and high is not None and low > high:
            raise ValueError("min amount must not exceed max amount")
        return self

    @property
    def is_expense(self) -> bool:
        return self.kind == "expense"
```

- [ ] **Step 4: Add the matching module**

Create `src/canhoto/core/user_rules.py`:

```python
"""Pure matching helpers for user classification rules."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from canhoto.core.models import LedgerTransaction, UserRule

_MINOR_PER_MAJOR = Decimal(100)


def match_user_rule(
    tx: LedgerTransaction, rules: Sequence[UserRule], *, text: str
) -> UserRule | None:
    """Return the first rule that matches ``tx``; ``rules`` must be in priority order."""
    return next((rule for rule in rules if _matches(rule, tx, text)), None)


def amount_bound_to_minor(value: str | None) -> int | None:
    """Convert a non-negative major-unit amount ("700", "1234.56") to minor units."""
    if value is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc
    minor = amount * _MINOR_PER_MAJOR
    if amount < 0 or minor != minor.to_integral_value():
        raise ValueError(f"amount must be non-negative with at most 2 decimals: {value!r}")
    return int(minor)


def _matches(rule: UserRule, tx: LedgerTransaction, text: str) -> bool:
    if rule.source_kind is not None and rule.source_kind != tx.source_kind:
        return False
    if rule.direction == "in" and tx.amount_minor <= 0:
        return False
    if rule.direction == "out" and tx.amount_minor >= 0:
        return False
    magnitude = abs(tx.amount_minor)
    if rule.min_amount_minor is not None and magnitude < rule.min_amount_minor:
        return False
    if rule.max_amount_minor is not None and magnitude > rule.max_amount_minor:
        return False
    return re.search(rule.pattern, text, re.IGNORECASE) is not None
```

- [ ] **Step 5: Add the store functions**

In `src/canhoto/core/store.py`, import `UserRule` and `Iterable` (`from collections.abc import Iterable, Iterator`). Add before `__all__`, and add the four names to `__all__`:

```python
_USER_RULE_COLUMNS = (
    "pattern, direction, min_amount_minor, max_amount_minor, source_kind,"
    " category, kind, needs_review, note, priority"
)


def add_user_rule(rule: UserRule, *, path: Path | None = None) -> UserRule:
    with connect(path) as conn:
        cursor = conn.execute(
            f"INSERT INTO user_rules ({_USER_RULE_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rule.pattern, rule.direction, rule.min_amount_minor, rule.max_amount_minor,
                rule.source_kind, rule.category, rule.kind, 1 if rule.needs_review else 0,
                rule.note, rule.priority,
            ),
        )
        rule_id = cursor.lastrowid
    return rule.model_copy(update={"id": rule_id})


def list_user_rules(*, path: Path | None = None) -> list[UserRule]:
    with connect(path) as conn:
        rows = conn.execute(
            f"SELECT id, {_USER_RULE_COLUMNS} FROM user_rules ORDER BY priority ASC, id ASC"
        ).fetchall()
    return [
        UserRule.model_validate({**dict(row), "needs_review": bool(row["needs_review"])})
        for row in rows
    ]


def delete_user_rule(rule_id: int, *, path: Path | None = None) -> bool:
    with connect(path) as conn:
        cursor = conn.execute("DELETE FROM user_rules WHERE id = ?", (rule_id,))
    return cursor.rowcount > 0


def user_rule_notes(rule_ids: Iterable[int], *, path: Path | None = None) -> dict[int, str]:
    ids = sorted(set(rule_ids))
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    with connect(path) as conn:
        rows = conn.execute(
            f"SELECT id, note FROM user_rules WHERE id IN ({placeholders})", ids
        ).fetchall()
    return {int(row["id"]): str(row["note"]) for row in rows}
```

`ON DELETE SET NULL` needs `PRAGMA foreign_keys = ON`. `connect` already sets it.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -q tests/test_user_rules.py && uv run mypy -p canhoto`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/canhoto/core/models.py src/canhoto/core/store.py src/canhoto/core/user_rules.py tests/test_user_rules.py
git commit -m "feat: add user classification rule model, store, and matching"
```

### Task 3: Apply user rules in `run_rules` and tag provenance

**Files:**
- Modify: `src/canhoto/core/categorize.py` (`apply_rules`, `run_rules_for_month`, `_classify_from_merchant_memory`, `_diff_classification`, `_classify`), `src/canhoto/core/models.py` (`ClassificationResult`)
- Test: `tests/test_user_rules.py`

**Interfaces:**
- Consumes: `match_user_rule`, `list_user_rules`, `UserRule`.
- Produces: `apply_rules(tx, *, own_name_markers=None, rules=None, user_rules: Sequence[UserRule] = ()) -> LedgerTransaction`; `ClassificationResult.user_rule_applied: int = 0`; `run_rules_for_month` loads rules from the store.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_rules.py`:

```python
from canhoto.core.categorize import apply_rules, run_rules_for_month


def test_user_rule_reclassifies_settled_parser_row() -> None:
    rule = _rule(id=7, note="company pay")
    out = apply_rules(_tx("a1"), user_rules=[rule])
    assert (out.category, out.kind, out.is_expense) == ("Income", "income", False)
    assert out.classification_source == "user_rule"
    assert out.user_rule_id == 7
    assert out.needs_review is False


def test_user_rule_never_overwrites_manual_rows() -> None:
    manual = _tx("a1", category="Gifts", kind="expense", classification_source="manual")
    out = apply_rules(manual, user_rules=[_rule(id=7)])
    assert out == manual


def test_user_rule_runs_before_builtin_rules() -> None:
    card_payment = _tx(
        "a1", description="PAGAMENTO DE FATURA ACME", amount_minor=-5000,
        needs_review=True, category="", kind="",
    )
    rule = _rule(id=3, pattern="ACME", direction="out", category="Loans", kind="transfer")
    out = apply_rules(card_payment, user_rules=[rule])
    assert out.category == "Loans"


def test_confirm_rule_keeps_row_in_review() -> None:
    out = apply_rules(_tx("a1"), user_rules=[_rule(id=9, needs_review=True)])
    assert out.needs_review is True
    assert out.review_reason == "user_rule_confirm"


def test_builtin_rule_tags_its_source() -> None:
    pending = _tx(
        "a1", description="PAGAMENTO DA FATURA CARTAO", amount_minor=-5000,
        needs_review=True, category="", kind="",
    )
    assert apply_rules(pending).classification_source == "builtin_rule"


def test_run_rules_applies_stored_rules_and_is_idempotent(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    core_store.add_user_rule(_rule(), path=db)
    upsert_transactions([_tx("a1"), _tx("a2", classification_source="manual")], path=db)

    first = run_rules_for_month("2026-06", path=db)
    second = run_rules_for_month("2026-06", path=db)

    assert first.user_rule_applied == 1
    assert second.applied == 0
    assert get_transaction("a1", path=db).category == "Income"  # type: ignore[union-attr]
    assert get_transaction("a2", path=db).category == "Transfers"  # type: ignore[union-attr]


def test_higher_priority_rule_takes_over_rule_owned_row(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    core_store.add_user_rule(_rule(priority=50), path=db)
    upsert_transactions([_tx("a1")], path=db)
    run_rules_for_month("2026-06", path=db)

    newer = core_store.add_user_rule(_rule(priority=10), path=db)
    run_rules_for_month("2026-06", path=db)

    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.user_rule_id == newer.id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/test_user_rules.py -k "user_rule or builtin or run_rules"`
Expected: FAIL (`apply_rules` has no `user_rules` parameter).

- [ ] **Step 3: Implement**

In `src/canhoto/core/models.py`, add to `ClassificationResult`:

```python
    # Rows classified by a user rule in this run.
    user_rule_applied: int = 0
```

In `src/canhoto/core/categorize.py`:

1. Import `UserRule`, `ClassificationSource` from `canhoto.core.models` and `from canhoto.core.user_rules import match_user_rule`.
2. Give `_classify` two required keyword parameters, `source: ClassificationSource` and `user_rule_id: int | None`, and add `"classification_source": source, "user_rule_id": user_rule_id` to its `update` dict.
3. Pass `source="builtin_rule", user_rule_id=None` in the rule-pack and self-transfer branches. In the sign-default branches, pass `source=out.classification_source, user_rule_id=out.user_rule_id` (the defaults only flag rows for review; they do not take ownership). In `_classify_from_merchant_memory`, pass `source="merchant_memory", user_rule_id=None`.
4. Add `"classification_source"` and `"user_rule_id"` to the `fields` tuple in `_diff_classification`.
5. Change `apply_rules`:

```python
def apply_rules(
    tx: LedgerTransaction,
    *,
    own_name_markers: list[str] | None = None,
    rules: Sequence[Rule] | None = None,
    user_rules: Sequence[UserRule] = (),
) -> LedgerTransaction:
    """Return a deep-copied row with classification fields filled by rules.

    Does not mutate ``tx``. Does not touch the store.
    User rules run first and may reclassify any row a human did not set.
    Built-in rules only touch rows that still need review.
    """
    out = tx.model_copy(deep=True)
    if out.classification_source != "manual":
        rule = match_user_rule(out, user_rules, text=_description_blob(out))
        if rule is not None:
            return _apply_user_rule(out, rule)
    if not _eligible_for_rule_reclassify(out):
        return out
    # ... existing body unchanged from "desc = _description_blob(out)" onward
```

and add below it:

```python
def _apply_user_rule(tx: LedgerTransaction, rule: UserRule) -> LedgerTransaction:
    return _classify(
        tx,
        category=rule.category,
        kind=rule.kind,
        is_expense=rule.is_expense,
        confidence=0.6 if rule.needs_review else 1.0,
        needs_review=rule.needs_review,
        review_reason="user_rule_confirm" if rule.needs_review else None,
        merchant_normalized=tx.merchant_normalized,
        source="user_rule",
        user_rule_id=rule.id,
    )
```

6. In `run_rules_for_month`, load the rules once and count user-rule patches:

```python
    user_rules = core_store.list_user_rules(path=path)
    txs = core_store.list_transactions(month=month, limit=limit, path=path)
    patches: list[ClassificationPatch] = []
    for tx in txs:
        classified = apply_rules(
            tx, own_name_markers=own_name_markers, rules=rules, user_rules=user_rules
        )
        patch = _diff_classification(tx, classified)
        if patch is not None:
            patches.append(patch)
    user_rule_applied = sum(1 for p in patches if p.classification_source == "user_rule")
```

and return `user_rule_applied=user_rule_applied` in the final `ClassificationResult`. Update the docstring order: "1. User rules (non-manual rows). 2. Built-in rule pack and self-transfer markers (pending rows). 3. Merchant memory (pending rows)."

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q && uv run mypy -p canhoto`
Expected: PASS. The existing `tests/test_categorize.py` and `tests/test_merchant_memory.py` must stay green.

- [ ] **Step 5: Commit**

```bash
git add src/canhoto/core/categorize.py src/canhoto/core/models.py tests/test_user_rules.py
git commit -m "feat: apply user rules first in run_rules and record provenance"
```

### Task 4: Service layer, manual provenance, and review notes

**Files:**
- Modify: `src/canhoto/service.py` (`run_rules`, `set_categories`, `review_batch`, new `rule_add`, `rule_list`, `rule_remove`), `src/canhoto/core/redaction.py`, `src/canhoto/core/models.py` (`ReviewItem`), `src/canhoto/core/store.py` (`list_transactions`)
- Test: `tests/test_user_rules.py`, `tests/guardrails/test_review_batch.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces:
  - `service.rule_add(pattern: str, category: str, kind: str, *, direction: str = "any", min_amount: str | None = None, max_amount: str | None = None, source_kind: str | None = None, needs_review: bool = False, note: str = "", priority: int = 100, root: Path | None = None) -> dict[str, Any]` returning `{"ok": True, "rule": {...}}`.
  - `service.rule_list(*, root: Path | None = None) -> dict[str, Any]` returning `{"ok": True, "rules": [...], "count": n}`.
  - `service.rule_remove(rule_id: int, *, root: Path | None = None) -> dict[str, Any]` returning `{"ok": True, "removed": bool, "rule_id": rule_id}`.
  - `run_rules` result gains `"user_rule_applied"`.
  - `ReviewItem.rule_note: str | None = None`; `to_review_item(tx, view, *, rule_note: str | None = None)`.
  - `store.list_transactions(..., include_user_rule_flags: bool = False)`: with `is_expense=True`, also returns rows whose `classification_source = 'user_rule'`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_rules.py`:

```python
from canhoto import service


def test_service_rule_lifecycle(data_home: Path) -> None:
    added = service.rule_add(
        "PIX RECEBIDO ACME", "Income", "income",
        direction="in", min_amount="1200", max_amount="1300", note="company pay",
    )
    rule_id = added["rule"]["id"]
    listed = service.rule_list()
    assert listed["count"] == 1
    assert listed["rules"][0]["note"] == "company pay"
    assert listed["rules"][0]["min_amount_minor"] == 120000
    assert service.rule_remove(rule_id)["removed"] is True
    assert service.rule_list()["count"] == 0


def test_service_rule_add_rejects_unknown_kind(data_home: Path) -> None:
    with pytest.raises(ValueError):
        service.rule_add("ACME", "Transfers", "transfers")


def test_run_rules_reports_user_rule_count(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    service.rule_add("PIX RECEBIDO ACME", "Income", "income", direction="in")
    assert service.run_rules("2026-06")["user_rule_applied"] == 1


def test_set_categories_marks_rows_manual_and_ignores_spoofed_source(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1")], path=db)
    service.set_categories(
        [{"id": "a1", "category": "Gifts", "classification_source": "user_rule", "user_rule_id": 4}]
    )
    stored = get_transaction("a1", path=db)
    assert stored is not None
    assert stored.classification_source == "manual"
    assert stored.user_rule_id is None


def test_review_batch_shows_rule_note_for_flagged_income(data_home: Path) -> None:
    db = core_config.db_path(data_home)
    upsert_transactions([_tx("a1", amount_minor=900000)], path=db)
    service.rule_add(
        "PIX RECEBIDO ACME", "Income", "income", direction="in",
        min_amount="5000", needs_review=True, note="usually profit share; confirm",
    )
    service.run_rules("2026-06")
    items = service.review_batch("2026-06")["items"]
    assert [item["id"] for item in items] == ["a1"]
    assert items[0]["rule_note"] == "usually profit share; confirm"
```

In `tests/guardrails/test_review_batch.py`, add (reuse the module's `data_home` fixture and seeding helpers):

```python
def test_review_batch_still_hides_parser_income_when_expense_only(data_home: Path) -> None:
    from canhoto.core import config as core_config
    from canhoto.core.models import LedgerTransaction
    from canhoto.core.store import upsert_transactions

    upsert_transactions(
        [
            LedgerTransaction(
                id="inc1", date=date(2026, 6, 3), amount_minor=10000, currency="XXX",
                description="PIX RECEBIDO JANE DOE", source_kind="account",
                category="income", kind="income", needs_review=True, month="2026-06",
            )
        ],
        path=core_config.db_path(data_home),
    )
    ids = [item["id"] for item in service.review_batch("2026-06")["items"]]
    assert "inc1" not in ids
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/test_user_rules.py tests/guardrails/test_review_batch.py`
Expected: FAIL (`service` has no `rule_add`).

- [ ] **Step 3: Implement the review projection**

In `src/canhoto/core/models.py`, add to `ReviewItem` (last field):

```python
    # Reason from the user rule that classified this row, if any.
    rule_note: str | None = None
```

In `src/canhoto/core/redaction.py`, change the signature to `def to_review_item(tx: Transaction, view: AgentViewConfig, *, rule_note: str | None = None) -> ReviewItem:` and pass `rule_note=rule_note` to `ReviewItem(...)`.

In `src/canhoto/core/store.py` `list_transactions`, add the parameter `include_user_rule_flags: bool = False` and replace the `is_expense` clause:

```python
    if is_expense is not None:
        if include_user_rule_flags and is_expense:
            # Rows a user rule flagged for confirmation can be income or transfers.
            clauses.append("(is_expense = 1 OR classification_source = 'user_rule')")
        else:
            clauses.append("is_expense = ?")
            args.append(1 if is_expense else 0)
```

- [ ] **Step 4: Implement the service functions**

In `src/canhoto/service.py`, import `UserRule` from `canhoto.core.models` and `amount_bound_to_minor` from `canhoto.core.user_rules`.

`run_rules`: add `"user_rule_applied": result.user_rule_applied,` to the result dict, and update the docstring order (user rules first).

`set_categories`: replace the append with:

```python
        patch = ClassificationPatch.model_validate(raw)
        # Patches are human or agent decisions: always manual, never rule-owned.
        parsed.append(
            patch.model_copy(update={"classification_source": "manual", "user_rule_id": None})
        )
```

`review_batch`: pass `include_user_rule_flags=True` to `list_transactions`, then build items with notes:

```python
    notes = core_store.user_rule_notes(
        (tx.user_rule_id for tx in page if tx.user_rule_id is not None), path=db_file
    )
    items = [
        to_review_item(
            tx, cfg.agent_view, rule_note=notes.get(tx.user_rule_id or -1)
        ).model_dump(mode="json")
        for tx in page
    ]
```

Add after `set_merchant_category`:

```python
# --- User classification rules ---


def rule_add(
    pattern: str,
    category: str,
    kind: str,
    *,
    direction: str = "any",
    min_amount: str | None = None,
    max_amount: str | None = None,
    source_kind: str | None = None,
    needs_review: bool = False,
    note: str = "",
    priority: int = 100,
    root: Path | None = None,
) -> dict[str, Any]:
    """Store a user rule. ``run_rules`` applies it to non-manual rows.

    Amounts are non-negative major units ("1234.56"); bounds are inclusive.
    Raises ``ValueError`` for an invalid regex, kind, direction, or range.
    """
    try:
        rule = UserRule.model_validate(
            {
                "pattern": pattern,
                "category": category,
                "kind": kind,
                "direction": direction,
                "min_amount_minor": amount_bound_to_minor(min_amount),
                "max_amount_minor": amount_bound_to_minor(max_amount),
                "source_kind": source_kind or None,
                "needs_review": needs_review,
                "note": note.strip(),
                "priority": priority,
            }
        )
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    data_dir = _ensure_data_dir(root)
    db_file = core_config.db_path(data_dir)
    stored = core_store.add_user_rule(rule, path=db_file)
    return {"ok": True, "rule": stored.model_dump(mode="json")}


def rule_list(*, root: Path | None = None) -> dict[str, Any]:
    """Return all user rules in the order ``run_rules`` tries them."""
    data_dir = _ensure_data_dir(root)
    rules = core_store.list_user_rules(path=core_config.db_path(data_dir))
    return {
        "ok": True,
        "rules": [rule.model_dump(mode="json") for rule in rules],
        "count": len(rules),
    }


def rule_remove(rule_id: int, *, root: Path | None = None) -> dict[str, Any]:
    """Delete a user rule. Rows it classified keep their classification."""
    data_dir = _ensure_data_dir(root)
    removed = core_store.delete_user_rule(rule_id, path=core_config.db_path(data_dir))
    return {"ok": True, "removed": removed, "rule_id": rule_id}
```

Add `from pydantic import ValidationError` to the imports.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q && uv run ruff check src/canhoto tests && uv run mypy -p canhoto`
Expected: PASS. `test_review_item_has_no_forbidden_fields` stays green because `rule_note` is not a forbidden field.

- [ ] **Step 6: Commit**

```bash
git add src/canhoto/service.py src/canhoto/core/redaction.py src/canhoto/core/models.py src/canhoto/core/store.py tests/test_user_rules.py tests/guardrails/test_review_batch.py
git commit -m "feat: expose user rules in service and show rule notes in review"
```

### Task 5: CLI and MCP surfaces, with docs

**Files:**
- Modify: `src/canhoto/cli.py`, `src/canhoto/mcp/server.py`, `src/canhoto/mcp/allowlist.py`, `README.md`, `AGENTS.md`
- Test: `tests/guardrails/test_mcp_allowlist.py`, `tests/test_mcp_server.py`, `tests/test_cli_ingest.py`

**Interfaces:**
- Consumes: `service.rule_add`, `service.rule_list`, `service.rule_remove`.
- Produces: `canhoto rules add|list|remove`; MCP tools `rule_add`, `rule_list`, `rule_remove`.

- [ ] **Step 1: Write the failing tests**

In `tests/guardrails/test_mcp_allowlist.py`, add `"rule_list"`, `"rule_add"`, `"rule_remove"` to `EXPECTED_ALLOWLIST`. This is a deliberate contract change.

In `tests/test_mcp_server.py`, add `"rule_list"` and `"rule_add"` to the keyword tuple in `test_server_instructions_describe_happy_path`.

Append to `tests/test_cli_ingest.py`:

```python
def test_cli_rules_add_list_remove(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main([
        "rules", "add", "--pattern", "PIX RECEBIDO ACME", "--category", "Income",
        "--kind", "income", "--direction", "in", "--min", "1200", "--max", "1300",
        "--note", "company pay",
    ]) == 0
    rule_id = json.loads(capsys.readouterr().out)["rule"]["id"]

    assert cli_main(["rules", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["rules"][0]["note"] == "company pay"

    assert cli_main(["rules", "remove", "--id", str(rule_id)]) == 0
    assert json.loads(capsys.readouterr().out)["removed"] is True


def test_cli_rules_add_rejects_bad_kind(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli_main(["rules", "add", "--pattern", "X", "--category", "C", "--kind", "bogus"])
    assert code != 0
    assert json.loads(capsys.readouterr().out)["ok"] is False
```

Add `import json` to the file if it is not there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest -q tests/guardrails/test_mcp_allowlist.py tests/test_mcp_server.py tests/test_cli_ingest.py`
Expected: FAIL.

- [ ] **Step 3: Implement the CLI**

In `src/canhoto/cli.py` `build_parser`, after the `categorize` group:

```python
    rule_p = sub.add_parser("rules", help="Manage user classification rules")
    rule_sub = rule_p.add_subparsers(dest="rules_cmd", required=True)
    add_p = rule_sub.add_parser("add", help="Store a rule that run_rules applies")
    add_p.add_argument("--pattern", required=True, help="Case-insensitive regex on the description")
    add_p.add_argument("--category", required=True)
    add_p.add_argument("--kind", required=True, help="expense, income, transfer, ...")
    add_p.add_argument("--direction", choices=("in", "out", "any"), default="any")
    add_p.add_argument("--min", dest="min_amount", help="Minimum absolute amount, inclusive")
    add_p.add_argument("--max", dest="max_amount", help="Maximum absolute amount, inclusive")
    add_p.add_argument("--source-kind", help="Only rows from this source (account, card)")
    add_p.add_argument("--review", action="store_true", help="Classify, but keep for review")
    add_p.add_argument("--note", default="", help="Why this rule exists")
    add_p.add_argument("--priority", type=int, default=100, help="Lower runs first")
    rule_sub.add_parser("list", help="List rules in evaluation order")
    rm_p = rule_sub.add_parser("remove", help="Delete a rule")
    rm_p.add_argument("--id", dest="rule_id", type=int, required=True)
```

In `main`, after the `categorize` dispatch, add `if args.cmd == "rules": return _run_rules(args)`, and add:

```python
def _run_rules(args: argparse.Namespace) -> int:
    if args.rules_cmd == "add":
        return _run_service_cmd(
            lambda: service.rule_add(
                args.pattern,
                args.category,
                args.kind,
                direction=args.direction,
                min_amount=args.min_amount,
                max_amount=args.max_amount,
                source_kind=args.source_kind,
                needs_review=args.review,
                note=args.note,
                priority=args.priority,
            )
        )
    if args.rules_cmd == "list":
        return _run_service_cmd(service.rule_list)
    if args.rules_cmd == "remove":
        return _run_service_cmd(lambda: service.rule_remove(args.rule_id))
    _print_json({"ok": False, "error": f"unknown rules command: {args.rules_cmd}"})
    return 2
```

Confirm that `_run_service_cmd` turns `ValueError` into `{"ok": false, ...}` with a non-zero exit. If it does not, the bad-kind test fails. In that case, extend `_run_service_cmd` to catch `ValueError` in the same way it catches the other service errors.

- [ ] **Step 4: Implement the MCP tools**

In `src/canhoto/mcp/allowlist.py`, add `"rule_list"`, `"rule_add"`, `"rule_remove"` to `MCP_TOOL_ALLOWLIST`.

In `src/canhoto/mcp/server.py` `_register_tools`, after `set_merchant_category`:

```python
    @server.tool()
    def rule_list() -> dict[str, Any]:
        """List user classification rules and their notes, in evaluation order."""
        return service.rule_list()

    @server.tool()
    def rule_add(
        pattern: str,
        category: str,
        kind: str,
        direction: str = "any",
        min_amount: str | None = None,
        max_amount: str | None = None,
        source_kind: str | None = None,
        needs_review: bool = False,
        note: str = "",
        priority: int = 100,
    ) -> dict[str, Any]:
        """Store a rule the user stated. Always include a note that says why."""
        return service.rule_add(
            pattern, category, kind, direction=direction, min_amount=min_amount,
            max_amount=max_amount, source_kind=source_kind, needs_review=needs_review,
            note=note, priority=priority,
        )

    @server.tool()
    def rule_remove(rule_id: int) -> dict[str, Any]:
        """Delete a user classification rule."""
        return service.rule_remove(rule_id)
```

In `_INSTRUCTIONS`, replace step 3 with:

```text
3. rule_list (read the notes) → run_rules → review_batch loop → set_categories.
   When the user explains a recurring counterparty, store it with rule_add and a note.
   Use needs_review=true when an amount range cannot separate the cases.
```

- [ ] **Step 5: Update the docs**

`AGENTS.md`, "MCP happy path" step 3: `rule_list` → `run_rules` → `review_batch` loop → `set_categories`; add "Store recurring decisions with `rule_add` and a note. Rules never overwrite rows set by `set_categories`."

`README.md`, "Process a month": add a "Teach Canhoto your rules" subsection with this example (invented names only):

```bash
canhoto rules add --pattern "PIX RECEBIDO ACME LTDA" --direction in \
  --min 1200 --max 1300 --category Income --kind income \
  --note "Monthly pay from my company"
canhoto rules list
```

and one sentence: "Rules run before the built-in rules. They never change a row that you or an agent categorized with `categorize apply` / `set_categories`."

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q && uv run ruff check src/canhoto tests && uv run mypy -p canhoto`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/canhoto/cli.py src/canhoto/mcp/server.py src/canhoto/mcp/allowlist.py README.md AGENTS.md tests/guardrails/test_mcp_allowlist.py tests/test_mcp_server.py tests/test_cli_ingest.py
git commit -m "feat: add rules CLI and MCP tools"
```

### Task 6: Seed the owner's rules (local data only, no commit)

This task changes `~/.canhoto/canhoto.db` only. Do not write these values into the repository. Get the exact names, patterns, and ranges from the owner's conversation record, or ask the owner. Do not copy them into this file.

- [ ] **Step 1: Back up and migrate**

Run: `cp ~/.canhoto/canhoto.db ~/.canhoto/canhoto.db.bak-pre-002 && uv run canhoto doctor`
Expected: `db_revision` is `002_user_rules`.

- [ ] **Step 2: Add the rules with `canhoto rules add`**

The owner supplies the rule set in the session. Do not record it in the repository.

- [ ] **Step 3: Verify without changing the reviewed months**

Run: `uv run canhoto rules list`, then `uv run canhoto categorize rules --month <each ingested month>`.
Expected: `user_rule_applied` is 0 for every month already reviewed, because the migration marked those rows `manual`. Breakdown totals stay the same as before the migration.

- [ ] **Step 4: Report to the owner**

State the rule count, and confirm that the totals did not change. The next statement ingest will exercise the rules.

---

## Self-Review Notes

- Coverage: storage (Task 1, 2), matching (Task 2), provenance and precedence (Task 1, 3), confirm flow with notes (Task 3, 4), agent surfaces (Task 5), docs (Task 5), real data (Task 6).
- Deliberate contract edits: `HEAD_REVISION`, `EXPECTED_ALLOWLIST`, MCP instruction keywords, `ReviewItem.rule_note`, `review_batch` filter for rule-flagged rows, `to_review_item` signature.
- Names are consistent across tasks: `classification_source`, `user_rule_id`, `UserRule`, `USER_RULE_KINDS`, `match_user_rule`, `amount_bound_to_minor`, `add_user_rule`, `list_user_rules`, `delete_user_rule`, `user_rule_notes`, `user_rule_applied`, `rule_note`, `include_user_rule_flags`.
