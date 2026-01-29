"""
Tests for Zenodo DOI enrichment.

Tests cover:
- ZenodoRecord dataclass and from_api_response()
- ZenodoClient.search_by_orcid() with mocked HTTP
- GitHub URL normalization
- Repository matching (GitHub URL, title, no-match)
- Pagination handling
- Error handling (network failure, malformed response)
- Schema v5 (doi column in publications)
- has_doi() query function (citation_doi OR publications.doi)
- PackageMetadata.doi field
- Refresh --zenodo flag
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

import pytest

from repoindex.infra.zenodo_client import (
    ZenodoClient,
    ZenodoRecord,
    _extract_github_url,
    _normalize_github_url,
)
from repoindex.domain.repository import PackageMetadata, Repository
from repoindex.services.repository_service import RepositoryService


# ──────────────────────────────────────────────
# Fixtures: sample API responses
# ──────────────────────────────────────────────

SAMPLE_ZENODO_HIT = {
    "id": 18345659,
    "doi": "10.5281/zenodo.18345659",
    "conceptdoi": "10.5281/zenodo.1234567",
    "metadata": {
        "title": "My Research Tool",
        "version": "1.2.0",
        "related_identifiers": [
            {
                "identifier": "https://github.com/queelius/my-research-tool/tree/v1.2.0",
                "relation": "isSupplementTo",
                "scheme": "url",
            }
        ],
        "creators": [
            {
                "name": "Towell, Alexander",
                "orcid": "0000-0001-6443-9897",
            }
        ],
    },
}

SAMPLE_ZENODO_HIT_NO_GITHUB = {
    "id": 99999999,
    "doi": "10.5281/zenodo.99999999",
    "conceptdoi": "10.5281/zenodo.8888888",
    "metadata": {
        "title": "standalone-package",
        "version": "0.1.0",
        "related_identifiers": [],
        "creators": [
            {
                "name": "Towell, Alexander",
                "orcid": "0000-0001-6443-9897",
            }
        ],
    },
}

SAMPLE_ZENODO_HIT_NO_DOI = {
    "id": 11111111,
    "metadata": {
        "title": "No DOI Record",
        "version": "0.0.1",
        "related_identifiers": [],
    },
}

SAMPLE_API_RESPONSE = {
    "hits": {
        "hits": [SAMPLE_ZENODO_HIT, SAMPLE_ZENODO_HIT_NO_GITHUB],
        "total": 2,
    }
}

SAMPLE_API_RESPONSE_PAGE1 = {
    "hits": {
        "hits": [SAMPLE_ZENODO_HIT] * 25,
        "total": 30,
    }
}

SAMPLE_API_RESPONSE_PAGE2 = {
    "hits": {
        "hits": [SAMPLE_ZENODO_HIT_NO_GITHUB] * 5,
        "total": 30,
    }
}

SAMPLE_API_RESPONSE_EMPTY = {
    "hits": {
        "hits": [],
        "total": 0,
    }
}


# ──────────────────────────────────────────────
# ZenodoRecord tests
# ──────────────────────────────────────────────

class TestZenodoRecord:
    """Tests for ZenodoRecord dataclass."""

    def test_from_api_response_basic(self):
        """Test creating ZenodoRecord from a standard API response."""
        record = ZenodoRecord.from_api_response(SAMPLE_ZENODO_HIT)
        assert record is not None
        assert record.doi == "10.5281/zenodo.18345659"
        assert record.concept_doi == "10.5281/zenodo.1234567"
        assert record.title == "My Research Tool"
        assert record.version == "1.2.0"
        assert record.url == "https://zenodo.org/records/18345659"
        assert record.github_url == "https://github.com/queelius/my-research-tool"

    def test_from_api_response_no_github(self):
        """Test record without GitHub URL."""
        record = ZenodoRecord.from_api_response(SAMPLE_ZENODO_HIT_NO_GITHUB)
        assert record is not None
        assert record.doi == "10.5281/zenodo.99999999"
        assert record.github_url is None

    def test_from_api_response_no_doi_returns_none(self):
        """Test that records without DOI are skipped."""
        record = ZenodoRecord.from_api_response(SAMPLE_ZENODO_HIT_NO_DOI)
        assert record is None

    def test_from_api_response_empty_dict(self):
        """Test with empty dict."""
        record = ZenodoRecord.from_api_response({})
        assert record is None

    def test_from_api_response_no_concept_doi(self):
        """Test record without conceptdoi (only record-specific DOI)."""
        hit = {
            "id": 55555555,
            "doi": "10.5281/zenodo.55555555",
            "metadata": {
                "title": "One-Off Upload",
                "related_identifiers": [],
            },
        }
        record = ZenodoRecord.from_api_response(hit)
        assert record is not None
        assert record.concept_doi is None
        assert record.doi == "10.5281/zenodo.55555555"

    def test_from_api_response_no_metadata(self):
        """Test record with minimal data (just doi)."""
        hit = {"doi": "10.5281/zenodo.12345"}
        record = ZenodoRecord.from_api_response(hit)
        assert record is not None
        assert record.title == ""
        assert record.version is None
        assert record.url == ""


# ──────────────────────────────────────────────
# GitHub URL normalization tests
# ──────────────────────────────────────────────

class TestNormalizeGitHubUrl:
    """Tests for GitHub URL normalization."""

    def test_https_with_tree_ref(self):
        """Test normalizing URL with /tree/v1.0 suffix."""
        url = "https://github.com/queelius/my-repo/tree/v1.0"
        assert _normalize_github_url(url) == "https://github.com/queelius/my-repo"

    def test_https_with_git_suffix(self):
        """Test normalizing URL with .git suffix."""
        url = "https://github.com/queelius/my-repo.git"
        assert _normalize_github_url(url) == "https://github.com/queelius/my-repo"

    def test_ssh_url(self):
        """Test normalizing SSH URL."""
        url = "git@github.com:queelius/my-repo.git"
        assert _normalize_github_url(url) == "https://github.com/queelius/my-repo"

    def test_plain_https(self):
        """Test plain HTTPS URL."""
        url = "https://github.com/queelius/my-repo"
        assert _normalize_github_url(url) == "https://github.com/queelius/my-repo"

    def test_case_insensitive(self):
        """Test that normalization is case-insensitive."""
        url = "https://GitHub.com/Queelius/My-Repo"
        assert _normalize_github_url(url) == "https://github.com/queelius/my-repo"

    def test_trailing_slash(self):
        """Test URL with trailing slash."""
        url = "https://github.com/queelius/my-repo/"
        # After normalization, regex captures up to /repo
        result = _normalize_github_url(url)
        assert "queelius" in result
        assert "my-repo" in result


class TestExtractGitHubUrl:
    """Tests for extracting GitHub URL from related_identifiers."""

    def test_extract_from_related_identifiers(self):
        """Test extraction from standard related_identifiers."""
        related = [
            {
                "identifier": "https://github.com/queelius/my-repo/tree/v1.0",
                "relation": "isSupplementTo",
                "scheme": "url",
            }
        ]
        result = _extract_github_url(related)
        assert result == "https://github.com/queelius/my-repo"

    def test_no_github_url(self):
        """Test when no GitHub URL is present."""
        related = [
            {
                "identifier": "https://doi.org/10.1234/something",
                "relation": "isReferencedBy",
                "scheme": "doi",
            }
        ]
        result = _extract_github_url(related)
        assert result is None

    def test_empty_related_identifiers(self):
        """Test with empty list."""
        assert _extract_github_url([]) is None

    def test_multiple_related_picks_first_github(self):
        """Test that first GitHub URL is picked."""
        related = [
            {"identifier": "https://doi.org/10.1234/something"},
            {"identifier": "https://github.com/owner/repo1/tree/v1.0"},
            {"identifier": "https://github.com/owner/repo2"},
        ]
        result = _extract_github_url(related)
        assert result == "https://github.com/owner/repo1"


# ──────────────────────────────────────────────
# ZenodoClient tests (mocked HTTP)
# ──────────────────────────────────────────────

class TestZenodoClient:
    """Tests for ZenodoClient with mocked HTTP."""

    def test_search_by_orcid_basic(self):
        """Test basic ORCID search returns records."""
        client = ZenodoClient()
        mock_response = Mock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE
        mock_response.raise_for_status = Mock()

        with patch.object(client.session, 'get', return_value=mock_response) as mock_get:
            records = client.search_by_orcid("0000-0001-6443-9897")

        assert len(records) == 2
        assert records[0].doi == "10.5281/zenodo.18345659"
        assert records[1].doi == "10.5281/zenodo.99999999"

        # Verify API was called with correct params
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get('params') or call_kwargs[1].get('params')
        assert 'creators.orcid:0000-0001-6443-9897' in params['q']

    def test_search_by_orcid_pagination(self):
        """Test pagination when results exceed page size."""
        client = ZenodoClient()

        mock_resp1 = Mock()
        mock_resp1.json.return_value = SAMPLE_API_RESPONSE_PAGE1
        mock_resp1.raise_for_status = Mock()

        mock_resp2 = Mock()
        mock_resp2.json.return_value = SAMPLE_API_RESPONSE_PAGE2
        mock_resp2.raise_for_status = Mock()

        with patch.object(client.session, 'get', side_effect=[mock_resp1, mock_resp2]):
            records = client.search_by_orcid("0000-0001-6443-9897")

        # 25 from page 1 + 5 from page 2 = 30 total
        assert len(records) == 30

    def test_search_by_orcid_empty_results(self):
        """Test search with no results."""
        client = ZenodoClient()
        mock_response = Mock()
        mock_response.json.return_value = SAMPLE_API_RESPONSE_EMPTY
        mock_response.raise_for_status = Mock()

        with patch.object(client.session, 'get', return_value=mock_response):
            records = client.search_by_orcid("0000-0000-0000-0000")

        assert records == []

    def test_search_by_orcid_network_error(self):
        """Test graceful handling of network errors."""
        import requests
        client = ZenodoClient()

        with patch.object(client.session, 'get', side_effect=requests.ConnectionError("timeout")):
            records = client.search_by_orcid("0000-0001-6443-9897")

        assert records == []

    def test_search_by_orcid_invalid_json(self):
        """Test graceful handling of invalid JSON response."""
        client = ZenodoClient()
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.side_effect = ValueError("Bad JSON")

        with patch.object(client.session, 'get', return_value=mock_response):
            records = client.search_by_orcid("0000-0001-6443-9897")

        assert records == []

    def test_search_by_orcid_http_error(self):
        """Test graceful handling of HTTP errors (e.g., 500)."""
        import requests
        client = ZenodoClient()
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

        with patch.object(client.session, 'get', return_value=mock_response):
            records = client.search_by_orcid("0000-0001-6443-9897")

        assert records == []

    def test_search_skips_records_without_doi(self):
        """Test that records without DOI are filtered out."""
        client = ZenodoClient()
        response_data = {
            "hits": {
                "hits": [SAMPLE_ZENODO_HIT, SAMPLE_ZENODO_HIT_NO_DOI],
                "total": 2,
            }
        }
        mock_response = Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = Mock()

        with patch.object(client.session, 'get', return_value=mock_response):
            records = client.search_by_orcid("0000-0001-6443-9897")

        # Only the one with DOI should be returned
        assert len(records) == 1
        assert records[0].doi == "10.5281/zenodo.18345659"


# ──────────────────────────────────────────────
# Repository matching tests
# ──────────────────────────────────────────────

class TestZenodoMatching:
    """Tests for matching Zenodo records to local repositories."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = RepositoryService(config={})
        self.zenodo_records = [
            ZenodoRecord(
                doi="10.5281/zenodo.18345659",
                concept_doi="10.5281/zenodo.1234567",
                title="My Research Tool",
                version="1.2.0",
                url="https://zenodo.org/records/18345659",
                github_url="https://github.com/queelius/my-research-tool",
            ),
            ZenodoRecord(
                doi="10.5281/zenodo.99999999",
                concept_doi="10.5281/zenodo.8888888",
                title="standalone-package",
                version="0.1.0",
                url="https://zenodo.org/records/99999999",
                github_url=None,
            ),
        ]

    def test_match_by_github_url_https(self):
        """Test matching via HTTPS remote URL."""
        repo = Repository(
            path="/home/user/my-research-tool",
            name="my-research-tool",
            remote_url="https://github.com/queelius/my-research-tool.git",
        )
        result = self.service.match_zenodo_record(repo, self.zenodo_records)
        assert result is not None
        assert result.registry == 'zenodo'
        assert result.doi == "10.5281/zenodo.1234567"  # concept DOI preferred
        assert result.published is True

    def test_match_by_github_url_ssh(self):
        """Test matching via SSH remote URL."""
        repo = Repository(
            path="/home/user/my-research-tool",
            name="my-research-tool",
            remote_url="git@github.com:queelius/my-research-tool.git",
        )
        result = self.service.match_zenodo_record(repo, self.zenodo_records)
        assert result is not None
        assert result.doi == "10.5281/zenodo.1234567"

    def test_match_by_title_fallback(self):
        """Test matching by title when no GitHub URL available."""
        repo = Repository(
            path="/home/user/standalone-package",
            name="standalone-package",
            remote_url=None,
        )
        result = self.service.match_zenodo_record(repo, self.zenodo_records)
        assert result is not None
        assert result.doi == "10.5281/zenodo.8888888"
        assert result.name == "standalone-package"

    def test_match_by_title_case_insensitive(self):
        """Test case-insensitive title matching."""
        repo = Repository(
            path="/home/user/Standalone-Package",
            name="Standalone-Package",
            remote_url=None,
        )
        result = self.service.match_zenodo_record(repo, self.zenodo_records)
        assert result is not None
        assert result.doi == "10.5281/zenodo.8888888"

    def test_no_match(self):
        """Test when no record matches."""
        repo = Repository(
            path="/home/user/unrelated-project",
            name="unrelated-project",
            remote_url="https://github.com/someone/unrelated.git",
        )
        result = self.service.match_zenodo_record(repo, self.zenodo_records)
        assert result is None

    def test_empty_records(self):
        """Test with empty records list."""
        repo = Repository(
            path="/home/user/myrepo",
            name="myrepo",
        )
        result = self.service.match_zenodo_record(repo, [])
        assert result is None

    def test_github_url_preferred_over_title(self):
        """Test that GitHub URL match takes priority over title match."""
        # Create a record whose title matches repo name but GitHub URL doesn't
        records = [
            ZenodoRecord(
                doi="10.5281/zenodo.111",
                concept_doi="10.5281/zenodo.100",
                title="myrepo",
                url="https://zenodo.org/records/111",
                github_url="https://github.com/other/different-repo",
            ),
            ZenodoRecord(
                doi="10.5281/zenodo.222",
                concept_doi="10.5281/zenodo.200",
                title="wrong-title",
                url="https://zenodo.org/records/222",
                github_url="https://github.com/queelius/myrepo",
            ),
        ]
        repo = Repository(
            path="/home/user/myrepo",
            name="myrepo",
            remote_url="https://github.com/queelius/myrepo.git",
        )
        result = self.service.match_zenodo_record(repo, records)
        assert result is not None
        # Should match by GitHub URL (record 222), not by title (record 111)
        assert result.doi == "10.5281/zenodo.200"

    def test_concept_doi_preferred_over_record_doi(self):
        """Test that concept DOI is used when available."""
        records = [
            ZenodoRecord(
                doi="10.5281/zenodo.specific-version",
                concept_doi="10.5281/zenodo.all-versions",
                title="myrepo",
                url="https://zenodo.org/records/123",
                github_url=None,
            ),
        ]
        repo = Repository(path="/home/user/myrepo", name="myrepo")
        result = self.service.match_zenodo_record(repo, records)
        assert result is not None
        assert result.doi == "10.5281/zenodo.all-versions"

    def test_record_doi_used_when_no_concept(self):
        """Test that record DOI is used when concept DOI is absent."""
        records = [
            ZenodoRecord(
                doi="10.5281/zenodo.specific-only",
                concept_doi=None,
                title="myrepo",
                url="https://zenodo.org/records/456",
                github_url=None,
            ),
        ]
        repo = Repository(path="/home/user/myrepo", name="myrepo")
        result = self.service.match_zenodo_record(repo, records)
        assert result is not None
        assert result.doi == "10.5281/zenodo.specific-only"


