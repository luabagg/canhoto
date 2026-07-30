"""Service façade for CLI/MCP adapters.

Thin orchestration over core config + store. No parser loader, no Sheets,
no raw SQL exposure, no unbounded ledger dumps.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from canhoto.core import config as core_config
from canhoto.core import store as core_store


def init(root: Path | None = None) -> dict[str, Any]:
    """Create data-dir layout and default config. Does not require parsers."""
    path = core_config.init_data_dir(root)
    return {
        "data_dir": str(path.resolve()),
        "config_path": str(core_config.config_path(path)),
        "db_path": str(core_config.db_path(path)),
    }


def doctor(root: Path | None = None) -> dict[str, Any]:
    """Return a JSON-serializable health report for the active data dir.

    Checks: data root writable, config present, enabled/disabled parser
    counts, database openability, pending-review total. Never returns
    ledger rows or SQL.
    """
    data_dir = (root if root is not None else core_config.get_data_dir()).expanduser()
    checks: list[str] = []
    ok = True

    writable = _is_writable(data_dir)
    if writable:
        checks.append("ok: data_dir_writable")
    else:
        ok = False
        checks.append("error: data_dir_not_writable")

    cfg_file = core_config.config_path(data_dir)
    config_present = cfg_file.is_file()
    if config_present:
        checks.append("ok: config_present")
    else:
        ok = False
        checks.append("error: config_missing")

    parsers_enabled = 0
    parsers_disabled = 0
    if config_present:
        try:
            cfg = core_config.load_config(data_dir)
            for entry in cfg.parsers:
                if entry.enabled:
                    parsers_enabled += 1
                else:
                    parsers_disabled += 1
            checks.append(
                f"ok: parsers enabled={parsers_enabled} disabled={parsers_disabled}"
            )
        except Exception as exc:  # noqa: BLE001 — report, do not raise
            ok = False
            checks.append(f"error: config_unreadable ({type(exc).__name__})")
    else:
        checks.append("skip: parsers (no config)")

    db_file = core_config.db_path(data_dir)
    db_openable = False
    pending_review = 0
    if writable:
        try:
            core_store.ensure_schema(db_file)
            # Prove a real read works after schema ensure.
            with core_store.connect(db_file) as conn:
                conn.execute("SELECT 1").fetchone()
            db_openable = True
            pending_review = core_store.count_pending_review(path=db_file)
            checks.append("ok: db_openable")
            checks.append(f"ok: pending_review={pending_review}")
        except (OSError, sqlite3.Error) as exc:
            ok = False
            checks.append(f"error: db_not_openable ({type(exc).__name__})")
    else:
        ok = False
        checks.append("skip: db (data_dir not writable)")

    return {
        "ok": ok,
        "data_dir": str(data_dir.resolve()) if data_dir.exists() else str(data_dir),
        "data_dir_writable": writable,
        "config_present": config_present,
        "config_path": str(cfg_file),
        "db_path": str(db_file),
        "parsers_enabled": parsers_enabled,
        "parsers_disabled": parsers_disabled,
        "db_openable": db_openable,
        "pending_review": pending_review,
        "checks": checks,
    }


def _is_writable(path: Path) -> bool:
    """Return True if ``path`` exists (or can be created) and is writable."""
    try:
        if path.exists():
            if not path.is_dir():
                return False
            return os.access(path, os.W_OK | os.X_OK)
        # Parent must allow creating the data dir.
        parent = path.parent
        return parent.exists() and os.access(parent, os.W_OK | os.X_OK)
    except OSError:
        return False
