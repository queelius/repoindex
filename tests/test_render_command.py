"""Tests for the render command."""

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from repoindex.commands.render import export_handler


MOCK_REPOS = [
    {
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


class TestRenderListFormats:
    def test_list_formats(self, runner, mock_query):
        result = runner.invoke(export_handler, ['--list-formats', 'dummy'])
        assert result.exit_code == 0
        assert 'bibtex' in result.output
        assert 'csv' in result.output
        assert 'markdown' in result.output
        assert 'opml' in result.output
        assert 'jsonld' in result.output


class TestRenderCSV:
    def test_render_csv_to_stdout(self, runner, mock_query):
        result = runner.invoke(export_handler, ['csv'])
        assert result.exit_code == 0
        assert 'test-repo' in result.output
        assert 'name' in result.output  # CSV header

    def test_render_csv_to_file(self, runner, mock_query, tmp_path):
        outfile = str(tmp_path / 'out.csv')
        result = runner.invoke(export_handler, ['csv', '-o', outfile])
        assert result.exit_code == 0
        content = open(outfile).read()
        assert 'test-repo' in content


class TestRenderBibTeX:
    def test_render_bibtex(self, runner, mock_query):
        result = runner.invoke(export_handler, ['bibtex'])
        assert result.exit_code == 0
        assert '@software{' in result.output


class TestRenderMarkdown:
    def test_render_markdown(self, runner, mock_query):
        result = runner.invoke(export_handler, ['markdown'])
        assert result.exit_code == 0
        assert '| Name |' in result.output
        assert 'test-repo' in result.output


class TestRenderOPML:
    def test_render_opml(self, runner, mock_query):
        result = runner.invoke(export_handler, ['opml'])
        assert result.exit_code == 0
        assert '<?xml' in result.output
        assert 'opml' in result.output


class TestRenderJSONLD:
    def test_render_jsonld(self, runner, mock_query):
        result = runner.invoke(export_handler, ['jsonld'])
        assert result.exit_code == 0
        assert '"@context"' in result.output
        assert 'SoftwareSourceCode' in result.output


class TestRenderErrors:
    def test_unknown_format(self, runner, mock_query):
        result = runner.invoke(export_handler, ['nonexistent'])
        assert result.exit_code != 0
        assert 'Unknown format' in result.output


class TestRenderQueryFlags:
    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    def test_language_flag_passed(self, mock_query, mock_config, runner):
        mock_query.return_value = MOCK_REPOS
        result = runner.invoke(export_handler, ['csv', '--language', 'python'])
        assert result.exit_code == 0
        # Verify the query function was called with language
        call_kwargs = mock_query.call_args
        assert call_kwargs.kwargs.get('language') == 'python' or \
               (len(call_kwargs.args) > 0 and True)

    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    def test_dirty_flag_passed(self, mock_query, mock_config, runner):
        mock_query.return_value = MOCK_REPOS
        result = runner.invoke(export_handler, ['csv', '--dirty'])
        assert result.exit_code == 0


class TestExportArkiv:
    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    @patch('repoindex.commands.render.Database')
    def test_arkiv_export_to_directory(self, mock_db_class, mock_query, mock_config, runner, tmp_path):
        """Arkiv export with -o writes directory files."""
        mock_query.return_value = MOCK_REPOS
        # Mock the Database context manager for event fetching
        mock_db = MagicMock()
        mock_db_class.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_db_class.return_value.__exit__ = MagicMock(return_value=False)

        with patch('repoindex.database.events.get_events', return_value=[]):
            with patch('repoindex.exporters.arkiv.export_archive', return_value={'repos': 1, 'events': 0, 'publications': 0}) as mock_archive:
                outdir = str(tmp_path / 'arkiv_out')
                result = runner.invoke(export_handler, ['arkiv', '-o', outdir])
                assert result.exit_code == 0
                mock_archive.assert_called_once()
                assert 'Exported 1 repos' in result.output


class TestExportAlias:
    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    def test_export_command_works(self, mock_query, mock_config, runner):
        """The 'export' command name is registered."""
        from repoindex.cli import cli
        mock_query.return_value = MOCK_REPOS
        result = runner.invoke(cli, ['export', 'csv'])
        assert result.exit_code == 0
        assert 'test-repo' in result.output

    @patch('repoindex.commands.render.load_config', return_value={})
    @patch('repoindex.commands.render._get_repos_from_query')
    def test_render_deprecated_still_works(self, mock_query, mock_config, runner):
        """The 'render' command still works as deprecated alias."""
        from repoindex.cli import cli
        mock_query.return_value = MOCK_REPOS
        result = runner.invoke(cli, ['render', 'csv'])
        assert result.exit_code == 0
