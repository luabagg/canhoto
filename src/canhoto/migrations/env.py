"""Alembic env — SQLite URL injected by ``canhoto.core.migrate``."""

from __future__ import annotations

import sqlite3
from typing import Any

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
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connect_args: dict[str, Any] = {"isolation_level": None}
    legacy_control = getattr(sqlite3, "LEGACY_TRANSACTION_CONTROL", None)
    if legacy_control is not None:
        connect_args["autocommit"] = legacy_control
    connectable = create_engine(
        _sqlalchemy_url(), poolclass=pool.NullPool, connect_args=connect_args
    )
    try:
        with connectable.begin() as connection:
            # SQLite does not begin transactions for DDL. Keep schema changes and revision atomic.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                transactional_ddl=True,
            )
            context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
