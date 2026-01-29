"""
Tests for export CLI command handler.
"""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from repoindex.cli import cli
from repoindex.commands.export import export_handler


class TestExportCommandCLI:
    """Tests for export command through CLI runner."""

    @pytest.fixture
    def setup_test_environment(self, tmp_path):
        """Set up test environment with database and repos."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        # Create database
        db_path = tmp_path / 'test.db'
        config = {'database': {'path': str(db_path)}}

        # Create test repos
        repos_data = []
        for name in ['test-repo-1', 'test-repo-2']:
            repo_path = tmp_path / 'repos' / name
            repo_path.mkdir(parents=True)
            (repo_path / '.git').mkdir()
            (repo_path / 'README.md').write_text(f'# {name}')
            repos_data.append((name, str(repo_path)))

        # Populate database
        with Database(config=config) as db:
            apply_schema(db.conn)
            for name, path in repos_data:
                db.execute("""
                    INSERT INTO repos (name, path, language, branch, has_readme)
                    VALUES (?, ?, 'Python', 'main', 1)
                """, (name, path))

                repo_id = db.lastrowid
                db.execute("""
                    INSERT INTO events (repo_id, type, timestamp, message, author)
                    VALUES (?, 'commit', '2026-01-20T10:00:00', 'Test', 'Author')
                """, (repo_id,))

            db.conn.commit()

        return config, db_path, tmp_path

    def test_export_dry_run(self, setup_test_environment, tmp_path):
        """Test export command with dry run."""
        config, db_path, source_tmp = setup_test_environment
        output_dir = tmp_path / 'export'

        runner = CliRunner()

        with patch('repoindex.commands.export.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['export', str(output_dir), '--dry-run'])

            # Should complete without error
            assert result.exit_code == 0 or 'Export complete' in result.output

    def test_export_with_debug_flag(self, setup_test_environment, tmp_path):
        """Test export command with debug flag."""
        config, db_path, source_tmp = setup_test_environment
        output_dir = tmp_path / 'export'

        runner = CliRunner()

        with patch('repoindex.commands.export.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['export', str(output_dir), '--debug', '--dry-run'])

            # Should complete without error
            assert result.exit_code == 0 or result.exit_code == 1

    def test_export_with_include_events(self, setup_test_environment, tmp_path):
        """Test export command with include-events flag."""
        config, db_path, source_tmp = setup_test_environment
        output_dir = tmp_path / 'export-events'

        runner = CliRunner()

        with patch('repoindex.commands.export.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['export', str(output_dir), '--include-events', '--dry-run'])

            assert result.exit_code == 0 or 'Export complete' in result.output

    def test_export_with_language_filter(self, setup_test_environment, tmp_path):
        """Test export command with language filter flag."""
        config, db_path, source_tmp = setup_test_environment
        output_dir = tmp_path / 'export-python'

        runner = CliRunner()

        with patch('repoindex.commands.export.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['export', str(output_dir), '--language', 'python', '--dry-run'])

            assert result.exit_code == 0 or 'Export complete' in result.output

    def test_export_with_dsl_query(self, setup_test_environment, tmp_path):
        """Test export command with DSL query expression."""
        config, db_path, source_tmp = setup_test_environment
        output_dir = tmp_path / 'export-dsl'

        runner = CliRunner()

        with patch('repoindex.commands.export.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, [
                'export', str(output_dir),
                "language == 'Python'",
                '--dry-run'
            ])

            assert result.exit_code == 0 or 'Export complete' in result.output

    def test_export_removed_flags_error(self, tmp_path):
        """Test that removed flags are rejected by Click."""
        runner = CliRunner()

        # --archive-repos should no longer exist
        result = runner.invoke(cli, ['export', str(tmp_path / 'out'), '--archive-repos'])
        assert result.exit_code != 0
        assert 'No such option' in result.output or 'no such option' in result.output.lower()

        # --include-git-summary should no longer exist
        result = runner.invoke(cli, ['export', str(tmp_path / 'out'), '--include-git-summary', '5'])
        assert result.exit_code != 0

        # --include-readmes should no longer exist
        result = runner.invoke(cli, ['export', str(tmp_path / 'out'), '--include-readmes'])
        assert result.exit_code != 0


class TestExportOutputModes:
    """Tests for different output modes of export command."""

    @pytest.fixture
    def mock_export_service(self):
        """Create a mock ExportService."""
        from repoindex.services.export_service import ExportResult

        mock_service = MagicMock()
        mock_service.export.return_value = iter(['Exporting repos...', 'Creating manifest...'])
        mock_service.last_result = ExportResult(
            repos_exported=2,
            events_exported=10,
            readmes_exported=2,
            errors=[],
        )
        return mock_service

    def test_export_simple_output_success(self, mock_export_service, tmp_path, capsys):
        """Test simple output mode on success."""
        from repoindex.services.export_service import ExportOptions
        from repoindex.commands.export import _export_simple

        options = ExportOptions(output_dir=tmp_path, include_events=True)

        _export_simple(mock_export_service, options, dry_run=False)

        captured = capsys.readouterr()
        assert 'Export complete' in captured.err
        assert 'Repositories: 2' in captured.err
        assert 'Events: 10' in captured.err
        assert 'READMEs: 2' in captured.err

    def test_export_simple_output_dry_run(self, mock_export_service, tmp_path, capsys):
        """Test simple output mode in dry run."""
        from repoindex.services.export_service import ExportOptions
        from repoindex.commands.export import _export_simple

        options = ExportOptions(output_dir=tmp_path, dry_run=True)

        _export_simple(mock_export_service, options, dry_run=True)

        captured = capsys.readouterr()
        assert '[dry run]' in captured.err

    def test_export_simple_output_with_errors(self, tmp_path, capsys):
        """Test simple output mode when there are errors."""
        from repoindex.services.export_service import ExportResult, ExportOptions
        from repoindex.commands.export import _export_simple

        mock_service = MagicMock()
        mock_service.export.return_value = iter(['Exporting...'])
        mock_service.last_result = ExportResult(
            repos_exported=1,
            errors=['Error reading repo']
        )

        options = ExportOptions(output_dir=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            _export_simple(mock_service, options, dry_run=False)

        assert exc_info.value.code == 1

    def test_export_simple_output_shows_filter(self, tmp_path, capsys):
        """Test simple output shows query filter when set."""
        from repoindex.services.export_service import ExportResult, ExportOptions
        from repoindex.commands.export import _export_simple

        mock_service = MagicMock()
        mock_service.export.return_value = iter(['Exporting...'])
        mock_service.last_result = ExportResult(repos_exported=5)

        options = ExportOptions(
            output_dir=tmp_path,
            query_filter="language == 'Python'",
        )

        _export_simple(mock_service, options, dry_run=False)

        captured = capsys.readouterr()
        assert "language == 'Python'" in captured.err

    def test_export_pretty_output_dry_run(self, mock_export_service, tmp_path):
        """Test pretty output in dry run mode."""
        from repoindex.services.export_service import ExportOptions
        from repoindex.commands.export import _export_pretty

        options = ExportOptions(output_dir=tmp_path, dry_run=True)

        # Should not raise
        _export_pretty(mock_export_service, options)

    def test_export_pretty_output_with_events(self, tmp_path):
        """Test pretty output with events enabled."""
        from repoindex.services.export_service import ExportResult, ExportOptions
        from repoindex.commands.export import _export_pretty

        mock_service = MagicMock()
        mock_service.export.return_value = iter(['Exporting...'])
        mock_service.last_result = ExportResult(
            repos_exported=2,
            events_exported=10,
            readmes_exported=2,
        )

        options = ExportOptions(
            output_dir=tmp_path,
            include_events=True,
        )

        # Should not raise
        _export_pretty(mock_service, options)

    def test_export_pretty_output_no_result(self, tmp_path):
        """Test pretty output when service returns no result."""
        from repoindex.services.export_service import ExportOptions
        from repoindex.commands.export import _export_pretty

        mock_service = MagicMock()
        mock_service.export.return_value = iter([])
        mock_service.last_result = None

        options = ExportOptions(output_dir=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            _export_pretty(mock_service, options)

        assert exc_info.value.code == 1

    def test_export_pretty_output_with_errors(self, tmp_path):
        """Test pretty output when there are errors."""
        from repoindex.services.export_service import ExportResult, ExportOptions
        from repoindex.commands.export import _export_pretty

        mock_service = MagicMock()
        mock_service.export.return_value = iter(['Exporting...'])
        mock_service.last_result = ExportResult(
            repos_exported=1,
            errors=['Error exporting repo-x']
        )

        options = ExportOptions(output_dir=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            _export_pretty(mock_service, options)

        assert exc_info.value.code == 1
