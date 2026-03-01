"""Tests for the MCP server tools."""
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_db():
    """Mock Database that works as context manager."""
    db = MagicMock()
    return db


@pytest.fixture
def patch_db(mock_db):
    """Patch Database class and load_config for MCP server tests.

    Yields the mock_db so tests can configure fetchone/fetchall etc.
    """
    with patch('repoindex.mcp.server.Database') as MockDB:
        MockDB.return_value.__enter__ = MagicMock(return_value=mock_db)
        MockDB.return_value.__exit__ = MagicMock(return_value=False)
        with patch('repoindex.mcp.server.load_config', return_value={}):
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
        patch_db.fetchall.side_effect = [[], []]
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table='nonexistent')
        assert result['ddl'] == []

    def test_invalid_table_name_rejected(self, patch_db):
        """SQL injection via crafted table name is rejected."""
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table="repos; DROP TABLE repos")
        assert 'error' in result
        assert 'Invalid table name' in result['error']
        # DB should never be queried
        patch_db.execute.assert_not_called()

    def test_invalid_table_name_with_parens(self, patch_db):
        """Table names with parentheses are rejected."""
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table="repos()")
        assert 'error' in result


class TestRunSql:
    def test_select(self, patch_db):
        patch_db.fetchall.return_value = [{'name': 'repoindex', 'language': 'Python'}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELECT name, language FROM repos")
        assert result['rows'] == [{'name': 'repoindex', 'language': 'Python'}]

    def test_cte(self, patch_db):
        patch_db.fetchall.return_value = [{'cnt': 5}]
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
        patch_db.fetchall.return_value = [{'id': i} for i in range(600)]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELECT id FROM repos")
        assert len(result['rows']) == 500
        assert result['truncated'] is True
        assert result['total_count'] == 600
        assert result['row_count'] == 500

    def test_total_count_when_not_truncated(self, patch_db):
        patch_db.fetchall.return_value = [{'id': i} for i in range(10)]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELECT id FROM repos")
        assert result['truncated'] is False
        assert result['total_count'] == 10
        assert result['row_count'] == 10

    def test_rejects_update(self):
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("UPDATE repos SET name = 'x'")
        assert 'error' in result

    def test_case_insensitive_select(self, patch_db):
        """SELECT keyword is case-insensitive."""
        patch_db.fetchall.return_value = [{'cnt': 1}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("select count(*) as cnt from repos")
        assert 'rows' in result

    def test_leading_whitespace(self, patch_db):
        """Leading whitespace before SELECT is accepted."""
        patch_db.fetchall.return_value = [{'cnt': 1}]
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("  SELECT count(*) as cnt FROM repos")
        assert 'rows' in result


class TestRefresh:
    def test_runs_subprocess(self):
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Refreshed 42 repos', stderr='')
            from repoindex.mcp.server import _refresh_impl
            result = _refresh_impl()
        assert result['status'] == 'ok'
        assert '42' in result['output']

    def test_with_flags(self):
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='Done', stderr='')
            from repoindex.mcp.server import _refresh_impl
            _refresh_impl(github=True, full=True)
        cmd = mock_run.call_args[0][0]
        assert '--github' in cmd
        assert '--full' in cmd

    def test_failure(self):
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='Config not found')
            from repoindex.mcp.server import _refresh_impl
            result = _refresh_impl()
        assert result['status'] == 'error'

    def test_timeout(self):
        with patch('repoindex.mcp.server.subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired('repoindex', 300)
            from repoindex.mcp.server import _refresh_impl
            result = _refresh_impl()
        assert result['status'] == 'error'
        assert 'timed out' in result['error'].lower()


class TestMcpCli:
    def test_mcp_command_registered(self):
        from click.testing import CliRunner
        from repoindex.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ['mcp', '--help'])
        assert result.exit_code == 0
        assert 'MCP server' in result.output
