"""Data-dir layout and plugin-aware config.json I/O.

Resolves ``CANHOTO_DATA_DIR`` or ``~/.canhoto``. No Google/Sheets fields, no
legacy finance paths, and no SQLite open here (store lands in the next task).
"""

from __future__ import annotations

import os
from pathlib import Path

from canhoto.core.models import AppConfig

_ENV_DATA_DIR = "CANHOTO_DATA_DIR"
_DEFAULT_DIRNAME = ".canhoto"
_CONFIG_NAME = "config.json"
_DB_NAME = "canhoto.db"
_SUBDIRS = ("parsers", "exports", "raw", "fixtures")


def get_data_dir() -> Path:
    """Return the configured data directory path (may not exist yet)."""
    override = os.environ.get(_ENV_DATA_DIR)
    if override:
        return Path(override).expanduser()
    return Path.home() / _DEFAULT_DIRNAME


def config_path(root: Path | None = None) -> Path:
    return (root if root is not None else get_data_dir()) / _CONFIG_NAME


def db_path(root: Path | None = None) -> Path:
    """Reserved SQLite path. File is not created by layout init."""
    return (root if root is not None else get_data_dir()) / _DB_NAME


def init_data_dir(root: Path | None = None) -> Path:
    """Create data-dir layout and default config.json if missing.

    Creates ``parsers/``, ``exports/``, ``raw/``, ``fixtures/``, and
    ``config.json``. Does not create the database file.
    """
    path = (root if root is not None else get_data_dir()).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    for name in _SUBDIRS:
        (path / name).mkdir(exist_ok=True)

    cfg_file = config_path(path)
    if not cfg_file.exists():
        save_config(_default_config(path), root=path)
    return path


def load_config(root: Path | None = None) -> AppConfig:
    """Load config.json, writing defaults when the file is absent."""
    path = (root if root is not None else get_data_dir()).expanduser()
    cfg_file = config_path(path)
    if not cfg_file.exists():
        cfg = _default_config(path)
        save_config(cfg, root=path)
        return cfg
    return AppConfig.model_validate_json(cfg_file.read_text(encoding="utf-8"))


def save_config(cfg: AppConfig, root: Path | None = None) -> AppConfig:
    """Persist config.json (plugin registry + agent_view). Returns ``cfg``."""
    path = (root if root is not None else get_data_dir()).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    cfg_file = config_path(path)
    # Ensure data_dir in the document matches the active root.
    to_write = cfg
    resolved = str(path.resolve())
    if cfg.data_dir != resolved:
        to_write = cfg.model_copy(update={"data_dir": resolved})
    cfg_file.write_text(
        to_write.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return to_write


def _default_config(root: Path) -> AppConfig:
    return AppConfig(data_dir=str(root.resolve()))
