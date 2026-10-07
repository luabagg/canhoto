"""Alembic migration wiring — upgrade to head."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from canhoto.core import migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine


def test_upgrade_creates_versioned_schema(tmp_path: Path) -> None:
    db = tmp_path / "canhoto.db"
    rev = migrate.upgrade_to_head(db)
    assert rev == migrate.HEAD_REVISION
    assert rev == migrate.head_revision()
    assert migrate.current_revision(db) == migrate.HEAD_REVISION

    with sqlite3.connect(db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "transactions",
        "statements",
        "statement_transactions",
        "merchant_category_map",
        "alembic_version",
    } <= tables


def test_wipe_and_upgrade_deletes_versioned_db(tmp_path: Path) -> None:
    db = tmp_path / "canhoto.db"
    migrate.upgrade_to_head(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO merchant_category_map (merchant_key, category) VALUES ('a', 'food')"
        )
        conn.commit()

    migrate.wipe_and_upgrade(db)
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM merchant_category_map").fetchone()[0]
    assert count == 0
    assert migrate.current_revision(db) == migrate.HEAD_REVISION


def test_upgrade_adds_user_rules_and_provenance(tmp_path: Path) -> None:
    db = tmp_path / "canhoto.db"
    migrate.upgrade_to_head(db)
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
    assert "user_rules" in tables
    assert {"classification_source", "user_rule_id"} <= columns


def test_failed_currency_migration_rolls_back_and_can_be_retried(tmp_path: Path) -> None:
    db = tmp_path / "canhoto.db"
    command.upgrade(migrate.alembic_config(db), "002_user_rules")

    def fail_second_alter(
        connection: object, cursor: object, statement: str, parameters: object,
        context: object, executemany: bool,
    ) -> None:
        if statement.startswith("ALTER TABLE user_rules ADD COLUMN amount_exponent"):
            raise OSError("injected migration failure")

    event.listen(Engine, "before_cursor_execute", fail_second_alter)
    try:
        with pytest.raises(OSError, match="injected"):
            migrate.upgrade_to_head(db)
    finally:
        event.remove(Engine, "before_cursor_execute", fail_second_alter)
    assert migrate.current_revision(db) == "002_user_rules"
    with sqlite3.connect(db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)")}
    assert "amount_exponent" not in columns
    assert migrate.upgrade_to_head(db) == migrate.HEAD_REVISION


def test_upgrade_marks_settled_rows_manual_and_pending_rows_parser(tmp_path: Path) -> None:
    db = tmp_path / "canhoto.db"
    cfg = migrate.alembic_config(db)
    command.upgrade(cfg, "001_initial")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO transactions (id, date, amount_minor, currency, source_kind,"
            " category, kind, month, needs_review) VALUES ('t1', '2026-06-01', -100, 'XXX',"
            " 'card', 'Food', 'expense', '2026-06', 0)"
        )
        conn.execute(
            "INSERT INTO transactions (id, date, amount_minor, currency, source_kind,"
            " category, kind, month, needs_review) VALUES ('t2', '2026-06-02', -200, 'XXX',"
            " 'card', '', '', '2026-06', 1)"
        )
        conn.commit()
    migrate.upgrade_to_head(db)
    with sqlite3.connect(db) as conn:
        sources = dict(
            conn.execute("SELECT id, classification_source FROM transactions").fetchall()
        )
    assert sources == {"t1": "manual", "t2": "parser"}
