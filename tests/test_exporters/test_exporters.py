"""Tests for all built-in exporter implementations."""

import io
import json

import pytest

from repoindex.exporters.bibtex import BibTeXExporter, _make_bibtex_key, _escape_bibtex, _format_authors
from repoindex.exporters.csv_exporter import CSVExporter
from repoindex.exporters.markdown import MarkdownExporter
from repoindex.exporters.opml import OPMLExporter
from repoindex.exporters.jsonld import JSONLDExporter


SAMPLE_REPOS = [
    {
        'name': 'alpha-lib',
        'path': '/home/user/alpha-lib',
        'language': 'Python',
        'branch': 'main',
        'is_clean': True,
        'remote_url': 'https://github.com/user/alpha-lib',
        'github_stars': 42,
        'license_key': 'mit',
        'description': 'A test library',
        'owner': 'user',
        'citation_doi': '10.5281/zenodo.12345',
        'citation_title': 'Alpha Library',
        'citation_authors': json.dumps([
            {'given-names': 'Alice', 'family-names': 'Smith'},
            {'given-names': 'Bob', 'family-names': 'Jones'},
        ]),
        'citation_version': '2.0.0',
    },
    {
        'name': 'beta-tool',
        'path': '/home/user/beta-tool',
        'language': 'Rust',
        'branch': 'develop',
        'is_clean': False,
        'remote_url': 'https://github.com/user/beta-tool',
        'github_stars': 0,
        'license_key': 'apache-2.0',
        'description': 'Beta tool for testing',
    },
]


# ============================================================================
# BibTeX
# ============================================================================

class TestBibTeXHelpers:
    def test_make_bibtex_key_simple(self):
        assert _make_bibtex_key({'name': 'my-lib'}) == 'my_lib'

    def test_make_bibtex_key_special_chars(self):
        assert _make_bibtex_key({'name': '@scope/pkg'}) == '_scope_pkg'

    def test_escape_bibtex(self):
        assert _escape_bibtex('10% done & more') == '10\\% done \\& more'

    def test_format_authors_json(self):
        authors = json.dumps([
            {'given-names': 'Alice', 'family-names': 'Smith'},
            {'name': 'Bob'},
        ])
        result = _format_authors(authors)
        assert 'Smith, Alice' in result
        assert 'Bob' in result
        assert ' and ' in result

    def test_format_authors_none(self):
        assert _format_authors(None) is None

    def test_format_authors_empty(self):
        assert _format_authors('[]') is None

    def test_format_authors_invalid_json(self):
        assert _format_authors('not json') is None


class TestBibTeXExporter:
    def test_export_basic(self):
        e = BibTeXExporter()
        out = io.StringIO()
        count = e.export(SAMPLE_REPOS, out)
        assert count == 2
        content = out.getvalue()
        assert '@software{alpha_lib,' in content
        assert '@software{beta_tool,' in content
        assert 'doi = {10.5281/zenodo.12345}' in content

    def test_export_empty(self):
        e = BibTeXExporter()
        out = io.StringIO()
        count = e.export([], out)
        assert count == 0
        assert out.getvalue() == ''

    def test_export_has_title(self):
        e = BibTeXExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS[:1], out)
        assert 'Alpha Library' in out.getvalue()

    def test_export_has_authors(self):
        e = BibTeXExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS[:1], out)
        assert 'Smith, Alice' in out.getvalue()

    def test_attributes(self):
        e = BibTeXExporter()
        assert e.format_id == "bibtex"
        assert e.extension == ".bib"


# ============================================================================
# CSV
# ============================================================================

class TestCSVExporter:
    def test_export_basic(self):
        e = CSVExporter()
        out = io.StringIO()
        count = e.export(SAMPLE_REPOS, out)
        assert count == 2
        content = out.getvalue()
        # Header
        assert 'name' in content.split('\n')[0]
        assert 'alpha-lib' in content
        assert 'beta-tool' in content

    def test_export_empty(self):
        e = CSVExporter()
        out = io.StringIO()
        count = e.export([], out)
        assert count == 0

    def test_csv_is_parseable(self):
        import csv
        e = CSVExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS, out)
        out.seek(0)
        reader = csv.DictReader(out)
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]['name'] == 'alpha-lib'

    def test_attributes(self):
        e = CSVExporter()
        assert e.format_id == "csv"
        assert e.extension == ".csv"


