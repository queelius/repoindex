"""Tests for arkiv directory export."""
import json
import sqlite3
import pytest
import yaml


MOCK_REPOS = [
    {
        'id': 1, 'name': 'myrepo', 'path': '/home/user/github/myrepo',
        'branch': 'main', 'language': 'Python', 'is_clean': 1,
        'description': 'A test repo', 'remote_url': 'https://github.com/user/myrepo',
        'owner': 'user', 'license_key': 'MIT', 'scanned_at': '2026-02-28T10:00:00',
        'has_readme': 1, 'has_license': 1, 'has_ci': 0, 'has_citation': 0,
        'languages': '["Python", "Shell"]', 'readme_content': None,
        'tags': '["topic/cli"]',
        'citation_doi': None, 'citation_title': None, 'citation_version': None,
        'citation_repository': None, 'citation_license': None, 'citation_authors': None,
        'github_stars': 5, 'github_forks': 1, 'github_watchers': 3,
        'github_open_issues': 2, 'github_is_fork': 0, 'github_is_private': 0,
        'github_is_archived': 0, 'github_description': 'A repo index tool',
        'github_created_at': '2025-01-01', 'github_updated_at': '2026-02-28',
        'github_topics': '["cli", "git"]',
    },
]

MOCK_EVENTS = [
    {
        'repo_name': 'myrepo', 'repo_path': '/home/user/github/myrepo',
        'type': 'commit', 'timestamp': '2026-02-28T09:30:00',
        'ref': 'abc1234', 'message': 'feat: add export',
        'author': 'user', 'data': {},
    },
]


