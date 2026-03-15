"""Tests for arkiv exporter."""

import io
import json

import pytest

from repoindex.exporters.arkiv import (
    ArkivExporter,
    _repo_to_arkiv,
    _event_to_arkiv,
)


SAMPLE_REPO = {
    'name': 'alpha-lib',
    'path': '/home/user/alpha-lib',
    'language': 'Python',
    'languages': json.dumps(['Python', 'Shell']),
    'branch': 'main',
    'is_clean': True,
    'remote_url': 'https://github.com/user/alpha-lib',
    'owner': 'user',
    'license_key': 'mit',
    'description': 'A test library',
    'scanned_at': '2026-02-15T14:32:07Z',
    'has_readme': 1,
    'has_license': 1,
    'has_ci': 0,
    'has_citation': 1,
    'readme_content': '# Alpha Lib\n\nA test library.',
    'github_stars': 42,
    'github_forks': 3,
    'github_is_private': 0,
    'github_is_fork': 0,
    'github_is_archived': 0,
    'github_topics': json.dumps(['python', 'library']),
    'github_created_at': '2024-01-01T00:00:00Z',
    'github_updated_at': '2026-02-15T14:32:07Z',
    'citation_doi': '10.5281/zenodo.12345',
    'citation_title': 'Alpha Library',
    'citation_authors': json.dumps([
        {'given-names': 'Alice', 'family-names': 'Smith'},
    ]),
    'citation_version': '2.0.0',
    'citation_repository': 'https://github.com/user/alpha-lib',
    'citation_license': 'MIT',
}

MINIMAL_REPO = {
    'name': 'bare-repo',
    'path': '/home/user/bare-repo',
}

SAMPLE_COMMIT_EVENT = {
    'repo_path': '/home/user/alpha-lib',
    'repo_name': 'alpha-lib',
    'type': 'commit',
    'ref': 'abc1234',
    'message': 'feat: Add new feature',
    'author': 'Alice',
    'timestamp': '2026-02-15T14:32:07Z',
    'data': {'branch': 'main'},
}

SAMPLE_TAG_EVENT = {
    'repo_path': '/home/user/alpha-lib',
    'repo_name': 'alpha-lib',
    'type': 'git_tag',
    'ref': 'v2.0.0',
    'message': 'Release 2.0.0',
    'author': 'Alice',
    'timestamp': '2026-02-14T09:00:00Z',
    'data': {},
}

UNANNOTATED_TAG_EVENT = {
    'repo_path': '/home/user/alpha-lib',
    'repo_name': 'alpha-lib',
    'type': 'git_tag',
    'ref': 'v1.0.0',
    'message': None,
    'author': 'Alice',
    'timestamp': '2026-02-13T00:00:00Z',
    'data': {},
}


# ============================================================================
# Repo conversion
# ============================================================================

