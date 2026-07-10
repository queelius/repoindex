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
                     "created_at": "2026-05-01T10:00:00Z",
                     "published_at": "2026-05-01T10:00:00Z",
                     "html_url": "r", "author": {"login": "al"}},
                    {"tag_name": "v1", "name": "v1",
                     "created_at": "2026-01-01T10:00:00Z",
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

    def test_release_early_stop_keys_on_created_at(self):
        # The list is ordered by creation; published_at can be out of order
        # (backdated / late-published releases). Keying the early-stop on
        # published_at falsely truncates the stream — same hazard the GitHub
        # client documents for iter_releases.
        from repoindex.sources.forges.gitea import GiteaSource
        forge = GiteaSource()
        releases = [{"tag_name": "v3", "name": "v3",
                     "created_at": "2026-05-01T10:00:00Z",
                     "published_at": "2026-05-01T10:00:00Z",
                     "html_url": "r", "author": {"login": "al"}},
                    {"tag_name": "v2-backdated", "name": "v2",
                     "created_at": "2026-04-20T10:00:00Z",
                     "published_at": "2026-01-05T10:00:00Z",
                     "html_url": "r", "author": {"login": "al"}},
                    {"tag_name": "v1", "name": "v1",
                     "created_at": "2026-01-01T10:00:00Z",
                     "published_at": "2026-01-01T10:00:00Z",
                     "html_url": "r0", "author": {"login": "al"}}]

        def fake_iter(host, path, config):
            if "/releases" in path:
                return iter(releases)
            return iter([])

        with patch.object(forge, "_iter_list", side_effect=fake_iter):
            events = list(forge.fetch_events(self._repo(),
                                             datetime(2026, 3, 1), {}))
        assert [e.data["tag"] for e in events] == ["v3", "v2-backdated"]


class TestSharedItemToEvent:
    """The event payload contract is defined once on GitForge; Gitea mirrors
    GitHub's JSON field names, so one mapping serves every forge."""

    def _forge(self):
        class F(GitForge):
            source_id = "f"
            name = "F"

            def detect(self, repo_path, repo_record=None):
                return True

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        return F()

    def test_release_payload(self):
        ev = self._forge()._item_to_event(
            "release",
            {"tag_name": "v1", "name": "One", "html_url": "u",
             "published_at": "2026-05-01T10:00:00Z",
             "author": {"login": "al"}},
            "repo", "/tmp/repo")
        assert ev.type == "release"
        assert ev.data == {"tag": "v1", "title": "One", "url": "u",
                           "author": "al"}
        assert ev.timestamp == datetime(2026, 5, 1, 10, 0, 0)

    def test_pull_request_and_issue_payload(self):
        forge = self._forge()
        item = {"number": 7, "title": "T", "state": "open", "html_url": "u",
                "created_at": "2026-05-02T10:00:00Z", "user": {"login": "bo"}}
        for etype in ("pull_request", "issue"):
            ev = forge._item_to_event(etype, item, "repo", "/tmp/repo")
            assert ev.type == etype
            assert ev.data == {"number": 7, "title": "T", "state": "open",
                               "url": "u", "author": "bo"}


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


class TestForgeIndexReuse:
    """The refresh loop must not re-discover sources (re-scanning
    ~/.repoindex/sources and re-importing user modules) once per repo."""

    def test_fetch_uses_prebuilt_forge_index(self):
        from repoindex.commands.refresh import _fetch_forge_events
        forge = MagicMock()
        ev = MagicMock()
        forge.fetch_events.return_value = iter([ev])
        with patch("repoindex.commands.refresh.lookup_repo_forge") as lookup:
            out = list(_fetch_forge_events(
                {"forge_id": "github", "path": "/tmp/x"},
                datetime(2026, 1, 1), {},
                forges={"github": forge}))
        lookup.assert_not_called()
        assert out == [ev]

    def test_prebuilt_index_miss_yields_nothing(self):
        from repoindex.commands.refresh import _fetch_forge_events
        with patch("repoindex.commands.refresh.lookup_repo_forge") as lookup:
            out = list(_fetch_forge_events(
                {"forge_id": "sourcehut", "path": "/tmp/x"},
                datetime(2026, 1, 1), {}, forges={}))
        lookup.assert_not_called()
        assert out == []


class TestForgeEventsOnSkippedRepos:
    """Forge activity never touches .git/index, so the incremental-skip
    path must still enqueue repos for the forge-events phase."""

    def _run(self, forge_events, dry_run=False):
        from repoindex.commands.refresh import _process_repo
        db = MagicMock()
        db.fetchone.return_value = {"id": 7, "path": "/tmp/x",
                                    "forge_id": "github"}
        repo = MagicMock()
        repo.path = "/tmp/x"
        repo.name = "x"
        stats = {"scanned": 0, "updated": 0, "skipped": 0,
                 "events_added": 0, "errors": 0}
        pending = []
        with patch("repoindex.commands.refresh.needs_refresh",
                   return_value=False):
            _process_repo(db, MagicMock(), repo, stats, full=False,
                          since=datetime(2026, 1, 1), sources=[], config={},
                          dry_run=dry_run, quiet=True,
                          forge_events=forge_events, forge_pending=pending)
        return stats, pending

    def test_skipped_repo_is_enqueued_for_forge_events(self):
        stats, pending = self._run(forge_events=True)
        assert stats["skipped"] == 1
        assert len(pending) == 1
        record, repo_id, name = pending[0]
        assert repo_id == 7
        assert name == "x"
        assert record["forge_id"] == "github"

    def test_skipped_repo_without_forge_events_not_enqueued(self):
        stats, pending = self._run(forge_events=False)
        assert stats["skipped"] == 1
        assert pending == []

    def test_dry_run_skipped_repo_not_enqueued(self):
        stats, pending = self._run(forge_events=True, dry_run=True)
        assert stats["skipped"] == 1
        assert pending == []


class TestForgeEventsPhase:
    """Network fetches fan out in a thread pool; DB inserts stay serial on
    the caller's thread; one repo's failure doesn't block the rest."""

    def _job(self, repo_id, name):
        return ({"forge_id": "github", "path": f"/tmp/{name}"},
                repo_id, name, datetime(2026, 1, 1))

    def test_inserts_events_per_repo(self):
        from repoindex.commands.refresh import _run_forge_events_phase
        db = MagicMock()
        stats = {"events_added": 0}
        ev = MagicMock()

        def fake_fetch(record, since, config, forges=None):
            return iter([ev])

        with patch("repoindex.commands.refresh._fetch_forge_events",
                   side_effect=fake_fetch), \
             patch("repoindex.commands.refresh.insert_events",
                   return_value=1) as ins:
            _run_forge_events_phase(
                db, [self._job(1, "a"), self._job(2, "b")],
                {}, {}, stats, quiet=True)
        assert stats["events_added"] == 2
        inserted_ids = {call.args[2] for call in ins.call_args_list}
        assert inserted_ids == {1, 2}

    def test_failure_is_isolated_per_repo(self, capsys):
        from repoindex.commands.refresh import _run_forge_events_phase
        db = MagicMock()
        stats = {"events_added": 0}
        ev = MagicMock()

        def fake_fetch(record, since, config, forges=None):
            if record["path"] == "/tmp/bad":
                raise RuntimeError("rate limited")
            return iter([ev])

        jobs = [self._job(1, "good"),
                ({"forge_id": "github", "path": "/tmp/bad"}, 2, "bad",
                 datetime(2026, 1, 1))]
        with patch("repoindex.commands.refresh._fetch_forge_events",
                   side_effect=fake_fetch), \
             patch("repoindex.commands.refresh.insert_events",
                   return_value=1):
            _run_forge_events_phase(db, jobs, {}, {}, stats, quiet=False)
        assert stats["events_added"] == 1
        assert "forge events failed for bad" in capsys.readouterr().err

    def test_fetches_run_concurrently(self):
        import time
        from repoindex.commands.refresh import _run_forge_events_phase
        db = MagicMock()
        stats = {"events_added": 0}

        def slow_fetch(record, since, config, forges=None):
            time.sleep(0.2)
            return iter([])

        jobs = [self._job(i, f"r{i}") for i in range(3)]
        with patch("repoindex.commands.refresh._fetch_forge_events",
                   side_effect=slow_fetch):
            start = time.time()
            _run_forge_events_phase(db, jobs, {}, {}, stats, quiet=True)
            elapsed = time.time() - start
        assert elapsed < 0.5  # serial would be 0.6s+


class TestForgeEventsWindowNarrowing:
    """Steady-state refreshes should fetch only events newer than what the
    DB already holds, not the whole configured window every run."""

    def _db(self, tmp_path):
        from repoindex.database.connection import Database
        from repoindex.database.schema import ensure_schema
        db = Database(db_path=tmp_path / "test.db")
        db.__enter__()
        ensure_schema(db.conn)
        db.execute("INSERT INTO repos (name, path) VALUES ('r', '/tmp/r')")
        return db

    def test_no_stored_events_uses_window(self, tmp_path):
        from repoindex.commands.refresh import _forge_events_since
        db = self._db(tmp_path)
        window = datetime(2026, 1, 1)
        assert _forge_events_since(db, 1, window) == window
        db.__exit__(None, None, None)

    def test_newer_stored_event_narrows_window(self, tmp_path):
        from repoindex.commands.refresh import _forge_events_since
        db = self._db(tmp_path)
        db.execute(
            "INSERT INTO events (repo_id, event_id, type, timestamp) "
            "VALUES (1, 'release_r_v1', 'release', '2026-06-15T10:00:00')")
        # git events must not affect the forge cutoff
        db.execute(
            "INSERT INTO events (repo_id, event_id, type, timestamp) "
            "VALUES (1, 'c1', 'commit', '2026-07-01T10:00:00')")
        db.conn.commit()
        window = datetime(2026, 1, 1)
        assert _forge_events_since(db, 1, window) == datetime(2026, 6, 15, 10)
        db.__exit__(None, None, None)

    def test_older_stored_event_keeps_window(self, tmp_path):
        from repoindex.commands.refresh import _forge_events_since
        db = self._db(tmp_path)
        db.execute(
            "INSERT INTO events (repo_id, event_id, type, timestamp) "
            "VALUES (1, 'release_r_v0', 'release', '2025-01-01T10:00:00')")
        db.conn.commit()
        window = datetime(2026, 1, 1)
        assert _forge_events_since(db, 1, window) == window
        db.__exit__(None, None, None)

    def test_build_jobs_narrow_false_uses_window_verbatim(self, tmp_path):
        # An explicit --since is a backfill request; honor it.
        from repoindex.commands.refresh import _build_forge_jobs
        db = self._db(tmp_path)
        db.execute(
            "INSERT INTO events (repo_id, event_id, type, timestamp) "
            "VALUES (1, 'release_r_v1', 'release', '2026-06-15T10:00:00')")
        db.conn.commit()
        window = datetime(2026, 1, 1)
        pending = [({"forge_id": "github"}, 1, "r")]
        narrowed = _build_forge_jobs(db, pending, window, narrow=True)
        verbatim = _build_forge_jobs(db, pending, window, narrow=False)
        assert narrowed[0][3] == datetime(2026, 6, 15, 10)
        assert verbatim[0][3] == window
        db.__exit__(None, None, None)
