# Global Currency Config Implementation Plan

> **For agentic workers:** Use regression tests before each change. Execute in this checkout and preserve the existing README changes.

**Goal:** Add user-wide currency defaults, ledger overrides, and explicit manual-entry currencies.

**Architecture:** Keep global defaults separate from declared ledger config. Resolve currency only when adding a manual row. Persist each row's currency and preserve it on ordinary edits.

**Tech Stack:** Python 3.11+, Pydantic, argparse, SQLite, pytest. No new dependencies or database migrations.

**Spec:** The user approved Git-style global/local config and manual-entry currency selection. The approved scope follows.

## Approved scope and constraints

- Global file: `$XDG_CONFIG_HOME/canhoto/config.json`, otherwise `~/.config/canhoto/config.json`.
- Ignore relative `XDG_CONFIG_HOME` values, as the XDG specification requires absolute paths.
- Ledger file: the active data directory's existing `config.json`.
- Supported setting: `currency`. Reject unknown keys instead of silently storing them.
- Commands: `config set`, `config get`, and `config unset`, with optional `--global`.
- Effective order: explicit manual `--currency`, ledger override, global default, built-in BRL.
- Global reads and effective reads must not create configuration files or a ledger.
- Ledger config must retain only its declared currency override. Parser/config saves must not freeze inherited defaults.
- Currency codes contain three ASCII letters. Normalize them to uppercase. This validates code format, not the ISO registry.
- Add/edit accepts an explicit currency. An edit without currency keeps the stored currency, even after config changes.
- Changing a row's currency corrects recorded facts. It does not convert its amount.
- Manual output includes currency. Duplicate identity includes currency.
- Config writes use a temporary file and rename. A failed write must preserve the old config.
- Isolate tests and smoke checks from real user global preferences.
- Local overrides belong in ledger backups. Global preferences do not.
- Keep config management and manual operations outside MCP.
- Currency precision, exchange rates, mixed-currency aggregation, and PDF currency formatting remain outside this scope.
- The current money model supports two-decimal currencies. Do not claim general currency support.
- The user approved committing this change. Do not tag, push, or publish without another explicit request.

## Task 1: Config storage and resolution

Files: `src/canhoto/core/models.py`, `src/canhoto/core/config.py`, `tests/test_config.py`, `tests/conftest.py`.

Interfaces:

- `GlobalConfig.currency: str | None`, validated and normalized.
- `AppConfig.currency: str | None`, an explicit override or inheritance.
- `global_config_path() -> Path`.
- `resolve_currency(root: Path | None = None, *, override: str | None = None) -> str`.
- `get_config_value(key, *, global_scope=False, root=None) -> str | None`.
- `set_config_value(key, value, *, global_scope=False, root=None) -> str`.
- `unset_config_value(key, *, global_scope=False, root=None) -> bool`.

- [x] Add regressions for read-only fallback, precedence, XDG paths, unset, unknown keys, invalid values, and inherited defaults after config saves.
- [x] Run `uv run pytest -q tests/test_config.py` and observe failures.
- [x] Add typed optional currency settings and one shared currency-code validator.
- [x] Read global settings separately. Do not merge inherited values into `AppConfig`.
- [x] Add atomic config writes and regression coverage for installation failure.
- [x] Run the focused tests again.

Example precedence test:

```python
set_config_value("currency", "EUR", global_scope=True)
assert resolve_currency(root) == "EUR"
set_config_value("currency", "USD", root=root)
assert resolve_currency(root) == "USD"
assert resolve_currency(root, override="BRL") == "BRL"
```

## Task 2: CLI and manual rows

Files: `src/canhoto/cli.py`, `src/canhoto/service.py`, `src/canhoto/core/manual.py`, `tests/test_manual_transactions.py`, `tests/test_config.py`, `tests/test_backup.py`.

Interfaces:

- Service: `config_get`, `config_set`, and `config_unset` delegate to core config.
- `manual_add(..., currency: str | None = None)` resolves the default once.
- `manual_edit(..., currency: str | None = None)` does not resolve a default.
- Manual domain functions receive currency explicitly.

- [x] Add failing tests for config command flows, add precedence, stored currency after config changes, explicit correction, invalid currency rejection, and duplicate identity.
- [x] Add `--currency` to manual add/edit and include currency in manual views.
- [x] Include currency in duplicate comparison and automatic reclassification after fact edits.
- [x] Add config command dispatch through the service facade. Do not expose new MCP tools.
- [x] Test a local currency override through backup/restore.
- [x] Run `uv run pytest -q tests/test_config.py tests/test_manual_transactions.py tests/test_backup.py tests/guardrails`.

## Task 3: Documentation and verification

Files: `README.md`, `scripts/smoke_test.py`.

- [x] Document set/get/unset, precedence, file locations, read-only gets, and currency correction without conversion.
- [x] Keep the existing Mermaid improvements and document remaining currency limitations.
- [x] Extend the smoke check with isolated global settings and local override restoration.
- [x] Run `uv run pytest -q`, `uv run ruff check src/canhoto tests scripts`, `uv run mypy -p canhoto`, and `git diff --check`.
- [x] Run the smoke check against the installed code and inspect the final diff.
- [x] Obtain a fresh read-only review before completion.

## Verification

294 tests passed. Ruff, mypy, the smoke check, and diff checks passed.
Independent review approved the implementation.
Fault tests cover partial writes, close failures, and replacement failures in both config scopes.
No new dependencies, database migrations, or MCP tools were added.
This change does not include a release tag, push, or publication.
