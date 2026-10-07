# Release Blocker Fixes Implementation Plan

> **For agentic workers:** Use regression tests before each fix. Execute this plan in the current checkout.

**Goal:** Fix the confirmed release blockers, then publish version 0.2.0.

**Architecture:** Validate manual input in the manual domain module. Reset automatic classification when facts change. Prepare restores in a private sibling directory. Install the complete directory only after validation.

**Tech Stack:** Python 3.11+, pytest, SQLite, Alembic, pathlib, tempfile.

**Spec:** The release review and the user's request to fix its findings.

## Constraints

- Preserve all current changes. The user requested release from this checkout.
- Do not change parser-facing ledger contracts.
- Keep manual and backup operations outside MCP.
- Preserve explicit human categories and merchant names.
- Restore requires a new or empty directory. Reject files and directory links.
- Restore parser modules under `parsers/` in the destination.
- Backups are trusted local input. Checksums do not authenticate their author.
- Do not publish until tests, lint, type checks, and distribution checks pass.

## Task 1: Validate manual kinds

Files: `src/canhoto/core/manual.py`, `tests/test_manual_transactions.py`.

- [x] Add tests that reject unknown kinds on add and edit without changing stored rows.
- [x] Add a test that normalizes a valid kind and preserves expense totals.
- [x] Run `uv run pytest -q tests/test_manual_transactions.py` and observe the failures.
- [x] Add one shared kind validator using `USER_RULE_KINDS`.
- [x] Run the focused tests again.

## Task 2: Reclassify edited facts

Files: `src/canhoto/core/manual.py`, `src/canhoto/service.py`, `tests/test_manual_transactions.py`.

- [x] Test that an edited row outside its old rule returns to review.
- [x] Test that edits can select a different rule, including built-in rules.
- [x] Test that human categories and explicit merchant names survive fact edits.
- [x] Test that a note-only edit preserves classification.
- [x] Observe the missing behavior before implementation.
- [x] Clear stale automatic classification before applying rules to changed facts.
- [x] Track explicit merchant names in metadata. Clear derived names when descriptions change.
- [x] Run the focused tests again.
- [x] Update implicit kinds after sign changes. Preserve explicit kinds and merchants from review.

## Task 3: Prepare and install complete restores

Files: `src/canhoto/core/backup.py`, `tests/test_backup.py`, `README.md`.

- [x] Test that existing restore-related files and config links remain unchanged.
- [x] Test that migration, config, and parser failures leave no published ledger and permit retry.
- [x] Test empty-directory restore and custom parser location normalization.
- [x] Observe the failures before implementation.
- [x] Reject non-empty destinations and links before creating staging files.
- [x] Use a unique private sibling directory for all restored files.
- [x] Check database revision and integrity, then migrate the staged ledger.
- [x] Serialize config with the final data directory and the local parser directory.
- [x] Install the prepared directory with one rename. Clean up staging on failure.
- [x] Update restore documentation and run the focused tests.
- [x] Round-trip safe parser filenames. Reject path separators and drive syntax.

## Task 4: Validate and release

Files: `pyproject.toml`, `uv.lock`, `scripts/smoke_test.py` if needed.

- [x] Run the full pytest suite, Ruff, mypy, and `git diff --check`.
- [x] Obtain a fresh read-only review of the fixes.
- [x] Set package version to 0.2.0 and update the lock file.
- [x] Build wheel and source distribution. Smoke-test both installed distributions.

Verification: 263 tests passed. Ruff and mypy passed. Independent review approved the fixes.
Both installed distributions passed CLI smoke checks outside the project.
Smoke checks used locked dependencies already installed in the project environment.
Fresh dependency downloads stalled locally. Release CI still checks clean installations.

- [x] Inspect staged files for private data and unintended changes.
- [ ] Commit, create annotated tag `v0.2.0`, and push the commit and tag without force.
- [ ] Check the release workflow result and report the publication status.
