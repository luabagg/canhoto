"""Ledger configuration and user-wide currency defaults.

Ledger saves retain declared overrides, not inherited global defaults.
SQLite open and migration stay in ``store`` and ``migrate``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from canhoto.core.models import AppConfig, GlobalConfig, normalize_currency_code

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
    """Load declared settings, writing defaults when the file is absent."""
    path = (root if root is not None else get_data_dir()).expanduser()
    cfg = _read_config(path)
    if not config_path(path).exists():
        save_config(cfg, root=path)
    return cfg


def _read_config(root: Path | None = None) -> AppConfig:
    path = (root if root is not None else get_data_dir()).expanduser()
    cfg_file = config_path(path)
    if not cfg_file.exists():
        return _default_config(path)
    return AppConfig.model_validate_json(cfg_file.read_text(encoding="utf-8"))


def save_config(cfg: AppConfig, root: Path | None = None) -> AppConfig:
    """Persist config.json (plugin registry + agent_view). Returns ``cfg``."""
    path = (root if root is not None else get_data_dir()).expanduser()
    cfg_file = config_path(path)
    # Ensure data_dir in the document matches the active root.
    to_write = cfg
    resolved = str(path.resolve())
    if cfg.data_dir != resolved:
        to_write = cfg.model_copy(update={"data_dir": resolved})
    _write_config(cfg_file, to_write.model_dump_json(indent=2) + "\n")
    return to_write


def global_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    if not base.is_absolute():
        base = Path.home() / ".config"
    return base / "canhoto" / _CONFIG_NAME


def _read_global_config() -> GlobalConfig:
    path = global_config_path()
    if not path.exists():
        return GlobalConfig()
    return GlobalConfig.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_currency(root: Path | None = None, *, override: str | None = None) -> str:
    if override is not None:
        return normalize_currency_code(override)
    local = _read_config(root).currency
    if local is not None:
        return local
    return _read_global_config().currency or "BRL"


def get_config_value(
    key: str, *, global_scope: bool = False, root: Path | None = None
) -> str | None:
    _check_key(key)
    if global_scope:
        return _read_global_config().currency
    return resolve_currency(root)


def set_config_value(
    key: str, value: str, *, global_scope: bool = False, root: Path | None = None
) -> str:
    _check_key(key)
    currency = normalize_currency_code(value)
    if global_scope:
        cfg = _read_global_config().model_copy(update={"currency": currency})
        _write_config(global_config_path(), cfg.model_dump_json(indent=2, exclude_none=True) + "\n")
    else:
        local = _read_config(root).model_copy(update={"currency": currency})
        save_config(local, root=root)
    return currency


def unset_config_value(
    key: str, *, global_scope: bool = False, root: Path | None = None
) -> bool:
    _check_key(key)
    if global_scope:
        cfg = _read_global_config()
        if cfg.currency is None:
            return False
        cfg = cfg.model_copy(update={"currency": None})
        _write_config(global_config_path(), cfg.model_dump_json(indent=2, exclude_none=True) + "\n")
    else:
        local = _read_config(root)
        if local.currency is None:
            return False
        save_config(local.model_copy(update={"currency": None}), root=root)
    return True


def _check_key(key: str) -> None:
    if key != "currency":
        raise ValueError(f"unknown config key {key!r}; supported key: currency")


def _write_config(path: Path, content: str) -> None:
    """Replace complete config files. A failed write preserves the previous file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _default_config(root: Path) -> AppConfig:
    return AppConfig(data_dir=str(root.resolve()))
