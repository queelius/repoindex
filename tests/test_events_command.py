"""Tests for the events command's _parse_since delegation."""

import pytest
from datetime import datetime, timedelta

from repoindex.commands.events import _parse_since


def test_days_token():
    result = _parse_since("7d")
    expected = datetime.now() - timedelta(days=7)
    assert abs((result - expected).total_seconds()) < 2


def test_m_is_months_now():
    # Previously 'm' meant minutes here; it now means months.
    result = _parse_since("6m")
    expected = datetime.now() - timedelta(days=6 * 30)
    assert abs((result - expected).total_seconds()) < 2


def test_min_is_minutes():
    result = _parse_since("15min")
    expected = datetime.now() - timedelta(minutes=15)
    assert abs((result - expected).total_seconds()) < 2


def test_invalid_raises():
    with pytest.raises(ValueError):
        _parse_since("nonsense")
