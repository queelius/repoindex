"""Tests for the Zenodo provider wrapper."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.providers.zenodo import ZenodoProvider, provider
from repoindex.infra.zenodo_client import ZenodoRecord


class TestZenodoProviderAttributes:
    def test_registry(self):
        assert provider.registry == "zenodo"

    def test_name(self):
        assert provider.name == "Zenodo"

    def test_batch(self):
        assert provider.batch is True


class TestZenodoPrefetch:
    @patch('repoindex.infra.zenodo_client.ZenodoClient')
    def test_prefetch_with_orcid(self, mock_cls):
        mock_client = MagicMock()
        mock_client.search_by_orcid.return_value = [
            ZenodoRecord(doi="10.5281/zenodo.123", title="my-repo", url="https://zenodo.org/records/123")
        ]
        mock_cls.return_value = mock_client

        p = ZenodoProvider()
        p.prefetch({'author': {'orcid': '0000-0001-1234-5678'}})
        assert len(p._records) == 1
        mock_client.search_by_orcid.assert_called_once_with('0000-0001-1234-5678')

    def test_prefetch_without_orcid(self):
        p = ZenodoProvider()
        p.prefetch({'author': {}})
        assert p._records == []

    def test_prefetch_no_author(self):
        p = ZenodoProvider()
        p.prefetch({})
        assert p._records == []

    @patch('repoindex.infra.zenodo_client.ZenodoClient')
    def test_prefetch_api_error(self, mock_cls):
        mock_cls.return_value.search_by_orcid.side_effect = Exception("API error")
        p = ZenodoProvider()
        p.prefetch({'author': {'orcid': '0000-0001-1234-5678'}})
        assert p._records == []


class TestZenodoMatch:
    def test_match_no_records(self, tmp_path):
        p = ZenodoProvider()
        p._records = []
        assert p.match(str(tmp_path)) is None

    def test_match_by_github_url(self, tmp_path):
        p = ZenodoProvider()
        p._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.123",
                concept_doi="10.5281/zenodo.100",
                title="My Repo",
                version="1.0.0",
                url="https://zenodo.org/records/123",
                github_url="https://github.com/owner/my-repo",
            )
        ]
        result = p.match(
            str(tmp_path),
            repo_record={'remote_url': 'https://github.com/owner/my-repo', 'name': 'my-repo'}
        )
        assert result is not None
        assert result.registry == "zenodo"
        assert result.doi == "10.5281/zenodo.100"

    def test_match_by_name(self, tmp_path):
        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()
        p = ZenodoProvider()
        p._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.456",
                title="my-repo",
                url="https://zenodo.org/records/456",
            )
        ]
        result = p.match(str(repo_dir))
        assert result is not None
        assert result.name == "my-repo"

    def test_match_case_insensitive_name(self, tmp_path):
        repo_dir = tmp_path / "My-Repo"
        repo_dir.mkdir()
        p = ZenodoProvider()
        p._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.789",
                title="my-repo",
                url="https://zenodo.org/records/789",
            )
        ]
        result = p.match(str(repo_dir))
        assert result is not None

    def test_match_no_match(self, tmp_path):
        repo_dir = tmp_path / "unmatched"
        repo_dir.mkdir()
        p = ZenodoProvider()
        p._records = [
            ZenodoRecord(
                doi="10.5281/zenodo.111",
                title="different-repo",
                url="https://zenodo.org/records/111",
            )
        ]
        result = p.match(str(repo_dir))
        assert result is None

    def test_detect_returns_none(self):
        """Batch providers don't use detect()."""
        p = ZenodoProvider()
        assert p.detect("/some/path") is None

    def test_check_returns_none(self):
        """Batch providers don't use check()."""
        p = ZenodoProvider()
        assert p.check("some-name") is None
