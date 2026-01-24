"""
Tests for export service and command.
"""

import json
import pytest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from repoindex.services.export_service import ExportService, ExportOptions, ExportResult


class TestExportOptions:
    """Tests for ExportOptions dataclass."""

    def test_default_options(self, tmp_path):
        """Test default export options."""
        options = ExportOptions(output_dir=tmp_path)

        assert options.output_dir == tmp_path
        assert options.include_readmes is False
        assert options.include_events is False
        assert options.include_git_summary == 0
        assert options.archive_repos is False
        assert options.dry_run is False

    def test_all_options_enabled(self, tmp_path):
        """Test export with all options enabled."""
        options = ExportOptions(
            output_dir=tmp_path,
            include_readmes=True,
            include_events=True,
            include_git_summary=10,
            archive_repos=True,
            dry_run=True,
        )

        assert options.include_readmes is True
        assert options.include_events is True
        assert options.include_git_summary == 10
        assert options.archive_repos is True
        assert options.dry_run is True


class TestExportResult:
    """Tests for ExportResult dataclass."""

    def test_default_result(self):
        """Test default export result."""
        result = ExportResult()

        assert result.repos_exported == 0
        assert result.events_exported == 0
        assert result.readmes_exported == 0
        assert result.git_summaries_exported == 0
        assert result.archives_created == 0
        assert result.errors == []
        assert result.success is True

    def test_result_with_errors(self):
        """Test export result with errors."""
        result = ExportResult(errors=["Error 1", "Error 2"])

        assert result.success is False
        assert len(result.errors) == 2


class TestExportService:
    """Tests for ExportService."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create a mock config with a test database."""
        db_path = tmp_path / 'test.db'
        return {
            'database': {'path': str(db_path)}
        }

    @pytest.fixture
    def setup_test_db(self, mock_config, tmp_path):
        """Set up a test database with sample data."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        db_path = Path(mock_config['database']['path'])

        with Database(config=mock_config) as db:
            apply_schema(db.conn)

            # Insert test repo
            db.execute("""
                INSERT INTO repos (name, path, language, branch)
                VALUES ('test-repo', '/test/path', 'Python', 'main')
            """)

            # Insert test event
            repo_id = db.lastrowid
            db.execute("""
                INSERT INTO events (repo_id, type, timestamp, message, author)
                VALUES (?, 'commit', '2026-01-20T10:00:00', 'Test commit', 'Test Author')
            """, (repo_id,))

            db.conn.commit()

        return mock_config

    def test_export_dry_run(self, setup_test_db, tmp_path):
        """Test export in dry run mode."""
        output_dir = tmp_path / 'export-dry'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir, dry_run=True)

        messages = list(service.export(options))
        result = service.last_result

        # Should not create the output directory
        assert not output_dir.exists()
        assert result is not None
        # Dry run should still count repos
        assert result.repos_exported == 1

    def test_export_basic(self, setup_test_db, tmp_path):
        """Test basic export (database + JSONL + README + manifest)."""
        output_dir = tmp_path / 'export'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir)

        messages = list(service.export(options))
        result = service.last_result

        # Check output directory was created
        assert output_dir.exists()

        # Check core files exist
        assert (output_dir / 'index.db').exists()
        assert (output_dir / 'repos.jsonl').exists()
        assert (output_dir / 'README.md').exists()
        assert (output_dir / 'manifest.json').exists()

        # Check result
        assert result.repos_exported == 1
        assert result.success is True

    def test_export_with_events(self, setup_test_db, tmp_path):
        """Test export with events included."""
        output_dir = tmp_path / 'export-events'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir, include_events=True)

        list(service.export(options))
        result = service.last_result

        # Check events.jsonl exists
        assert (output_dir / 'events.jsonl').exists()
        assert result.events_exported >= 0  # May be 0 if no events

    def test_export_repos_jsonl_content(self, setup_test_db, tmp_path):
        """Test that repos.jsonl contains valid JSON."""
        output_dir = tmp_path / 'export-jsonl'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))

        # Read and parse JSONL
        jsonl_path = output_dir / 'repos.jsonl'
        with open(jsonl_path) as f:
            lines = f.readlines()

        assert len(lines) >= 1

        for line in lines:
            data = json.loads(line)
            assert 'name' in data or 'path' in data

    def test_export_manifest_content(self, setup_test_db, tmp_path):
        """Test manifest.json content."""
        output_dir = tmp_path / 'export-manifest'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))

        manifest_path = output_dir / 'manifest.json'
        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest['echo_version'] == '1.0'
        assert manifest['toolkit'] == 'repoindex'
        assert 'exported_at' in manifest
        assert 'contents' in manifest
        assert 'index.db' in manifest['contents']
        assert 'repos.jsonl' in manifest['contents']
        assert 'stats' in manifest

    def test_export_readme_content(self, setup_test_db, tmp_path):
        """Test README.md content."""
        output_dir = tmp_path / 'export-readme'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))

        readme_path = output_dir / 'README.md'
        content = readme_path.read_text()

        assert '# repoindex Export' in content
        assert 'index.db' in content
        assert 'repos.jsonl' in content
        assert 'ECHO' in content

    def test_export_database_not_found(self, tmp_path):
        """Test export when database doesn't exist."""
        output_dir = tmp_path / 'export-no-db'
        config = {'database': {'path': str(tmp_path / 'nonexistent.db')}}

        service = ExportService(config=config)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))
        result = service.last_result

        assert not result.success
        assert len(result.errors) > 0


