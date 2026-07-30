"""Focused ingest tests (Task 3.1) — demo plugin parser + TXT fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from canhoto import service
from canhoto.core import config as core_config
from canhoto.core import store as core_store
from canhoto.core.models import ClassificationPatch, ParserEntry
from canhoto.core.pdf_text import extract_text
from canhoto.parsers.loader import ParserNotFoundError

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


def test_extract_text_passthrough_for_txt(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("hello\nworld\n", encoding="utf-8")
    assert extract_text(path) == "hello\nworld\n"


def test_ingest_inserts_transactions_and_archives_raw(
    data_home: Path, tmp_path: Path
) -> None:
    _install_demo_parser(data_home, enabled=True)
    statement = _copy_fixture(tmp_path)

    result = service.ingest([statement], root=data_home)

    assert result["ok"] is True
    assert result["file_count"] == 1
    assert result["transaction_count"] == 3
    file_result = result["files"][0]
    assert file_result["ok"] is True
    assert file_result["parser_id"] == "demo_line"
    assert file_result["transaction_count"] == 3
    assert file_result["inserted"] == 3
    assert file_result["updated"] == 0
    assert file_result["content_hash"]
    archived = Path(file_result["archived_path"])
    assert archived.is_file()
    assert archived.parent == (data_home / "raw").resolve()
    assert archived.read_bytes() == statement.read_bytes()

    db = core_config.db_path(data_home)
    txs = core_store.list_transactions(path=db)
    assert len(txs) == 3
    assert {t.merchant_raw for t in txs} == {
        "COFFEE SHOP",
        "PAYROLL",
        "STREAMING",
    }
    assert all(t.source_kind == "account" for t in txs)
    assert all(t.institution == "Demo Bank" for t in txs)

    with core_store.connect(db) as conn:
        stmts = conn.execute("SELECT content_hash FROM statements").fetchall()
        assert len(stmts) == 1
        assert stmts[0]["content_hash"] == file_result["content_hash"]
        links = conn.execute(
            "SELECT COUNT(*) AS n FROM statement_transactions"
        ).fetchone()
        assert int(links["n"]) == 3


def test_reingest_preserves_classification(data_home: Path, tmp_path: Path) -> None:
    _install_demo_parser(data_home, enabled=True)
    statement = _copy_fixture(tmp_path)

    first = service.ingest([statement], root=data_home)
    assert first["ok"] is True
    db = core_config.db_path(data_home)

    coffee_id = "demo_line-2026-07-01-0001"
    core_store.apply_classifications(
        [
            ClassificationPatch(
                id=coffee_id,
                category="Eating",
                kind="expense",
                is_expense=True,
                needs_review=False,
                confidence=0.99,
                review_reason=None,
            )
        ],
        path=db,
    )

    second = service.ingest([statement], root=data_home)
    assert second["ok"] is True
    assert second["files"][0]["updated"] == 3
    assert second["files"][0]["inserted"] == 0

    stored = core_store.get_transaction(coffee_id, path=db)
    assert stored is not None
    assert stored.category == "Eating"
    assert stored.kind == "expense"
    assert stored.needs_review is False
    assert stored.confidence == 0.99
    assert stored.merchant_raw == "COFFEE SHOP"


def test_ingest_fails_clearly_when_no_enabled_parser(
    data_home: Path, tmp_path: Path
) -> None:
    _install_demo_parser(data_home, enabled=False)
    statement = _copy_fixture(tmp_path)

    with pytest.raises(ParserNotFoundError, match="no enabled parser"):
        service.ingest([statement], root=data_home)


def test_ingest_fails_clearly_when_no_parser_matches(
    data_home: Path, tmp_path: Path
) -> None:
    _install_demo_parser(data_home, enabled=True)
    alien = tmp_path / "alien.txt"
    alien.write_text("NOT A DEMO STATEMENT\n2026-07-01 -1.00 X\n", encoding="utf-8")

    with pytest.raises(ParserNotFoundError, match="no enabled parser claimed"):
        service.ingest([alien], root=data_home)


def test_ingest_missing_file_fails_clearly(data_home: Path, tmp_path: Path) -> None:
    _install_demo_parser(data_home, enabled=True)
    missing = tmp_path / "gone.txt"

    with pytest.raises(FileNotFoundError, match="not found"):
        service.ingest([missing], root=data_home)
