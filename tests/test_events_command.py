"""Tests for the events command's _parse_since delegation."""

import pytest
from datetime import datetime, timedelta

from click.testing import CliRunner

from repoindex.commands.events import _parse_since, events_handler


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


class TestForgeTypeIntersection:
    """--forge combined with --type must not silently drop the filter."""

    def test_forge_with_non_forge_type_is_usage_error(self):
        # ('commit',) ∩ FORGE_TYPES is empty; returning ALL event types
        # (the old behavior) is the opposite of what the user asked for.
        runner = CliRunner()
        result = runner.invoke(events_handler, ['--forge', '--type', 'commit'])
        assert result.exit_code != 0
        assert 'forge' in result.output.lower()
        assert 'commit' in result.output

    def test_forge_with_forge_type_keeps_filter(self, monkeypatch):
        captured = {}

        def fake_show_pretty(config, event_types, repo, since_dt, until_dt, limit):
            captured['event_types'] = event_types

        monkeypatch.setattr(
            'repoindex.commands.events._show_pretty', fake_show_pretty)
        monkeypatch.setattr(
            'repoindex.commands.events.load_config', lambda: {})
        runner = CliRunner()
        result = runner.invoke(events_handler, ['--forge', '--type', 'release'])
        assert result.exit_code == 0
        assert captured['event_types'] == ('release',)


def test_type_help_does_not_advertise_removed_pr_type():
    # The vocabulary renamed 'pr' to 'pull_request'; help must not
    # steer users to a type that silently matches zero rows.
    runner = CliRunner()
    result = runner.invoke(events_handler, ['--help'])
    assert ' pr)' not in result.output and ' pr,' not in result.output
    assert 'release' in result.output
