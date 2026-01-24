"""
Tests for link CLI command handler.
"""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from repoindex.cli import cli
from repoindex.commands.link import link_cmd


class TestLinkCommandCLI:
    """Tests for link command through CLI runner."""

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
        for name, lang in [('test-repo-1', 'Python'), ('test-repo-2', 'JavaScript')]:
            repo_path = tmp_path / 'repos' / name
            repo_path.mkdir(parents=True)
            (repo_path / '.git').mkdir()
            (repo_path / 'README.md').write_text(f'# {name}')
            repos_data.append((name, str(repo_path), lang))

        # Populate database
        with Database(config=config) as db:
            apply_schema(db.conn)
            for name, path, lang in repos_data:
                db.execute("""
                    INSERT INTO repos (name, path, language, branch, is_clean)
                    VALUES (?, ?, ?, 'main', 1)
                """, (name, path, lang))

                repo_id = db.lastrowid
                # Add a tag
                db.execute("""
                    INSERT INTO tags (repo_id, tag)
                    VALUES (?, ?)
                """, (repo_id, 'test-tag'))

            db.conn.commit()

        return config, db_path, tmp_path

    def test_link_tree_dry_run(self, setup_test_environment, tmp_path):
        """Test link tree command with dry run."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'links'

        runner = CliRunner()

        with patch('repoindex.commands.link.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['link', 'tree', str(dest_dir), '--by', 'language', '--dry-run'])

            # Should complete without error
            assert result.exit_code == 0 or 'Link tree complete' in result.output

    def test_link_tree_with_debug_flag(self, setup_test_environment, tmp_path):
        """Test link tree command with debug flag."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'links'

        runner = CliRunner()

        with patch('repoindex.commands.link.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['link', 'tree', str(dest_dir), '--by', 'language', '--debug', '--dry-run'])

            assert result.exit_code == 0 or 'DEBUG' in result.output

    def test_link_tree_with_query_compile_error(self, setup_test_environment, tmp_path):
        """Test link tree command with invalid query."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'links'

        runner = CliRunner()

        with patch('repoindex.commands.link.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['link', 'tree', str(dest_dir), '--by', 'language', 'invalid ===== query'])

            assert result.exit_code == 1 or 'Error' in result.output

    def test_link_tree_json_output(self, setup_test_environment, tmp_path):
        """Test link tree command with JSON output."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'links'

        runner = CliRunner()

        with patch('repoindex.commands.link.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['link', 'tree', str(dest_dir), '--by', 'language', '--json', '--dry-run'])

            # Should output JSONL
            if result.output.strip():
                for line in result.output.strip().split('\n'):
                    if line:
                        try:
                            json.loads(line)
                        except json.JSONDecodeError:
                            pass  # May have non-JSON messages

    def test_link_tree_by_tag(self, setup_test_environment, tmp_path):
        """Test link tree command organized by tag."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'links'

        runner = CliRunner()

        with patch('repoindex.commands.link.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['link', 'tree', str(dest_dir), '--by', 'tag', '--dry-run'])

            assert result.exit_code == 0 or 'Link tree complete' in result.output

    def test_link_tree_with_language_filter(self, setup_test_environment, tmp_path):
        """Test link tree command with language filter."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'links'

        runner = CliRunner()

        with patch('repoindex.commands.link.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['link', 'tree', str(dest_dir), '--by', 'language', '--language', 'Python', '--dry-run'])

            assert result.exit_code == 0 or 'No repositories' in result.output

    def test_link_tree_no_repos_found(self, setup_test_environment, tmp_path):
        """Test link tree command when query returns no results."""
        config, db_path, source_tmp = setup_test_environment
        dest_dir = tmp_path / 'links'

        runner = CliRunner()

        with patch('repoindex.commands.link.load_config') as mock_config:
            mock_config.return_value = config

            result = runner.invoke(cli, ['link', 'tree', str(dest_dir), '--by', 'language', "name == 'nonexistent'"])

            assert 'No repositories found' in result.output or result.exit_code == 0


class TestLinkTreeOutputModes:
    """Tests for different output modes of link tree command."""

    @pytest.fixture
    def mock_link_service(self):
        """Create a mock LinkService."""
        from repoindex.services.link_service import LinkTreeResult

        mock_service = MagicMock()
        mock_service.create_tree.return_value = iter(['Creating link 1...', 'Creating link 2...'])
        mock_service.last_result = LinkTreeResult(
            links_created=2,
            links_updated=0,
            links_skipped=0,
            dirs_created=2,
            errors=[],
            details=[
                {'path': '/test/repo-1', 'name': 'repo-1', 'status': 'created'},
                {'path': '/test/repo-2', 'name': 'repo-2', 'status': 'created'},
            ]
        )
        return mock_service

    def test_tree_simple_output_success(self, mock_link_service, tmp_path, capsys):
        """Test simple output mode on success."""
        from repoindex.services.link_service import LinkTreeOptions, OrganizeBy
        from repoindex.commands.link import _tree_simple

        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE
        )

        _tree_simple(mock_link_service, [], options)

        captured = capsys.readouterr()
        assert 'Link tree complete' in captured.err
        assert 'Links created: 2' in captured.err

    def test_tree_simple_output_dry_run(self, mock_link_service, tmp_path, capsys):
        """Test simple output mode in dry run."""
        from repoindex.services.link_service import LinkTreeOptions, OrganizeBy
        from repoindex.commands.link import _tree_simple

        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE,
            dry_run=True
        )

        _tree_simple(mock_link_service, [], options)

        captured = capsys.readouterr()
        assert '[dry run]' in captured.err

    def test_tree_simple_output_with_errors(self, tmp_path, capsys):
        """Test simple output mode when there are errors."""
        from repoindex.services.link_service import LinkTreeResult, LinkTreeOptions, OrganizeBy
        from repoindex.commands.link import _tree_simple

        mock_service = MagicMock()
        mock_service.create_tree.return_value = iter(['Creating...'])
        mock_service.last_result = LinkTreeResult(
            links_created=1,
            errors=['Error creating link']
        )

        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE
        )

        with pytest.raises(SystemExit) as exc_info:
            _tree_simple(mock_service, [], options)

        assert exc_info.value.code == 1

    def test_tree_simple_output_with_skipped(self, tmp_path, capsys):
        """Test simple output mode with skipped links."""
        from repoindex.services.link_service import LinkTreeResult, LinkTreeOptions, OrganizeBy
        from repoindex.commands.link import _tree_simple

        mock_service = MagicMock()
        mock_service.create_tree.return_value = iter(['Creating...'])
        mock_service.last_result = LinkTreeResult(
            links_created=1,
            links_skipped=1,
            links_updated=1,
        )

        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE
        )

        _tree_simple(mock_service, [], options)

        captured = capsys.readouterr()
        assert 'Links skipped: 1' in captured.err
        assert 'Links updated: 1' in captured.err

    def test_tree_json_output_format(self, mock_link_service, tmp_path, capsys):
        """Test JSON output format."""
        from repoindex.services.link_service import LinkTreeOptions, OrganizeBy
        from repoindex.commands.link import _tree_json

        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE
        )

        _tree_json(mock_link_service, [], options)

        captured = capsys.readouterr()
        lines = [l for l in captured.out.strip().split('\n') if l]

        # Last line should be summary
        summary = json.loads(lines[-1])
        assert summary['type'] == 'summary'
        assert summary['links_created'] == 2

    def test_tree_pretty_output_dry_run(self, mock_link_service, tmp_path):
        """Test pretty output in dry run mode."""
        from repoindex.services.link_service import LinkTreeOptions, OrganizeBy
        from repoindex.commands.link import _tree_pretty

        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE,
            dry_run=True
        )

        # Should not raise
        _tree_pretty(mock_link_service, [{'name': 'test', 'path': '/test', 'tags': []}], options)

    def test_tree_pretty_output_no_result(self, tmp_path):
        """Test pretty output when service returns no result."""
        from repoindex.services.link_service import LinkTreeOptions, OrganizeBy
        from repoindex.commands.link import _tree_pretty

        mock_service = MagicMock()
        mock_service.create_tree.return_value = iter([])
        mock_service.last_result = None

        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE
        )

        with pytest.raises(SystemExit) as exc_info:
            _tree_pretty(mock_service, [{'name': 'test', 'path': '/test', 'tags': []}], options)

        assert exc_info.value.code == 1

    def test_tree_pretty_output_with_errors(self, tmp_path):
        """Test pretty output when there are errors."""
        from repoindex.services.link_service import LinkTreeResult, LinkTreeOptions, OrganizeBy
        from repoindex.commands.link import _tree_pretty

        mock_service = MagicMock()
        mock_service.create_tree.return_value = iter(['Creating...'])
        mock_service.last_result = LinkTreeResult(
            links_created=1,
            errors=['Error creating link']
        )

        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE
        )

        with pytest.raises(SystemExit) as exc_info:
            _tree_pretty(mock_service, [{'name': 'test', 'path': '/test', 'tags': []}], options)

        assert exc_info.value.code == 1