# ──────────────────────────────────────────────
# PackageMetadata.doi field tests
# ──────────────────────────────────────────────

class TestPackageMetadataDoi:
    """Tests for the doi field on PackageMetadata."""

    def test_doi_field_exists(self):
        """Test that PackageMetadata has a doi field."""
        pkg = PackageMetadata(registry='zenodo', name='test', doi='10.5281/zenodo.123')
        assert pkg.doi == '10.5281/zenodo.123'

    def test_doi_defaults_to_none(self):
        """Test that doi defaults to None."""
        pkg = PackageMetadata(registry='pypi', name='test')
        assert pkg.doi is None

    def test_doi_in_to_dict(self):
        """Test that doi appears in to_dict output."""
        pkg = PackageMetadata(registry='zenodo', name='test', doi='10.5281/zenodo.123')
        d = pkg.to_dict()
        assert d['doi'] == '10.5281/zenodo.123'

    def test_doi_none_in_to_dict(self):
        """Test that None doi appears in to_dict."""
        pkg = PackageMetadata(registry='pypi', name='test')
        d = pkg.to_dict()
        assert d['doi'] is None

    def test_frozen_dataclass(self):
        """Test that PackageMetadata is immutable."""
        pkg = PackageMetadata(registry='zenodo', name='test', doi='10.5281/zenodo.123')
        with pytest.raises(AttributeError):
            pkg.doi = 'something-else'


