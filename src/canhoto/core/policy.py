"""Agent-view policy helpers (batch clamps, required month filters)."""

from __future__ import annotations

import re
from datetime import datetime

from canhoto.core.models import AgentViewConfig

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def assert_month(month: str) -> str:
    """Validate and return a calendar month key in ``YYYY-MM`` form.

    Empty / blank values and non-calendar months raise ``ValueError``.
    """
    if not isinstance(month, str) or not month.strip():
        raise ValueError("month is required")
    value = month.strip()
    if _MONTH_RE.fullmatch(value) is None:
        raise ValueError("month must use YYYY-MM")
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("month must use YYYY-MM") from exc
    return value


def clamp_batch_size(requested: int | None, view: AgentViewConfig) -> int:
    """Return a positive batch size capped by agent-view limits.

    ``None`` uses ``view.max_batch_size``, then both default and requested sizes
    are hard-capped at ``view.absolute_max_batch_size``.
    """
    if requested is None:
        size = view.max_batch_size
    else:
        if not isinstance(requested, int) or isinstance(requested, bool):
            raise ValueError("batch size must be a positive integer")
        if requested <= 0:
            raise ValueError("batch size must be a positive integer")
        size = requested

    cap = view.absolute_max_batch_size
    if cap <= 0:
        raise ValueError("absolute_max_batch_size must be a positive integer")
    return min(size, cap)
