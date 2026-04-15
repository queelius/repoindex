"""Tests for the MCP server tools."""
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_db():
    """Mock database connection."""
    return MagicMock()


@pytest.fixture
def patch_db(mock_db):
    """Patch _open_db to yield a mock db and empty config.

    Yields the mock_db so tests can configure fetchone/fetchall/fetchmany etc.
    """
    @contextmanager
    def _fake_open_db():
        yield mock_db, {}

    with patch('repoindex.mcp.server._open_db', _fake_open_db):
        yield mock_db


class TestGetManifest:
    def test_structure(self, patch_db):
        patch_db.fetchone.side_effect = [
            {'count': 143}, {'count': 2841}, {'count': 312}, {'count': 28},
        ]
        patch_db.fetchall.side_effect = [
            [{'language': 'Python', 'cnt': 45}, {'language': 'R', 'cnt': 12}],
            [{'started_at': '2026-02-28T10:00:00'}],
        ]
        with patch('repoindex.mcp.server.get_db_path', return_value=Path('/fake/path')):
            from repoindex.mcp.server import _get_manifest_impl
            result = _get_manifest_impl()
        assert result['tables']['repos']['row_count'] == 143
        assert result['tables']['events']['row_count'] == 2841
        assert result['tables']['tags']['row_count'] == 312
        assert result['tables']['publications']['row_count'] == 28
        assert 'languages' in result['summary']
        assert result['summary']['languages']['Python'] == 45

    def test_empty_db(self, patch_db):
        patch_db.fetchone.side_effect = [
            {'count': 0}, {'count': 0}, {'count': 0}, {'count': 0},
        ]
        patch_db.fetchall.side_effect = [[], []]
        with patch('repoindex.mcp.server.get_db_path', return_value=Path('/fake/path')):
            from repoindex.mcp.server import _get_manifest_impl
            result = _get_manifest_impl()
        assert result['tables']['repos']['row_count'] == 0
        assert result['summary']['last_refresh'] is None


class TestGetSchema:
    def test_all_tables(self, patch_db):
        patch_db.fetchall.return_value = [
            {'sql': 'CREATE TABLE repos (id INTEGER PRIMARY KEY)'},
            {'sql': 'CREATE TABLE events (id INTEGER PRIMARY KEY)'},
        ]
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl()
        assert len(result['ddl']) == 2

    def test_single_table(self, patch_db):
        patch_db.fetchall.side_effect = [
            [{'sql': 'CREATE TABLE repos (id INTEGER PRIMARY KEY, name TEXT)'}],
            [{'cid': 0, 'name': 'id', 'type': 'INTEGER', 'notnull': 0, 'dflt_value': None, 'pk': 1},
             {'cid': 1, 'name': 'name', 'type': 'TEXT', 'notnull': 1, 'dflt_value': None, 'pk': 0}],
        ]
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table='repos')
        assert result['table'] == 'repos'
        assert result['columns'][0]['name'] == 'id'

    def test_unknown_table(self, patch_db):
        patch_db.fetchall.return_value = []
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table='nonexistent')
        assert 'error' in result
        assert 'not found' in result['error'].lower()

    def test_invalid_table_name_rejected(self, patch_db):
        """SQL injection via crafted table name is rejected."""
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table="repos; DROP TABLE repos")
        assert 'error' in result
        assert 'Invalid table name' in result['error']
        patch_db.execute.assert_not_called()

    def test_invalid_table_name_with_parens(self, patch_db):
        """Table names with parentheses are rejected."""
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table="repos()")
        assert 'error' in result


