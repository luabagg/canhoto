"""Backup and restore of a data dir as one .canhoto file."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

import pytest
from canhoto import service
from canhoto.cli import main as cli_main
from canhoto.core import backup as core_backup
from canhoto.core import config as core_config
from canhoto.core import migrate
from canhoto.core.models import LedgerTransaction
from canhoto.core.store import ensure_schema, get_transaction, upsert_transactions
from canhoto.mcp.allowlist import MCP_TOOL_ALLOWLIST, MCP_TOOL_DENYLIST

_PARSER_SOURCE = "def register():\n    return None\n"


def _seed(root: Path) -> None:
    core_config.init_data_dir(root)
    cfg = core_config.load_config(root)
    core_config.save_config(cfg.model_copy(update={"own_name_markers": ["ACME OWNER"]}), root=root)
    (root / "parsers" / "my_bank.py").write_text(_PARSER_SOURCE, encoding="utf-8")
    (root / "raw" / "statement.pdf").write_bytes(b"%PDF-1.4 private statement")
    db = core_config.db_path(root)
    ensure_schema(db)
    upsert_transactions(
        [
            LedgerTransaction(
                id="t1",
                date=date(2026, 9, 5),
                amount_minor=-1234,
                currency="BRL",
                description='Café "São" João, 1/3',
                merchant_raw="Café São João",
                merchant_normalized="Café São João",
                source_kind="card",
                category="Restaurants",
                kind="expense",
                is_expense=True,
                needs_review=False,
                month="2026-09",
                metadata={"purchase_date": "2026-09-05"},
            )
        ],
        path=db,
    )
    service.rule_add(
        pattern="PIX ENVIADO LANDLORD",
        category="Housing",
        kind="expense",
        direction="out",
        note="Rent",
        root=root,
    )
    service.set_merchant_category("Café São João", "Restaurants", root=root)


def _table_rows(db: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(db) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            t: sorted(conn.execute(f'SELECT * FROM "{t}"').fetchall(), key=repr) for t in tables
        }


def test_backup_round_trip_restores_ledger_rules_config_and_parsers(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"

    result = service.backup(output=backup_file, root=source)
    assert result["ok"] is True
    restored = service.restore(backup_file, root=target)

    assert restored["ok"] is True
    assert _table_rows(core_config.db_path(target)) == _table_rows(core_config.db_path(source))
    assert (target / "parsers" / "my_bank.py").read_text(encoding="utf-8") == _PARSER_SOURCE
    cfg = core_config.load_config(target)
    assert cfg.own_name_markers == ["ACME OWNER"]
    assert cfg.data_dir == str(target.resolve())


def test_backup_restores_local_currency_override_without_changing_global_config(
    tmp_path: Path,
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    core_config.set_config_value("currency", "EUR", root=source)
    core_config.set_config_value("currency", "USD", global_scope=True)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)

    service.restore(backup_file, root=target)

    assert core_config.resolve_currency(target) == "EUR"
    assert core_config.get_config_value("currency", global_scope=True) == "USD"
    restored = get_transaction("t1", path=core_config.db_path(target))
    assert restored is not None
    assert restored.currency == "BRL"


def test_backup_does_not_freeze_inherited_global_currency(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    core_config.set_config_value("currency", "EUR", global_scope=True)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    core_config.set_config_value("currency", "USD", global_scope=True)

    service.restore(backup_file, root=target)

    assert core_config.load_config(target).currency is None
    assert core_config.resolve_currency(target) == "USD"
    restored = get_transaction("t1", path=core_config.db_path(target))
    assert restored is not None
    assert restored.currency == "BRL"


def test_backup_is_a_zip_with_manifest_and_no_statements(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)

    with zipfile.ZipFile(backup_file) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        sql = archive.read("canhoto.sql").decode("utf-8")
    assert names == {"manifest.json", "canhoto.sql", "config.json", "parsers/my_bank.py"}
    assert manifest["format"] == "canhoto-backup"
    assert manifest["schema_revision"] == migrate.HEAD_REVISION
    assert set(manifest["files"]) == names - {"manifest.json"}
    assert "CREATE TABLE" in sql
    assert "Café" in sql


def test_backup_refuses_to_overwrite_a_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    backup_file.write_bytes(b"keep me")

    with pytest.raises(FileExistsError):
        service.backup(output=backup_file, root=source)
    assert backup_file.read_bytes() == b"keep me"


def test_restore_refuses_a_data_dir_that_has_a_ledger(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)

    with pytest.raises(FileExistsError):
        service.restore(backup_file, root=source)


def _rewrite(backup_file: Path, dest: Path, **changes: bytes) -> None:
    with zipfile.ZipFile(backup_file) as src, zipfile.ZipFile(dest, "w") as out:
        for name in src.namelist():
            out.writestr(name, changes.pop(name, src.read(name)))
        for name, content in changes.items():
            out.writestr(name, content)


def test_restore_refuses_a_file_whose_content_changed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    tampered = tmp_path / "tampered.canhoto"
    _rewrite(backup_file, tampered, **{"canhoto.sql": b"DROP TABLE transactions;"})

    with pytest.raises(ValueError, match="checksum"):
        service.restore(tampered, root=tmp_path / "target")
    assert not core_config.db_path(tmp_path / "target").exists()


def test_restore_refuses_files_the_manifest_does_not_list(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    extra = tmp_path / "extra.canhoto"
    _rewrite(backup_file, extra, **{"../escape.py": b"print('x')"})

    with pytest.raises(ValueError, match="not in manifest"):
        service.restore(extra, root=tmp_path / "target")
    assert not (tmp_path / "escape.py").exists()


def test_restore_refuses_a_schema_this_version_does_not_know(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    with zipfile.ZipFile(backup_file) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["schema_revision"] = "999_from_the_future"
    newer = tmp_path / "newer.canhoto"
    _rewrite(backup_file, newer, **{"manifest.json": json.dumps(manifest).encode()})

    with pytest.raises(ValueError, match="schema revision"):
        service.restore(newer, root=tmp_path / "target")


def test_cli_backup_and_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"

    monkeypatch.setenv("CANHOTO_DATA_DIR", str(source))
    assert cli_main(["backup", "--output", str(backup_file)]) == 0
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(target))
    assert cli_main(["restore", str(backup_file)]) == 0
    out = capsys.readouterr().out
    assert '"schema_revision"' in out
    assert core_config.db_path(target).is_file()


def test_restore_preserves_unrelated_staging_file(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    target.mkdir()
    sentinel = target / "canhoto.db.restoring"
    sentinel.write_bytes(b"unrelated data")

    with pytest.raises(FileExistsError):
        service.restore(backup_file, root=target)

    assert sentinel.read_bytes() == b"unrelated data"
    assert not core_config.db_path(target).exists()


@pytest.mark.parametrize("existing", ["config", "config_link", "directory_link"])
def test_restore_preserves_existing_config_and_links(tmp_path: Path, existing: str) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_bytes(b"unrelated data")
    if existing == "directory_link":
        target.symlink_to(external, target_is_directory=True)
    else:
        target.mkdir()
        config_file = target / "config.json"
        if existing == "config_link":
            config_file.symlink_to(sentinel)
        else:
            config_file.write_bytes(b"existing settings")

    with pytest.raises(FileExistsError):
        service.restore(backup_file, root=target)

    assert sentinel.read_bytes() == b"unrelated data"
    assert not core_config.db_path(target).exists()
    if existing == "config":
        assert (target / "config.json").read_bytes() == b"existing settings"


@pytest.mark.parametrize("failure", ["migration", "config", "parser", "installation"])
def test_failed_restore_does_not_publish_files_and_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("injected restore failure")

    with monkeypatch.context() as patch:
        if failure == "migration":
            patch.setattr(core_backup.migrate, "upgrade_to_head", fail)
        elif failure == "config":
            patch.setattr(core_config, "save_config", fail)
        elif failure == "parser":
            write_bytes = Path.write_bytes

            def fail_parser(path: Path, data: bytes) -> int:
                if path.name == "my_bank.py":
                    raise OSError("injected restore failure")
                return write_bytes(path, data)

            patch.setattr(Path, "write_bytes", fail_parser)
        else:
            patch.setattr(core_backup.os, "rename", fail)
        with pytest.raises(OSError, match="injected restore failure"):
            service.restore(backup_file, root=target)

    assert not target.exists()
    assert not list(tmp_path.glob(".target-restore-*"))
    assert service.restore(backup_file, root=target)["ok"] is True
    assert _table_rows(core_config.db_path(target)) == _table_rows(core_config.db_path(source))


@pytest.mark.parametrize("filename", ["my-bank.py", "café helpers.py"])
def test_backup_restores_safe_parser_filenames(tmp_path: Path, filename: str) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    (source / "parsers" / filename).write_text(_PARSER_SOURCE, encoding="utf-8")
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)

    assert service.restore(backup_file, root=target)["ok"] is True
    assert (target / "parsers" / filename).read_text(encoding="utf-8") == _PARSER_SOURCE


def test_restore_rejects_listed_parser_paths_that_escape_the_directory(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    with zipfile.ZipFile(backup_file) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["files"]["parsers/../escape.py"] = manifest["files"]["parsers/my_bank.py"]
    unsafe = tmp_path / "unsafe.canhoto"
    _rewrite(
        backup_file, unsafe,
        **{"manifest.json": json.dumps(manifest).encode(),
           "parsers/../escape.py": _PARSER_SOURCE.encode()},
    )

    with pytest.raises(ValueError, match="unexpected files"):
        service.restore(unsafe, root=target)

    assert not target.exists()
    assert not (tmp_path / "escape.py").exists()


def test_restore_refuses_a_database_revision_that_disagrees_with_manifest(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    with zipfile.ZipFile(backup_file) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    manifest["schema_revision"] = "001_initial"
    inconsistent = tmp_path / "inconsistent.canhoto"
    _rewrite(backup_file, inconsistent, **{"manifest.json": json.dumps(manifest).encode()})

    with pytest.raises(ValueError, match="revision does not match"):
        service.restore(inconsistent, root=target)

    assert not target.exists()


def test_restore_refuses_invalid_statement_references(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    with sqlite3.connect(core_config.db_path(source)) as conn:
        conn.execute("INSERT INTO statement_transactions VALUES ('missing', 'missing')")
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)

    with pytest.raises(ValueError, match="invalid references"):
        service.restore(backup_file, root=target)

    assert not target.exists()


def test_restore_into_existing_empty_directory(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)
    target.mkdir()

    assert service.restore(backup_file, root=target)["ok"] is True
    assert core_config.db_path(target).is_file()


def test_restore_keeps_custom_parser_location_inside_destination(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    _seed(source)
    external = tmp_path / "external-parsers"
    external.mkdir()
    original = external / "my_bank.py"
    original.write_text(_PARSER_SOURCE, encoding="utf-8")
    cfg = core_config.load_config(source)
    core_config.save_config(cfg.model_copy(update={"parsers_dir": str(external)}), root=source)
    backup_file = tmp_path / "home.canhoto"
    service.backup(output=backup_file, root=source)

    assert service.restore(backup_file, root=target)["ok"] is True
    restored_cfg = core_config.load_config(target)
    assert restored_cfg.parsers_dir == "parsers"
    assert (target / "parsers" / "my_bank.py").read_text(encoding="utf-8") == _PARSER_SOURCE
    assert original.read_text(encoding="utf-8") == _PARSER_SOURCE


def test_backup_and_restore_stay_out_of_mcp() -> None:
    """A backup is a full ledger dump; agents must never get one."""
    assert {"backup", "restore"} <= MCP_TOOL_DENYLIST
    assert not {"backup", "restore"} & MCP_TOOL_ALLOWLIST
