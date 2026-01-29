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
        assert options.include_events is False
        assert options.dry_run is False
        assert options.query_filter is None

    def test_all_options_enabled(self, tmp_path):
        """Test export with all options enabled."""
        options = ExportOptions(
            output_dir=tmp_path,
            include_events=True,
            dry_run=True,
            query_filter="language == 'Python'",
        )

        assert options.include_events is True
        assert options.dry_run is True
        assert options.query_filter == "language == 'Python'"

    def test_removed_options_no_longer_exist(self):
        """Verify removed options are no longer accepted."""
        import inspect
        sig = inspect.signature(ExportOptions)
        param_names = set(sig.parameters.keys())

        # These fields were removed in the ECHO cleanup
        assert 'include_readmes' not in param_names
        assert 'include_git_summary' not in param_names
        assert 'archive_repos' not in param_names


class TestExportResult:
    """Tests for ExportResult dataclass."""

    def test_default_result(self):
        """Test default export result."""
        result = ExportResult()

        assert result.repos_exported == 0
        assert result.events_exported == 0
        assert result.readmes_exported == 0
        assert result.errors == []
        assert result.success is True

    def test_result_with_errors(self):
        """Test export result with errors."""
        result = ExportResult(errors=["Error 1", "Error 2"])

        assert result.success is False
        assert len(result.errors) == 2

    def test_removed_result_fields(self):
        """Verify removed result fields are gone."""
        import inspect
        sig = inspect.signature(ExportResult)
        param_names = set(sig.parameters.keys())

        assert 'git_summaries_exported' not in param_names
        assert 'archives_created' not in param_names


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
        """Test basic export (database + JSONL + READMEs + site + manifest)."""
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

        # READMEs directory always created (even if no READMEs found)
        assert (output_dir / 'readmes').exists()

        # Site directory always created
        assert (output_dir / 'site').exists()
        assert (output_dir / 'site' / 'index.html').exists()

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
        assert result.events_exported >= 0

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

    def test_export_manifest_echo_schema(self, setup_test_db, tmp_path):
        """Test manifest.json follows ECHO schema."""
        output_dir = tmp_path / 'export-manifest'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))

        manifest_path = output_dir / 'manifest.json'
        with open(manifest_path) as f:
            manifest = json.load(f)

        # ECHO standard keys
        assert manifest['version'] == '1.0'
        assert manifest['name'] == 'Repository Index'
        assert 'description' in manifest
        assert manifest['type'] == 'database'
        assert manifest['icon'] == 'code'

        # Tool-specific metadata under _repoindex
        assert '_repoindex' in manifest
        repoindex_meta = manifest['_repoindex']
        assert 'toolkit_version' in repoindex_meta
        assert 'exported_at' in repoindex_meta
        assert 'stats' in repoindex_meta
        assert repoindex_meta['stats']['total_repos'] == 1

        # Old schema keys should NOT exist
        assert 'echo_version' not in manifest
        assert 'toolkit' not in manifest
        assert 'contents' not in manifest

    def test_export_manifest_description_includes_stats(self, setup_test_db, tmp_path):
        """Test manifest description includes repo count and languages."""
        output_dir = tmp_path / 'export-desc'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))

        manifest_path = output_dir / 'manifest.json'
        with open(manifest_path) as f:
            manifest = json.load(f)

        desc = manifest['description']
        assert '1 repos' in desc
        assert 'Python' in desc

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
        assert 'readmes/' in content
        assert 'site/' in content
        assert 'ECHO' in content
        assert 'publications' in content.lower()

    def test_export_readme_no_archive_or_git_summary_sections(self, setup_test_db, tmp_path):
        """Test that removed features don't appear in README."""
        output_dir = tmp_path / 'export-no-old'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))

        readme_path = output_dir / 'README.md'
        content = readme_path.read_text()

        assert 'archives/' not in content
        assert 'git-summaries/' not in content

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

    def test_export_site_html_content(self, setup_test_db, tmp_path):
        """Test that site/index.html contains expected content."""
        output_dir = tmp_path / 'export-site'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))

        html_path = output_dir / 'site' / 'index.html'
        assert html_path.exists()

        content = html_path.read_text()
        assert '<!DOCTYPE html>' in content
        assert 'Repository Index' in content
        assert 'test-repo' in content
        assert 'Python' in content

    def test_export_site_dry_run_skips(self, setup_test_db, tmp_path):
        """Test that site/ is not created during dry run."""
        output_dir = tmp_path / 'export-site-dry'

        service = ExportService(config=setup_test_db)
        options = ExportOptions(output_dir=output_dir, dry_run=True)

        list(service.export(options))

        assert not (output_dir / 'site').exists()


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


