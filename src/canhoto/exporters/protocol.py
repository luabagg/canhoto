"""Exporter port — Strategy + Registry surface for report projections."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from canhoto.core.models import ReportBundle


class ExportResult(Protocol):
    path: Path
    bytes_written: int


class Exporter(Protocol):
    """Projection from an in-memory report bundle to an on-disk artifact."""

    id: str

    def export(self, bundle: ReportBundle, dest: Path) -> Path:
        """Write ``bundle`` to ``dest`` and return the final path."""
        ...
