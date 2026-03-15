"""Tests for the show command."""

import json
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from repoindex.commands.show import (
    show_handler,
    _find_repo,
    _shorten_path,
    _fetch_related,
)


MOCK_REPO_ROW = {
    'id': 1,
    'name': 'test-repo',
    'path': '/home/user/github/test-repo',
    'language': 'Python',
    'branch': 'main',
    'is_clean': True,
    'remote_url': 'https://github.com/user/test-repo',
    'github_stars': 5,
    'github_forks': 2,
    'github_is_private': False,
    'github_is_archived': False,
    'github_is_fork': False,
    'github_owner': 'user',
    'license_key': 'mit',
    'license_name': 'MIT License',
    'description': 'A test repository for unit testing',
}

MOCK_TAGS = [
    {'tag': 'topic/testing', 'source': 'user'},
    {'tag': 'work/active', 'source': 'user'},
]

MOCK_PUBLICATIONS = [
    {
        'registry': 'pypi',
        'package_name': 'test-repo',
        'current_version': '1.0.0',
        'published': 1,
        'url': 'https://pypi.org/project/test-repo/',
        'doi': None,
    },
]

MOCK_EVENTS = [
    {
        'type': 'commit',
        'timestamp': '2026-02-15 10:00:00',
        'ref': 'abc123',
        'message': 'Fix build script',
        'author': 'user',
    },
    {
        'type': 'git_tag',
        'timestamp': '2026-02-10 12:00:00',
        'ref': 'v1.0.0',
        'message': None,
        'author': 'user',
    },
]


class MockRow(dict):
    """Dict that also works as sqlite3.Row (supports dict() conversion)."""
    pass


def make_mock_db(repo=None, tags=None, publications=None, events=None, multiple_repos=None):
    """Create a mock Database context manager with preset query results."""
    db = MagicMock()

    call_count = [0]

    def mock_execute(sql, params=None):
        pass

    results_queue = []

    if repo is not None:
        # First query: find by name
        results_queue.append(MockRow(repo) if repo else None)
    elif multiple_repos is not None:
        # Name returns None, path returns None, LIKE returns multiple
        results_queue.append(None)
        results_queue.append(None)
        results_queue.append([MockRow(r) for r in multiple_repos])

    if tags is not None:
        results_queue.append([MockRow(t) for t in tags])
    if publications is not None:
        results_queue.append([MockRow(p) for p in publications])
    if events is not None:
        results_queue.append([MockRow(e) for e in events])

    fetch_index = [0]

    def mock_fetchone():
        idx = fetch_index[0]
        fetch_index[0] += 1
        if idx < len(results_queue):
            return results_queue[idx]
        return None

    def mock_fetchall():
        idx = fetch_index[0]
        fetch_index[0] += 1
        if idx < len(results_queue):
            result = results_queue[idx]
            if isinstance(result, list):
                return result
            return [result] if result else []
        return []

    db.execute = MagicMock(side_effect=mock_execute)
    db.fetchone = MagicMock(side_effect=mock_fetchone)
    db.fetchall = MagicMock(side_effect=mock_fetchall)
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    return db


@pytest.fixture
def runner():
    return CliRunner()


class TestShortenPath:
    def test_home_shortening(self):
        from pathlib import Path
        home = str(Path.home())
        assert _shorten_path(f"{home}/github/test") == "~/github/test"

    def test_non_home_path(self):
        assert _shorten_path("/opt/repos/test") == "/opt/repos/test"

    def test_empty_path(self):
        assert _shorten_path("") == ""


@pytest.fixture(autouse=True)
def no_warn_stale():
    """Suppress warn_if_stale in all show tests."""
    with patch('repoindex.commands.warn_if_stale'):
        yield


