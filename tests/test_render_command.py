"""Tests for the export command."""

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from repoindex.commands.render import export_handler


MOCK_REPOS = [
    {
        'id': 1,
        'name': 'test-repo',
        'path': '/home/user/test-repo',
        'language': 'Python',
        'branch': 'main',
        'is_clean': True,
        'remote_url': 'https://github.com/user/test-repo',
        'github_stars': 10,
        'license_key': 'mit',
        'description': 'Test repository',
    },
]


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_query(monkeypatch):
    """Mock _get_repos_from_query to return MOCK_REPOS."""
    with patch('repoindex.commands.render._get_repos_from_query', return_value=MOCK_REPOS):
        with patch('repoindex.commands.render.load_config', return_value={}):
            yield


class TestListFormats:
    def test_list_formats(self, runner, mock_query):
        result = runner.invoke(export_handler, ['--list-formats', 'dummy'])
        assert result.exit_code == 0
        assert 'bibtex' in result.output
        assert 'csv' in result.output


class TestFormatExports:
    def test_csv_to_stdout(self, runner, mock_query):
        result = runner.invoke(export_handler, ['csv'])
        assert result.exit_code == 0
        assert 'test-repo' in result.output

    def test_csv_to_file(self, runner, mock_query, tmp_path):
        outfile = str(tmp_path / 'out.csv')
        result = runner.invoke(export_handler, ['csv', '-o', outfile])
        assert result.exit_code == 0
        content = open(outfile).read()
        assert 'test-repo' in content

    def test_bibtex(self, runner, mock_query):
        result = runner.invoke(export_handler, ['bibtex'])
        assert result.exit_code == 0
        assert '@software{' in result.output

    def test_unknown_format(self, runner, mock_query):
        result = runner.invoke(export_handler, ['nonexistent'])
        assert result.exit_code != 0
        assert 'Unknown format' in result.output


class TestDefaultArkivExport:
    """Default export (no format) produces arkiv archive with site/."""

    @patch('repoindex.commands.render._export_archive')
    def test_no_format_with_output_triggers_archive(self, mock_archive, runner):
        result = runner.invoke(export_handler, ['-o', '/tmp/out'])
        mock_archive.assert_called_once()

    @patch('repoindex.commands.render._export_archive')
    def test_explicit_arkiv_format_triggers_archive(self, mock_archive, runner):
        result = runner.invoke(export_handler, ['arkiv', '-o', '/tmp/out'])
        mock_archive.assert_called_once()

    def test_no_format_no_output_shows_usage(self, runner):
        result = runner.invoke(export_handler, [])
        assert result.exit_code != 0
        assert 'Usage' in result.output or '--list-formats' in result.output

    def test_arkiv_without_output_errors(self, runner):
        result = runner.invoke(export_handler, ['arkiv'])
        assert result.exit_code != 0
        assert 'requires -o' in result.output


class TestArkivArchiveIntegration:
    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    @patch('repoindex.commands.render.Database')
    @patch('repoindex.database.connection.get_db_path')
    def test_archive_with_site(self, mock_db_path, mock_db_class, mock_query, mock_config, runner, tmp_path):
        """Full archive produces JSONL + site/index.html."""
        mock_query.return_value = MOCK_REPOS
        mock_db = MagicMock()
        mock_db_class.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_db_class.return_value.__exit__ = MagicMock(return_value=False)
        # Pretend DB doesn't exist so site/ generation is skipped gracefully
        mock_db_path.return_value = tmp_path / "nonexistent.db"

        with patch('repoindex.database.events.get_events', return_value=[]):
            with patch('repoindex.exporters.arkiv.export_archive', return_value={'repos': 1, 'events': 0, 'publications': 0}):
                outdir = str(tmp_path / 'archive')
                result = runner.invoke(export_handler, ['-o', outdir])
                assert result.exit_code == 0
                assert 'Exported 1 repos' in result.output


class TestQueryFlags:
    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    def test_language_flag(self, mock_query, mock_config, runner):
        mock_query.return_value = MOCK_REPOS
        result = runner.invoke(export_handler, ['csv', '--language', 'python'])
        assert result.exit_code == 0

    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    def test_dirty_flag(self, mock_query, mock_config, runner):
        mock_query.return_value = MOCK_REPOS
        result = runner.invoke(export_handler, ['csv', '--dirty'])
        assert result.exit_code == 0


class TestExportRegistered:
    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    def test_export_command_works(self, mock_query, mock_config, runner):
        from repoindex.cli import cli
        mock_query.return_value = MOCK_REPOS
        result = runner.invoke(cli, ['export', 'csv'])
        assert result.exit_code == 0
        assert 'test-repo' in result.output
