"""Alembic helpers for the local SQLite ledger."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from canhoto.core.config import db_path

HEAD_REVISION = "001_initial"


def migrations_dir() -> Path:
    """Return the filesystem path to packaged Alembic scripts."""
    return Path(__file__).resolve().parent.parent / "migrations"


def sqlite_url(path: Path) -> str:
    """Absolute SQLite URL for Alembic / SQLAlchemy."""
    return f"sqlite:///{path.resolve().as_posix()}"


def alembic_config(path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir()))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(path))
    cfg.set_main_option("prepend_sys_path", ".")
    # Alembic 1.19+: required to avoid DeprecationWarning (pytest treats as error).
    cfg.set_main_option("path_separator", "os")
    return cfg


def current_revision(path: Path) -> str | None:
    """Return the DB's Alembic revision, or ``None`` if unversioned/missing."""
    if not path.is_file():
        return None
    engine = create_engine(sqlite_url(path))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            return ctx.get_current_revision()
    finally:
        engine.dispose()


def upgrade_to_head(path: Path | None = None) -> str:
    """Run Alembic ``upgrade head`` on ``path`` (creates file if needed)."""
    db = path if path is not None else db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(db), "head")
    rev = current_revision(db)
    if rev is None:
        raise RuntimeError("alembic upgrade head left database unversioned")
    return rev


def wipe_and_upgrade(path: Path | None = None) -> str:
    """Delete the DB file if present, then upgrade to head."""
    db = path if path is not None else db_path()
    if db.is_file():
        db.unlink()
    return upgrade_to_head(db)


def head_revision() -> str:
    """Return the script-directory head revision id."""
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir()))
    cfg.set_main_option("path_separator", "os")
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected one alembic head, got {heads!r}")
    return heads[0]


__all__ = [
    "HEAD_REVISION",
    "alembic_config",
    "current_revision",
    "head_revision",
    "migrations_dir",
    "sqlite_url",
    "upgrade_to_head",
    "wipe_and_upgrade",
]
