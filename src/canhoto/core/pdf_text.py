"""Shared text extraction for statement files (PDF + plain text).

Used by ingest and parser_test. No bank-specific logic.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_PDF_PASSWORD = "CANHOTO_PDF_PASSWORD"


def pdf_password_from_env() -> str | None:
    """Return PDF unlock password from ``CANHOTO_PDF_PASSWORD`` when set."""
    value = os.environ.get(_ENV_PDF_PASSWORD, "").strip()
    return value or None


def extract_text(path: str | Path, *, pdf_password: str | None = None) -> str:
    """Extract UTF-8 text from a statement path.

    - ``.pdf``: page text via PyMuPDF (pymupdf)
    - plain-text suffixes: file contents as UTF-8 (replacement on errors)
    - unknown suffixes: UTF-8 passthrough (callers may still fail at parse)

    Encrypted PDFs require ``pdf_password`` or ``CANHOTO_PDF_PASSWORD``.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {p}")

    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(p, password=pdf_password)
    # Plain text and unknown: passthrough. Binary non-PDF is out of scope for v1.
    return p.read_text(encoding="utf-8", errors="replace")


def extract_pdf_text(path: str | Path, *, password: str | None = None) -> str:
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

    unlock = password if password is not None else pdf_password_from_env()

    parts: list[str] = []
    with pymupdf.open(p) as document:
        if document.is_encrypted:
            if not unlock:
                raise ValueError(
                    "PDF is password-protected; set CANHOTO_PDF_PASSWORD "
                    "or pass pdf_password"
                )
            if not document.authenticate(unlock):
                raise ValueError("PDF password incorrect")
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            parts.append(page.get_text("text") or "")
    return "\n".join(parts)


__all__ = ["extract_pdf_text", "extract_text", "pdf_password_from_env"]


__all__ = ["extract_pdf_text", "extract_text", "pdf_password_from_env"]