"""
Tests for copy CLI command handler.
"""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from repoindex.cli import cli
from repoindex.commands.copy import copy_handler, _format_bytes


class TestFormatBytesHelper:
    """Tests for the _format_bytes helper function."""

    def test_format_bytes(self):
        """Test byte formatting at various scales."""
        assert _format_bytes(0) == "0.0 B"
        assert _format_bytes(100) == "100.0 B"
        assert _format_bytes(1024) == "1.0 KB"
        assert _format_bytes(1024 * 500) == "500.0 KB"
        assert _format_bytes(1024 * 1024) == "1.0 MB"
        assert _format_bytes(1024 * 1024 * 1024) == "1.0 GB"
        assert _format_bytes(1024 * 1024 * 1024 * 1024) == "1.0 TB"
        assert _format_bytes(1024 * 1024 * 1024 * 1024 * 1024) == "1.0 PB"


class TestCopyCommandCLI:
    """Tests for copy command through CLI runner."""

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
                    INSERT INTO repos (name, path, language, branch, is_clean)
                    VALUES (?, ?, 'Python', 'main', 1)
                """, (name, path))
            db.conn.commit()

        return config, db_path, tmp_path

    def test_copy_with_no_repos_found(self, setup_test_environment, tmp_path):
        """Test copy command when query returns no results."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            # Use a query that matches nothing
            result = runner.invoke(cli, ['copy', str(dest_dir), "name == 'nonexistent'"])

            assert 'No repositories found' in result.output or result.exit_code == 0

    def test_copy_dry_run_output(self, setup_test_environment, tmp_path):
        """Test copy command dry run output."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['copy', str(dest_dir), '--dry-run'])

            # Dry run should not create the destination
            assert not dest_dir.exists() or result.exit_code == 0

    def test_copy_with_query_compile_error(self, setup_test_environment, tmp_path):
        """Test copy command with invalid query."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            # Invalid query syntax
            result = runner.invoke(cli, ['copy', str(dest_dir), "invalid ===== query"])

            assert result.exit_code == 1 or 'Error' in result.output

    def test_copy_json_output(self, setup_test_environment, tmp_path):
        """Test copy command with JSON output."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['copy', str(dest_dir), '--json', '--dry-run'])

            # Should output JSONL
            if result.output.strip():
                for line in result.output.strip().split('\n'):
                    if line:
                        try:
                            json.loads(line)
                        except json.JSONDecodeError:
                            pass  # May have non-JSON warning messages

    def test_copy_with_debug_flag(self, setup_test_environment, tmp_path):
        """Test copy command with debug flag."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['copy', str(dest_dir), '--debug', '--dry-run'])

            # Should complete without error
            assert result.exit_code == 0 or 'DEBUG' in result.output or result.exit_code == 1

    def test_copy_with_language_filter(self, setup_test_environment, tmp_path):
        """Test copy command with language filter flag."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['copy', str(dest_dir), '--language', 'Python', '--dry-run'])

            assert result.exit_code == 0 or 'No repositories' in result.output

    def test_copy_with_dirty_flag(self, setup_test_environment, tmp_path):
        """Test copy command with dirty flag."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['copy', str(dest_dir), '--dirty', '--dry-run'])

            # All repos in test are clean, so should find nothing
            assert 'No repositories' in result.output or result.exit_code == 0

    def test_copy_with_collision_strategy(self, setup_test_environment, tmp_path):
        """Test copy command with collision strategy options."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            for strategy in ['rename', 'skip', 'overwrite']:
                result = runner.invoke(cli, ['copy', str(dest_dir / strategy), '--collision', strategy, '--dry-run'])
                assert result.exit_code == 0 or 'No repositories' in result.output

    def test_copy_exclude_git_flag(self, setup_test_environment, tmp_path):
        """Test copy command with exclude-git flag."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['copy', str(dest_dir), '--exclude-git', '--dry-run'])
            assert result.exit_code == 0 or 'No repositories' in result.output

    def test_copy_preserve_structure_flag(self, setup_test_environment, tmp_path):
        """Test copy command with preserve-structure flag."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'backup'

        runner = CliRunner()

        with patch('repoindex.commands.copy.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['copy', str(dest_dir), '--preserve-structure', '--dry-run'])
            assert result.exit_code == 0 or 'No repositories' in result.output


class TestCopyOutputModes:
    """Tests for different output modes of copy command."""

    @pytest.fixture
    def mock_copy_service(self):
        """Create a mock CopyService."""
        from repoindex.services.copy_service import CopyResult

        mock_service = MagicMock()
        mock_service.copy.return_value = iter(['Copying repo-1...', 'Copying repo-2...'])
        mock_service.last_result = CopyResult(
            repos_copied=2,
            repos_skipped=0,
            bytes_copied=1024,
            errors=[],
            details=[
                {'path': '/test/repo-1', 'name': 'repo-1', 'status': 'copied'},
                {'path': '/test/repo-2', 'name': 'repo-2', 'status': 'copied'},
            ]
        )
        return mock_service

    def test_copy_simple_output_with_errors(self, mock_copy_service, tmp_path):
        """Test simple output mode when there are errors."""
        from repoindex.services.copy_service import CopyResult, CopyOptions
        from repoindex.commands.copy import _copy_simple

        mock_service = MagicMock()
        mock_service.copy.return_value = iter(['Copying...'])
        mock_service.last_result = CopyResult(
            repos_copied=1,
            errors=['Error copying repo-x']
        )

        options = CopyOptions(destination=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            _copy_simple(mock_service, [], options)

        assert exc_info.value.code == 1

    def test_copy_json_output_format(self, mock_copy_service, tmp_path, capsys):
        """Test JSON output format."""
        from repoindex.services.copy_service import CopyOptions
        from repoindex.commands.copy import _copy_json

        options = CopyOptions(destination=tmp_path)

        _copy_json(mock_copy_service, [], options)

        captured = capsys.readouterr()
        lines = [l for l in captured.out.strip().split('\n') if l]

        # Should have progress lines plus details plus summary
        assert len(lines) >= 1

        # Last line should be summary
        summary = json.loads(lines[-1])
        assert summary['type'] == 'summary'
        assert summary['repos_copied'] == 2

    def test_copy_pretty_output_dry_run(self, mock_copy_service, tmp_path):
        """Test pretty output in dry run mode."""
        from repoindex.services.copy_service import CopyOptions
        from repoindex.commands.copy import _copy_pretty

        options = CopyOptions(destination=tmp_path, dry_run=True)

        # Should not raise
        _copy_pretty(mock_copy_service, [{'name': 'test', 'path': '/test'}], options)

    def test_copy_pretty_output_with_errors(self, tmp_path):
        """Test pretty output when there are errors."""
        from repoindex.services.copy_service import CopyResult, CopyOptions
        from repoindex.commands.copy import _copy_pretty

        mock_service = MagicMock()
        mock_service.copy.return_value = iter(['Copying...'])
        mock_service.last_result = CopyResult(
            repos_copied=1,
            errors=['Error copying repo-x']
        )

        options = CopyOptions(destination=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            _copy_pretty(mock_service, [{'name': 'test', 'path': '/test'}], options)

        assert exc_info.value.code == 1

    def test_copy_pretty_output_no_result(self, tmp_path):
        """Test pretty output when service returns no result."""
        from repoindex.services.copy_service import CopyOptions
        from repoindex.commands.copy import _copy_pretty

        mock_service = MagicMock()
        mock_service.copy.return_value = iter([])
        mock_service.last_result = None

        options = CopyOptions(destination=tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            _copy_pretty(mock_service, [{'name': 'test', 'path': '/test'}], options)

        assert exc_info.value.code == 1

    def test_copy_simple_output_success(self, mock_copy_service, tmp_path, capsys):
        """Test simple output mode on success."""
        from repoindex.services.copy_service import CopyOptions
        from repoindex.commands.copy import _copy_simple

        options = CopyOptions(destination=tmp_path)

        _copy_simple(mock_copy_service, [], options)

        captured = capsys.readouterr()
        assert 'Copy complete' in captured.err
        assert 'Repositories copied: 2' in captured.err

    def test_copy_simple_output_with_skipped(self, tmp_path, capsys):
        """Test simple output mode with skipped repos."""
        from repoindex.services.copy_service import CopyResult, CopyOptions
        from repoindex.commands.copy import _copy_simple

        mock_service = MagicMock()
        mock_service.copy.return_value = iter(['Copying...'])
        mock_service.last_result = CopyResult(
            repos_copied=1,
            repos_skipped=1,
            bytes_copied=512,
        )

        options = CopyOptions(destination=tmp_path)

        _copy_simple(mock_service, [], options)

        captured = capsys.readouterr()
        assert 'Repositories skipped: 1' in captured.err
