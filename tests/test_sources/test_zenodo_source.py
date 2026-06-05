"""Tests for the Zenodo metadata source."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.sources.registries.zenodo import ZenodoSource, source
from repoindex.infra.zenodo_client import ZenodoRecord


class TestZenodoSourceAttributes:
    def test_source_id(self):
        assert source.source_id == "zenodo"

    def test_name(self):
        assert source.name == "Zenodo"

    def test_is_registry_instance(self):
        from repoindex.sources import Registry
        assert isinstance(source, Registry)

    def test_batch(self):
        assert source.batch is True


class TestZenodoPrefetch:
    @patch('repoindex.infra.zenodo_client.ZenodoClient')
    def test_prefetch_with_orcid(self, mock_cls):
        mock_client = MagicMock()
        mock_client.search_by_orcid.return_value = [
            ZenodoRecord(doi="10.5281/zenodo.123", title="my-repo", url="https://zenodo.org/records/123")
        ]
        mock_cls.return_value = mock_client

        s = ZenodoSource()
        s.prefetch({'author': {'orcid': '0000-0001-1234-5678'}})
        assert len(s._records) == 1
        mock_client.search_by_orcid.assert_called_once_with('0000-0001-1234-5678')

    def test_prefetch_without_orcid(self):
        s = ZenodoSource()
        s.prefetch({'author': {}})
        assert s._records == []

    def test_prefetch_no_author(self):
        s = ZenodoSource()
        s.prefetch({})
        assert s._records == []

    @patch('repoindex.infra.zenodo_client.ZenodoClient')
    def test_prefetch_api_error(self, mock_cls):
        mock_cls.return_value.search_by_orcid.side_effect = Exception("API error")
        s = ZenodoSource()
        s.prefetch({'author': {'orcid': '0000-0001-1234-5678'}})
        assert s._records == []


class TestZenodoDetect:
    def test_detect_always_true(self, tmp_path):
        """Batch sources always return True from detect -- matching happens in fetch()."""
        s = ZenodoSource()
        assert s.detect(str(tmp_path)) is True
        assert s.detect(str(tmp_path), repo_record={}) is True
        assert s.detect('/nonexistent/path') is True


class TestZenodoMatch:
    def test_match_no_records(self, tmp_path):
        s = ZenodoSource()
        s._records = []
        assert s.match(str(tmp_path)) is None

    def test_match_by_github_url(self, tmp_path):
        s = ZenodoSource()
        s._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.123",
                concept_doi="10.5281/zenodo.100",
                title="My Repo",
                version="1.0.0",
                url="https://zenodo.org/records/123",
                github_url="https://github.com/owner/my-repo",
            )
        ]
        result = s.match(
            str(tmp_path),
            repo_record={'remote_url': 'https://github.com/owner/my-repo', 'name': 'my-repo'}
        )
        assert result is not None
        assert result.registry == "zenodo"
        assert result.doi == "10.5281/zenodo.123"
        assert result.concept_doi == "10.5281/zenodo.100"

    def test_match_by_name(self, tmp_path):
        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()
        s = ZenodoSource()
        s._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.456",
                title="my-repo",
                url="https://zenodo.org/records/456",
            )
        ]
        result = s.match(str(repo_dir))
        assert result is not None
        assert result.name == "my-repo"

    def test_match_case_insensitive_name(self, tmp_path):
        repo_dir = tmp_path / "My-Repo"
        repo_dir.mkdir()
        s = ZenodoSource()
        s._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.789",
                title="my-repo",
                url="https://zenodo.org/records/789",
            )
        ]
        result = s.match(str(repo_dir))
        assert result is not None

    def test_match_no_match(self, tmp_path):
        repo_dir = tmp_path / "unmatched"
        repo_dir.mkdir()
        s = ZenodoSource()
        s._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.111",
                title="different-repo",
                url="https://zenodo.org/records/111",
            )
        ]
        result = s.match(str(repo_dir))
        assert result is None

    def test_match_stores_both_dois(self, tmp_path):
        s = ZenodoSource()
        s._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.123",
                concept_doi="10.5281/zenodo.100",
                title="My Repo",
                version="1.0.0",
                url="https://zenodo.org/records/123",
                github_url="https://github.com/owner/my-repo",
            )
        ]
        result = s.match(
            str(tmp_path),
            repo_record={'remote_url': 'https://github.com/owner/my-repo', 'name': 'my-repo'},
        )
        assert result is not None
        assert result.doi == "10.5281/zenodo.123"
        assert result.concept_doi == "10.5281/zenodo.100"

    def test_match_concept_doi_none_keeps_version_doi(self, tmp_path):
        s = ZenodoSource()
        s._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.123",
                concept_doi=None,
                title="My Repo",
                url="https://zenodo.org/records/123",
                github_url="https://github.com/owner/my-repo",
            )
        ]
        result = s.match(
            str(tmp_path),
            repo_record={'remote_url': 'https://github.com/owner/my-repo', 'name': 'my-repo'},
        )
        assert result is not None
        assert result.doi == "10.5281/zenodo.123"
        assert result.concept_doi is None


class TestZenodoFetch:
    def test_fetch_returns_match_dict(self, tmp_path):
        """fetch() returns metadata.to_dict() when match succeeds."""
        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()
        s = ZenodoSource()
        s._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.456",
                concept_doi="10.5281/zenodo.400",
                title="my-repo",
                url="https://zenodo.org/records/456",
                version="2.0.0",
            )
        ]
        result = s.fetch(str(repo_dir))
        assert result is not None
        assert result['registry'] == 'zenodo'
        assert result['name'] == 'my-repo'
        assert result['doi'] == '10.5281/zenodo.456'
        assert result['concept_doi'] == '10.5281/zenodo.400'
        assert result['version'] == '2.0.0'
        assert result['published'] is True

    def test_fetch_returns_none_no_match(self, tmp_path):
        repo_dir = tmp_path / "unmatched"
        repo_dir.mkdir()
        s = ZenodoSource()
        s._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.111",
                title="different",
                url="https://zenodo.org/records/111",
            )
        ]
        assert s.fetch(str(repo_dir)) is None

    def test_fetch_returns_none_no_records(self, tmp_path):
        s = ZenodoSource()
        s._records = []
        assert s.fetch(str(tmp_path)) is None
