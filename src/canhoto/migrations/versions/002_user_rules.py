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
    # Pending rows were never human decisions: let rules classify them.
    op.execute("UPDATE transactions SET classification_source = 'parser' WHERE needs_review = 1")


def downgrade() -> None:
    # SQLite cannot DROP COLUMN on a foreign-key column; batch mode rebuilds the table.
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("user_rule_id")
        batch.drop_column("classification_source")
    op.execute("DROP TABLE IF EXISTS user_rules")