class TestShowCommandPretty:
    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_by_name(self, mock_db_cls, mock_config, runner):
        """Show command finds repo by name and displays pretty output."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,
            tags=MOCK_TAGS,
            publications=MOCK_PUBLICATIONS,
            events=MOCK_EVENTS,
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo'])
        assert result.exit_code == 0
        assert 'test-repo' in result.output
        assert 'Python' in result.output
        assert 'main' in result.output

    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_displays_github_info(self, mock_db_cls, mock_config, runner):
        """Show command displays GitHub metadata."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,
            tags=[],
            publications=[],
            events=[],
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo'])
        assert result.exit_code == 0
        assert 'Stars' in result.output
        assert 'Forks' in result.output

    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_displays_publications(self, mock_db_cls, mock_config, runner):
        """Show command displays publication info."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,
            tags=[],
            publications=MOCK_PUBLICATIONS,
            events=[],
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo'])
        assert result.exit_code == 0
        assert 'pypi' in result.output
        assert 'v1.0.0' in result.output

    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_displays_tags(self, mock_db_cls, mock_config, runner):
        """Show command displays tags."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,
            tags=MOCK_TAGS,
            publications=[],
            events=[],
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo'])
        assert result.exit_code == 0
        assert 'topic/testing' in result.output
        assert 'work/active' in result.output

    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_displays_events(self, mock_db_cls, mock_config, runner):
        """Show command displays recent events."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,
            tags=[],
            publications=[],
            events=MOCK_EVENTS,
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo'])
        assert result.exit_code == 0
        assert 'commit' in result.output
        assert 'Fix build script' in result.output

    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_empty_sections(self, mock_db_cls, mock_config, runner):
        """Show command handles empty tags/publications/events gracefully."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,
            tags=[],
            publications=[],
            events=[],
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo'])
        assert result.exit_code == 0
        assert '(none)' in result.output


class TestShowCommandJSON:
    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_json_output(self, mock_db_cls, mock_config, runner):
        """Show command outputs valid JSON with --json."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,
            tags=MOCK_TAGS,
            publications=MOCK_PUBLICATIONS,
            events=MOCK_EVENTS,
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo', '--json'])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert data['name'] == 'test-repo'
        assert data['language'] == 'Python'
        assert 'topic/testing' in data['tags']
        assert len(data['publications']) == 1
        assert len(data['recent_events']) == 2

    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_json_includes_tags(self, mock_db_cls, mock_config, runner):
        """JSON output includes tags as a flat list."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,
            tags=MOCK_TAGS,
            publications=[],
            events=[],
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo', '--json'])
        data = json.loads(result.output.strip())
        assert data['tags'] == ['topic/testing', 'work/active']


class TestShowCommandErrors:
    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_not_found(self, mock_db_cls, mock_config, runner):
        """Show command exits with error when repo not found."""
        mock_db = MagicMock()
        mock_db.fetchone.return_value = None
        mock_db.fetchall.return_value = []
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['nonexistent'])
        assert result.exit_code != 0

    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_not_found_json(self, mock_db_cls, mock_config, runner):
        """Show command outputs JSON error when repo not found with --json."""
        mock_db = MagicMock()
        mock_db.fetchone.return_value = None
        mock_db.fetchall.return_value = []
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['nonexistent', '--json'])
        assert result.exit_code != 0


