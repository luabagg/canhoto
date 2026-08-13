"""Init + doctor service/CLI tests."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from canhoto import service
from canhoto.cli import main as cli_main
from canhoto.core.config import config_path, db_path, load_config
from canhoto.core.models import LedgerTransaction, ParserEntry
from canhoto.core.store import upsert_transactions


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    return root


def _pending_tx(tx_id: str, *, needs_review: bool) -> LedgerTransaction:
    return LedgerTransaction(
        id=tx_id,
        date=date(2026, 7, 1),
        amount_minor=-1000,
        currency="BRL",
        description="x",
        merchant_raw="Shop",
        source_kind="card",
        category="",
        kind="",
        is_expense=True,
        needs_review=needs_review,
        month="2026-07",
    )


def test_init_creates_layout_via_service(data_home: Path) -> None:
    assert not data_home.exists()

    result = service.init()

    assert result["data_dir"] == str(data_home.resolve())
    assert data_home.is_dir()
    for name in ("parsers", "exports", "raw", "fixtures"):
        assert (data_home / name).is_dir()
    assert config_path().is_file()
    assert not db_path().exists()
    assert load_config().parsers == []


def test_doctor_on_fresh_init(data_home: Path) -> None:
    service.init()

    report = service.doctor()

    assert report["data_dir"] == str(data_home.resolve())
    assert report["data_dir_writable"] is True
    assert report["config_present"] is True
    assert report["parsers_enabled"] == 0
    assert report["parsers_disabled"] == 0
    # Doctor is read-only: fresh init has no DB yet.
    assert report["db_openable"] is False
    assert report["pending_review"] == 0
    assert not db_path().exists()
    assert isinstance(report["ok"], bool)
    assert report["ok"] is True
    assert "checks" in report
    assert isinstance(report["checks"], list)
    assert any("db" in c.lower() and c.startswith("skip") for c in report["checks"])


def test_doctor_counts_enabled_disabled_parsers(data_home: Path) -> None:
    service.init()
    cfg = load_config()
    cfg.parsers = [
        ParserEntry(id="a", module="a.py", enabled=True),
        ParserEntry(id="b", module="b.py", enabled=False),
        ParserEntry(id="c", module="c.py", enabled=True),
    ]
    from canhoto.core.config import save_config

    save_config(cfg)

    report = service.doctor()

    assert report["parsers_enabled"] == 2
    assert report["parsers_disabled"] == 1
    assert report["ok"] is True


def test_doctor_pending_review_total(data_home: Path) -> None:
    service.init()
    upsert_transactions(
        [
            _pending_tx("p1", needs_review=True),
            _pending_tx("p2", needs_review=True),
            _pending_tx("ok1", needs_review=False),
        ]
    )

    report = service.doctor()

    assert report["pending_review"] == 2
    assert report["db_openable"] is True
    assert report["ok"] is True


def test_doctor_config_missing(data_home: Path) -> None:
    data_home.mkdir(parents=True)
    (data_home / "parsers").mkdir()
    (data_home / "exports").mkdir()
    (data_home / "raw").mkdir()
    (data_home / "fixtures").mkdir()
    assert not config_path().exists()

    report = service.doctor()

    assert report["config_present"] is False
    assert report["ok"] is False
    assert any("config" in c.lower() for c in report["checks"] if not c.startswith("ok"))


def test_doctor_data_dir_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ro-home"
    root.mkdir()
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    # Make directory non-writable for the current user.
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        report = service.doctor()
        assert report["data_dir_writable"] is False
        assert report["ok"] is False
    finally:
        root.chmod(stat.S_IRWXU)


def test_cli_init_and_doctor_json(
    data_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli_main(["init"]) == 0
    out_init = capsys.readouterr().out
    init_payload = json.loads(out_init)
    assert init_payload["data_dir"] == str(data_home.resolve())
    assert (data_home / "config.json").is_file()

    assert cli_main(["doctor"]) == 0
    out_doc = capsys.readouterr().out
    doc_payload = json.loads(out_doc)
    assert doc_payload["data_dir_writable"] is True
    assert doc_payload["config_present"] is True
    assert doc_payload["parsers_enabled"] == 0
    assert doc_payload["parsers_disabled"] == 0
    assert doc_payload["db_openable"] is False
    assert doc_payload["pending_review"] == 0
    assert doc_payload["ok"] is True


def test_cli_module_main_subprocess(data_home: Path) -> None:
    """Exercise ``python -m canhoto.cli`` without package console scripts."""
    env = os.environ.copy()
    env["CANHOTO_DATA_DIR"] = str(data_home)
    env["PYTHONPATH"] = str(
        Path(__file__).resolve().parents[1] / "src"
    ) + os.pathsep + env.get("PYTHONPATH", "")

    init = subprocess.run(
        [sys.executable, "-m", "canhoto.cli", "init"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert init.returncode == 0, init.stderr
    init_payload = json.loads(init.stdout)
    assert init_payload["data_dir"] == str(data_home.resolve())

    doctor = subprocess.run(
        [sys.executable, "-m", "canhoto.cli", "doctor"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert doctor.returncode == 0, doctor.stderr
    doc_payload = json.loads(doctor.stdout)
    assert doc_payload["ok"] is True
    assert doc_payload["config_present"] is True


def test_doctor_does_not_dump_ledger_or_sql(data_home: Path) -> None:
    service.init()
    upsert_transactions([_pending_tx("secret", needs_review=True)])
    report = service.doctor()
    dumped = json.dumps(report)
    assert "secret" not in dumped
    assert "SELECT" not in dumped.upper()
    assert "description" not in dumped
    assert "merchant_raw" not in dumped
