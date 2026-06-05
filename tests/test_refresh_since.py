"""Tests for the refresh command's _parse_since delegation."""

import pytest
from datetime import datetime, timedelta

from repoindex.commands.refresh import _parse_since


def test_days_token():
    result = _parse_since("30d")
    expected = datetime.now() - timedelta(days=30)
    assert abs((result - expected).total_seconds()) < 2


def test_months_token():
    result = _parse_since("6m")
    expected = datetime.now() - timedelta(days=6 * 30)
    assert abs((result - expected).total_seconds()) < 2


def test_years_token():
    result = _parse_since("1y")
    expected = datetime.now() - timedelta(days=365)
    assert abs((result - expected).total_seconds()) < 2


def test_invalid_raises():
    # Previously fell back silently to 90 days; now raises.
    with pytest.raises(ValueError):
        _parse_since("garbage")
