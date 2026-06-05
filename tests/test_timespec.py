"""Tests for the unified duration parser in repoindex.services.timespec."""

import pytest
from datetime import datetime, timedelta

from repoindex.services.timespec import parse_since


FIXED_NOW = datetime(2026, 6, 4, 12, 0, 0)


class TestParseSinceRelative:
    """Relative duration tokens resolve to now minus the duration."""

    def test_seconds_s(self):
        assert parse_since("30s", now=FIXED_NOW) == FIXED_NOW - timedelta(seconds=30)

    def test_seconds_sec(self):
        assert parse_since("30sec", now=FIXED_NOW) == FIXED_NOW - timedelta(seconds=30)

    def test_minutes_min(self):
        assert parse_since("15min", now=FIXED_NOW) == FIXED_NOW - timedelta(minutes=15)

    def test_hours_h(self):
        assert parse_since("24h", now=FIXED_NOW) == FIXED_NOW - timedelta(hours=24)

    def test_days_d(self):
        assert parse_since("7d", now=FIXED_NOW) == FIXED_NOW - timedelta(days=7)

    def test_weeks_w(self):
        assert parse_since("2w", now=FIXED_NOW) == FIXED_NOW - timedelta(weeks=2)

    def test_months_m_lower(self):
        # 'm' is MONTHS (not minutes): 6 months == 6 * 30 days.
        assert parse_since("6m", now=FIXED_NOW) == FIXED_NOW - timedelta(days=6 * 30)

    def test_months_M_alias(self):
        assert parse_since("6M", now=FIXED_NOW) == FIXED_NOW - timedelta(days=6 * 30)

    def test_years_y(self):
        assert parse_since("1y", now=FIXED_NOW) == FIXED_NOW - timedelta(days=365)

    def test_whitespace_and_quotes_stripped(self):
        assert parse_since("  '7d'  ", now=FIXED_NOW) == FIXED_NOW - timedelta(days=7)


class TestParseSinceAbsolute:
    """ISO dates and datetimes parse to themselves."""

    def test_iso_date(self):
        result = parse_since("2024-01-15", now=FIXED_NOW)
        assert (result.year, result.month, result.day) == (2024, 1, 15)

    def test_iso_datetime(self):
        result = parse_since("2024-01-15T10:30:00", now=FIXED_NOW)
        assert (result.year, result.month, result.day) == (2024, 1, 15)
        assert (result.hour, result.minute) == (10, 30)


class TestParseSinceInvalid:
    """Invalid input raises ValueError: no silent default."""

    @pytest.mark.parametrize("spec", ["", "   ", "invalid", "abc123", "7x", "d", "1.5d"])
    def test_raises(self, spec):
        with pytest.raises(ValueError):
            parse_since(spec, now=FIXED_NOW)


class TestParseSinceDefaultNow:
    """now defaults to datetime.now() when omitted."""

    def test_now_defaults(self):
        before = datetime.now()
        result = parse_since("1d")
        after = datetime.now()
        assert before - timedelta(days=1, seconds=1) <= result <= after - timedelta(days=1) + timedelta(seconds=1)