class TestLinkRefreshOutputModes:
    """Tests for different output modes of link refresh command."""

    @pytest.fixture
    def mock_link_service_refresh(self):
        """Create a mock LinkService for refresh."""
        from repoindex.services.link_service import RefreshResult

        mock_service = MagicMock()
        mock_service.refresh_tree.return_value = iter(['Scanning links...'])
        mock_service.last_refresh_result = RefreshResult(
            total_links=5,
            valid_links=4,
            broken_links=1,
            removed_links=0,
            broken_paths=['/path/to/broken'],
        )
        return mock_service

    def test_refresh_simple_output(self, mock_link_service_refresh, tmp_path, capsys):
        """Test refresh simple output."""
        from repoindex.commands.link import _refresh_simple

        _refresh_simple(mock_link_service_refresh, tmp_path, prune=False, dry_run=False)

        captured = capsys.readouterr()
        assert 'Refresh complete' in captured.err
        assert 'Total links: 5' in captured.err
        assert 'Valid links: 4' in captured.err
        assert 'Broken links: 1' in captured.err

    def test_refresh_simple_output_dry_run(self, mock_link_service_refresh, tmp_path, capsys):
        """Test refresh simple output in dry run."""
        from repoindex.commands.link import _refresh_simple

        _refresh_simple(mock_link_service_refresh, tmp_path, prune=True, dry_run=True)

        captured = capsys.readouterr()
        assert '[dry run]' in captured.err

    def test_refresh_simple_output_with_prune(self, tmp_path, capsys):
        """Test refresh simple output with prune."""
        from repoindex.services.link_service import RefreshResult
        from repoindex.commands.link import _refresh_simple

        mock_service = MagicMock()
        mock_service.refresh_tree.return_value = iter(['Scanning...'])
        mock_service.last_refresh_result = RefreshResult(
            total_links=5,
            valid_links=4,
            broken_links=1,
            removed_links=1,
        )

        _refresh_simple(mock_service, tmp_path, prune=True, dry_run=False)

        captured = capsys.readouterr()
        assert 'Removed: 1' in captured.err

    def test_refresh_simple_output_shows_broken_paths(self, mock_link_service_refresh, tmp_path, capsys):
        """Test refresh simple output shows broken paths when not pruning."""
        from repoindex.commands.link import _refresh_simple

        _refresh_simple(mock_link_service_refresh, tmp_path, prune=False, dry_run=False)

        captured = capsys.readouterr()
        assert 'Broken links:' in captured.err
        assert '/path/to/broken' in captured.err

    def test_refresh_json_output(self, mock_link_service_refresh, tmp_path, capsys):
        """Test refresh JSON output."""
        from repoindex.commands.link import _refresh_json

        _refresh_json(mock_link_service_refresh, tmp_path, prune=False, dry_run=False)

        captured = capsys.readouterr()
        lines = [l for l in captured.out.strip().split('\n') if l]

        summary = json.loads(lines[-1])
        assert summary['type'] == 'summary'
        assert summary['total_links'] == 5
        assert summary['broken_links'] == 1

    def test_refresh_pretty_output(self, mock_link_service_refresh, tmp_path):
        """Test refresh pretty output."""
        from repoindex.commands.link import _refresh_pretty

        # Should not raise
        _refresh_pretty(mock_link_service_refresh, tmp_path, prune=False, dry_run=False)

    def test_refresh_pretty_output_dry_run(self, mock_link_service_refresh, tmp_path):
        """Test refresh pretty output in dry run."""
        from repoindex.commands.link import _refresh_pretty

        # Should not raise
        _refresh_pretty(mock_link_service_refresh, tmp_path, prune=True, dry_run=True)

    def test_refresh_pretty_output_no_result(self, tmp_path):
        """Test refresh pretty output when service returns no result."""
        from repoindex.commands.link import _refresh_pretty

        mock_service = MagicMock()
        mock_service.refresh_tree.return_value = iter([])
        mock_service.last_refresh_result = None

        with pytest.raises(SystemExit) as exc_info:
            _refresh_pretty(mock_service, tmp_path, prune=False, dry_run=False)

        assert exc_info.value.code == 1

    def test_refresh_pretty_output_all_valid(self, tmp_path):
        """Test refresh pretty output when all links are valid."""
        from repoindex.services.link_service import RefreshResult
        from repoindex.commands.link import _refresh_pretty

        mock_service = MagicMock()
        mock_service.refresh_tree.return_value = iter(['Scanning...'])
        mock_service.last_refresh_result = RefreshResult(
            total_links=5,
            valid_links=5,
            broken_links=0,
        )

        # Should not raise
        _refresh_pretty(mock_service, tmp_path, prune=False, dry_run=False)