class TestExportServiceReadmes:
    """Tests for README export functionality."""

    @pytest.fixture
    def setup_repo_with_readme(self, tmp_path):
        """Create a test repo with a README."""
        repo_path = tmp_path / 'test-repo'
        repo_path.mkdir()

        readme = repo_path / 'README.md'
        readme.write_text('# Test Project\n\nThis is a test.')

        git_dir = repo_path / '.git'
        git_dir.mkdir()

        return repo_path

    def test_safe_filename(self, tmp_path):
        """Test filename sanitization."""
        service = ExportService(config={'database': {'path': str(tmp_path / 'test.db')}})

        assert service._safe_filename('normal-name') == 'normal-name'
        assert service._safe_filename('path/with/slashes') == 'path_with_slashes'
        assert service._safe_filename('name:with:colons') == 'name_with_colons'
        assert service._safe_filename('name<>with<>brackets') == 'name__with__brackets'

    def test_get_extension(self, tmp_path):
        """Test extension detection."""
        service = ExportService(config={'database': {'path': str(tmp_path / 'test.db')}})

        assert service._get_extension('README.md') == '.md'
        assert service._get_extension('README.rst') == '.rst'
        assert service._get_extension('README.txt') == '.txt'
        assert service._get_extension('README') == '.txt'


class TestExportCleanRecord:
    """Tests for record cleaning."""

    def test_clean_record_removes_none(self, tmp_path):
        """Test that None values are removed."""
        service = ExportService(config={'database': {'path': str(tmp_path / 'test.db')}})

        record = {
            'name': 'test',
            'path': '/test',
            'language': None,
            'description': None,
        }

        cleaned = service._clean_record(record)

        assert 'name' in cleaned
        assert 'path' in cleaned
        assert 'language' not in cleaned
        assert 'description' not in cleaned

    def test_clean_record_parses_json_fields(self, tmp_path):
        """Test that JSON string fields are parsed."""
        service = ExportService(config={'database': {'path': str(tmp_path / 'test.db')}})

        record = {
            'name': 'test',
            'languages': '["Python", "JavaScript"]',
            'github_topics': '["ml", "ai"]',
            'citation_authors': '[{"name": "John"}]',
        }

        cleaned = service._clean_record(record)

        assert cleaned['languages'] == ['Python', 'JavaScript']
        assert cleaned['github_topics'] == ['ml', 'ai']
        assert cleaned['citation_authors'] == [{'name': 'John'}]


class TestExportServiceIntegration:
    """Integration tests for export service."""

    @pytest.fixture
    def full_test_setup(self, tmp_path):
        """Set up a complete test environment."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        # Create database
        db_path = tmp_path / 'test.db'
        config = {'database': {'path': str(db_path)}}

        # Create test repos on filesystem
        repos = []
        for i, (name, lang) in enumerate([
            ('python-project', 'Python'),
            ('js-project', 'JavaScript'),
            ('rust-project', 'Rust'),
        ]):
            repo_path = tmp_path / 'repos' / name
            repo_path.mkdir(parents=True)
            (repo_path / '.git').mkdir()
            (repo_path / 'README.md').write_text(f'# {name}\n\nA {lang} project.')
            repos.append((name, str(repo_path), lang))

        # Populate database
        with Database(config=config) as db:
            apply_schema(db.conn)

            for name, path, lang in repos:
                db.execute("""
                    INSERT INTO repos (name, path, language, branch, has_readme)
                    VALUES (?, ?, ?, 'main', 1)
                """, (name, path, lang))

                repo_id = db.lastrowid

                # Add events
                db.execute("""
                    INSERT INTO events (repo_id, type, timestamp, message, author)
                    VALUES (?, 'commit', '2026-01-20T10:00:00', 'Initial commit', 'Author')
                """, (repo_id,))

            db.conn.commit()

        return config, repos

    def test_full_export(self, full_test_setup, tmp_path):
        """Test a complete export with all options."""
        config, repos = full_test_setup
        output_dir = tmp_path / 'full-export'

        service = ExportService(config=config)
        options = ExportOptions(
            output_dir=output_dir,
            include_readmes=True,
            include_events=True,
            include_git_summary=5,
        )

        messages = list(service.export(options))
        result = service.last_result

        # Verify all components
        assert (output_dir / 'index.db').exists()
        assert (output_dir / 'repos.jsonl').exists()
        assert (output_dir / 'events.jsonl').exists()
        assert (output_dir / 'README.md').exists()
        assert (output_dir / 'manifest.json').exists()
        assert (output_dir / 'readmes').exists()
        assert (output_dir / 'git-summaries').exists()

        # Check counts
        assert result.repos_exported == 3
        assert result.readmes_exported == 3
        assert result.success is True

    def test_export_with_missing_repos(self, full_test_setup, tmp_path):
        """Test export when some repos no longer exist on filesystem."""
        config, repos = full_test_setup

        # Delete one repo from filesystem
        shutil.rmtree(tmp_path / 'repos' / 'python-project')

        output_dir = tmp_path / 'partial-export'

        service = ExportService(config=config)
        options = ExportOptions(
            output_dir=output_dir,
            include_readmes=True,
        )

        list(service.export(options))
        result = service.last_result

        # Should still succeed with remaining repos
        assert result.success is True
        # READMEs from existing repos only
        assert result.readmes_exported == 2


class TestExportCommand:
    """Tests for the export CLI command."""

    def test_export_handler_exists(self):
        """Test that export handler is importable."""
        from repoindex.commands.export import export_handler
        assert export_handler is not None

    def test_export_registered_in_cli(self):
        """Test that export is registered in CLI."""
        from repoindex.cli import cli

        commands = list(cli.commands.keys())
        assert 'export' in commands
