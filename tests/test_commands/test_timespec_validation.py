"""Invalid --since/--recent values must be clean usage errors, not tracebacks.

parse_since raises ValueError on unparseable input; the CLI boundary converts
that via the shared TIMESPEC param type instead of leaking the exception.
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner


def _runner():
    return CliRunner()


class TestInvalidTimespecIsUsageError:
    def test_events_since(self):
        from repoindex.commands.events import events_handler

        result = _runner().invoke(events_handler, ['--since', 'bogus'])
        assert result.exit_code == 2
        assert 'Cannot parse time specification' in result.output
        assert not isinstance(result.exception, ValueError)

    def test_events_until(self):
        from repoindex.commands.events import events_handler

        result = _runner().invoke(events_handler, ['--until', 'bogus'])
        assert result.exit_code == 2
        assert 'Cannot parse time specification' in result.output

    def test_copy_recent(self):
        from repoindex.commands.copy import copy_handler

        result = _runner().invoke(copy_handler, ['/tmp/x', '--recent', 'bogus'])
        assert result.exit_code == 2
        assert 'Cannot parse time specification' in result.output
        assert not isinstance(result.exception, ValueError)

    def test_refresh_since(self):
        from repoindex.commands.refresh import refresh_handler

        result = _runner().invoke(refresh_handler, ['--since', 'junk'])
        assert result.exit_code == 2
        assert 'Cannot parse time specification' in result.output

    def test_ops_git_status_recent(self):
        from repoindex.commands.ops import git_status_handler

        with patch('repoindex.commands.ops.load_config', return_value={}):
            result = _runner().invoke(git_status_handler, ['--recent', '5x'])
        assert result.exit_code == 2
        assert 'Cannot parse time specification' in result.output

    def test_link_tree_recent(self):
        from repoindex.commands.link import link_cmd

        result = _runner().invoke(
            link_cmd, ['tree', '/tmp/x', '--by', 'tag', '--recent', '5x'])
        assert result.exit_code == 2
        assert 'Cannot parse time specification' in result.output


class TestValidTimespecStillAccepted:
    def test_events_since_valid_reaches_handler(self):
        from repoindex.commands.events import events_handler

        with patch('repoindex.commands.events._show_pretty') as show, \
                patch('repoindex.commands.events.load_config', return_value={}):
            result = _runner().invoke(events_handler, ['--since', '24h'])
        assert result.exit_code == 0
        assert show.called