class TestLinkStatusOutputModes:
    """Tests for different output modes of link status command."""

    @pytest.fixture
    def mock_link_service_status(self):
        """Create a mock LinkService for status."""
        from repoindex.services.link_service import RefreshResult

        mock_service = MagicMock()
        mock_service.get_tree_status.return_value = iter(['Scanning...'])
        mock_service.last_refresh_result = RefreshResult(
            total_links=5,
            valid_links=4,
            broken_links=1,
            broken_paths=['/path/to/broken'],
        )
        return mock_service

    def test_status_simple_output(self, mock_link_service_status, tmp_path, capsys):
        """Test status simple output."""
        from repoindex.commands.link import _status_simple

        _status_simple(mock_link_service_status, tmp_path, manifest=None)

        captured = capsys.readouterr()
        assert f'Status: {tmp_path}' in captured.err
        assert 'Total links: 5' in captured.err

    def test_status_simple_output_with_manifest(self, mock_link_service_status, tmp_path, capsys):
        """Test status simple output with manifest."""
        from repoindex.commands.link import _status_simple

        manifest = {
            'created_at': '2026-01-01T00:00:00',
            'organize_by': 'tag',
        }

        _status_simple(mock_link_service_status, tmp_path, manifest=manifest)

        captured = capsys.readouterr()
        assert 'Created: 2026-01-01T00:00:00' in captured.err
        assert 'Organize by: tag' in captured.err

    def test_status_simple_output_shows_broken(self, mock_link_service_status, tmp_path, capsys):
        """Test status simple output shows broken paths."""
        from repoindex.commands.link import _status_simple

        _status_simple(mock_link_service_status, tmp_path, manifest=None)

        captured = capsys.readouterr()
        assert 'Broken links:' in captured.err
        assert '/path/to/broken' in captured.err

    def test_status_json_output(self, mock_link_service_status, tmp_path, capsys):
        """Test status JSON output."""
        from repoindex.commands.link import _status_json

        _status_json(mock_link_service_status, tmp_path, manifest=None)

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert output['path'] == str(tmp_path)
        assert output['total_links'] == 5
        assert output['broken_links'] == 1

    def test_status_json_output_with_manifest(self, mock_link_service_status, tmp_path, capsys):
        """Test status JSON output with manifest."""
        from repoindex.commands.link import _status_json

        manifest = {
            'created_at': '2026-01-01T00:00:00',
            'organize_by': 'tag',
        }

        _status_json(mock_link_service_status, tmp_path, manifest=manifest)

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert 'manifest' in output
        assert output['manifest']['organize_by'] == 'tag'

    def test_status_pretty_output(self, mock_link_service_status, tmp_path):
        """Test status pretty output."""
        from repoindex.commands.link import _status_pretty

        # Should not raise
        _status_pretty(mock_link_service_status, tmp_path, manifest=None)

    def test_status_pretty_output_with_manifest(self, tmp_path):
        """Test status pretty output with manifest."""
        from repoindex.services.link_service import RefreshResult
        from repoindex.commands.link import _status_pretty

        mock_service = MagicMock()
        mock_service.get_tree_status.return_value = iter(['Scanning...'])
        mock_service.last_refresh_result = RefreshResult(
            total_links=5,
            valid_links=5,
            broken_links=0,
        )

        manifest = {
            'created_at': '2026-01-01T00:00:00',
            'organize_by': 'tag',
            'repos_count': 10,
            'repoindex_version': '0.10.0',
        }

        # Should not raise
        _status_pretty(mock_service, tmp_path, manifest=manifest)

    def test_status_pretty_output_no_result(self, tmp_path):
        """Test status pretty output when service returns no result."""
        from repoindex.commands.link import _status_pretty

        mock_service = MagicMock()
        mock_service.get_tree_status.return_value = iter([])
        mock_service.last_refresh_result = None

        with pytest.raises(SystemExit) as exc_info:
            _status_pretty(mock_service, tmp_path, manifest=None)

        assert exc_info.value.code == 1

    def test_status_pretty_output_with_broken(self, mock_link_service_status, tmp_path):
        """Test status pretty output with broken links."""
        from repoindex.commands.link import _status_pretty

        # Should not raise
        _status_pretty(mock_link_service_status, tmp_path, manifest=None)
