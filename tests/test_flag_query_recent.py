"""Tests for flag_query._parse_recent_duration delegation."""

import pytest
from datetime import datetime, timedelta

from repoindex.services.flag_query import _parse_recent_duration


def test_days():
    result = _parse_recent_duration("14d")
    expected = datetime.now() - timedelta(days=14)
    assert abs((result - expected).total_seconds()) < 2


def test_hours():
    result = _parse_recent_duration("12h")
    expected = datetime.now() - timedelta(hours=12)
    assert abs((result - expected).total_seconds()) < 2


def test_months():
    result = _parse_recent_duration("3m")
    expected = datetime.now() - timedelta(days=3 * 30)
    assert abs((result - expected).total_seconds()) < 2


def test_quoted_value_stripped():
    result = _parse_recent_duration("'7d'")
    expected = datetime.now() - timedelta(days=7)
    assert abs((result - expected).total_seconds()) < 2


def test_invalid_raises():
    # Previously fell back silently to 30 days; now raises.
    with pytest.raises(ValueError):
        _parse_recent_duration("not-a-duration")
