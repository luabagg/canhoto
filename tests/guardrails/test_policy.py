"""Guardrail tests for agent view policy helpers."""

from __future__ import annotations

import pytest

from canhoto.core.models import AgentViewConfig
from canhoto.core.policy import assert_month, clamp_batch_size


def test_assert_month_rejects_empty() -> None:
    with pytest.raises(ValueError, match="month"):
        assert_month("")
    with pytest.raises(ValueError, match="month"):
        assert_month("   ")


def test_assert_month_rejects_invalid_format() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        assert_month("2026/07")
    with pytest.raises(ValueError, match="YYYY-MM"):
        assert_month("2026-13")
    with pytest.raises(ValueError, match="YYYY-MM"):
        assert_month("26-07")


def test_assert_month_accepts_valid() -> None:
    assert assert_month("2026-07") == "2026-07"


def test_clamp_batch_size_defaults_to_max_batch_size() -> None:
    view = AgentViewConfig(max_batch_size=25, absolute_max_batch_size=50)
    assert clamp_batch_size(None, view) == 25


def test_clamp_batch_size_caps_at_absolute_max() -> None:
    view = AgentViewConfig(max_batch_size=25, absolute_max_batch_size=50)
    assert clamp_batch_size(100, view) == 50
    assert clamp_batch_size(50, view) == 50
    assert clamp_batch_size(40, view) == 40


def test_clamp_batch_size_respects_lower_absolute_than_default() -> None:
    view = AgentViewConfig(max_batch_size=25, absolute_max_batch_size=10)
    assert clamp_batch_size(None, view) == 10
    assert clamp_batch_size(20, view) == 10


def test_clamp_batch_size_rejects_non_positive() -> None:
    view = AgentViewConfig()
    with pytest.raises(ValueError, match="batch size"):
        clamp_batch_size(0, view)
    with pytest.raises(ValueError, match="batch size"):
        clamp_batch_size(-3, view)
