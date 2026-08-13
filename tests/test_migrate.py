"""Alembic migration wiring — upgrade to head."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from canhoto.core import migrate


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
