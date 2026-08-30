"""Built-in, summary-only monthly PDF exporter profiles."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from fpdf import FPDF

from canhoto.core.models import ReportBundle

EXPORTER_ID = "pdf_summary"
PDF_PROFILES = frozenset({"canhoto", "modern", "minimal"})

# Shared palette
_BLUE = (42, 99, 255)
_TEAL = (22, 163, 154)
_PURPLE = (124, 58, 237)
_ORANGE = (245, 158, 11)
_RED = (239, 68, 68)
_PINK = (236, 72, 153)
_SLATE = (71, 85, 105)
_CHART_COLORS = (_BLUE, _TEAL, _PURPLE, _ORANGE, _PINK, _RED, _SLATE)

# canhoto (receipt)
_PAPER = (244, 232, 190)
_INK = (74, 71, 64)
_FADED_INK = (133, 128, 116)

# modern (stripe-inspired)
_MODERN_BLUE = (37, 99, 235)
_MODERN_BLUE_LIGHT = (219, 234, 254)
_MODERN_INK = (15, 23, 42)
_MODERN_MUTED = (100, 116, 139)
_MODERN_WHITE = (255, 255, 255)

# minimal
_MIN_INK = (30, 30, 30)
_MIN_MUTED = (120, 120, 120)


class PdfSummaryExporter:
    """Write an aggregate-only monthly report using a built-in profile."""

    id = EXPORTER_ID

    def __init__(self, profile: str = "canhoto") -> None:
        if profile not in PDF_PROFILES:
            choices = ", ".join(sorted(PDF_PROFILES))
            raise ValueError(f"unknown PDF profile {profile!r}; choose one of: {choices}")
        self.profile = profile

    def export(self, bundle: ReportBundle, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        bd = bundle.breakdown
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_margins(15, 15, 15)
        self._add_page(pdf)

        self._header(pdf, bd.month, bundle.generated_at)
        self._metrics(pdf, bd.income, bd.expenses, bd.net)
        if self.profile != "minimal":
            self._category_chart(pdf, bd.by_category, bd.expenses)
        else:
            self._category_list(pdf, bd.by_category, bd.expenses)
        self._merchant_summary(pdf, bundle.merchant_spend_by_category)
        self._footer(pdf)

        pdf.output(str(dest))
        return dest

    def _add_page(self, pdf: FPDF) -> None:
        """Add a styled page without treating a page break as content."""
        pdf.add_page()
        if self.profile == "canhoto":
            pdf.set_fill_color(*_PAPER)
            pdf.rect(0, 0, 210, 297, style="F")

    def _header(self, pdf: FPDF, month: str, generated_at: str) -> None:
        if self.profile == "canhoto":
            pdf.set_text_color(*_INK)
            pdf.set_font("Courier", "B", 14)
            pdf.set_xy(15, 13)
            pdf.cell(90, 6, "CANHOTO // COUNTERFOIL")
            pdf.set_font("Courier", "B", 10)
            pdf.set_xy(125, 13)
            pdf.cell(70, 6, _safe(month), align="R")
            pdf.set_draw_color(*_FADED_INK)
            pdf.line(15, 22, 195, 22)
            pdf.set_font("Courier", size=7)
            pdf.set_xy(15, 25)
            pdf.cell(180, 4, f"MONTHLY SPENDING RECORD  |  GENERATED {_safe(generated_at[:10])}")
            pdf.set_y(37)
            return

        if self.profile == "minimal":
            pdf.set_text_color(*_MIN_INK)
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_xy(15, 15)
            pdf.cell(0, 8, "CANHOTO")
            pdf.set_font("Helvetica", size=9)
            pdf.set_text_color(*_MIN_MUTED)
            pdf.set_xy(15, 24)
            pdf.cell(100, 5, f"Monthly summary  ·  {_safe(month)}")
            pdf.set_xy(125, 24)
            pdf.cell(70, 5, _safe(generated_at[:10]), align="R")
            pdf.set_draw_color(*_MIN_MUTED)
            pdf.line(15, 32, 195, 32)
            pdf.set_y(40)
            return

        # modern: thin blue stripe header
        pdf.set_fill_color(*_MODERN_BLUE)
        pdf.rect(15, 12, 3, 22, style="F")
        pdf.set_text_color(*_MODERN_INK)
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_xy(22, 13)
        pdf.cell(100, 8, "CANHOTO")
        pdf.set_font("Helvetica", size=8)
        pdf.set_text_color(*_MODERN_MUTED)
        pdf.set_xy(22, 22)
        pdf.cell(100, 5, "Monthly spending counterfoil")
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_MODERN_BLUE)
        pdf.set_xy(130, 14)
        pdf.cell(65, 6, _safe(month), align="R")
        pdf.set_font("Helvetica", size=7)
        pdf.set_text_color(*_MODERN_MUTED)
        pdf.set_xy(130, 22)
        pdf.cell(65, 5, f"Generated {_safe(generated_at[:10])}", align="R")
        pdf.set_draw_color(*_MODERN_BLUE)
        pdf.set_line_width(0.2)
        pdf.line(15, 38, 195, 38)
        pdf.set_y(46)

    def _metrics(self, pdf: FPDF, income: str, expenses: str, net: str) -> None:
        cards = (
            ("INCOME", income, False),
            ("EXPENSES", expenses, False),
            ("NET", net, True),
        )

        if self.profile == "canhoto":
            pdf.set_font("Courier", "B", 8)
            pdf.set_text_color(*_INK)
            for label, value, show_sign in cards:
                pdf.cell(50, 5, label)
                pdf.cell(55, 5, _brl(value, show_sign=show_sign), align="R")
                pdf.cell(75, 5, "." * 35, align="R", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)
            return

        if self.profile == "minimal":
            pdf.set_font("Helvetica", size=10)
            pdf.set_text_color(*_MIN_INK)
            for label, value, show_sign in cards:
                pdf.cell(40, 6, label)
                pdf.cell(
                    140, 6, _brl(value, show_sign=show_sign), align="R",
                    new_x="LMARGIN", new_y="NEXT",
                )
            pdf.ln(4)
            return

        # modern: bordered metric boxes with blue stripe accent
        y = pdf.get_y()
        x = 15
        for label, value, show_sign in cards:
            pdf.set_draw_color(*_MODERN_BLUE)
            pdf.set_line_width(0.2)
            pdf.rect(x, y, 57, 24, style="D")
            pdf.set_fill_color(*_MODERN_BLUE_LIGHT)
            pdf.rect(x, y, 57, 2, style="F")
            pdf.set_text_color(*_MODERN_MUTED)
            pdf.set_font("Helvetica", "B", 6)
            pdf.set_xy(x + 4, y + 5)
            pdf.cell(49, 4, label)
            pdf.set_text_color(*_MODERN_INK)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_xy(x + 4, y + 12)
            pdf.cell(49, 7, _brl(value, show_sign=show_sign))
            x += 61
        pdf.set_text_color(0, 0, 0)
        pdf.set_y(y + 30)

    def _category_chart(self, pdf: FPDF, categories: dict[str, str], expenses: str) -> None:
        if self.profile == "canhoto":
            ink, muted, font = _INK, _FADED_INK, "Courier"
            hole_color = _PAPER
        else:
            ink, muted, font = _MODERN_INK, _MODERN_MUTED, "Helvetica"
            hole_color = _MODERN_WHITE

        pdf.set_font(font, "B", 11)
        pdf.set_text_color(*ink)
        pdf.cell(0, 7, "SPENDING BY CATEGORY", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font, size=8)
        pdf.set_text_color(*muted)
        pdf.cell(0, 4, "Where your money went this month", new_x="LMARGIN", new_y="NEXT")

        chart_box_bottom: float | None = None
        if self.profile == "modern":
            pdf.set_draw_color(*_MODERN_BLUE)
            pdf.set_line_width(0.2)
            y_box = pdf.get_y()
            pdf.rect(15, y_box, 180, 72, style="D")
            chart_box_bottom = y_box + 72

        chart_rows = _chart_rows(categories)
        total = _amount(expenses)
        center_x, center_y, radius = 55, pdf.get_y() + 30, 26
        angle = 0.0
        if total > 0 and chart_rows:
            for _, amount, color in chart_rows:
                sweep = float(amount / total * 360)
                pdf.set_fill_color(*color)
                pdf.solid_arc(
                    center_x - radius,
                    center_y - radius,
                    radius,
                    angle,
                    angle + sweep,
                    b=radius,
                    style="F",
                )
                angle += sweep
        else:
            fallback = _MODERN_BLUE_LIGHT if self.profile == "modern" else (230, 230, 230)
            pdf.set_fill_color(*fallback)
            pdf.circle(center_x, center_y, radius, style="F")
        pdf.set_fill_color(*hole_color)
        pdf.circle(center_x, center_y, 15, style="F")
        pdf.set_text_color(*ink)
        pdf.set_font(font, "B", 8)
        pdf.set_xy(center_x - 14, center_y - 5)
        pdf.cell(28, 4, "TOTAL", align="C")
        pdf.set_font(font, "B", 9)
        pdf.set_xy(center_x - 14, center_y + 1)
        pdf.cell(28, 5, _brl(expenses), align="C")

        y = center_y - 20
        for name, amount, color in chart_rows:
            pdf.set_fill_color(*color)
            pdf.rect(94, y + 1, 4, 4, style="F")
            pdf.set_text_color(*ink)
            pdf.set_font(font, "B", 8)
            pdf.set_xy(101, y)
            pdf.cell(50, 5, _safe(_truncate(name, 22)))
            pdf.set_text_color(*muted)
            pdf.set_font(font, size=8)
            pdf.set_xy(153, y)
            share = amount / total * 100 if total > 0 else Decimal(0)
            pdf.cell(42, 5, f"{share:.0f}%  {_brl(amount)}", align="R")
            y += 7
        pdf.set_text_color(0, 0, 0)
        content_bottom = max(center_y + 35, y + 5)
        if chart_box_bottom is not None:
            content_bottom = max(content_bottom, chart_box_bottom + 5)
        pdf.set_y(content_bottom)

    def _category_list(self, pdf: FPDF, categories: dict[str, str], expenses: str) -> None:
        """Minimal profile: text-only category breakdown, no chart."""
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_MIN_INK)
        pdf.cell(0, 7, "By category", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)
        total = _amount(expenses)
        for name, value in sorted(categories.items(), key=lambda i: _amount(i[1]), reverse=True):
            amt = _amount(value)
            share = amt / total * 100 if total > 0 else Decimal(0)
            pdf.set_text_color(*_MIN_INK)
            pdf.cell(90, 5, _safe(name))
            pdf.set_text_color(*_MIN_MUTED)
            pdf.cell(30, 5, f"{share:.0f}%")
            pdf.set_text_color(*_MIN_INK)
            pdf.cell(60, 5, _brl(amt), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    def _merchant_summary(
        self, pdf: FPDF, merchant_spend_by_category: dict[str, dict[str, str]]
    ) -> None:
        """Render top normalized merchants per category, never ledger rows."""
        if not merchant_spend_by_category:
            return

        self._ensure_receipt_space(pdf, 12)
        self._receipt_heading(pdf)
        row_height = 5
        categories = sorted(
            merchant_spend_by_category.items(),
            key=lambda item: sum((_amount(value) for value in item[1].values()), Decimal("0")),
            reverse=True,
        )
        for category, merchants in categories:
            self._ensure_receipt_space(pdf, row_height * 2)
            pdf.set_font("Courier" if self.profile != "minimal" else "Helvetica", "B", 8)
            pdf.cell(
                180,
                row_height,
                _safe(_truncate(category.upper(), 30)),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_font("Courier" if self.profile != "minimal" else "Helvetica", size=8)
            for merchant, amount in _top_merchants(merchants):
                self._ensure_receipt_space(pdf, row_height)
                label = _safe(_truncate(merchant, 30))
                formatted = _brl(amount)
                dots = "." * max(3, 41 - len(label) - len(formatted))
                pdf.cell(
                    180,
                    row_height,
                    f"  {label} {dots} {formatted}",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            pdf.ln(1)

    def _ensure_receipt_space(self, pdf: FPDF, height: float) -> None:
        """Reserve footer space and start a fully styled continuation page."""
        if pdf.get_y() + height <= pdf.h - 23:
            return
        self._footer(pdf)
        self._add_page(pdf)
        self._receipt_heading(pdf, continuation=True)

    def _receipt_heading(self, pdf: FPDF, *, continuation: bool = False) -> None:
        title = "MERCHANT SUMMARY" + (" (CONT.)" if continuation else "")
        if self.profile == "canhoto":
            pdf.set_draw_color(*_FADED_INK)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(3)
            pdf.set_text_color(*_INK)
            pdf.set_font("Courier", "B", 9)
        elif self.profile == "minimal":
            pdf.set_draw_color(*_MIN_MUTED)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(3)
            pdf.set_text_color(*_MIN_INK)
            pdf.set_font("Helvetica", "B", 9)
            title = "Top merchants by category" + (" (continued)" if continuation else "")
        else:
            pdf.set_draw_color(*_MODERN_BLUE)
            pdf.set_line_width(0.2)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(3)
            pdf.set_text_color(*_MODERN_INK)
            pdf.set_font("Courier", "B", 9)
        pdf.cell(180, 6, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier" if self.profile != "minimal" else "Helvetica", size=9)

    def _footer(self, pdf: FPDF) -> None:
        """Draw the footer inside the page-break boundary; never create a blank page."""
        if self.profile == "canhoto":
            divider, muted, font = _FADED_INK, _FADED_INK, "Courier"
        elif self.profile == "minimal":
            divider, muted, font = _MIN_MUTED, _MIN_MUTED, "Helvetica"
        else:
            divider, muted, font = _MODERN_BLUE, _MODERN_MUTED, "Helvetica"
        footer_y = pdf.h - 23
        pdf.set_draw_color(*divider)
        pdf.set_line_width(0.2)
        pdf.line(15, footer_y, 195, footer_y)
        pdf.set_text_color(*muted)
        pdf.set_font(font, size=7)
        pdf.set_xy(15, footer_y + 3)
        pdf.cell(180, 4, "CANHOTO  |  A compact record of what you keep", align="C")
        pdf.set_text_color(0, 0, 0)


def _chart_rows(categories: dict[str, str]) -> list[tuple[str, Decimal, tuple[int, int, int]]]:
    rows = sorted(
        ((name, _amount(value)) for name, value in categories.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    if len(rows) > len(_CHART_COLORS):
        kept = rows[: len(_CHART_COLORS) - 1]
        other = sum((amount for _, amount in rows[len(_CHART_COLORS) - 1 :]), Decimal(0))
        rows = [*kept, ("Other", other)]
    return [(name, amount, _CHART_COLORS[index]) for index, (name, amount) in enumerate(rows)]


def _top_merchants(merchants: dict[str, str]) -> list[tuple[str, Decimal]]:
    """Return up to three merchants plus an aggregate remainder."""
    rows = sorted(
        ((name, _amount(value)) for name, value in merchants.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    if len(rows) <= 3:
        return rows
    other = sum((amount for _, amount in rows[3:]), Decimal("0"))
    return [*rows[:3], ("Other merchants", other)]


def _amount(value: str | Decimal) -> Decimal:
    try:
        return abs(Decimal(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _brl(value: str | Decimal, *, show_sign: bool = False) -> str:
    raw = Decimal(value)
    amount = abs(raw)
    whole, fractional = f"{amount:.2f}".split(".")
    sign = "-" if show_sign and raw < 0 else ""
    return f"{sign}R$ {int(whole):,}".replace(",", ".") + f",{fractional}"


def _truncate(value: str, length: int) -> str:
    return value if len(value) <= length else f"{value[: length - 1]}…"


def _safe(value: object) -> str:
    """fpdf core fonts are Latin-1; strip non-encodable glyphs for v1."""
    text = str(value)
    return text.encode("latin-1", errors="replace").decode("latin-1")