# ============================================================================
# Markdown
# ============================================================================

class TestMarkdownExporter:
    def test_export_basic(self):
        e = MarkdownExporter()
        out = io.StringIO()
        count = e.export(SAMPLE_REPOS, out)
        assert count == 2
        content = out.getvalue()
        # GFM table
        assert '| Name |' in content
        assert '|------|' in content
        assert 'alpha-lib' in content

    def test_export_links_names(self):
        e = MarkdownExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS[:1], out)
        assert '[alpha-lib](https://github.com/user/alpha-lib)' in out.getvalue()

    def test_export_empty(self):
        e = MarkdownExporter()
        out = io.StringIO()
        count = e.export([], out)
        assert count == 0

    def test_truncates_long_descriptions(self):
        repo = {'name': 'test', 'description': 'x' * 200}
        e = MarkdownExporter()
        out = io.StringIO()
        e.export([repo], out)
        content = out.getvalue()
        assert '...' in content

    def test_attributes(self):
        e = MarkdownExporter()
        assert e.format_id == "markdown"
        assert e.extension == ".md"


# ============================================================================
# OPML
# ============================================================================

class TestOPMLExporter:
    def test_export_basic(self):
        e = OPMLExporter()
        out = io.StringIO()
        count = e.export(SAMPLE_REPOS, out)
        assert count == 2
        content = out.getvalue()
        assert '<?xml version' in content
        assert '<opml version="2.0">' in content
        assert 'Repository Index' in content

    def test_export_groups_by_language(self):
        e = OPMLExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS, out)
        content = out.getvalue()
        assert 'text="Python"' in content
        assert 'text="Rust"' in content

    def test_export_empty(self):
        e = OPMLExporter()
        out = io.StringIO()
        count = e.export([], out)
        assert count == 0
        assert '<body/>' in out.getvalue()

    def test_escapes_xml(self):
        repo = {'name': 'a&b<c', 'language': 'Python'}
        e = OPMLExporter()
        out = io.StringIO()
        e.export([repo], out)
        content = out.getvalue()
        assert 'a&amp;b&lt;c' in content

    def test_attributes(self):
        e = OPMLExporter()
        assert e.format_id == "opml"
        assert e.extension == ".opml"


# ============================================================================
# JSON-LD
# ============================================================================

class TestJSONLDExporter:
    def test_export_basic(self):
        e = JSONLDExporter()
        out = io.StringIO()
        count = e.export(SAMPLE_REPOS, out)
        assert count == 2
        out.seek(0)
        doc = json.loads(out.read())
        assert doc['@context'] == 'https://schema.org'
        assert len(doc['@graph']) == 2

    def test_export_software_source_code_type(self):
        e = JSONLDExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS[:1], out)
        out.seek(0)
        doc = json.loads(out.read())
        obj = doc['@graph'][0]
        assert obj['@type'] == 'SoftwareSourceCode'
        assert obj['name'] == 'alpha-lib'
        assert obj['programmingLanguage'] == 'Python'

    def test_export_includes_doi(self):
        e = JSONLDExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS[:1], out)
        out.seek(0)
        doc = json.loads(out.read())
        obj = doc['@graph'][0]
        assert 'doi.org/10.5281/zenodo.12345' in obj.get('identifier', '')

    def test_export_includes_authors(self):
        e = JSONLDExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS[:1], out)
        out.seek(0)
        doc = json.loads(out.read())
        obj = doc['@graph'][0]
        assert 'author' in obj
        assert obj['author'][0]['@type'] == 'Person'
        assert obj['author'][0]['familyName'] == 'Smith'

    def test_export_license_as_spdx_url(self):
        e = JSONLDExporter()
        out = io.StringIO()
        e.export(SAMPLE_REPOS[:1], out)
        out.seek(0)
        doc = json.loads(out.read())
        obj = doc['@graph'][0]
        assert 'spdx.org/licenses/mit' in obj.get('license', '')

    def test_export_empty(self):
        e = JSONLDExporter()
        out = io.StringIO()
        count = e.export([], out)
        assert count == 0
        out.seek(0)
        doc = json.loads(out.read())
        assert doc['@graph'] == []

    def test_attributes(self):
        e = JSONLDExporter()
        assert e.format_id == "jsonld"
        assert e.extension == ".jsonld"
