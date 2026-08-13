"""Alembic env — SQLite URL injected by ``canhoto.core.migrate``."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

# Raw SQL revisions — no SQLAlchemy ORM metadata.
target_metadata = None


def _sqlalchemy_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("alembic config missing sqlalchemy.url")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sqlalchemy_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_sqlalchemy_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