class TestShowCleanStatus:
    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_dirty_repo(self, mock_db_cls, mock_config, runner):
        """Show command displays dirty status."""
        dirty_repo = {**MOCK_REPO_ROW, 'is_clean': False}
        mock_db = make_mock_db(
            repo=dirty_repo,
            tags=[],
            publications=[],
            events=[],
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo'])
        assert result.exit_code == 0
        assert 'No' in result.output

    @patch('repoindex.commands.show.load_config', return_value={})
    @patch('repoindex.commands.show.Database')
    def test_show_clean_repo(self, mock_db_cls, mock_config, runner):
        """Show command displays clean status."""
        mock_db = make_mock_db(
            repo=MOCK_REPO_ROW,  # is_clean=True
            tags=[],
            publications=[],
            events=[],
        )
        mock_db_cls.return_value = mock_db

        result = runner.invoke(show_handler, ['test-repo'])
        assert result.exit_code == 0
        assert 'Yes' in result.output


class TestQueryDefaultColumns:
    """Test that query command uses improved default columns."""

    def test_display_pretty_defaults(self):
        """Default columns include path, language, is_clean, description."""
        from repoindex.commands.query import _display_pretty_results
        from io import StringIO
        from rich.console import Console

        results = [
            {
                'name': 'myrepo',
                'path': '/home/user/github/myrepo',
                'language': 'Python',
                'is_clean': True,
                'description': 'A cool project',
                'branch': 'main',
            },
        ]

        buf = StringIO()
        console = Console(file=buf)
        with patch('rich.console.Console', return_value=console):
            _display_pretty_results(results, fields=None)

        output = buf.getvalue()
        assert 'myrepo' in output
        assert 'Python' in output
        assert 'Clean' in output
        assert 'Description' in output

    def test_display_pretty_with_custom_fields(self):
        """Custom --fields overrides default columns."""
        from repoindex.commands.query import _display_pretty_results
        from io import StringIO
        from rich.console import Console

        results = [
            {
                'name': 'myrepo',
                'path': '/home/user/github/myrepo',
                'language': 'Python',
                'branch': 'main',
                'remote_url': 'https://github.com/user/myrepo',
            },
        ]

        buf = StringIO()
        console = Console(file=buf)
        with patch('rich.console.Console', return_value=console):
            _display_pretty_results(results, fields='branch,remote_url')

        output = buf.getvalue()
        assert 'main' in output
        assert 'github.com' in output

    def test_display_pretty_clean_status_rendering(self):
        """Clean status renders as yes/no in pretty output."""
        from repoindex.commands.query import _display_pretty_results
        from io import StringIO
        from rich.console import Console

        results = [
            {'name': 'clean-repo', 'path': '/tmp/clean', 'language': 'Go', 'is_clean': True, 'description': ''},
            {'name': 'dirty-repo', 'path': '/tmp/dirty', 'language': 'Go', 'is_clean': False, 'description': ''},
        ]

        buf = StringIO()
        console = Console(file=buf, no_color=True)
        with patch('rich.console.Console', return_value=console):
            _display_pretty_results(results, fields=None)

        output = buf.getvalue()
        assert 'yes' in output
        assert 'no' in output

    def test_display_pretty_description_truncation(self):
        """Long descriptions get truncated."""
        from repoindex.commands.query import _display_pretty_results
        from io import StringIO
        from rich.console import Console

        results = [
            {
                'name': 'myrepo',
                'path': '/tmp/myrepo',
                'language': 'Python',
                'is_clean': True,
                'description': 'A' * 100,
            },
        ]

        buf = StringIO()
        console = Console(file=buf)
        with patch('rich.console.Console', return_value=console):
            _display_pretty_results(results, fields=None)

        output = buf.getvalue()
        assert '...' in output

    def test_display_pretty_github_stars_conditional(self):
        """github_stars column only appears when repos have stars."""
        from repoindex.commands.query import _display_pretty_results
        from io import StringIO
        from rich.console import Console

        # No stars - column should not appear
        results_no_stars = [
            {'name': 'r1', 'path': '/tmp/r1', 'language': 'Go', 'is_clean': True,
             'description': '', 'github_stars': 0},
        ]

        buf = StringIO()
        console = Console(file=buf)
        with patch('rich.console.Console', return_value=console):
            _display_pretty_results(results_no_stars, fields=None)

        output = buf.getvalue()
        assert 'Github Stars' not in output

        # With stars - column should appear
        results_with_stars = [
            {'name': 'r1', 'path': '/tmp/r1', 'language': 'Go', 'is_clean': True,
             'description': '', 'github_stars': 42},
        ]

        buf2 = StringIO()
        console2 = Console(file=buf2)
        with patch('rich.console.Console', return_value=console2):
            _display_pretty_results(results_with_stars, fields=None)

        output2 = buf2.getvalue()
        assert '42' in output2


class TestQueryColumnsAlias:
    """Test that --columns works as an alias for --fields."""

    def test_columns_option_accepted(self, runner):
        """--columns is accepted as an alias for --fields."""
        from repoindex.commands.query import query_handler

        # Just verify the option is accepted (won't error on unknown option)
        # We mock the database to avoid actual queries
        with patch('repoindex.commands.query.load_config', return_value={}):
            with patch('repoindex.commands.query.Database') as mock_db:
                db = MagicMock()
                db.fetchall.return_value = []
                db.__enter__ = MagicMock(return_value=db)
                db.__exit__ = MagicMock(return_value=False)
                mock_db.return_value = db

                result = runner.invoke(query_handler, ['--columns', 'name,language'])
                # Should not fail with "No such option"
                assert 'No such option' not in (result.output or '')


class TestOpsQueryOptionsMinimal:
    """Test that query_options provides the 4 essential flags."""

    def test_git_status_accepts_language(self):
        """ops git status accepts --language option."""
        from repoindex.commands.ops import git_status_handler

        runner = CliRunner()
        with patch('repoindex.commands.ops.load_config', return_value={}):
            with patch('repoindex.commands.ops._get_repos_from_query', return_value=[]):
                result = runner.invoke(git_status_handler, ['--language', 'python'])
                assert 'No such option' not in (result.output or '')

    def test_removed_flags_are_gone(self):
        """Removed flags like --name, --has-remote should not be accepted."""
        from repoindex.commands.ops import git_status_handler

        runner = CliRunner()
        result = runner.invoke(git_status_handler, ['--has-remote'])
        assert result.exit_code != 0
