"""Focused summary PDF export tests (Task 6.1)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from canhoto import service
from canhoto.cli import main as cli_main
from canhoto.core import config as core_config
from canhoto.core.models import LedgerTransaction, MonthBreakdown
from canhoto.core.store import ensure_schema, upsert_transactions
from canhoto.mcp.server import create_server


@pytest.fixture
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canhoto-home"
    monkeypatch.setenv("CANHOTO_DATA_DIR", str(root))
    core_config.init_data_dir(root)
    return root


def _seed_month(root: Path, month: str = "2026-06") -> None:
    db = core_config.db_path(root)
    ensure_schema(db)
    upsert_transactions(
        [
            LedgerTransaction(
                id="e1",
                date=date(2026, 6, 5),
                amount_minor=-5000,
                currency="BRL",
                description="Cafe",
                merchant_raw="Cafe",
                merchant_normalized="CAFE",
                source_kind="card",
                category="Eating",
                kind="expense",
                is_expense=True,
                needs_review=False,
                month=month,
            ),
            LedgerTransaction(
                id="i1",
                date=date(2026, 6, 1),
                amount_minor=10000,
                currency="BRL",
                description="Salary",
                merchant_raw="Salary",
                merchant_normalized="SALARY",
                source_kind="account",
                category="Income",
                kind="income",
                is_expense=False,
                needs_review=False,
                month=month,
            ),
        ],
        path=db,
    )


def test_export_pdf_writes_nonempty_file_under_exports(data_home: Path) -> None:
    _seed_month(data_home)
    result = service.export_pdf("2026-06", root=data_home)
    assert result["ok"] is True
    out = Path(result["path"])
    assert out.is_file()
    assert out.stat().st_size > 0
    assert result["size"] == out.stat().st_size
    exports = (data_home / "exports").resolve()
    assert out.resolve() == (exports / "2026-06-summary.pdf").resolve()
    assert exports in out.resolve().parents or out.resolve().parent == exports


def test_export_pdf_path_confined_to_exports(data_home: Path) -> None:
    _seed_month(data_home)
    result = service.export_pdf("2026-06", root=data_home)
    out = Path(result["path"]).resolve()
    exports = (data_home / "exports").resolve()
    assert out.is_relative_to(exports)


def test_export_pdf_requires_valid_month(data_home: Path) -> None:
    with pytest.raises(ValueError):
        service.export_pdf("not-a-month", root=data_home)


def test_cli_export_pdf(data_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_month(data_home)
    code = cli_main(["export", "pdf", "2026-06"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert Path(payload["path"]).is_file()


def test_mcp_export_pdf_no_longer_stub(data_home: Path) -> None:
    import asyncio

    _seed_month(data_home)
    server = create_server()
    result = asyncio.run(server.call_tool("export_pdf", {"month": "2026-06"}))
    assert result.is_error is False
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict):
        payload = sc
    else:
        parts: list[str] = []
        for item in getattr(result, "content", None) or []:
            t = getattr(item, "text", None)
            if t is not None:
                parts.append(str(t))
        payload = json.loads("\n".join(parts))
    assert payload.get("error") != "export_pdf_not_ready"
    assert payload["ok"] is True
    assert Path(payload["path"]).is_file()


def test_pdf_summary_contains_metrics_not_tx_table(data_home: Path) -> None:
    _seed_month(data_home)
    result = service.export_pdf("2026-06", root=data_home)
    # lightweight content check via pymupdf text extract
    from canhoto.core.pdf_text import extract_text

    text = extract_text(Path(result["path"]))
    assert "2026-06" in text
    assert "Eating" in text or "expenses" in text.lower() or "Expenses" in text
    # must not dump raw transaction ids as a full ledger table
    assert "e1" not in text