class TestRunSql:
    def test_select(self, patch_db):
        patch_db.fetchmany.return_value = [{'name': 'repoindex', 'language': 'Python'}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELECT name, language FROM repos")
        assert result['rows'] == [{'name': 'repoindex', 'language': 'Python'}]

    def test_cte(self, patch_db):
        patch_db.fetchmany.return_value = [{'cnt': 5}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("WITH x AS (SELECT 1) SELECT COUNT(*) as cnt FROM repos")
        assert 'rows' in result

    def test_rejects_insert(self):
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("INSERT INTO repos (name, path) VALUES ('x', '/x')")
        assert 'error' in result

    def test_rejects_drop(self):
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("DROP TABLE repos")
        assert 'error' in result

    def test_rejects_delete(self):
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("DELETE FROM repos")
        assert 'error' in result

    def test_syntax_error(self, patch_db):
        from sqlite3 import OperationalError
        patch_db.execute.side_effect = OperationalError("syntax error")
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELCT * FROM repos")
        assert 'error' in result

    def test_row_limit(self, patch_db):
        patch_db.fetchmany.return_value = [{'id': i} for i in range(501)]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELECT id FROM repos")
        assert len(result['rows']) == 500
        assert result['truncated'] is True
        assert result['row_count'] == 500

    def test_not_truncated(self, patch_db):
        patch_db.fetchmany.return_value = [{'id': i} for i in range(10)]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELECT id FROM repos")
        assert result['truncated'] is False
        assert result['row_count'] == 10

    def test_rejects_update(self):
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("UPDATE repos SET name = 'x'")
        assert 'error' in result

    def test_case_insensitive_select(self, patch_db):
        """SELECT keyword is case-insensitive."""
        patch_db.fetchmany.return_value = [{'cnt': 1}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("select count(*) as cnt from repos")
        assert 'rows' in result

    def test_leading_whitespace(self, patch_db):
        """Leading whitespace before SELECT is accepted."""
        patch_db.fetchmany.return_value = [{'cnt': 1}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("  SELECT count(*) as cnt FROM repos")
        assert 'rows' in result


class TestRefresh:
    def test_runs_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Refreshed 42 repos', stderr='')
            from repoindex.mcp.server import _refresh_impl
            result = _refresh_impl()
        assert result['status'] == 'ok'
        assert '42' in result['output']

    def test_with_flags(self, tmp_path, monkeypatch):
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Done', stderr='')
            from repoindex.mcp.server import _refresh_impl
            _refresh_impl(github=True, full=True)
        cmd = mock_run.call_args[0][0]
        assert '--github' in cmd
        assert '--full' in cmd

    def test_with_pypi_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Done', stderr='')
            from repoindex.mcp.server import _refresh_impl
            _refresh_impl(pypi=True)
        cmd = mock_run.call_args[0][0]
        assert '--source' in cmd
        assert 'pypi' in cmd

    def test_with_cran_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Done', stderr='')
            from repoindex.mcp.server import _refresh_impl
            _refresh_impl(cran=True)
        cmd = mock_run.call_args[0][0]
        assert '--source' in cmd
        assert 'cran' in cmd

    def test_with_external_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Done', stderr='')
            from repoindex.mcp.server import _refresh_impl
            _refresh_impl(external=True)
        cmd = mock_run.call_args[0][0]
        assert '--external' in cmd

    def test_with_all_sources(self, tmp_path, monkeypatch):
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Done', stderr='')
            from repoindex.mcp.server import _refresh_impl
            _refresh_impl(github=True, pypi=True, cran=True)
        cmd = mock_run.call_args[0][0]
        assert '--github' in cmd
        # Two --source pairs (pypi + cran)
        assert cmd.count('--source') == 2
        assert 'pypi' in cmd
        assert 'cran' in cmd

    def test_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='Config not found')
            from repoindex.mcp.server import _refresh_impl
            result = _refresh_impl()
        assert result['status'] == 'error'

    def test_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired('repoindex', 300)
            from repoindex.mcp.server import _refresh_impl
            result = _refresh_impl()
        assert result['status'] == 'error'
        assert 'timed out' in result['error'].lower()

    def test_concurrent_refresh_returns_error(self, tmp_path, monkeypatch):
        """Two simultaneous refreshes — second should fail with lock error."""
        import fcntl
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)

        # Acquire the lock manually to simulate another refresh in progress
        lock_path = tmp_path / '.repoindex' / 'refresh.lock'
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        f = open(lock_path, 'w')
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            from repoindex.mcp.server import _refresh_impl
            result = _refresh_impl()
            assert result['status'] == 'error'
            assert 'already running' in result['error'].lower()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()

    def test_refresh_lock_failure_closes_fd(self, tmp_path, monkeypatch):
        """Non-BlockingIOError during flock must not leak the lock file descriptor.

        Regression: code review found that if fcntl.flock raised OSError (e.g.,
        EIO on NFS), the fd was opened but never closed.
        """
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)

        opened_files = []
        real_open = open

        def tracking_open(path, *args, **kwargs):
            f = real_open(path, *args, **kwargs)
            opened_files.append(f)
            return f

        with patch('repoindex.mcp.server.open', tracking_open), \
             patch('repoindex.mcp.server.fcntl.flock',
                   side_effect=OSError(5, 'Input/output error')):
            from repoindex.mcp.server import _refresh_impl
            result = _refresh_impl()

        assert result['status'] == 'error'
        assert 'lock' in result['error'].lower()
        # The lock fd must be closed even though acquisition raised a non-
        # BlockingIOError; otherwise we leak one fd per failed attempt.
        for f in opened_files:
            assert f.closed, f'lock fd {f.name} was not closed'


class TestTag:
    def test_list_tags(self, patch_db):
        patch_db.fetchall.return_value = [
            {'tag': 'lang:python', 'source': 'implicit'},
            {'tag': 'work/active', 'source': 'user'},
        ]
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('myrepo', 'list')
        assert result['count'] == 2
        assert result['tags'][0]['tag'] == 'lang:python'

    def test_list_all_tags(self, patch_db):
        patch_db.fetchall.return_value = [{'tag': 'lang:python', 'source': 'implicit'}]
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('', 'list')
        assert 'tags' in result

    def test_add_tag(self):
        from repoindex.mcp.server import _tag_impl
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
            result = _tag_impl('myrepo', 'add', 'work/active')
        assert result['status'] == 'ok'
        assert result['action'] == 'add'
        cmd = mock_run.call_args[0][0]
        assert cmd == ['repoindex', 'tag', 'add', 'myrepo', 'work/active']

    def test_remove_tag(self):
        from repoindex.mcp.server import _tag_impl
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
            result = _tag_impl('myrepo', 'remove', 'old-tag')
        assert result['status'] == 'ok'

    def test_invalid_action(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('myrepo', 'invalid')
        assert 'error' in result

    def test_add_without_tag_errors(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('myrepo', 'add', '')
        assert 'error' in result

    def test_add_failure(self):
        from repoindex.mcp.server import _tag_impl
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='Repo not found')
            result = _tag_impl('nonexistent', 'add', 'x')
        assert result['status'] == 'error'

    def test_tag_add_rejects_empty_repo(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('', 'add', 'sometag')
        assert 'error' in result

    def test_tag_add_rejects_whitespace_repo(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('   ', 'add', 'sometag')
        assert 'error' in result

    def test_tag_remove_rejects_empty_repo(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('', 'remove', 'sometag')
        assert 'error' in result

    def test_tag_rejects_flag_like_repo(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('--help', 'add', 'tag')
        assert 'error' in result
        assert '-' in result['error']

    def test_tag_rejects_flag_like_tag(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('repo', 'add', '--force')
        assert 'error' in result
        assert '-' in result['error']

    def test_tag_remove_rejects_flag_like_args(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('-repo', 'remove', 'tag')
        assert 'error' in result

    def test_tag_rejects_whitespace_only_tag(self):
        from repoindex.mcp.server import _tag_impl
        result = _tag_impl('repo', 'add', '   ')
        assert 'error' in result


class TestExport:
    def test_export_success(self, tmp_path):
        from repoindex.mcp.server import _export_impl
        target = tmp_path / 'new_out'  # does not exist yet
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='Exported 42 repos', stderr=''
            )
            result = _export_impl(str(target))
        assert result['status'] == 'ok'
        assert '42' in result['output']
        cmd = mock_run.call_args[0][0]
        assert cmd == ['repoindex', 'export', '-o', str(target.resolve())]

    def test_export_with_query(self, tmp_path):
        from repoindex.mcp.server import _export_impl
        target = tmp_path / 'new_out'
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Done', stderr='')
            _export_impl(str(target), "language == 'Python'")
        cmd = mock_run.call_args[0][0]
        # Must pass 'arkiv' explicitly so click doesn't parse query as FORMAT_ID
        assert cmd == [
            'repoindex', 'export', 'arkiv', "language == 'Python'",
            '-o', str(target.resolve()),
        ]

    def test_export_failure(self, tmp_path):
        from repoindex.mcp.server import _export_impl
        target = tmp_path / 'new_out'
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='DB not found')
            result = _export_impl(str(target))
        assert result['status'] == 'error'

    def test_export_timeout(self, tmp_path):
        from repoindex.mcp.server import _export_impl
        target = tmp_path / 'new_out'
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired('repoindex', 120)
            result = _export_impl(str(target))
        assert result['status'] == 'error'
        assert 'timed out' in result['error'].lower()

    def test_export_rejects_existing_non_archive_dir(self, tmp_path):
        """Export refuses to clobber a non-empty directory that isn't an arkiv archive."""
        from repoindex.mcp.server import _export_impl
        # Create a directory with random content (not an arkiv archive)
        (tmp_path / 'random.txt').write_text('hello')
        result = _export_impl(str(tmp_path))
        assert result['status'] == 'error'
        assert (
            'arkiv' in result['error'].lower()
            or 'empty' in result['error'].lower()
            or 'readme' in result['error'].lower()
        )

    def test_export_rejects_sensitive_dirs(self, monkeypatch, tmp_path):
        """Export refuses to write to ~/.ssh, ~/.gnupg, etc."""
        from repoindex.mcp.server import _export_impl
        # Point Path.home() at our fake home so test is hermetic
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        result = _export_impl(str(tmp_path / '.ssh' / 'foo'))
        assert result['status'] == 'error'
        assert 'sensitive' in result['error'].lower()

    def test_export_rejects_gnupg_dir(self, monkeypatch, tmp_path):
        from repoindex.mcp.server import _export_impl
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        result = _export_impl(str(tmp_path / '.gnupg' / 'backup'))
        assert result['status'] == 'error'
        assert 'sensitive' in result['error'].lower()

    def test_export_allows_new_directory(self, tmp_path):
        """Export succeeds when output_dir does not exist yet."""
        from repoindex.mcp.server import _export_impl
        new_dir = str(tmp_path / 'new_archive')
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='ok', stderr='')
            result = _export_impl(new_dir)
        assert result['status'] == 'ok'

    def test_export_allows_empty_existing_directory(self, tmp_path):
        """Export allows existing empty directory."""
        from repoindex.mcp.server import _export_impl
        empty_dir = tmp_path / 'empty_archive'
        empty_dir.mkdir()
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='ok', stderr='')
            result = _export_impl(str(empty_dir))
        assert result['status'] == 'ok'

    def test_export_allows_existing_arkiv_archive(self, tmp_path):
        """Export allows overwriting an existing repoindex arkiv archive."""
        from repoindex.mcp.server import _export_impl
        archive = tmp_path / 'archive'
        archive.mkdir()
        (archive / 'README.md').write_text(
            '---\ngenerator: repoindex\nformat: arkiv\n---\n'
        )
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='ok', stderr='')
            result = _export_impl(str(archive))
        assert result['status'] == 'ok'

    def test_export_rejects_file_as_output(self, tmp_path):
        """Export rejects output_dir that is a file, not a directory."""
        from repoindex.mcp.server import _export_impl
        a_file = tmp_path / 'a_file'
        a_file.write_text('not a directory')
        result = _export_impl(str(a_file))
        assert result['status'] == 'error'
        assert 'not a directory' in result['error'].lower()

    def test_export_rejects_non_empty_dir_without_readme(self, tmp_path):
        """Export rejects dir with content but no README at all."""
        from repoindex.mcp.server import _export_impl
        target = tmp_path / 'populated'
        target.mkdir()
        (target / 'arbitrary.txt').write_text('stuff')
        result = _export_impl(str(target))
        assert result['status'] == 'error'
        assert 'readme' in result['error'].lower()

    def test_export_rejects_flag_like_query(self, tmp_path):
        """Query must not be parseable as a CLI flag by Click."""
        from repoindex.mcp.server import _export_impl
        target = tmp_path / 'new_out'
        # Must reject before subprocess.run is called — assert it never runs.
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            result = _export_impl(str(target), query='--help')
        assert result['status'] == 'error'
        assert '-' in result['error']
        mock_run.assert_not_called()


class TestSanitizeError:
    def test_sanitize_strips_home(self, monkeypatch, tmp_path):
        from repoindex.mcp.server import _sanitize_error
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        msg = f'Failed at {tmp_path}/some/path'
        result = _sanitize_error(msg)
        assert str(tmp_path) not in result
        assert '~' in result

    def test_sanitize_no_home_in_msg(self, tmp_path, monkeypatch):
        from repoindex.mcp.server import _sanitize_error
        monkeypatch.setattr('repoindex.mcp.server.Path.home', lambda: tmp_path)
        msg = 'Generic error without any path'
        assert _sanitize_error(msg) == msg


class TestSqlCommentStripping:
    def test_leading_line_comment(self, patch_db):
        """SQL with leading -- comment is accepted."""
        patch_db.fetchmany.return_value = [{'n': 1}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("-- count repos\nSELECT COUNT(*) AS n FROM repos")
        assert 'rows' in result

    def test_leading_block_comment(self, patch_db):
        """SQL with leading /* ... */ comment is accepted."""
        patch_db.fetchmany.return_value = [{'n': 1}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("/* a block comment */ SELECT COUNT(*) AS n FROM repos")
        assert 'rows' in result

    def test_multiple_leading_comments(self, patch_db):
        """Multiple stacked leading comments are stripped."""
        patch_db.fetchmany.return_value = [{'n': 1}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl(
            "-- first comment\n"
            "-- second comment\n"
            "/* block */ SELECT COUNT(*) AS n FROM repos"
        )
        assert 'rows' in result

    def test_comment_then_insert_still_rejected(self):
        """Comments don't bypass the INSERT/DROP/DELETE reject."""
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("-- sneaky\nDELETE FROM repos")
        assert 'error' in result

    def test_only_comments_rejected(self):
        """Query that contains only comments is rejected."""
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("-- only a comment")
        assert 'error' in result

    def test_unclosed_block_comment_rejected(self):
        """Unclosed block comment gets rejected (returns empty after strip)."""
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("/* never closed SELECT * FROM repos")
        assert 'error' in result


class TestMcpCli:
    def test_mcp_command_registered(self):
        from click.testing import CliRunner
        from repoindex.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ['mcp', '--help'])
        assert result.exit_code == 0
        assert 'MCP server' in result.output
