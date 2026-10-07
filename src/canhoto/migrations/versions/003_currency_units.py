"""Record money scales without changing existing amounts or guessing rule currencies."""

from __future__ import annotations

from alembic import op

revision: str = "003_currency_units"
down_revision: str | None = "002_user_rules"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Previous releases interpreted every stored integer amount as hundredths.
    op.execute(
        "ALTER TABLE transactions ADD COLUMN amount_exponent INTEGER NOT NULL DEFAULT 2"
        " CHECK (amount_exponent BETWEEN 0 AND 9)"
    )
    op.execute(
        "ALTER TABLE user_rules ADD COLUMN amount_exponent INTEGER NOT NULL DEFAULT 2"
        " CHECK (amount_exponent BETWEEN 0 AND 9)"
    )
    op.execute("ALTER TABLE user_rules ADD COLUMN currency TEXT")


def downgrade() -> None:
    raise RuntimeError("currency-unit migration cannot be downgraded without changing money values")
