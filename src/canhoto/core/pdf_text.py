"""Shared text extraction for statement files (PDF + plain text).

Used by ingest and parser_test. No bank-specific logic.
"""

from __future__ import annotations

from pathlib import Path


def extract_text(path: str | Path) -> str:
    """Extract UTF-8 text from a statement path.

    - ``.pdf``: page text via PyMuPDF (pymupdf)
    - plain-text suffixes: file contents as UTF-8 (replacement on errors)
    - unknown suffixes: UTF-8 passthrough (callers may still fail at parse)
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {p}")

    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(p)
    # Plain text and unknown: passthrough. Binary non-PDF is out of scope for v1.
    return p.read_text(encoding="utf-8", errors="replace")


def extract_pdf_text(path: str | Path) -> str:
    """Extract plain text from a PDF using pymupdf."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - env dependent
        raise ValueError(
            "PDF extraction requires PyMuPDF (pymupdf); install project deps or use .txt"
        ) from exc

    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {p}")

    parts: list[str] = []
    with pymupdf.open(p) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            parts.append(page.get_text("text") or "")
    return "\n".join(parts)


__all__ = ["extract_pdf_text", "extract_text"]
