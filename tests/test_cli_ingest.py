"""Focused CLI tests for ingest."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from canhoto.cli import main as cli_main
from canhoto.core import config as core_config
from canhoto.core import store as core_store
from canhoto.core.models import ParserEntry

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_PARSER = _REPO_ROOT / "examples" / "parsers" / "demo_line_parser.py"
_DEMO_FIXTURE = (
    _REPO_ROOT / "examples" / "parsers" / "fixtures" / "demo_statement.txt"
)


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    core_config.init_data_dir(root)
    return root


def _install_demo_parser(data_home: Path, *, enabled: bool = True) -> None:
    assert _DEMO_PARSER.is_file(), f"missing demo parser: {_DEMO_PARSER}"
    dest = data_home / "parsers" / "demo_line_parser.py"
    shutil.copy2(_DEMO_PARSER, dest)
    cfg = core_config.load_config(data_home)
    entry = ParserEntry(
        id="demo_line",
        module="demo_line_parser.py",
        enabled=enabled,
        last_test_ok=True if enabled else None,
        last_test_at="2026-07-29T00:00:00Z" if enabled else None,
        last_test_error=None,
    )
    core_config.save_config(
        cfg.model_copy(update={"parsers": [entry]}), root=data_home
    )


def _copy_fixture(tmp_path: Path) -> Path:
    assert _DEMO_FIXTURE.is_file(), f"missing fixture: {_DEMO_FIXTURE}"
    dest = tmp_path / "demo_statement.txt"
    shutil.copy2(_DEMO_FIXTURE, dest)
    return dest


def test_cli_ingest_writes_ledger(
    data_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_demo_parser(data_home, enabled=True)
    statement = _copy_fixture(tmp_path)

    assert cli_main(["ingest", str(statement)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["file_count"] == 1
    assert payload["transaction_count"] == 3
    assert payload["files"][0]["parser_id"] == "demo_line"
    assert payload["files"][0]["inserted"] == 3

    db = core_config.db_path(data_home)
    assert db.is_file()
    txs = core_store.list_transactions(path=db)
    assert len(txs) == 3
    assert {t.merchant_raw for t in txs} == {
        "COFFEE SHOP",
        "PAYROLL",
        "STREAMING",
    }
    archived = Path(payload["files"][0]["archived_path"])
    assert archived.is_file()
    assert archived.parent == (data_home / "raw").resolve()
