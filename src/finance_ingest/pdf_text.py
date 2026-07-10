from __future__ import annotations

from pathlib import Path


def extract_pdf_text(path: str | Path) -> str:
    """Extract plain text from a PDF using pymupdf."""
    import pymupdf

    path = Path(path)
    doc = pymupdf.open(path)
    parts: list[str] = []
    for i, page in enumerate(doc, 1):
        parts.append(f"--- Page {i}/{len(doc)} ---\n")
        parts.append(page.get_text("text") or "")
    doc.close()
    return "\n".join(parts)