class TestRepoToArkiv:
    def test_mimetype_is_directory(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        assert record['mimetype'] == 'inode/directory'

    def test_uri_is_file_path(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        assert record['uri'] == 'file:///home/user/alpha-lib'

    def test_content_omitted(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        assert 'content' not in record

    def test_timestamp_from_scanned_at(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        assert record['timestamp'] == '2026-02-15T14:32:07Z'

    def test_core_metadata(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        meta = record['metadata']
        assert meta['name'] == 'alpha-lib'
        assert meta['language'] == 'Python'
        assert meta['description'] == 'A test library'
        assert meta['branch'] == 'main'
        assert meta['remote_url'] == 'https://github.com/user/alpha-lib'
        assert meta['owner'] == 'user'
        assert meta['license_key'] == 'mit'

    def test_languages_array(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        assert record['metadata']['languages'] == ['Python', 'Shell']

    def test_is_clean_bool(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        assert record['metadata']['is_clean'] is True

    def test_file_presence_flags(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        meta = record['metadata']
        assert meta['has_readme'] is True
        assert meta['has_license'] is True
        assert meta['has_ci'] is False
        assert meta['has_citation'] is True

    def test_readme_in_metadata(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        assert record['metadata']['readme'] == '# Alpha Lib\n\nA test library.'

    def test_github_nested(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        gh = record['metadata']['github']
        assert gh['stars'] == 42
        assert gh['forks'] == 3
        assert gh['topics'] == ['python', 'library']
        assert gh['created_at'] == '2024-01-01T00:00:00Z'

    def test_citation_nested(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        cit = record['metadata']['citation']
        assert cit['doi'] == '10.5281/zenodo.12345'
        assert cit['title'] == 'Alpha Library'
        assert cit['version'] == '2.0.0'
        assert cit['authors'] == [{'given-names': 'Alice', 'family-names': 'Smith'}]

    def test_minimal_repo(self):
        record = _repo_to_arkiv(MINIMAL_REPO)
        assert record['mimetype'] == 'inode/directory'
        assert record['uri'] == 'file:///home/user/bare-repo'
        assert 'content' not in record
        assert 'timestamp' not in record
        assert record['metadata']['name'] == 'bare-repo'
        # No github, citation, etc.
        assert 'github' not in record['metadata']
        assert 'citation' not in record['metadata']
        assert 'readme' not in record['metadata']

    def test_empty_strings_excluded(self):
        repo = {'name': 'test', 'path': '/test', 'description': '', 'owner': ''}
        record = _repo_to_arkiv(repo)
        assert 'description' not in record['metadata']
        assert 'owner' not in record['metadata']

    def test_languages_as_list(self):
        """Languages already parsed as list (not JSON string)."""
        repo = {'name': 'test', 'path': '/test', 'languages': ['Go', 'Rust']}
        record = _repo_to_arkiv(repo)
        assert record['metadata']['languages'] == ['Go', 'Rust']

    def test_github_topics_as_list(self):
        """Topics already parsed as list."""
        repo = {'name': 'test', 'path': '/test', 'github_topics': ['a', 'b']}
        record = _repo_to_arkiv(repo)
        assert record['metadata']['github']['topics'] == ['a', 'b']

    def test_invalid_json_languages_skipped(self):
        repo = {'name': 'test', 'path': '/test', 'languages': 'not json'}
        record = _repo_to_arkiv(repo)
        assert 'languages' not in record['metadata']

    def test_tags_included(self):
        repo = {'name': 'test', 'path': '/test', 'tags': json.dumps(['work/active', 'topic:ml'])}
        record = _repo_to_arkiv(repo)
        assert record['metadata']['tags'] == ['work/active', 'topic:ml']


# ============================================================================
# Event conversion
# ============================================================================

class TestEventToArkiv:
    def test_commit_mimetype(self):
        record = _event_to_arkiv(SAMPLE_COMMIT_EVENT)
        assert record['mimetype'] == 'text/plain'

    def test_commit_content(self):
        record = _event_to_arkiv(SAMPLE_COMMIT_EVENT)
        assert record['content'] == 'feat: Add new feature'

    def test_commit_uri_with_fragment(self):
        record = _event_to_arkiv(SAMPLE_COMMIT_EVENT)
        assert record['uri'] == 'file:///home/user/alpha-lib#abc1234'

    def test_commit_timestamp(self):
        record = _event_to_arkiv(SAMPLE_COMMIT_EVENT)
        assert record['timestamp'] == '2026-02-15T14:32:07Z'

    def test_commit_metadata(self):
        record = _event_to_arkiv(SAMPLE_COMMIT_EVENT)
        meta = record['metadata']
        assert meta['type'] == 'commit'
        assert meta['repo'] == 'alpha-lib'
        assert meta['ref'] == 'abc1234'
        assert meta['author'] == 'Alice'
        assert meta['branch'] == 'main'

    def test_tag_with_message(self):
        record = _event_to_arkiv(SAMPLE_TAG_EVENT)
        assert record['mimetype'] == 'text/plain'
        assert record['content'] == 'Release 2.0.0'
        assert record['uri'] == 'file:///home/user/alpha-lib#v2.0.0'
        assert record['metadata']['type'] == 'git_tag'
        assert record['metadata']['ref'] == 'v2.0.0'

    def test_unannotated_tag_no_content(self):
        record = _event_to_arkiv(UNANNOTATED_TAG_EVENT)
        assert 'mimetype' not in record
        assert 'content' not in record

    def test_unannotated_tag_uri(self):
        record = _event_to_arkiv(UNANNOTATED_TAG_EVENT)
        assert record['uri'] == 'file:///home/user/alpha-lib#v1.0.0'

    def test_event_no_ref(self):
        event = {
            'repo_path': '/home/user/repo',
            'repo_name': 'repo',
            'type': 'branch',
            'ref': '',
            'message': None,
            'data': {},
        }
        record = _event_to_arkiv(event)
        assert record['uri'] == 'file:///home/user/repo'
        assert 'ref' not in record['metadata']

    def test_event_no_author(self):
        event = {
            'repo_path': '/home/user/repo',
            'repo_name': 'repo',
            'type': 'commit',
            'ref': 'abc',
            'message': 'test',
            'data': {},
        }
        record = _event_to_arkiv(event)
        assert 'author' not in record['metadata']


# ============================================================================
# Exporter class
# ============================================================================

class TestArkivExporter:
    def test_attributes(self):
        e = ArkivExporter()
        assert e.format_id == 'arkiv'
        assert e.name == 'Arkiv Universal Records'
        assert e.extension == '.jsonl'

    def test_export_repos_only(self):
        """Without config, only repos are exported (no DB access)."""
        e = ArkivExporter()
        out = io.StringIO()
        count = e.export([SAMPLE_REPO, MINIMAL_REPO], out)
        assert count == 2

        out.seek(0)
        lines = [json.loads(line) for line in out if line.strip()]
        assert len(lines) == 2
        assert lines[0]['mimetype'] == 'inode/directory'
        assert lines[0]['uri'] == 'file:///home/user/alpha-lib'
        assert lines[1]['uri'] == 'file:///home/user/bare-repo'

    def test_export_empty(self):
        e = ArkivExporter()
        out = io.StringIO()
        count = e.export([], out)
        assert count == 0
        assert out.getvalue() == ''

    def test_export_single_repo_valid_jsonl(self):
        """Each line is valid JSON."""
        e = ArkivExporter()
        out = io.StringIO()
        e.export([SAMPLE_REPO], out)
        out.seek(0)
        for line in out:
            if line.strip():
                record = json.loads(line)
                assert 'uri' in record
                assert 'mimetype' in record

    def test_export_preserves_all_arkiv_fields(self):
        """Verify arkiv fields: present fields included, absent fields omitted."""
        e = ArkivExporter()
        out = io.StringIO()
        e.export([SAMPLE_REPO], out)
        out.seek(0)
        record = json.loads(out.readline())
        assert 'mimetype' in record
        assert 'uri' in record
        assert 'metadata' in record
        assert 'content' not in record

    def test_export_no_config_skips_events(self):
        """Without config=None, no events are fetched."""
        e = ArkivExporter()
        out = io.StringIO()
        count = e.export([SAMPLE_REPO], out, config=None)
        assert count == 1  # Just the repo

    def test_export_bad_config_skips_events_gracefully(self):
        """Invalid config doesn't crash, just skips events."""
        e = ArkivExporter()
        out = io.StringIO()
        count = e.export([SAMPLE_REPO], out, config={'database': {'path': '/nonexistent/db'}})
        # Should still export the repo, silently skip events
        assert count >= 1


# ============================================================================
# Discovery
# ============================================================================

class TestArkivDiscovery:
    def test_discovered_in_builtin(self):
        from repoindex.exporters import discover_exporters
        exporters = discover_exporters()
        assert 'arkiv' in exporters

    def test_discovered_with_only_filter(self):
        from repoindex.exporters import discover_exporters
        exporters = discover_exporters(only=['arkiv'])
        assert 'arkiv' in exporters
        assert len(exporters) == 1


# ============================================================================
# Round-trip serialization
# ============================================================================

class TestRoundTrip:
    def test_repo_record_is_valid_json(self):
        record = _repo_to_arkiv(SAMPLE_REPO)
        serialized = json.dumps(record, default=str)
        deserialized = json.loads(serialized)
        assert deserialized['mimetype'] == 'inode/directory'

    def test_event_record_is_valid_json(self):
        record = _event_to_arkiv(SAMPLE_COMMIT_EVENT)
        serialized = json.dumps(record, default=str)
        deserialized = json.loads(serialized)
        assert deserialized['mimetype'] == 'text/plain'
        assert deserialized['content'] == 'feat: Add new feature'

    def test_mixed_output_parseable(self):
        """Simulate repos + events in single JSONL stream."""
        out = io.StringIO()
        repo_record = _repo_to_arkiv(SAMPLE_REPO)
        event_record = _event_to_arkiv(SAMPLE_COMMIT_EVENT)
        out.write(json.dumps(repo_record, default=str) + '\n')
        out.write(json.dumps(event_record, default=str) + '\n')

        out.seek(0)
        records = [json.loads(line) for line in out if line.strip()]
        assert len(records) == 2
        assert records[0]['mimetype'] == 'inode/directory'
        assert records[1]['mimetype'] == 'text/plain'
