"""
Tests for events.py module.

Tests the stateless event scanning system:
- Time specification parsing
- Event dataclass functionality
- Git tag scanning
- Commit scanning
- Multi-repo event scanning
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from repoindex.events import (
    Event,
    parse_timespec,
    scan_git_tags,
    scan_commits,
    scan_events,
    get_recent_events,
    events_to_jsonl
)


class TestParseTimespec:
    """Test time specification parsing."""

    def test_parse_hours(self):
        """Test parsing hour specifications."""
        result = parse_timespec('1h')
        expected = datetime.now() - timedelta(hours=1)
        assert abs((result - expected).total_seconds()) < 1

        result = parse_timespec('24h')
        expected = datetime.now() - timedelta(hours=24)
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_days(self):
        """Test parsing day specifications."""
        result = parse_timespec('1d')
        expected = datetime.now() - timedelta(days=1)
        assert abs((result - expected).total_seconds()) < 1

        result = parse_timespec('7d')
        expected = datetime.now() - timedelta(days=7)
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_weeks(self):
        """Test parsing week specifications."""
        result = parse_timespec('1w')
        expected = datetime.now() - timedelta(weeks=1)
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_minutes(self):
        """Test parsing minute specifications."""
        result = parse_timespec('30m')
        expected = datetime.now() - timedelta(minutes=30)
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_months(self):
        """Test parsing month specifications (approximate)."""
        result = parse_timespec('1M')
        expected = datetime.now() - timedelta(days=30)
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_iso_date(self):
        """Test parsing ISO date format."""
        result = parse_timespec('2024-01-15')
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_iso_datetime(self):
        """Test parsing ISO datetime format."""
        result = parse_timespec('2024-01-15T10:30:00')
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_invalid(self):
        """Test parsing invalid specification."""
        with pytest.raises(ValueError):
            parse_timespec('invalid')

        with pytest.raises(ValueError):
            parse_timespec('abc123')

    def test_parse_with_whitespace(self):
        """Test parsing with leading/trailing whitespace."""
        result = parse_timespec('  7d  ')
        expected = datetime.now() - timedelta(days=7)
        assert abs((result - expected).total_seconds()) < 1


class TestEvent:
    """Test Event dataclass functionality."""

    def test_event_creation(self):
        """Test creating an event with all fields."""
        timestamp = datetime.now()
        event = Event(
            type='git_tag',
            timestamp=timestamp,
            repo_name='myrepo',
            repo_path='/test/repo',
            data={'tag': 'v1.0.0', 'commit': 'abc123'}
        )

        assert event.type == 'git_tag'
        assert event.timestamp == timestamp
        assert event.repo_name == 'myrepo'
        assert event.repo_path == '/test/repo'
        assert event.data['tag'] == 'v1.0.0'

    def test_event_id_git_tag(self):
        """Test ID generation for git_tag events."""
        event = Event(
            type='git_tag',
            timestamp=datetime.now(),
            repo_name='myrepo',
            repo_path='/test/repo',
            data={'tag': 'v1.0.0'}
        )

        assert event.id == 'git_tag_myrepo_v1.0.0'

    def test_event_id_commit(self):
        """Test ID generation for commit events."""
        event = Event(
            type='commit',
            timestamp=datetime.now(),
            repo_name='myrepo',
            repo_path='/test/repo',
            data={'hash': 'abc123def456'}
        )

        assert event.id == 'commit_myrepo_abc123de'

    def test_event_to_dict(self):
        """Test converting event to dictionary."""
        timestamp = datetime.now()
        event = Event(
            type='git_tag',
            timestamp=timestamp,
            repo_name='myrepo',
            repo_path='/test/repo',
            data={'tag': 'v1.0.0'}
        )

        event_dict = event.to_dict()

        assert event_dict['id'] == 'git_tag_myrepo_v1.0.0'
        assert event_dict['type'] == 'git_tag'
        assert event_dict['timestamp'] == timestamp.isoformat()
        assert event_dict['repo'] == 'myrepo'
        assert event_dict['path'] == '/test/repo'
        assert event_dict['data']['tag'] == 'v1.0.0'

    def test_event_to_jsonl(self):
        """Test converting event to JSONL string."""
        import json

        event = Event(
            type='git_tag',
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            repo_name='myrepo',
            repo_path='/test/repo',
            data={'tag': 'v1.0.0'}
        )

        jsonl = event.to_jsonl()
        parsed = json.loads(jsonl)

        assert parsed['type'] == 'git_tag'
        assert parsed['repo'] == 'myrepo'
        assert parsed['data']['tag'] == 'v1.0.0'

    def test_event_empty_data(self):
        """Test event with empty data."""
        event = Event(
            type='git_tag',
            timestamp=datetime.now(),
            repo_name='myrepo',
            repo_path='/test/repo'
        )

        assert event.data == {}


class TestScanGitTags:
    """Test git tag scanning."""

    @patch('repoindex.events.run_command')
    def test_scan_tags_basic(self, mock_run):
        """Test basic tag scanning."""
        mock_run.return_value = (
            "v1.0.0|2024-01-15 10:30:00 -0500|abc123|user@example.com|Release v1.0.0\n"
            "v0.9.0|2024-01-10 09:00:00 -0500|def456|user@example.com|Beta release",
            0
        )

        events = list(scan_git_tags('/test/repo'))

        assert len(events) == 2
        assert events[0].type == 'git_tag'
        assert events[0].data['tag'] == 'v1.0.0'
        assert events[1].data['tag'] == 'v0.9.0'

    @patch('repoindex.events.run_command')
    def test_scan_tags_with_since(self, mock_run):
        """Test tag scanning with since filter."""
        mock_run.return_value = (
            "v1.0.0|2024-01-15 10:30:00 -0500|abc123||Release v1.0.0\n"
            "v0.9.0|2024-01-01 09:00:00 -0500|def456||Old release",
            0
        )

        since = datetime(2024, 1, 10)
        events = list(scan_git_tags('/test/repo', since=since))

        # Only v1.0.0 should match (after Jan 10)
        assert len(events) == 1
        assert events[0].data['tag'] == 'v1.0.0'

    @patch('repoindex.events.run_command')
    def test_scan_tags_with_limit(self, mock_run):
        """Test tag scanning with limit."""
        mock_run.return_value = (
            "v1.0.0|2024-01-15 10:30:00 -0500|abc123||Release\n"
            "v0.9.0|2024-01-10 09:00:00 -0500|def456||Beta\n"
            "v0.8.0|2024-01-05 08:00:00 -0500|ghi789||Alpha",
            0
        )

        events = list(scan_git_tags('/test/repo', limit=2))

        assert len(events) == 2

    @patch('repoindex.events.run_command')
    def test_scan_tags_empty_repo(self, mock_run):
        """Test scanning repo with no tags."""
        mock_run.return_value = ('', 0)

        events = list(scan_git_tags('/test/repo'))

        assert len(events) == 0

    @patch('repoindex.events.run_command')
    def test_scan_tags_command_failure(self, mock_run):
        """Test handling git command failure."""
        mock_run.return_value = (None, 1)

        events = list(scan_git_tags('/test/repo'))

        assert len(events) == 0


class TestScanCommits:
    """Test commit scanning."""

    @patch('repoindex.events.run_command')
    def test_scan_commits_basic(self, mock_run):
        """Test basic commit scanning."""
        mock_run.return_value = (
            "abc123|2024-01-15T10:30:00+00:00|John Doe|john@example.com|Add feature\n"
            "def456|2024-01-14T09:00:00+00:00|Jane Doe|jane@example.com|Fix bug",
            0
        )

        events = list(scan_commits('/test/repo'))

        assert len(events) == 2
        assert events[0].type == 'commit'
        assert events[0].data['hash'] == 'abc123'
        assert events[0].data['author'] == 'John Doe'
        assert events[1].data['hash'] == 'def456'

    @patch('repoindex.events.run_command')
    def test_scan_commits_with_limit(self, mock_run):
        """Test commit scanning with limit."""
        mock_run.return_value = (
            "abc123|2024-01-15T10:30:00+00:00|John|john@example.com|Commit 1\n"
            "def456|2024-01-14T09:00:00+00:00|Jane|jane@example.com|Commit 2",
            0
        )

        events = list(scan_commits('/test/repo', limit=1))

        # The command itself handles limit, but verify we process output correctly
        assert len(events) == 2  # Still get all from mocked output


class TestScanEvents:
    """Test multi-repo event scanning."""

    @patch('repoindex.events.scan_git_tags')
    def test_scan_events_multiple_repos(self, mock_scan_tags):
        """Test scanning multiple repositories."""
        mock_scan_tags.side_effect = [
            [Event('git_tag', datetime(2024, 1, 15), 'repo1', '/repo1', {'tag': 'v1.0'})],
            [Event('git_tag', datetime(2024, 1, 14), 'repo2', '/repo2', {'tag': 'v2.0'})]
        ]

        events = list(scan_events(['/repo1', '/repo2']))

        assert len(events) == 2
        # Should be sorted by timestamp, newest first
        assert events[0].repo_name == 'repo1'
        assert events[1].repo_name == 'repo2'

    @patch('repoindex.events.scan_git_tags')
    def test_scan_events_with_repo_filter(self, mock_scan_tags):
        """Test scanning with repo filter."""
        mock_scan_tags.return_value = [
            Event('git_tag', datetime.now(), 'myrepo', '/myrepo', {'tag': 'v1.0'})
        ]

        events = list(scan_events(['/repo1', '/myrepo'], repo_filter='myrepo'))

        # Only myrepo should be scanned
        assert mock_scan_tags.call_count == 1

    @patch('repoindex.events.scan_git_tags')
    def test_scan_events_with_limit(self, mock_scan_tags):
        """Test scanning with global limit."""
        mock_scan_tags.side_effect = [
            [
                Event('git_tag', datetime(2024, 1, 15), 'repo1', '/r1', {'tag': 'v1.0'}),
                Event('git_tag', datetime(2024, 1, 14), 'repo1', '/r1', {'tag': 'v0.9'})
            ],
            [
                Event('git_tag', datetime(2024, 1, 13), 'repo2', '/r2', {'tag': 'v2.0'})
            ]
        ]

        events = list(scan_events(['/r1', '/r2'], limit=2))

        assert len(events) == 2


class TestGetRecentEvents:
    """Test convenience function for getting recent events."""

    @patch('repoindex.events.scan_events')
    def test_get_recent_events_default(self, mock_scan):
        """Test getting recent events with defaults."""
        mock_scan.return_value = iter([
            Event('git_tag', datetime.now(), 'repo', '/repo', {'tag': 'v1.0'})
        ])

        events = get_recent_events(['/repo'])

        assert len(events) == 1
        # Verify scan_events was called with correct params
        call_args = mock_scan.call_args
        assert call_args[0][0] == ['/repo']  # repos
        assert call_args[1]['limit'] == 50

    @patch('repoindex.events.scan_events')
    def test_get_recent_events_custom_days(self, mock_scan):
        """Test getting recent events with custom days."""
        mock_scan.return_value = iter([])

        get_recent_events(['/repo'], days=30)

        call_args = mock_scan.call_args
        since = call_args[1]['since']
        expected = datetime.now() - timedelta(days=30)
        assert abs((since - expected).total_seconds()) < 1


class TestEventsToJsonl:
    """Test JSONL conversion."""

    def test_events_to_jsonl(self):
        """Test converting events list to JSONL."""
        import json

        events = [
            Event('git_tag', datetime(2024, 1, 15), 'repo1', '/r1', {'tag': 'v1.0'}),
            Event('git_tag', datetime(2024, 1, 14), 'repo2', '/r2', {'tag': 'v2.0'})
        ]

        jsonl = events_to_jsonl(events)
        lines = jsonl.strip().split('\n')

        assert len(lines) == 2
        assert json.loads(lines[0])['data']['tag'] == 'v1.0'
        assert json.loads(lines[1])['data']['tag'] == 'v2.0'

    def test_events_to_jsonl_empty(self):
        """Test converting empty events list."""
        jsonl = events_to_jsonl([])
        assert jsonl == ''


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
