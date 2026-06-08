"""Tests for the GitForge.fetch_events capability and forge event fetching."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from repoindex.sources import GitForge


class TestFetchEventsDefault:
    def test_default_raises_not_implemented(self):
        class BareForge(GitForge):
            source_id = "bare"
            name = "Bare"

            def detect(self, repo_path, repo_record=None):
                return True

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        forge = BareForge()
        with pytest.raises(NotImplementedError):
            list(forge.fetch_events({"forge_owner": "o", "forge_name": "n"},
                                    datetime(2026, 1, 1), {}))


class TestGitHubFetchEvents:
    def _repo(self):
        return {"forge_id": "github", "forge_owner": "o", "forge_name": "n",
                "remote_url": "https://github.com/o/n"}

    def test_translates_releases_pulls_issues(self):
        from repoindex.sources.forges.github import GitHubSource
        forge = GitHubSource()
        client = MagicMock()
        client.iter_releases.return_value = [
            {"tag_name": "v1.2", "name": "Release 1.2",
             "published_at": "2026-05-01T10:00:00Z", "html_url": "r",
             "author": {"login": "alice"}}]
        client.iter_pulls.return_value = [
            {"number": 9, "title": "Add thing", "created_at": "2026-05-02T10:00:00Z",
             "html_url": "p", "state": "open", "user": {"login": "bob"}}]
        client.iter_issues.return_value = [
            {"number": 3, "title": "A bug", "created_at": "2026-05-03T10:00:00Z",
             "html_url": "i", "state": "closed", "user": {"login": "cara"}}]
        with patch.object(forge, "_get_client", return_value=client), \
             patch.object(forge, "_resolve_token", return_value="t"):
            events = list(forge.fetch_events(self._repo(),
                                             datetime(2026, 1, 1), {}))
        by_type = {e.type: e for e in events}
        assert set(by_type) == {"release", "pull_request", "issue"}
        assert by_type["release"].data["tag"] == "v1.2"
        assert by_type["release"].id == "release_n_v1.2"
        assert by_type["pull_request"].data["number"] == 9
        assert by_type["issue"].data["number"] == 3
        assert by_type["issue"].data["state"] == "closed"

    def test_unresolvable_owner_yields_nothing(self):
        from repoindex.sources.forges.github import GitHubSource
        forge = GitHubSource()
        events = list(forge.fetch_events({"forge_id": "github"},
                                         datetime(2026, 1, 1), {}))
        assert events == []