class TestExportArchive:
    def test_creates_all_files(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        assert (tmp_path / "repos.jsonl").exists()
        assert (tmp_path / "events.jsonl").exists()
        assert (tmp_path / "README.md").exists()
        assert (tmp_path / "schema.yaml").exists()

    def test_repos_jsonl_valid_arkiv(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        with open(tmp_path / "repos.jsonl") as f:
            records = [json.loads(line) for line in f if line.strip()]
        assert len(records) == 1
        assert records[0]['mimetype'] == 'inode/directory'
        assert records[0]['uri'].startswith('file://')
        assert 'metadata' in records[0]

    def test_events_jsonl_valid_arkiv(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        with open(tmp_path / "events.jsonl") as f:
            records = [json.loads(line) for line in f if line.strip()]
        assert len(records) == 1
        assert records[0]['mimetype'] == 'text/plain'
        assert records[0]['content'] == 'feat: add export'
        assert records[0]['metadata']['type'] == 'commit'

    def test_readme_yaml_frontmatter(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        content = (tmp_path / "README.md").read_text()
        assert content.startswith('---\n')
        parts = content.split('---\n', 2)
        fm = yaml.safe_load(parts[1])
        assert fm['name'] == 'repoindex export'
        paths = [c['path'] for c in fm['contents']]
        assert 'repos.jsonl' in paths
        assert 'events.jsonl' in paths

    def test_schema_yaml_structure(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        with open(tmp_path / "schema.yaml") as f:
            schema = yaml.safe_load(f)
        assert 'repos' in schema
        assert 'events' in schema
        # Verify proper types and counts (not just key presence)
        repo_keys = schema['repos']['metadata_keys']
        assert repo_keys['name']['type'] == 'string'
        assert repo_keys['name']['count'] == 1
        assert repo_keys['github.stars']['type'] == 'number'
        assert repo_keys['is_clean']['type'] == 'boolean'
        assert repo_keys['languages']['type'] == 'array'
        # Parent keys should not appear — only leaf keys
        assert 'github' not in repo_keys
        assert 'citation' not in repo_keys
        # Event schema
        event_keys = schema['events']['metadata_keys']
        assert event_keys['type']['type'] == 'string'
        assert event_keys['repo']['count'] == 1

    def test_empty_export(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, [], [], version='0.12.0')
        assert (tmp_path / "repos.jsonl").exists()
        assert (tmp_path / "repos.jsonl").stat().st_size == 0
        assert (tmp_path / "README.md").exists()

    def test_counts_returned(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        counts = export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        assert counts['repos'] == 1
        assert counts['events'] == 1
        assert counts['publications'] == 0

    def test_creates_subdirectory(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        output = tmp_path / "subdir" / "archive"
        export_archive(output, MOCK_REPOS, [], version='0.12.0')
        assert output.exists()
        assert (output / "repos.jsonl").exists()


class TestDiscoverSchema:
    def test_infers_string_type(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'name': 'alpha'}}, {'metadata': {'name': 'beta'}}]
        schema = _discover_schema(records)
        assert schema['name']['type'] == 'string'
        assert schema['name']['count'] == 2

    def test_infers_number_type(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'stars': 42}}, {'metadata': {'stars': 10}}]
        schema = _discover_schema(records)
        assert schema['stars']['type'] == 'number'

    def test_infers_boolean_type(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'is_clean': True}}, {'metadata': {'is_clean': False}}]
        schema = _discover_schema(records)
        assert schema['is_clean']['type'] == 'boolean'

    def test_infers_array_type(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'langs': ['Python', 'Go']}}]
        schema = _discover_schema(records)
        assert schema['langs']['type'] == 'array'

    def test_low_cardinality_emits_values(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'lang': v}} for v in ['Python', 'Go', 'Rust']]
        schema = _discover_schema(records)
        assert 'values' in schema['lang']
        assert 'example' not in schema['lang']
        assert schema['lang']['values'] == ['Go', 'Python', 'Rust']

    def test_high_cardinality_emits_example(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'name': f'repo-{i}'}} for i in range(25)]
        schema = _discover_schema(records)
        assert 'example' in schema['name']
        assert 'values' not in schema['name']
        assert schema['name']['example'] == 'repo-0'

    def test_nested_keys_use_dot_notation(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'github': {'stars': 5, 'forks': 1}}}]
        schema = _discover_schema(records)
        assert 'github.stars' in schema
        assert 'github.forks' in schema
        # Parent key should NOT be in schema
        assert 'github' not in schema

    def test_count_reflects_presence(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [
            {'metadata': {'name': 'a', 'lang': 'Python'}},
            {'metadata': {'name': 'b'}},
            {'metadata': {'name': 'c', 'lang': 'Go'}},
        ]
        schema = _discover_schema(records)
        assert schema['name']['count'] == 3
        assert schema['lang']['count'] == 2

    def test_empty_records(self):
        from repoindex.exporters.arkiv import _discover_schema
        schema = _discover_schema([])
        assert schema == {}

    def test_mixed_types_uses_most_common(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [
            {'metadata': {'val': 'hello'}},
            {'metadata': {'val': 'world'}},
            {'metadata': {'val': 42}},
        ]
        schema = _discover_schema(records)
        # string appears 2x, number 1x — string wins
        assert schema['val']['type'] == 'string'


MOCK_PUBLICATIONS = [
    {
        'registry': 'pypi', 'package_name': 'myrepo', 'current_version': '1.0.0',
        'published': 1, 'url': 'https://pypi.org/project/myrepo/',
        'doi': None, 'downloads_total': None, 'downloads_30d': None,
        'scanned_at': '2026-02-28T10:00:00',
        'last_published': None,
        'repo_name': 'myrepo', 'repo_path': '/home/user/github/myrepo',
    },
]


class TestExportArchivePublications:
    def test_publications_jsonl_created(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS, version='0.12.0')
        assert (tmp_path / "publications.jsonl").exists()

    def test_publications_jsonl_valid_records(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS, version='0.12.0')
        with open(tmp_path / "publications.jsonl") as f:
            records = [json.loads(line) for line in f if line.strip()]
        assert len(records) == 1
        assert records[0]['mimetype'] == 'application/json'
        assert records[0]['uri'] == 'https://pypi.org/project/myrepo/'
        assert records[0]['metadata']['registry'] == 'pypi'
        assert records[0]['metadata']['package_name'] == 'myrepo'

    def test_publications_in_schema(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS, version='0.12.0')
        with open(tmp_path / "schema.yaml") as f:
            schema = yaml.safe_load(f)
        assert 'publications' in schema
        assert schema['publications']['record_count'] == 1

    def test_publications_in_readme_frontmatter(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS, version='0.12.0')
        content = (tmp_path / "README.md").read_text()
        parts = content.split('---\n', 2)
        fm = yaml.safe_load(parts[1])
        paths = [c['path'] for c in fm['contents']]
        assert 'publications.jsonl' in paths

    def test_publications_in_readme_body(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS, version='0.12.0')
        content = (tmp_path / "README.md").read_text()
        assert 'publications.jsonl' in content
        assert '1 publication records' in content

    def test_no_publications_no_file(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=[], version='0.12.0')
        assert not (tmp_path / "publications.jsonl").exists()

    def test_publications_default_none(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        counts = export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        assert counts['publications'] == 0
        assert not (tmp_path / "publications.jsonl").exists()

    def test_no_publications_not_in_schema(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=[], version='0.12.0')
        with open(tmp_path / "schema.yaml") as f:
            schema = yaml.safe_load(f)
        assert 'publications' not in schema

    def test_no_publications_not_in_readme_frontmatter(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        content = (tmp_path / "README.md").read_text()
        parts = content.split('---\n', 2)
        fm = yaml.safe_load(parts[1])
        paths = [c['path'] for c in fm['contents']]
        assert 'publications.jsonl' not in paths

    def test_counts_include_publications(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        counts = export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS, version='0.12.0')
        assert counts['publications'] == 1


class TestArchiveSqlite:
    def test_archive_db_created(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        assert (tmp_path / "archive.db").exists()

    def test_records_table_schema(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        cursor = conn.execute("PRAGMA table_info(records)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert cols == {'id', 'collection', 'mimetype', 'uri', 'content', 'timestamp', 'metadata'}

    def test_records_count_matches_jsonl(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS, version='0.12.0')
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        repos_n = conn.execute("SELECT COUNT(*) FROM records WHERE collection='repos'").fetchone()[0]
        events_n = conn.execute("SELECT COUNT(*) FROM records WHERE collection='events'").fetchone()[0]
        pubs_n = conn.execute("SELECT COUNT(*) FROM records WHERE collection='publications'").fetchone()[0]
        conn.close()
        assert repos_n == 1
        assert events_n == 1
        assert pubs_n == 1

    def test_metadata_is_queryable_json(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        row = conn.execute(
            "SELECT json_extract(metadata, '$.name') FROM records WHERE collection='repos'"
        ).fetchone()
        conn.close()
        assert row[0] == 'myrepo'

    def test_schema_table_populated(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        rows = conn.execute("SELECT * FROM _schema WHERE collection='repos'").fetchall()
        conn.close()
        assert len(rows) > 0

    def test_metadata_table_has_frontmatter(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        row = conn.execute("SELECT value FROM _metadata WHERE key='readme_frontmatter'").fetchone()
        conn.close()
        assert row is not None
        fm = json.loads(row[0])
        assert fm['name'] == 'repoindex export'

    def test_empty_export_creates_db(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, [], [], version='0.12.0')
        assert (tmp_path / "archive.db").exists()
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        n = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        conn.close()
        assert n == 0
