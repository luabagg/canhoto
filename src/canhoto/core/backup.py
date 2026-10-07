"""Back up a data dir to one ``.canhoto`` file and restore it.

A ``.canhoto`` file is a zip archive:

- ``manifest.json``: format, versions, schema revision, row counts, and a
  SHA-256 checksum for every other member.
- ``canhoto.sql``: a plain SQL dump of ``canhoto.db`` (schema and rows).
- ``config.json``: settings and the parser registry.
- ``parsers/*.py``: user parser modules.

Raw statements are never included. Restore verifies every checksum and the
schema revision before it writes anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from canhoto.core import config as core_config
from canhoto.core import migrate
from canhoto.core.models import AppConfig

FORMAT = "canhoto-backup"
FORMAT_VERSION = 1
FILE_SUFFIX = ".canhoto"

_MANIFEST = "manifest.json"
_SQL = "canhoto.sql"
_CONFIG = "config.json"
_PARSER_MEMBER = re.compile(r"^parsers/([^/\\:]*\.py)$")
_COUNTED_TABLES = ("transactions", "statements", "user_rules", "merchant_category_map")


def write_backup(data_dir: Path, dest: Path) -> dict[str, Any]:
    """Write ``dest`` and return its manifest. Never overwrites a file."""
    db_file = core_config.db_path(data_dir)
    if not db_file.is_file():
        raise FileNotFoundError(f"no ledger to back up at {db_file}")
    cfg = core_config.load_config(data_dir)

    sql, counts = _dump_database(db_file)
    members: dict[str, bytes] = {
        _SQL: sql.encode("utf-8"),
        _CONFIG: core_config.config_path(data_dir).read_bytes(),
    }
    parsers_root = data_dir / cfg.parsers_dir
    for module in sorted(parsers_root.glob("*.py")):
        name = f"parsers/{module.name}"
        if not _PARSER_MEMBER.fullmatch(name):
            raise ValueError(f"parser filename is not portable: {module.name!r}")
        members[name] = module.read_bytes()

    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "canhoto_version": version("canhoto"),
        "schema_revision": migrate.current_revision(db_file),
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": counts,
        "files": {name: _sha256(content) for name, content in members.items()},
    }
    with zipfile.ZipFile(dest, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_MANIFEST, json.dumps(manifest, indent=2) + "\n")
        for name, content in members.items():
            archive.writestr(name, content)
    return manifest


def restore_backup(src: Path, data_dir: Path) -> dict[str, Any]:
    """Install a complete restore into a new or empty directory. Reject directory links."""
    manifest, members = _read_verified(src)
    cfg = AppConfig.model_validate_json(members[_CONFIG]).model_copy(
        update={"data_dir": str(data_dir.resolve()), "parsers_dir": "parsers"}
    )
    _require_empty_destination(data_dir)
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{data_dir.name}-restore-", dir=data_dir.parent) as temporary:
        staging = Path(temporary)
        _prepare_restore(staging, members, manifest, cfg)
        _require_empty_destination(data_dir)
        if data_dir.exists():
            data_dir.rmdir()
        os.rename(staging, data_dir)
    return manifest


def _require_empty_destination(data_dir: Path) -> None:
    if data_dir.is_symlink():
        raise FileExistsError(f"refusing to restore into a directory link at {data_dir}")
    if data_dir.exists() and (not data_dir.is_dir() or any(data_dir.iterdir())):
        raise FileExistsError(f"restore requires a new or empty directory: {data_dir}")


def _prepare_restore(
    staging: Path, members: dict[str, bytes], manifest: dict[str, Any], cfg: AppConfig
) -> None:
    core_config.init_data_dir(staging)
    db_file = core_config.db_path(staging)
    with closing(sqlite3.connect(db_file)) as conn:
        conn.executescript(members[_SQL].decode("utf-8"))
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("backup database failed its integrity check")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("backup database contains invalid references")
    if migrate.current_revision(db_file) != manifest["schema_revision"]:
        raise ValueError("backup database revision does not match its manifest")
    migrate.upgrade_to_head(db_file)

    core_config.config_path(staging).write_text(
        cfg.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    for name, content in members.items():
        if match := _PARSER_MEMBER.fullmatch(name):
            (staging / "parsers" / match.group(1)).write_bytes(content)


def _dump_database(db_file: Path) -> tuple[str, dict[str, int]]:
    """Dump a consistent snapshot: copy to memory first, then iterdump the copy."""
    snapshot = sqlite3.connect(":memory:")
    try:
        with sqlite3.connect(db_file) as live:
            live.backup(snapshot)
        live.close()
        counts = {
            table: snapshot.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in _COUNTED_TABLES
        }
        return "\n".join(snapshot.iterdump()) + "\n", counts
    finally:
        snapshot.close()


def _read_verified(src: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    with zipfile.ZipFile(src) as archive:
        names = set(archive.namelist())
        if _MANIFEST not in names:
            raise ValueError(f"{src} is not a canhoto backup: no {_MANIFEST}")
        manifest = json.loads(archive.read(_MANIFEST))
        if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
            raise ValueError(
                f"unsupported backup format {manifest.get('format')!r} "
                f"v{manifest.get('format_version')!r}"
            )
        listed: dict[str, str] = manifest["files"]
        unlisted = sorted(names - {_MANIFEST} - set(listed))
        if unlisted:
            raise ValueError(f"backup has files not in manifest: {', '.join(unlisted)}")
        missing = sorted(({_SQL, _CONFIG} | set(listed)) - names)
        if missing:
            raise ValueError(f"backup is missing files: {', '.join(missing)}")
        allowed = {_SQL, _CONFIG}
        unexpected = sorted(
            name for name in listed if name not in allowed and not _PARSER_MEMBER.fullmatch(name)
        )
        if unexpected:
            raise ValueError(f"backup has unexpected files: {', '.join(unexpected)}")
        members = {name: archive.read(name) for name in listed}

    for name, content in members.items():
        if _sha256(content) != listed[name]:
            raise ValueError(f"checksum mismatch for {name}: the backup is damaged or edited")
    revision = manifest.get("schema_revision")
    if revision not in migrate.known_revisions():
        raise ValueError(
            f"backup schema revision {revision!r} is unknown to canhoto {version('canhoto')}; "
            "upgrade canhoto first"
        )
    return manifest, members


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


__all__ = ["FILE_SUFFIX", "FORMAT", "FORMAT_VERSION", "restore_backup", "write_backup"]
