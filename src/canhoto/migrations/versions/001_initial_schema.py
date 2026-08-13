"""Initial ledger schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transactions (
          id TEXT PRIMARY KEY,
          date TEXT NOT NULL,
          amount_minor INTEGER NOT NULL,
          currency TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          merchant_raw TEXT NOT NULL DEFAULT '',
          merchant_normalized TEXT,
          source_kind TEXT NOT NULL,
          institution TEXT,
          source_file TEXT,
          operation_id TEXT,
          running_balance_minor INTEGER,
          account_id TEXT,
          category TEXT NOT NULL,
          kind TEXT NOT NULL,
          is_expense INTEGER NOT NULL DEFAULT 0,
          needs_review INTEGER NOT NULL DEFAULT 1,
          confidence REAL NOT NULL DEFAULT 0,
          review_reason TEXT,
          installment TEXT,
          month TEXT NOT NULL,
          billing_cycle TEXT,
          metadata TEXT NOT NULL DEFAULT '{}',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE TABLE statements (
          content_hash TEXT PRIMARY KEY,
          source_file TEXT NOT NULL,
          statement_type TEXT NOT NULL,
          institution TEXT,
          meta_json TEXT NOT NULL DEFAULT '{}',
          ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE TABLE statement_transactions (
          content_hash TEXT NOT NULL,
          transaction_id TEXT NOT NULL,
          PRIMARY KEY (content_hash, transaction_id),
          FOREIGN KEY (content_hash) REFERENCES statements(content_hash),
          FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE merchant_category_map (
          merchant_key TEXT PRIMARY KEY,
          category TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_transactions_month ON transactions(month)"
    )
    op.execute(
        "CREATE INDEX idx_transactions_needs_review ON transactions(needs_review)"
    )
    op.execute(
        "CREATE INDEX idx_transactions_month_review ON transactions(month, needs_review)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_transactions_month_review")
    op.execute("DROP INDEX IF EXISTS idx_transactions_needs_review")
    op.execute("DROP INDEX IF EXISTS idx_transactions_month")
    op.execute("DROP TABLE IF EXISTS merchant_category_map")
    op.execute("DROP TABLE IF EXISTS statement_transactions")
    op.execute("DROP TABLE IF EXISTS statements")
    op.execute("DROP TABLE IF EXISTS transactions")
