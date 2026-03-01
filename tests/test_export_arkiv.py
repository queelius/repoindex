"""Tests for arkiv directory export."""
import json
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

    def test_creates_subdirectory(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        output = tmp_path / "subdir" / "archive"
        export_archive(output, MOCK_REPOS, [], version='0.12.0')
        assert output.exists()
        assert (output / "repos.jsonl").exists()


class TestCollectMetaKeys:
    def test_flat_dict(self):
        from repoindex.exporters.arkiv import _collect_meta_keys
        keys = _collect_meta_keys({'name': 'foo', 'language': 'Python'})
        assert set(keys) == {'name', 'language'}

    def test_nested_dict(self):
        from repoindex.exporters.arkiv import _collect_meta_keys
        keys = _collect_meta_keys({'github': {'stars': 5, 'forks': 1}})
        assert 'github' in keys
        assert 'github.stars' in keys
        assert 'github.forks' in keys
