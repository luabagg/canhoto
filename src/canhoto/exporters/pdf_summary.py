"""Summary-only PDF exporter (v1).

Renders month metrics + category totals. Never dumps full transaction tables.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from canhoto.core.models import ReportBundle

EXPORTER_ID = "pdf_summary"


class PdfSummaryExporter:
    """Write a compact monthly summary PDF under the caller's destination path."""

    id = EXPORTER_ID

    def export(self, bundle: ReportBundle, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        bd = bundle.breakdown
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, _safe(bundle.title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        pdf.cell(
            0,
            8,
            f"Generated: {_safe(bundle.generated_at)}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"Month {_safe(bd.month)}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        for label, value in (
            ("Income", bd.income),
            ("Expenses", bd.expenses),
            ("Net", bd.net),
            ("Transactions", str(bd.transaction_count)),
            ("Expense count", str(bd.expense_count)),
            ("Pending review", str(bd.pending_review)),
        ):
            pdf.cell(0, 7, f"{label}: {_safe(value)}", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "By category", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        if not bd.by_category:
            pdf.cell(0, 7, "(none)", new_x="LMARGIN", new_y="NEXT")
        else:
            for name, total in sorted(bd.by_category.items()):
                pdf.cell(
                    0,
                    7,
                    f"- {_safe(name)}: {_safe(total)}",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )

        pdf.output(str(dest))
        return dest


def _safe(value: object) -> str:
    """fpdf core fonts are Latin-1; strip non-encodable glyphs for v1."""
    text = str(value)
    return text.encode("latin-1", errors="replace").decode("latin-1")
