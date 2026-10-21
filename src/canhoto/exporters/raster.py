"""Render PDF bytes to PNG page images for on-screen previews."""

from __future__ import annotations

import pymupdf

PREVIEW_DPI = 110


def pdf_to_png_pages(content: bytes, *, dpi: int = PREVIEW_DPI) -> list[bytes]:
    """Return one PNG image per PDF page, in page order."""
    if not content:
        raise ValueError("PDF content is empty")
    with pymupdf.open(stream=content, filetype="pdf") as document:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in document]


__all__ = ["PREVIEW_DPI", "pdf_to_png_pages"]