class TestExportPublications:
    """Tests for publication data in export."""

    @pytest.fixture
    def setup_db_with_publications(self, tmp_path):
        """Set up a database with repos and publications."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        db_path = tmp_path / 'test.db'
        config = {'database': {'path': str(db_path)}}

        with Database(config=config) as db:
            apply_schema(db.conn)

            db.execute("""
                INSERT INTO repos (name, path, language, branch)
                VALUES ('my-lib', '/test/my-lib', 'Python', 'main')
            """)
            repo_id = db.lastrowid

            db.execute("""
                INSERT INTO publications (repo_id, registry, package_name, current_version, published, url)
                VALUES (?, 'pypi', 'my-lib', '1.2.3', 1, 'https://pypi.org/project/my-lib/')
            """, (repo_id,))

            db.conn.commit()

        return config

    def test_repos_jsonl_includes_publications(self, setup_db_with_publications, tmp_path):
        """Test that repos.jsonl includes publication data."""
        output_dir = tmp_path / 'export-pub'

        service = ExportService(config=setup_db_with_publications)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))

        jsonl_path = output_dir / 'repos.jsonl'
        with open(jsonl_path) as f:
            data = json.loads(f.readline())

        assert 'publications' in data
        assert len(data['publications']) == 1
        pub = data['publications'][0]
        assert pub['registry'] == 'pypi'
        assert pub['package_name'] == 'my-lib'
        assert pub['current_version'] == '1.2.3'


class TestExportQueryFiltering:
    """Tests for query filtering in export."""

    @pytest.fixture
    def setup_multi_lang_db(self, tmp_path):
        """Set up a database with repos in multiple languages."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        db_path = tmp_path / 'test.db'
        config = {'database': {'path': str(db_path)}}

        with Database(config=config) as db:
            apply_schema(db.conn)

            for name, lang in [('py-proj', 'Python'), ('js-proj', 'JavaScript'), ('rs-proj', 'Rust')]:
                repo_path = tmp_path / 'repos' / name
                repo_path.mkdir(parents=True)
                (repo_path / '.git').mkdir()

                db.execute("""
                    INSERT INTO repos (name, path, language, branch)
                    VALUES (?, ?, ?, 'main')
                """, (name, str(repo_path), lang))

            db.conn.commit()

        return config

    def test_export_with_query_filter(self, setup_multi_lang_db, tmp_path):
        """Test export with a query filter limits repos."""
        output_dir = tmp_path / 'export-filtered'

        service = ExportService(config=setup_multi_lang_db)
        options = ExportOptions(
            output_dir=output_dir,
            query_filter="language == 'Python'",
        )

        list(service.export(options))
        result = service.last_result

        assert result.repos_exported == 1
        assert result.success is True

        # Verify JSONL only has Python repo
        jsonl_path = output_dir / 'repos.jsonl'
        with open(jsonl_path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data['name'] == 'py-proj'

    def test_export_no_filter_exports_all(self, setup_multi_lang_db, tmp_path):
        """Test export without filter exports everything."""
        output_dir = tmp_path / 'export-all'

        service = ExportService(config=setup_multi_lang_db)
        options = ExportOptions(output_dir=output_dir)

        list(service.export(options))
        result = service.last_result

        assert result.repos_exported == 3

    def test_export_filter_in_manifest(self, setup_multi_lang_db, tmp_path):
        """Test that query filter is recorded in manifest."""
        output_dir = tmp_path / 'export-manifest-filter'

        service = ExportService(config=setup_multi_lang_db)
        options = ExportOptions(
            output_dir=output_dir,
            query_filter="language == 'Rust'",
        )

        list(service.export(options))

        manifest_path = output_dir / 'manifest.json'
        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest['_repoindex']['options']['query_filter'] == "language == 'Rust'"
        assert manifest['_repoindex']['stats']['total_repos'] == 1

    def test_export_site_respects_filter(self, setup_multi_lang_db, tmp_path):
        """Test that site/ only includes filtered repos."""
        output_dir = tmp_path / 'export-site-filter'

        service = ExportService(config=setup_multi_lang_db)
        options = ExportOptions(
            output_dir=output_dir,
            query_filter="language == 'Python'",
        )

        list(service.export(options))

        html = (output_dir / 'site' / 'index.html').read_text()
        assert 'py-proj' in html
        assert 'js-proj' not in html
        assert 'rs-proj' not in html


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
            include_events=True,
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
        assert (output_dir / 'site').exists()
        assert (output_dir / 'site' / 'index.html').exists()

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
        options = ExportOptions(output_dir=output_dir)

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

    def test_export_has_query_options(self):
        """Test that export command has query flags."""
        from repoindex.commands.export import export_handler

        # Check that query options are present
        param_names = [p.name for p in export_handler.params]
        assert 'dirty' in param_names
        assert 'language' in param_names
        assert 'starred' in param_names
        assert 'tag' in param_names

    def test_export_removed_flags_absent(self):
        """Test that removed flags are no longer present."""
        from repoindex.commands.export import export_handler

        param_names = [p.name for p in export_handler.params]
        assert 'include_readmes' not in param_names
        assert 'include_git_summary' not in param_names
        assert 'archive_repos' not in param_names


class TestHtmlEscape:
    """Tests for HTML escaping utility."""

    def test_html_escape_basic(self):
        """Test basic HTML escaping."""
        from repoindex.services.export_service import _html_escape

        assert _html_escape('hello') == 'hello'
        assert _html_escape('<script>') == '&lt;script&gt;'
        assert _html_escape('a & b') == 'a &amp; b'
        assert _html_escape('"quoted"') == '&quot;quoted&quot;'

    def test_html_escape_combined(self):
        """Test combined special characters."""
        from repoindex.services.export_service import _html_escape

        assert _html_escape('<a href="x">&</a>') == '&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;'
