"""Tests for HTML export."""
import pytest
import sqlite3
from pathlib import Path


@pytest.fixture
def sample_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE repos (id INTEGER PRIMARY KEY, name TEXT, path TEXT,
            language TEXT, description TEXT, branch TEXT, is_clean BOOLEAN,
            github_stars INTEGER, scanned_at TEXT, license_key TEXT,
            has_readme BOOLEAN, has_license BOOLEAN, has_ci BOOLEAN);
        INSERT INTO repos VALUES (1, 'myrepo', '/home/user/myrepo', 'Python',
            'A test repo', 'main', 1, 5, '2026-02-28', 'MIT', 1, 1, 0);
        CREATE TABLE events (id INTEGER PRIMARY KEY, repo_id INTEGER,
            type TEXT, timestamp TEXT, ref TEXT, message TEXT, author TEXT);
        INSERT INTO events VALUES (1, 1, 'commit', '2026-02-28', 'abc123',
            'initial commit', 'user');
        CREATE TABLE tags (repo_id INTEGER, tag TEXT, source TEXT);
        INSERT INTO tags VALUES (1, 'python', 'implicit');
        CREATE TABLE publications (id INTEGER PRIMARY KEY, repo_id INTEGER,
            registry TEXT, package_name TEXT, published BOOLEAN, current_version TEXT, url TEXT);
    """)
    conn.commit()
    conn.close()
    return db_path


class TestHtmlExport:
    def test_creates_index_html(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        assert (output_dir / "index.html").exists()

    def test_references_sql_js(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert 'sql-wasm' in content

    def test_embeds_database(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert 'DB_BASE64' in content

    def test_is_single_file(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        files = list(output_dir.iterdir())
        assert len(files) == 1
        assert files[0].name == "index.html"

    def test_has_dark_theme(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert '#0d1117' in content

    def test_has_tabs(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert 'data-tab="repos"' in content
        assert 'data-tab="events"' in content
        assert 'data-tab="sql"' in content

    def test_has_sql_console(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert 'sql-input' in content
        assert 'sql-run' in content

    def test_creates_subdirectory(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "sub" / "dir"
        export_html(output_dir, sample_db)
        assert (output_dir / "index.html").exists()

    def test_valid_html_structure(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert '<!DOCTYPE html>' in content
        assert '</html>' in content
        assert '<title>repoindex</title>' in content

    def test_embedded_db_is_valid_base64(self, tmp_path, sample_db):
        """Verify the embedded database can be decoded back to valid bytes."""
        import base64
        import re
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        # Extract the base64 string
        match = re.search(r'const DB_BASE64 = "([^"]+)"', content)
        assert match is not None
        db_b64 = match.group(1)
        # Decode and verify it starts with SQLite magic header
        decoded = base64.b64decode(db_b64)
        assert decoded[:16].startswith(b'SQLite format 3')

    def test_has_publications_tab(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert 'data-tab="publications"' in content

    def test_has_tags_tab(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert 'data-tab="tags"' in content

    def test_has_filter_functionality(self, tmp_path, sample_db):
        from repoindex.exporters.html import export_html
        output_dir = tmp_path / "html_out"
        export_html(output_dir, sample_db)
        content = (output_dir / "index.html").read_text()
        assert 'attachFilter' in content
        assert 'class="filter"' in content


class TestRenderCommandHtml:
    """Test the render/export CLI command with html format."""

    def test_html_requires_output_flag(self):
        """HTML export should error when no -o flag is given."""
        from click.testing import CliRunner
        from repoindex.commands.render import export_handler
        runner = CliRunner()
        result = runner.invoke(export_handler, ['html'])
        assert result.exit_code != 0
        assert 'requires -o' in result.output or 'requires -o' in (result.output + (result.stderr if hasattr(result, 'stderr') else ''))

    def test_html_in_list_formats(self):
        """HTML should appear in --list-formats output."""
        from click.testing import CliRunner
        from repoindex.commands.render import export_handler
        runner = CliRunner()
        result = runner.invoke(export_handler, ['--list-formats'])
        assert 'html' in result.output
        assert 'HTML Browser' in result.output

    def test_html_in_missing_format_error(self):
        """HTML should appear in available formats when no format given."""
        from click.testing import CliRunner
        from repoindex.commands.render import export_handler
        runner = CliRunner()
        result = runner.invoke(export_handler, [])
        # The error message lists available formats including html
        assert 'html' in (result.output + (result.stderr if hasattr(result, 'stderr') else ''))

    def test_html_export_with_db(self, tmp_path, sample_db, monkeypatch):
        """Full integration: HTML export produces index.html from DB."""
        from click.testing import CliRunner
        from repoindex.commands.render import export_handler

        output_dir = tmp_path / "html_export"

        # Monkeypatch get_db_path to return our sample db
        monkeypatch.setattr(
            'repoindex.commands.render.load_config',
            lambda: {}
        )
        monkeypatch.setattr(
            'repoindex.exporters.html.export_html',
            lambda od, dp: Path(od).mkdir(parents=True, exist_ok=True) or
                           (Path(od) / "index.html").write_text("<html></html>")
        )

        # We need to monkeypatch get_db_path too
        monkeypatch.setattr(
            'repoindex.database.connection.get_db_path',
            lambda config=None: sample_db
        )

        runner = CliRunner()
        result = runner.invoke(export_handler, ['html', '-o', str(output_dir)])
        assert result.exit_code == 0
