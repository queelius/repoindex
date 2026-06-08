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


class TestGiteaFetchEvents:
    def _repo(self):
        return {"forge_id": "gitea", "forge_host": "codeberg.org",
                "forge_owner": "o", "forge_name": "n",
                "remote_url": "https://codeberg.org/o/n"}

    def test_translates_and_filters_since(self):
        from repoindex.sources.forges.gitea import GiteaSource
        forge = GiteaSource()
        releases = [{"tag_name": "v2", "name": "v2",
                     "published_at": "2026-05-01T10:00:00Z",
                     "html_url": "r", "author": {"login": "al"}},
                    {"tag_name": "v1", "name": "v1",
                     "published_at": "2026-01-01T10:00:00Z",
                     "html_url": "r0", "author": {"login": "al"}}]

        def fake_iter(host, path, config):
            if "/releases" in path:
                return iter(releases)
            return iter([])

        with patch.object(forge, "_iter_list", side_effect=fake_iter):
            events = list(forge.fetch_events(self._repo(),
                                             datetime(2026, 3, 1), {}))
        assert [e.type for e in events] == ["release"]
        assert events[0].data["tag"] == "v2"
        assert events[0].id == "release_n_v2"


class TestEventsModuleCleanup:
    def test_no_scan_github_functions_remain(self):
        import inspect
        from repoindex import events as ev
        src = inspect.getsource(ev)
        assert "def scan_github_" not in src, "scan_github_* must be deleted"

    def test_forge_event_types_are_generic(self):
        from repoindex.events import FORGE_EVENT_TYPES
        assert FORGE_EVENT_TYPES == ['release', 'pull_request', 'issue']
        assert not any('github' in t for t in FORGE_EVENT_TYPES)

    def test_github_event_types_constant_removed(self):
        import repoindex.events as ev
        assert not hasattr(ev, 'GITHUB_EVENT_TYPES')


class TestEventServiceForgeTypes:
    def test_forge_types_constant(self):
        from repoindex.services.event_service import EventService
        assert EventService.FORGE_TYPES == ['release', 'pull_request', 'issue']

    def test_build_types_forge_flag(self):
        from repoindex.services.event_service import EventService
        svc = EventService()
        types = svc._build_types(None, github=False, pypi=False, cran=False,
                                 all_types=False, forge=True)
        assert 'release' in types and 'pull_request' in types

    def test_build_types_github_alias_still_works(self):
        from repoindex.services.event_service import EventService
        svc = EventService()
        types = svc._build_types(None, github=True, pypi=False, cran=False,
                                 all_types=False)
        assert 'release' in types  # github stays a back-compat alias for forge


class TestEventsForgeFlag:
    def _handler(self):
        import repoindex.commands.events as ev
        return getattr(ev, 'events_handler', None) or ev.events

    def test_forge_and_github_alias_accepted(self):
        params = {p.name for p in self._handler().params}
        assert 'forge' in params
        assert 'github' in params  # retained hidden alias


class TestForgeEventsConfig:
    def test_default_off(self):
        from repoindex.config import forge_events_enabled, get_default_config
        assert forge_events_enabled({}) is False
        cfg = get_default_config()
        assert cfg['refresh']['external_sources']['forge_events'] is False

    def test_enabled_via_config(self):
        from repoindex.config import forge_events_enabled
        cfg = {'refresh': {'external_sources': {'forge_events': True}}}
        assert forge_events_enabled(cfg) is True


class TestRefreshForgeDispatch:
    def test_dispatch_inserts_events_via_forge(self):
        from repoindex.commands.refresh import _fetch_forge_events
        forge = MagicMock()
        ev = MagicMock()
        forge.fetch_events.return_value = iter([ev])
        repo_record = {"forge_id": "github", "path": "/tmp/x"}
        with patch("repoindex.commands.refresh.lookup_repo_forge",
                   return_value=forge):
            out = list(_fetch_forge_events(repo_record,
                                           datetime(2026, 1, 1), {}))
        assert out == [ev]
        forge.fetch_events.assert_called_once()

    def test_dispatch_skips_when_no_forge(self):
        from repoindex.commands.refresh import _fetch_forge_events
        with patch("repoindex.commands.refresh.lookup_repo_forge",
                   return_value=None):
            out = list(_fetch_forge_events({"path": "/tmp/x"},
                                           datetime(2026, 1, 1), {}))
        assert out == []

    def test_dispatch_skips_on_not_implemented(self):
        from repoindex.commands.refresh import _fetch_forge_events
        forge = MagicMock()
        forge.fetch_events.side_effect = NotImplementedError
        with patch("repoindex.commands.refresh.lookup_repo_forge",
                   return_value=forge):
            out = list(_fetch_forge_events({"forge_id": "x", "path": "/tmp/x"},
                                           datetime(2026, 1, 1), {}))
        assert out == []