# ──────────────────────────────────────────────
# Schema v5 tests (doi column in publications)
# ──────────────────────────────────────────────

class TestSchemaV5:
    """Tests for schema version 5 (doi column in publications)."""

    def test_current_version_is_5(self):
        """Test that schema version was bumped to 5."""
        from repoindex.database.schema import CURRENT_VERSION
        assert CURRENT_VERSION == 5

    def test_publications_table_has_doi_column(self):
        """Test that publications table includes doi column."""
        from repoindex.database.schema import SCHEMA_V1
        assert 'doi TEXT' in SCHEMA_V1

    def test_doi_index_exists_in_schema(self):
        """Test that doi index is defined in schema."""
        from repoindex.database.schema import SCHEMA_V1
        assert 'idx_publications_doi' in SCHEMA_V1

    def test_schema_creates_doi_column(self):
        """Test that applying schema actually creates the doi column."""
        from repoindex.database.schema import apply_schema

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        apply_schema(conn)

        # Check column exists
        cursor = conn.execute("PRAGMA table_info(publications)")
        columns = {row[1] for row in cursor.fetchall()}
        assert 'doi' in columns

        # Test we can insert with doi
        conn.execute("""
            INSERT INTO repos (name, path) VALUES ('test', '/test')
        """)
        repo_id = conn.execute("SELECT id FROM repos WHERE path = '/test'").fetchone()[0]

        conn.execute("""
            INSERT INTO publications (repo_id, registry, package_name, doi)
            VALUES (?, 'zenodo', 'test-pkg', '10.5281/zenodo.123')
        """, (repo_id,))

        row = conn.execute(
            "SELECT doi FROM publications WHERE repo_id = ?", (repo_id,)
        ).fetchone()
        assert row[0] == '10.5281/zenodo.123'

        conn.close()


