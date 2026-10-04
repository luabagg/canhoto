"""Summary PDF export tests."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from canhoto import service
from canhoto.cli import main as cli_main
from canhoto.core import config as core_config
from canhoto.core.models import LedgerTransaction, ReportBundle
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
    assert result["profile"] == "canhoto"
    exports = (data_home / "exports").resolve()
    assert out.resolve() == (exports / "2026-06-summary.pdf").resolve()
    assert exports in out.resolve().parents or out.resolve().parent == exports


def test_export_pdf_path_confined_to_exports(data_home: Path) -> None:
    _seed_month(data_home)
    result = service.export_pdf("2026-06", root=data_home)
    out = Path(result["path"]).resolve()
    exports = (data_home / "exports").resolve()
    assert out.is_relative_to(exports)


def test_export_pdf_custom_output(data_home: Path, tmp_path: Path) -> None:
    _seed_month(data_home)
    custom = tmp_path / "reports" / "my-summary.pdf"
    result = service.export_pdf("2026-06", output=custom, root=data_home)
    assert result["ok"] is True
    assert Path(result["path"]).resolve() == custom.resolve()


def test_export_pdf_canhoto_profile(data_home: Path, tmp_path: Path) -> None:
    _seed_month(data_home)
    custom = tmp_path / "canhoto.pdf"
    result = service.export_pdf(
        "2026-06", output=custom, profile="canhoto", root=data_home
    )
    assert result["profile"] == "canhoto"
    assert custom.is_file()


def test_export_pdf_modern_profile(data_home: Path, tmp_path: Path) -> None:
    _seed_month(data_home)
    custom = tmp_path / "modern.pdf"
    result = service.export_pdf(
        "2026-06", output=custom, profile="modern", root=data_home
    )
    assert result["profile"] == "modern"
    assert custom.is_file()


def test_export_pdf_minimal_profile(data_home: Path, tmp_path: Path) -> None:
    _seed_month(data_home)
    custom = tmp_path / "minimal.pdf"
    result = service.export_pdf(
        "2026-06", output=custom, profile="minimal", root=data_home
    )
    assert result["profile"] == "minimal"
    assert custom.is_file()


def test_export_pdf_rejects_unknown_profile(data_home: Path) -> None:
    _seed_month(data_home)
    with pytest.raises(ValueError, match="unknown PDF profile"):
        service.export_pdf("2026-06", profile="custom", root=data_home)


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


def test_cli_export_pdf_modern_profile(
    data_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_month(data_home)
    custom = tmp_path / "modern-cli.pdf"
    code = cli_main(
        ["export", "pdf", "2026-06", "--profile", "modern", "--output", str(custom)]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "modern"
    assert Path(payload["path"]).resolve() == custom.resolve()


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


def test_export_pdf_does_not_create_footer_only_page(data_home: Path) -> None:
    import fitz

    _seed_month(data_home)
    result = service.export_pdf("2026-06", profile="modern", root=data_home)
    document = fitz.open(result["path"])
    assert len(document) == 1


def test_export_pdf_uses_styled_continuation_pages_for_long_receipts(
    tmp_path: Path,
) -> None:
    import fitz
    from canhoto.core.models import MonthBreakdown, ReportBundle
    from canhoto.exporters.pdf_summary import PdfSummaryExporter

    categories = {f"Category {index:02d}": "1.00" for index in range(60)}
    bundle = ReportBundle(
        breakdown=MonthBreakdown(
            month="2026-06",
            income="0.00",
            expenses="60.00",
            net="-60.00",
            by_category=categories,
            pending_review=0,
            transaction_count=60,
            expense_count=60,
        ),
        merchant_spend_by_category={
            f"Category {index:02d}": {f"Merchant {index:02d}": "1.00"}
            for index in range(60)
        },
        generated_at="2026-06-30T00:00:00Z",
        title="Canhoto summary — 2026-06",
    )
    output = tmp_path / "long.pdf"
    PdfSummaryExporter(profile="modern").export(bundle, output)

    document = fitz.open(output)
    assert len(document) > 1
    assert "MERCHANT SUMMARY (CONT.)" in document[1].get_text()
    for page in document:
        assert "CANHOTO  |  A compact record of what you keep" in page.get_text()


def test_pdf_summary_shows_normalized_merchants_by_category(data_home: Path) -> None:
    _seed_month(data_home)
    db = core_config.db_path(data_home)
    upsert_transactions(
        [
            LedgerTransaction(
                id="e2",
                date=date(2026, 6, 6),
                amount_minor=-2500,
                currency="BRL",
                description="Coffee Roasters 1234",
                merchant_raw="Coffee Roasters 1234",
                merchant_normalized="Coffee Roasters",
                source_kind="card",
                category="Eating",
                kind="expense",
                is_expense=True,
                needs_review=False,
                month="2026-06",
            ),
            LedgerTransaction(
                id="e3",
                date=date(2026, 6, 7),
                amount_minor=-1000,
                currency="BRL",
                description="private unnormalized memo",
                merchant_raw="private unnormalized memo",
                merchant_normalized=None,
                source_kind="card",
                category="Eating",
                kind="expense",
                is_expense=True,
                needs_review=False,
                month="2026-06",
            ),
        ],
        path=db,
    )
    result = service.export_pdf("2026-06", profile="minimal", root=data_home)
    # lightweight content check via pymupdf text extract
    from canhoto.core.pdf_text import extract_text

    text = extract_text(Path(result["path"]))
    assert "CANHOTO" in text
    assert "2026-06" in text
    assert "Eating" in text
    assert "CAFE" in text.upper()
    assert "COFFEE ROASTERS" in text.upper()
    assert "UNIDENTIFIED MERCHANT" in text.upper()
    assert "CATEGORY SUMMARY" not in text.upper()
    assert "private unnormalized memo" not in text
    # Must not dump raw transaction ids as a full ledger table.
    assert "e1" not in text


def _summary_bundle(
    by_category: dict[str, str],
    merchants: dict[str, dict[str, str]] | None = None,
) -> ReportBundle:
    from canhoto.core.models import MonthBreakdown, ReportBundle

    total = sum(Decimal(value) for value in by_category.values())
    return ReportBundle(
        breakdown=MonthBreakdown(
            month="2026-08",
            income="0.00",
            expenses=f"{total:.2f}",
            net=f"{-total:.2f}",
            by_category=by_category,
            pending_review=0,
            transaction_count=len(by_category),
            expense_count=len(by_category),
        ),
        merchant_spend_by_category=merchants or {},
        generated_at="2026-08-31T00:00:00Z",
        title="Canhoto summary — 2026-08",
    )


def test_chart_legend_merges_real_other_category_into_rollup(tmp_path: Path) -> None:
    import fitz
    from canhoto.exporters.pdf_summary import PdfSummaryExporter

    categories = {f"Category {index}": f"{100 - index}.00" for index in range(8)}
    categories["Other"] = "500.00"  # ranks first, so it is kept beside the rollup
    output = tmp_path / "other.pdf"
    PdfSummaryExporter(profile="canhoto").export(_summary_bundle(categories), output)

    lines = [line.strip() for line in fitz.open(output)[0].get_text().splitlines()]
    assert lines.count("Other") == 1


def test_chart_pie_fills_the_whole_ring_around_its_center(tmp_path: Path) -> None:
    import fitz
    from canhoto.exporters.pdf_summary import PdfSummaryExporter

    output = tmp_path / "pie.pdf"
    PdfSummaryExporter(profile="canhoto").export(
        _summary_bundle({"Groceries": "50.00", "Fuel": "30.00", "Health": "20.00"}),
        output,
    )

    page = fitz.open(output)[0]
    label = page.search_for("TOTAL")[0]
    mm = 72 / 25.4
    center_x = (label.x0 + label.x1) / 2
    center_y = label.y1 + 2 * mm  # label cell sits just above the pie center
    pixmap = page.get_pixmap(dpi=72)
    paper = pixmap.pixel(1, 1)
    ring = 21 * mm  # between the 15 mm hole and the 26 mm outer radius
    for dx, dy in ((ring, 0), (-ring, 0), (0, ring), (0, -ring)):
        assert pixmap.pixel(int(center_x + dx), int(center_y + dy)) != paper


def test_truncated_names_end_with_ascii_ellipsis(tmp_path: Path) -> None:
    import fitz
    from canhoto.exporters.pdf_summary import PdfSummaryExporter

    long_name = "VERY LONG MERCHANT NAME THAT DOES NOT FIT"
    output = tmp_path / "truncate.pdf"
    PdfSummaryExporter(profile="canhoto").export(
        _summary_bundle({"Groceries": "10.00"}, {"Groceries": {long_name: "10.00"}}),
        output,
    )

    text = fitz.open(output)[0].get_text()
    assert f"{long_name[:27]}..." in text
    assert "?" not in text


def test_merchant_rows_keep_one_font_size_across_page_breaks(tmp_path: Path) -> None:
    import fitz
    from canhoto.exporters.pdf_summary import PdfSummaryExporter

    merchants = {
        f"Category {index:02d}": {f"Merchant {index:02d}-{n}": "1.00" for n in range(4)}
        for index in range(20)
    }
    by_category = {name: "4.00" for name in merchants}
    output = tmp_path / "fonts.pdf"
    PdfSummaryExporter(profile="canhoto").export(_summary_bundle(by_category, merchants), output)

    sizes = {
        round(span["size"], 1)
        for page in fitz.open(output)
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
        if span["text"].strip().startswith(("Merchant ", "Other merchants"))
    }
    assert sizes == {8.0}
