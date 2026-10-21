"""Uploaded statements land in the data directory before ingest."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from canhoto import service
from canhoto.core.config import init_data_dir

_REPO = Path(__file__).resolve().parents[1]
_DEMO = _REPO / "examples" / "parsers" / "demo_line_parser.py"
_FIXTURE = _REPO / "examples" / "parsers" / "fixtures" / "demo_statement.txt"


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    init_data_dir(root)
    return root


def test_receive_statements_stores_hash_name_and_ingests(data_home: Path) -> None:
    _enable_demo(data_home)
    content = _FIXTURE.read_bytes()

    payload = service.receive_statements([("../../secret.txt", content)])

    assert payload["transaction_count"] == 3
    assert payload["original_names"] == ["secret.txt"]
    staged = Path(payload["files"][0]["path"])
    assert staged.parent == (data_home / "inbox").resolve()
    assert staged.name.endswith(".txt")
    assert staged.name != "secret.txt"
    assert staged.read_bytes() == content
    archived = Path(payload["files"][0]["archived_path"])
    assert archived.parent == (data_home / "raw").resolve()


def test_receive_statements_rejects_other_suffixes(data_home: Path) -> None:
    with pytest.raises(ValueError, match="pdf or .txt"):
        service.receive_statements([("parser.py", b"print(1)\n")])
    assert list((data_home / "inbox").iterdir()) == []


def test_receive_statements_rejects_empty_file(data_home: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        service.receive_statements([("empty.txt", b"")])


def _enable_demo(data_home: Path) -> None:
    from canhoto.core.config import load_config, save_config
    from canhoto.core.models import ParserEntry

    shutil.copy2(_DEMO, data_home / "parsers" / "demo_line_parser.py")
    cfg = load_config(data_home)
    entry = ParserEntry(
        id="demo_line",
        module="demo_line_parser.py",
        enabled=True,
        last_test_ok=True,
        last_test_at="2026-07-29T00:00:00Z",
    )
    save_config(cfg.model_copy(update={"parsers": [entry]}), root=data_home)