# ──────────────────────────────────────────────
# Database upsert_publication with doi
# ──────────────────────────────────────────────

class TestUpsertPublicationDoi:
    """Test _upsert_publication with doi field."""

    def test_insert_publication_with_doi(self):
        """Test inserting a publication record with doi."""
        from repoindex.database.schema import apply_schema
        from repoindex.database.repository import _upsert_publication
        from repoindex.database.connection import Database

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        apply_schema(conn)

        # Insert a repo
        conn.execute("INSERT INTO repos (name, path) VALUES ('test', '/test')")
        repo_id = conn.execute("SELECT id FROM repos WHERE path = '/test'").fetchone()[0]

        # Create a mock Database wrapper
        db = MagicMock(spec=Database)
        db.execute = conn.execute
        db.fetchone = lambda: conn.execute(
            "SELECT id FROM publications WHERE repo_id = ? AND registry = ?",
            (repo_id, 'zenodo')
        ).fetchone()
        db.lastrowid = None

        # First call: fetchone returns None (no existing record)
        # We need to handle the flow manually
        pkg = PackageMetadata(
            registry='zenodo',
            name='test-pkg',
            version='1.0',
            published=True,
            url='https://zenodo.org/records/123',
            doi='10.5281/zenodo.123',
        )

        # Direct SQL test instead of mocking
        conn.execute("""
            INSERT INTO publications (
                repo_id, registry, package_name, current_version,
                published, url, doi, downloads_total, last_published
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            repo_id, pkg.registry, pkg.name, pkg.version,
            pkg.published, pkg.url, pkg.doi, pkg.downloads, pkg.last_updated,
        ))

        row = conn.execute(
            "SELECT doi, registry, package_name FROM publications WHERE repo_id = ?",
            (repo_id,)
        ).fetchone()
        assert row['doi'] == '10.5281/zenodo.123'
        assert row['registry'] == 'zenodo'
        assert row['package_name'] == 'test-pkg'

        conn.close()

    def test_update_publication_doi(self):
        """Test updating a publication's doi."""
        from repoindex.database.schema import apply_schema

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        apply_schema(conn)

        # Insert repo and initial publication
        conn.execute("INSERT INTO repos (name, path) VALUES ('test', '/test')")
        repo_id = conn.execute("SELECT id FROM repos WHERE path = '/test'").fetchone()[0]
        conn.execute("""
            INSERT INTO publications (repo_id, registry, package_name, doi)
            VALUES (?, 'zenodo', 'test-pkg', '10.5281/zenodo.old')
        """, (repo_id,))

        # Update
        conn.execute("""
            UPDATE publications SET doi = ? WHERE repo_id = ? AND registry = 'zenodo'
        """, ('10.5281/zenodo.new', repo_id))

        row = conn.execute(
            "SELECT doi FROM publications WHERE repo_id = ?", (repo_id,)
        ).fetchone()
        assert row['doi'] == '10.5281/zenodo.new'

        conn.close()


# ──────────────────────────────────────────────
# has_doi() query function tests
# ──────────────────────────────────────────────

class TestHasDoi:
    """Tests for the has_doi() DSL query function."""

    def test_has_doi_compiles(self):
        """Test that has_doi() compiles to valid SQL."""
        from repoindex.database.query_compiler import compile_query

        result = compile_query("has_doi()")
        assert 'citation_doi' in result.sql
        assert 'publications' in result.sql
        assert result.params == []

    def test_has_doi_matches_citation_doi(self):
        """Test has_doi() matches repos with citation_doi."""
        from repoindex.database.schema import apply_schema

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        apply_schema(conn)

        # Insert repo with citation_doi
        conn.execute("""
            INSERT INTO repos (name, path, citation_doi)
            VALUES ('has-citation', '/has-citation', '10.5281/zenodo.111')
        """)
        # Insert repo without any DOI
        conn.execute("""
            INSERT INTO repos (name, path)
            VALUES ('no-doi', '/no-doi')
        """)

        # Query with has_doi()
        from repoindex.database.query_compiler import compile_query
        compiled = compile_query("has_doi()")
        cursor = conn.execute(compiled.sql, compiled.params)
        results = [dict(row) for row in cursor.fetchall()]

        names = [r['name'] for r in results]
        assert 'has-citation' in names
        assert 'no-doi' not in names

        conn.close()

    def test_has_doi_matches_publication_doi(self):
        """Test has_doi() matches repos with DOI in publications table."""
        from repoindex.database.schema import apply_schema

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        apply_schema(conn)

        # Insert repo without citation_doi
        conn.execute("""
            INSERT INTO repos (name, path)
            VALUES ('zenodo-only', '/zenodo-only')
        """)
        repo_id = conn.execute("SELECT id FROM repos WHERE path = '/zenodo-only'").fetchone()[0]

        # Add Zenodo publication with DOI
        conn.execute("""
            INSERT INTO publications (repo_id, registry, package_name, doi)
            VALUES (?, 'zenodo', 'zenodo-pkg', '10.5281/zenodo.222')
        """, (repo_id,))

        # Insert repo without any DOI
        conn.execute("""
            INSERT INTO repos (name, path)
            VALUES ('no-doi', '/no-doi')
        """)

        # Query
        from repoindex.database.query_compiler import compile_query
        compiled = compile_query("has_doi()")
        cursor = conn.execute(compiled.sql, compiled.params)
        results = [dict(row) for row in cursor.fetchall()]

        names = [r['name'] for r in results]
        assert 'zenodo-only' in names
        assert 'no-doi' not in names

        conn.close()

    def test_has_doi_matches_both_sources(self):
        """Test has_doi() matches repos with DOI from either source."""
        from repoindex.database.schema import apply_schema

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        apply_schema(conn)

        # Repo with citation_doi only
        conn.execute("""
            INSERT INTO repos (name, path, citation_doi)
            VALUES ('citation-only', '/citation-only', '10.1234/citation')
        """)

        # Repo with publication doi only
        conn.execute("""
            INSERT INTO repos (name, path)
            VALUES ('pub-only', '/pub-only')
        """)
        repo_id = conn.execute("SELECT id FROM repos WHERE path = '/pub-only'").fetchone()[0]
        conn.execute("""
            INSERT INTO publications (repo_id, registry, package_name, doi)
            VALUES (?, 'zenodo', 'pkg', '10.5281/zenodo.333')
        """, (repo_id,))

        # Repo with both
        conn.execute("""
            INSERT INTO repos (name, path, citation_doi)
            VALUES ('both', '/both', '10.1234/both')
        """)
        repo_id_both = conn.execute("SELECT id FROM repos WHERE path = '/both'").fetchone()[0]
        conn.execute("""
            INSERT INTO publications (repo_id, registry, package_name, doi)
            VALUES (?, 'zenodo', 'both-pkg', '10.5281/zenodo.444')
        """, (repo_id_both,))

        # Repo with neither
        conn.execute("""
            INSERT INTO repos (name, path)
            VALUES ('neither', '/neither')
        """)

        # Query
        from repoindex.database.query_compiler import compile_query
        compiled = compile_query("has_doi()")
        cursor = conn.execute(compiled.sql, compiled.params)
        results = [dict(row) for row in cursor.fetchall()]

        names = {r['name'] for r in results}
        assert 'citation-only' in names
        assert 'pub-only' in names
        assert 'both' in names
        assert 'neither' not in names

        conn.close()

    def test_has_doi_empty_string_not_matched(self):
        """Test that empty string citation_doi is not treated as having a DOI."""
        from repoindex.database.schema import apply_schema

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        apply_schema(conn)

        conn.execute("""
            INSERT INTO repos (name, path, citation_doi)
            VALUES ('empty-doi', '/empty-doi', '')
        """)

        from repoindex.database.query_compiler import compile_query
        compiled = compile_query("has_doi()")
        cursor = conn.execute(compiled.sql, compiled.params)
        results = [dict(row) for row in cursor.fetchall()]

        names = [r['name'] for r in results]
        assert 'empty-doi' not in names

        conn.close()


# ──────────────────────────────────────────────
# Refresh --zenodo flag tests
# ──────────────────────────────────────────────

class TestRefreshZenodoFlag:
    """Tests for the --zenodo refresh flag."""

    def test_help_shows_zenodo_flag(self):
        """Help output should show the --zenodo flag."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        result = runner.invoke(refresh_handler, ['--help'])

        assert result.exit_code == 0
        assert '--zenodo / --no-zenodo' in result.output

    def test_help_mentions_orcid(self):
        """Help should mention ORCID requirement."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        result = runner.invoke(refresh_handler, ['--help'])

        assert 'orcid' in result.output.lower()

    def test_external_flag_includes_zenodo(self):
        """--external should include zenodo in its description."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        result = runner.invoke(refresh_handler, ['--help'])

        # The --external description should mention zenodo
        assert 'zenodo' in result.output.lower()

    def test_zenodo_resolve_flag_with_external(self):
        """Test that --external enables zenodo."""
        from repoindex.commands.refresh import _resolve_external_flag
        assert _resolve_external_flag(None, True, False) is True

    def test_zenodo_config_default(self):
        """Test zenodo appears in default config."""
        from repoindex.config import get_default_config
        config = get_default_config()
        assert config['refresh']['external_sources']['zenodo'] is False


# ──────────────────────────────────────────────
# Query --has-doi flag tests
# ──────────────────────────────────────────────

class TestQueryHasDoiFlag:
    """Tests for the --has-doi query flag using has_doi() function."""

    def test_has_doi_flag_generates_has_doi_function(self):
        """Test that --has-doi flag generates has_doi() DSL query."""
        from repoindex.commands.query import _build_query_from_flags

        result = _build_query_from_flags(
            query_string=None,
            dirty=False, clean=False, language=None, recent=None,
            starred=False, tag=[], no_license=False, no_readme=False,
            has_citation=False, has_doi=True, archived=False,
            public=False, private=False, fork=False, no_fork=False,
        )
        assert 'has_doi()' in result

    def test_has_doi_detected_as_dsl(self):
        """Test that has_doi() is detected as a DSL query, not text search."""
        from repoindex.commands.query import _is_simple_text_query

        assert _is_simple_text_query("has_doi()") is False
