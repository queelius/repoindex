# Forge Events Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move forge event-fetching (release, pull_request, issue) behind a `GitForge.fetch_events` capability dispatched by `forge_id`, implement it for GitHub and Gitea via their API token clients, de-platform the event-type taxonomy, wire forge events into `refresh` behind a discrete opt-in toggle, and delete the GitHub-specific `scan_github_*` pile.

**Architecture:** Forge events become the third face of the `GitForge` abstraction alongside `fetch()` (metadata) and `set_*` (actions). `refresh` resolves the owning forge via `forge_actions.lookup_repo_forge(repo_record)` and calls `fetch_events`; a forge without support raises `NotImplementedError` and is skipped. Event provenance is the repo's existing `forge_id` (join), so there is no schema change. The `events` module keeps only platform-agnostic VCS scanners.

**Tech Stack:** Python 3.10+, Click, SQLite, `requests` (Gitea), the existing `GitHubClient` (GitHub), pytest with `unittest.mock`.

**Source spec:** `docs/superpowers/specs/2026-06-06-forge-events-capability-design.md`

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `repoindex/sources/__init__.py` | `GitForge` ABC | Add `fetch_events` (default `NotImplementedError`) |
| `repoindex/domain/event.py` | `Event` + stable `id` | De-platform `id` cases: `release`, `pull_request`, `issue` |
| `repoindex/infra/github_client.py` | GitHub REST client | Add paginated, since-aware `iter_releases`/`iter_pulls`/`iter_issues` |
| `repoindex/sources/forges/github.py` | GitHub forge | Implement `fetch_events` (client list calls to `Event`) |
| `repoindex/sources/forges/gitea.py` | Gitea forge | Implement `fetch_events` (paginated `_request` to `Event`) |
| `repoindex/events/__init__.py` | event scanners + type constants | `FORGE_EVENT_TYPES`; delete `scan_github_*`; drop github dispatch |
| `repoindex/services/event_service.py` | event-type groups, `_build_types` | `FORGE_TYPES`; `forge=` flag with `github=` alias |
| `repoindex/commands/events.py` | `events` CLI | `--forge` flag, `--github` hidden alias |
| `repoindex/config.py` | config defaults + helpers | `refresh.external_sources.forge_events`; `forge_events_enabled()` |
| `repoindex/commands/refresh.py` | refresh pipeline | `--forge-events` flag; dispatch `fetch_events` in `_process_repo` |
| `tests/test_forge_events.py` | new | capability, per-forge translate, dispatch, guards |

---

## Task 1: Add `fetch_events` to the `GitForge` ABC

**Files:**
- Modify: `repoindex/sources/__init__.py` (the `GitForge` class, after `enable_pages`, before `class Registry`)
- Test: `tests/test_forge_events.py` (create)

- [ ] **Step 1: Write the failing test.** Create `tests/test_forge_events.py`:

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestFetchEventsDefault -q`
Expected: FAIL with `AttributeError: 'BareForge' object has no attribute 'fetch_events'`.

- [ ] **Step 3: Add the method.** In `repoindex/sources/__init__.py`, inside `class GitForge`, immediately after the `enable_pages` method (the last method before `class Registry`), add:

```python
    def fetch_events(self, repo_record: dict, since: "datetime", config: dict):
        """Yield forge events (release, pull_request, issue) since the cutoff.

        Returns an iterator of domain ``Event`` objects. Default raises
        ``NotImplementedError`` so forges without event support degrade
        gracefully, exactly like the optional ``set_*`` actions.
        """
        raise NotImplementedError(
            f"{self.source_id} does not support fetch_events"
        )
```

Confirm `datetime` is importable at runtime: the annotation is a string, so no new import is required at module top. (If the file already imports `datetime`, the string annotation still works.)

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestFetchEventsDefault -q`
Expected: `1 passed`.

- [ ] **Step 5: Commit.**

```bash
git add repoindex/sources/__init__.py tests/test_forge_events.py
git commit -m "feat(sources): add GitForge.fetch_events capability (default NotImplementedError)"
```

---

## Task 2: De-platform the `Event.id` taxonomy

The `Event.id` property currently has cases for `github_release`, `pr`, `issue`, `workflow_run`. Rename to the generic vocabulary: `release`, `pull_request`, `issue`. The id stays `repo_name`-based, consistent with `commit`/`git_tag`/`branch`/`merge`.

**Files:**
- Modify: `repoindex/domain/event.py` (the `id` property, lines 62-73)
- Test: `tests/test_event_id_taxonomy.py` (create)

- [ ] **Step 1: Write the failing test.** Create `tests/test_event_id_taxonomy.py`:

```python
"""Event.id uses generic forge event types (no github_ prefix)."""
from datetime import datetime

from repoindex.domain.event import Event


def _ev(etype, data):
    return Event(type=etype, timestamp=datetime(2026, 1, 1),
                 repo_name="demo", repo_path="/tmp/demo", data=data)


def test_release_id():
    assert _ev("release", {"tag": "v1.0"}).id == "release_demo_v1.0"


def test_pull_request_id():
    assert _ev("pull_request", {"number": 42}).id == "pull_request_demo_42"


def test_issue_id():
    assert _ev("issue", {"number": 7}).id == "issue_demo_7"


def test_no_github_prefixed_types_remain():
    import inspect
    from repoindex.domain import event as ev_mod
    src = inspect.getsource(ev_mod.Event.id.fget)
    assert "github_release" not in src
    assert "'pr'" not in src and '"pr"' not in src
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_event_id_taxonomy.py -q`
Expected: FAIL (`release` falls through to the generic `else` branch giving a timestamp-based id; `pull_request` likewise; the `github_release`/`pr` strings still present).

- [ ] **Step 3: Edit the `id` property.** In `repoindex/domain/event.py`, replace the four forge cases (currently `github_release`, `pr`, `issue`, `workflow_run`, lines 62-73):

```python
        elif self.type == 'github_release':
            tag = self.data.get('tag', 'unknown')
            return f"github_release_{self.repo_name}_{tag}"
        elif self.type == 'pr':
            number = self.data.get('number', 'unknown')
            return f"pr_{self.repo_name}_{number}"
        elif self.type == 'issue':
            number = self.data.get('number', 'unknown')
            return f"issue_{self.repo_name}_{number}"
        elif self.type == 'workflow_run':
            run_id = self.data.get('id', 'unknown')
            return f"workflow_run_{self.repo_name}_{run_id}"
```

with:

```python
        elif self.type == 'release':
            tag = self.data.get('tag', 'unknown')
            return f"release_{self.repo_name}_{tag}"
        elif self.type == 'pull_request':
            number = self.data.get('number', 'unknown')
            return f"pull_request_{self.repo_name}_{number}"
        elif self.type == 'issue':
            number = self.data.get('number', 'unknown')
            return f"issue_{self.repo_name}_{number}"
```

Also update the module docstring line 7 (`- (future) pypi_publish, github_release, etc.`) to `- (future) pypi_publish, release, etc.`.

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_event_id_taxonomy.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit.**

```bash
git add repoindex/domain/event.py tests/test_event_id_taxonomy.py
git commit -m "refactor(event): generic forge event id taxonomy (release, pull_request, issue)"
```

---

## Task 3: GitHub client list methods (releases, pulls, issues)

Add paginated, since-aware iterators to `GitHubClient`. They yield raw API dicts and stop once a page's items predate `since`. They reuse the existing auth/header path used by `iter_user_repos` (direct `requests.get` with `self._get_headers()`-style headers).

**Files:**
- Modify: `repoindex/infra/github_client.py` (add three methods after `get_releases`, near line 401)
- Test: `tests/test_github_client_events.py` (create)

First, confirm the header/token accessor the existing `iter_user_repos` uses:

```bash
grep -n "_get_headers\|self.token\|headers =\|def iter_user_repos" repoindex/infra/github_client.py
```

Use whatever header construction `iter_user_repos` uses (it builds an `Authorization: token {self.token}` header and a `User-Agent`). The new methods mirror that exactly.

- [ ] **Step 1: Write the failing test.** Create `tests/test_github_client_events.py`:

```python
"""Paginated, since-aware GitHub list iterators for events."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from repoindex.infra.github_client import GitHubClient


def _resp(json_data, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data
    return r


def test_iter_releases_stops_before_since():
    client = GitHubClient(token="t")
    page1 = [
        {"tag_name": "v3", "name": "v3", "published_at": "2026-05-01T00:00:00Z",
         "html_url": "u3", "author": {"login": "a"}},
        {"tag_name": "v2", "name": "v2", "published_at": "2026-01-01T00:00:00Z",
         "html_url": "u2", "author": {"login": "a"}},
    ]
    with patch("repoindex.infra.github_client.requests.get",
               return_value=_resp(page1)) as g:
        out = list(client.iter_releases("o", "n",
                                        since=datetime(2026, 3, 1)))
    assert [r["tag_name"] for r in out] == ["v3"]
    assert g.call_count == 1  # stopped, did not page further


def test_iter_issues_filters_pull_requests():
    client = GitHubClient(token="t")
    page1 = [
        {"number": 5, "title": "real issue", "created_at": "2026-05-01T00:00:00Z",
         "html_url": "u", "state": "open", "user": {"login": "a"}},
        {"number": 6, "title": "a pr", "created_at": "2026-05-02T00:00:00Z",
         "html_url": "u", "state": "open", "user": {"login": "a"},
         "pull_request": {"url": "x"}},
    ]
    with patch("repoindex.infra.github_client.requests.get",
               side_effect=[_resp(page1), _resp([])]):
        out = list(client.iter_issues("o", "n", since=datetime(2026, 1, 1)))
    assert [i["number"] for i in out] == [5]
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_github_client_events.py -q`
Expected: FAIL with `AttributeError: 'GitHubClient' object has no attribute 'iter_releases'`.

- [ ] **Step 3: Implement the iterators.** In `repoindex/infra/github_client.py`, after `get_releases` (around line 401), add a shared paginator and the three methods:

```python
    def _iter_pages(self, endpoint: str, ts_key: str, since):
        """Yield items from a paginated list endpoint, newest-first.

        Stops as soon as an item's ``ts_key`` timestamp is older than
        ``since`` (the API is queried in descending creation order, so the
        first out-of-window item means every later item is too). ``since``
        may be None to fetch all pages.
        """
        from datetime import datetime as _dt
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "repoindex"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        page = 1
        while True:
            sep = "&" if "?" in endpoint else "?"
            url = f"https://api.github.com/{endpoint}{sep}per_page=100&page={page}"
            try:
                resp = requests.get(url, headers=headers, timeout=30)
            except requests.RequestException:
                return
            if resp.status_code != 200:
                return
            items = resp.json()
            if not isinstance(items, list) or not items:
                return
            for item in items:
                if since is not None:
                    raw = item.get(ts_key)
                    if raw:
                        try:
                            when = _dt.fromisoformat(raw.replace("Z", "+00:00"))
                            if when.replace(tzinfo=None) < since:
                                return
                        except ValueError:
                            pass
                yield item
            if len(items) < 100:
                return
            page += 1

    def iter_releases(self, owner: str, name: str, since=None):
        """Yield release dicts for owner/name, newest-first, stopping at since."""
        yield from self._iter_pages(
            f"repos/{owner}/{name}/releases", "published_at", since)

    def iter_pulls(self, owner: str, name: str, since=None):
        """Yield pull-request dicts, newest-first by creation, stopping at since."""
        yield from self._iter_pages(
            f"repos/{owner}/{name}/pulls?state=all&sort=created&direction=desc",
            "created_at", since)

    def iter_issues(self, owner: str, name: str, since=None):
        """Yield issue dicts (excluding PRs), newest-first, stopping at since."""
        for item in self._iter_pages(
                f"repos/{owner}/{name}/issues?state=all&sort=created&direction=desc",
                "created_at", since):
            if "pull_request" not in item:
                yield item
```

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_github_client_events.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit.**

```bash
git add repoindex/infra/github_client.py tests/test_github_client_events.py
git commit -m "feat(github-client): paginated since-aware iter_releases/iter_pulls/iter_issues"
```

---

## Task 4: GitHub forge `fetch_events`

Translate the client iterators into domain `Event` objects.

**Files:**
- Modify: `repoindex/sources/forges/github.py` (add `fetch_events` after `enable_pages`; add `Event` import)
- Test: `tests/test_forge_events.py` (extend)

- [ ] **Step 1: Write the failing test.** Append to `tests/test_forge_events.py`:

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestGitHubFetchEvents -q`
Expected: FAIL (`GitHubSource` has no `fetch_events`).

- [ ] **Step 3: Implement.** In `repoindex/sources/forges/github.py`, add the import near the top (after `from .. import GitForge, RemoteRepo`):

```python
from ...domain.event import Event
```

Add a helper and the method inside `class GitHubSource`, after `enable_pages`:

```python
    @staticmethod
    def _parse_ts(raw: Optional[str]):
        """Parse an ISO8601 GitHub timestamp into a naive datetime."""
        from datetime import datetime
        if not raw:
            return datetime.now()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return datetime.now()

    def fetch_events(self, repo_record: dict, since, config: dict):
        """Yield release/pull_request/issue Events from the GitHub API."""
        owner, name = self._resolve_owner_name(repo_record)
        if not owner or not name:
            return
        client = self._get_client(self._resolve_token(config))
        repo_path = (repo_record or {}).get('path', '')

        for rel in client.iter_releases(owner, name, since=since):
            yield Event(
                type='release', timestamp=self._parse_ts(rel.get('published_at')),
                repo_name=name, repo_path=repo_path,
                data={'tag': rel.get('tag_name') or rel.get('name') or 'unknown',
                      'title': rel.get('name') or '', 'url': rel.get('html_url'),
                      'author': (rel.get('author') or {}).get('login')})
        for pr in client.iter_pulls(owner, name, since=since):
            yield Event(
                type='pull_request', timestamp=self._parse_ts(pr.get('created_at')),
                repo_name=name, repo_path=repo_path,
                data={'number': pr.get('number'), 'title': pr.get('title') or '',
                      'state': pr.get('state'), 'url': pr.get('html_url'),
                      'author': (pr.get('user') or {}).get('login')})
        for issue in client.iter_issues(owner, name, since=since):
            yield Event(
                type='issue', timestamp=self._parse_ts(issue.get('created_at')),
                repo_name=name, repo_path=repo_path,
                data={'number': issue.get('number'), 'title': issue.get('title') or '',
                      'state': issue.get('state'), 'url': issue.get('html_url'),
                      'author': (issue.get('user') or {}).get('login')})
```

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestGitHubFetchEvents -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit.**

```bash
git add repoindex/sources/forges/github.py tests/test_forge_events.py
git commit -m "feat(github-forge): implement fetch_events (releases, PRs, issues)"
```

---

## Task 5: Gitea forge `fetch_events`

Mirror the GitHub forge using Gitea's existing `_request` + the `enumerate_user_repos` pagination pattern. Gitea's API returns arrays; add a small paginated list helper that uses the session directly (the existing `_request` returns one body).

**Files:**
- Modify: `repoindex/sources/forges/gitea.py` (add `fetch_events` + a `_iter_list` helper; add `Event` import)
- Test: `tests/test_forge_events.py` (extend)

- [ ] **Step 1: Write the failing test.** Append to `tests/test_forge_events.py`:

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestGiteaFetchEvents -q`
Expected: FAIL (`GiteaSource` has no `fetch_events`).

- [ ] **Step 3: Implement.** In `repoindex/sources/forges/gitea.py`, add the import after `from .. import GitForge, RemoteRepo`:

```python
from ...domain.event import Event
```

Add inside `class GiteaSource`, after `enable_pages`:

```python
    @staticmethod
    def _parse_ts(raw: Optional[str]):
        from datetime import datetime
        if not raw:
            return datetime.now()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return datetime.now()

    def _iter_list(self, host: str, path: str, config: Optional[dict]):
        """Yield items from a paginated Gitea list endpoint (50 per page)."""
        token = self._get_token(config, host)
        session = self._get_session(host, token)
        page = 1
        while True:
            sep = "&" if "?" in path else "?"
            url = f"https://{host}/api/v1{path}{sep}limit=50&page={page}"
            try:
                resp = session.get(url, timeout=30)
            except requests.RequestException:
                return
            if resp.status_code != 200:
                return
            try:
                items = resp.json()
            except ValueError:
                return
            if not isinstance(items, list) or not items:
                return
            for item in items:
                yield item
            if len(items) < 50:
                return
            page += 1

    def _stop_at(self, items, ts_key: str, since):
        """Yield items until one predates since (Gitea lists are newest-first)."""
        from datetime import datetime
        for item in items:
            if since is not None:
                raw = item.get(ts_key)
                if raw:
                    try:
                        when = datetime.fromisoformat(
                            raw.replace("Z", "+00:00")).replace(tzinfo=None)
                        if when < since:
                            return
                    except ValueError:
                        pass
            yield item

    def fetch_events(self, repo_record: dict, since, config: dict):
        """Yield release/pull_request/issue Events from the Gitea API."""
        host, owner, name = self._resolve_target(repo_record, config)
        if not host or not owner or not name:
            return
        repo_path = (repo_record or {}).get('path', '')
        base = f"/repos/{owner}/{name}"

        rels = self._stop_at(
            self._iter_list(host, f"{base}/releases", config),
            "published_at", since)
        for rel in rels:
            yield Event(
                type='release', timestamp=self._parse_ts(rel.get('published_at')),
                repo_name=name, repo_path=repo_path,
                data={'tag': rel.get('tag_name') or rel.get('name') or 'unknown',
                      'title': rel.get('name') or '', 'url': rel.get('html_url'),
                      'author': (rel.get('author') or {}).get('login')})

        prs = self._stop_at(
            self._iter_list(host, f"{base}/pulls?state=all", config),
            "created_at", since)
        for pr in prs:
            yield Event(
                type='pull_request', timestamp=self._parse_ts(pr.get('created_at')),
                repo_name=name, repo_path=repo_path,
                data={'number': pr.get('number'), 'title': pr.get('title') or '',
                      'state': pr.get('state'), 'url': pr.get('html_url'),
                      'author': (pr.get('user') or {}).get('login')})

        issues = self._stop_at(
            self._iter_list(host, f"{base}/issues?state=all&type=issues", config),
            "created_at", since)
        for issue in issues:
            yield Event(
                type='issue', timestamp=self._parse_ts(issue.get('created_at')),
                repo_name=name, repo_path=repo_path,
                data={'number': issue.get('number'), 'title': issue.get('title') or '',
                      'state': issue.get('state'), 'url': issue.get('html_url'),
                      'author': (issue.get('user') or {}).get('login')})
```

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestGiteaFetchEvents -q`
Expected: `1 passed`.

- [ ] **Step 5: Commit.**

```bash
git add repoindex/sources/forges/gitea.py tests/test_forge_events.py
git commit -m "feat(gitea-forge): implement fetch_events (releases, PRs, issues)"
```

---

## Task 6: De-platform event-type constants and delete `scan_github_*`

**Files:**
- Modify: `repoindex/events/__init__.py` (constants near line 67; the github dispatch in `scan_events`/`scan_repo_events`; delete the nine `scan_github_*` functions)
- Test: `tests/test_forge_events.py` (extend, regression guard)

- [ ] **Step 1: Write the failing guard test.** Append to `tests/test_forge_events.py`:

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestEventsModuleCleanup -q`
Expected: FAIL (functions present, `FORGE_EVENT_TYPES` missing, `GITHUB_EVENT_TYPES` present).

- [ ] **Step 3: Replace the constants.** In `repoindex/events/__init__.py`, replace the `GITHUB_EVENT_TYPES = [...]` block (lines 67-69):

```python
GITHUB_EVENT_TYPES = ['github_release', 'pr', 'issue', 'workflow_run', 'security_alert',
                      'repo_rename', 'repo_transfer', 'repo_visibility', 'repo_archive',
                      'deployment', 'fork', 'star']
```

with:

```python
# Forge events require API calls (opt-in). Generic across forges; provenance
# is the repo's forge_id.
FORGE_EVENT_TYPES = ['release', 'pull_request', 'issue']
```

Then update `REMOTE_EVENT_TYPES` (line 83-87) to use `FORGE_EVENT_TYPES` in place of `GITHUB_EVENT_TYPES`:

```python
REMOTE_EVENT_TYPES = (
    FORGE_EVENT_TYPES + PYPI_EVENT_TYPES + CRAN_EVENT_TYPES + NPM_EVENT_TYPES +
    CARGO_EVENT_TYPES + DOCKER_EVENT_TYPES + GEM_EVENT_TYPES + NUGET_EVENT_TYPES +
    MAVEN_EVENT_TYPES
)
```

- [ ] **Step 4: Remove the github dispatch from the orchestrators.** In `scan_events` (around lines 2987-3056) and `scan_repo_events` (around lines 3186-3202), delete the blocks that call `scan_github_prs`/`scan_github_issues`/`scan_github_workflows`/`scan_github_security_alerts`/`scan_github_deployments`/`scan_github_forks`/`scan_github_stars`/`scan_github_releases`/`scan_github_repo_events`. Find them:

```bash
grep -n "scan_github_" repoindex/events/__init__.py
```

Delete each `if '<github_type>' in types:` block that calls a `scan_github_*` function (the local `scan_git_tags`/`scan_commits`/`scan_branches`/`scan_merges` calls stay).

- [ ] **Step 5: Delete the nine functions.** Remove the function bodies `scan_github_releases`, `scan_github_prs`, `scan_github_issues`, `scan_github_workflows`, `scan_github_security_alerts`, `scan_github_repo_events`, `scan_github_deployments`, `scan_github_forks`, `scan_github_stars` (definition lines from the grep above). After removal, re-grep to confirm zero `def scan_github_` remain.

- [ ] **Step 6: Run the guard + import check.**

Run: `.venv/bin/python -c "import repoindex.events"` (expect no error)
Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestEventsModuleCleanup -q`
Expected: `3 passed`.

- [ ] **Step 7: Fix fallout.** Other modules/tests may reference the deleted names. Find and update:

```bash
grep -rn "GITHUB_EVENT_TYPES\|scan_github_\|'github_release'\|\"github_release\"\|'pr'\b" repoindex/ tests/ | grep -v test_forge_events
```

For each hit in `repoindex/` update to `FORGE_EVENT_TYPES` / generic types. For tests asserting the old taxonomy, update them to the generic vocabulary (or delete if they tested deleted `scan_github_*`).

- [ ] **Step 8: Commit.**

```bash
git add repoindex/events/__init__.py tests/
git commit -m "refactor(events): FORGE_EVENT_TYPES, delete scan_github_* pile"
```

---

## Task 7: `event_service` forge type group and `_build_types`

**Files:**
- Modify: `repoindex/services/event_service.py` (`GITHUB_TYPES` at line 52; `_build_types` github param)
- Test: `tests/test_forge_events.py` (extend)

- [ ] **Step 1: Write the failing test.** Append:

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestEventServiceForgeTypes -q`
Expected: FAIL (`FORGE_TYPES` missing; `_build_types` has no `forge` kwarg).

- [ ] **Step 3: Implement.** In `repoindex/services/event_service.py`:

Replace line 52 `GITHUB_TYPES = events_module.GITHUB_EVENT_TYPES` with:

```python
    FORGE_TYPES = events_module.FORGE_EVENT_TYPES
```

Update `_build_types` (lines 124-149) to accept `forge` (with `github` kept as a back-compat alias):

```python
    def _build_types(
        self,
        types: Optional[List[str]],
        github: bool = False,
        pypi: bool = False,
        cran: bool = False,
        all_types: bool = False,
        forge: bool = False,
    ) -> List[str]:
        """Build list of event types from flags."""
        if types:
            return list(types)
        if all_types:
            return self.ALL_TYPES.copy()
        result = self.LOCAL_TYPES.copy()
        if forge or github:  # github is a back-compat alias for forge
            result.extend(self.FORGE_TYPES)
        if pypi:
            result.extend(self.PYPI_TYPES)
        if cran:
            result.extend(self.CRAN_TYPES)
        return result
```

Update the `scan` method signature/call (lines 66-116) so a `forge` flag threads through: add `forge: bool = False` to `scan(...)` params and pass `forge=forge` into `_build_types`. The existing `github` param stays and also routes to forge types.

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestEventServiceForgeTypes -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit.**

```bash
git add repoindex/services/event_service.py tests/test_forge_events.py
git commit -m "refactor(event-service): FORGE_TYPES and _build_types forge flag (github alias)"
```

---

## Task 8: `events` command `--forge` flag (with `--github` alias)

**Files:**
- Modify: `repoindex/commands/events.py` (the `--github` option + handler)
- Test: `tests/test_forge_events.py` (extend)

First read the current option and handler:

```bash
grep -n "github\|def events\|@click.option\|service.scan\|_build_types" repoindex/commands/events.py
```

- [ ] **Step 1: Write the failing test.** Append (adjust the command import to the real handler name found above, commonly `events_handler` registered as `events`):

```python
class TestEventsForgeFlag:
    def test_forge_and_github_alias_accepted(self):
        from click.testing import CliRunner
        import repoindex.commands.events as ev
        handler = getattr(ev, 'events_handler', None) or ev.events
        params = {p.name for p in handler.params}
        assert 'forge' in params
        assert 'github' in params  # retained hidden alias
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestEventsForgeFlag -q`
Expected: FAIL (no `forge` param).

- [ ] **Step 3: Implement.** In `repoindex/commands/events.py`, add a `--forge` option beside the existing `--github` one, mark `--github` hidden, and route both into the service. Add the decorator:

```python
@click.option('--forge', is_flag=True, help='Include forge events (releases, PRs, issues)')
@click.option('--github', is_flag=True, hidden=True, help='Deprecated alias for --forge')
```

Add `forge: bool` to the handler signature and pass `forge=forge or github` where the handler calls `service.scan(...)` (replacing the bare `github=github`). If the handler previously passed `github=github`, change to `forge=forge or github`.

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestEventsForgeFlag -q`
Expected: `1 passed`.

- [ ] **Step 5: Commit.**

```bash
git add repoindex/commands/events.py tests/test_forge_events.py
git commit -m "feat(events-cmd): --forge flag with --github as hidden alias"
```

---

## Task 9: Config toggle for forge events

**Files:**
- Modify: `repoindex/config.py` (`get_default_config` `refresh.external_sources`; YAML template; add `forge_events_enabled` helper near `get_events_since`)
- Test: `tests/test_forge_events.py` (extend)

- [ ] **Step 1: Write the failing test.** Append:

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestForgeEventsConfig -q`
Expected: FAIL (`forge_events_enabled` missing; key absent).

- [ ] **Step 3: Implement.** In `repoindex/config.py`, add the key to `get_default_config()` under `refresh.external_sources`:

```python
            "external_sources": {
                "github": False,   # GitHub API (stars, topics) - moderate speed
                "forge_events": False,  # Forge events (releases, PRs, issues) - slow
            },
```

Add to the YAML template `refresh.external_sources` block:

```yaml
  external_sources:
    github: false   # GitHub API (stars, topics) - moderate speed
    forge_events: false  # Forge events (releases, PRs, issues) - slow, opt-in
```

Add the helper after `get_events_since`:

```python
def forge_events_enabled(config: dict) -> bool:
    """Whether refresh should fetch forge events (releases, PRs, issues).

    Slow (per-repo API calls), so opt-in. Default False. Enabled by the
    config key refresh.external_sources.forge_events or the --forge-events flag.
    """
    return bool(
        ((config.get('refresh') or {}).get('external_sources') or {})
        .get('forge_events', False)
    )
```

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestForgeEventsConfig -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit.**

```bash
git add repoindex/config.py tests/test_forge_events.py
git commit -m "feat(config): refresh.external_sources.forge_events toggle (default off)"
```

---

## Task 10: Wire `--forge-events` into refresh

**Files:**
- Modify: `repoindex/commands/refresh.py` (add `--forge-events` flag; thread to `_process_repo`; dispatch after the local event scan at lines 643-656)
- Test: `tests/test_forge_events.py` (extend)

- [ ] **Step 1: Write the failing test.** Append (a focused unit test of the dispatch helper added in Step 3):

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestRefreshForgeDispatch -q`
Expected: FAIL (`_fetch_forge_events` missing).

- [ ] **Step 3: Implement the dispatch helper.** In `repoindex/commands/refresh.py`, add near the top imports:

```python
from ..services.forge_actions import lookup_repo_forge
```

Add this helper (module level, near `_parse_since`):

```python
def _fetch_forge_events(repo_record: dict, since, config: dict):
    """Dispatch to the repo's GitForge.fetch_events; yield Events.

    Returns nothing if the repo has no resolved forge or the forge does not
    support events. Network/API errors propagate to the caller, which
    isolates them per repo.
    """
    forge = lookup_repo_forge(repo_record)
    if forge is None:
        return
    try:
        yield from forge.fetch_events(repo_record, since, config)
    except NotImplementedError:
        return
```

- [ ] **Step 4: Run it, expect PASS.**

Run: `.venv/bin/python -m pytest tests/test_forge_events.py::TestRefreshForgeDispatch -q`
Expected: `3 passed`.

- [ ] **Step 5: Add the flag and call site.** Add the option decorator on `refresh_handler` (next to `--external`, around line 129):

```python
@click.option('--forge-events', 'forge_events', is_flag=True, default=None,
              help='Fetch forge events (releases, PRs, issues). Slow; requires forge_id from a metadata refresh.')
```

Add `forge_events: Optional[bool]` to the handler signature. Resolve it against config near where `since` is resolved:

```python
    from ..config import forge_events_enabled
    do_forge_events = forge_events if forge_events is not None else forge_events_enabled(config)
```

Thread `do_forge_events` into `_process_repo` (add a `forge_events: bool = False` parameter to `_process_repo` and pass it at the call site around line 282-290). Inside `_process_repo`, after the local event scan block (after line 656), add:

```python
        # Forge events (opt-in, network): dispatch to the repo's forge.
        if repo_id and forge_events:
            try:
                db.execute("SELECT * FROM repos WHERE id = ?", (repo_id,))
                rec = db.fetchone()
                if rec:
                    fe = list(_fetch_forge_events(dict(rec), since, config))
                    if fe:
                        stats['events_added'] += insert_events(db, fe, repo_id)
            except Exception as e:
                if not quiet:
                    click.echo(f"Warning: forge events failed for {repo.name}: {e}", err=True)
```

- [ ] **Step 6: Run the focused suite + import check.**

Run: `.venv/bin/python -c "import repoindex.commands.refresh"`
Run: `.venv/bin/python -m pytest tests/test_forge_events.py -q`
Expected: all pass.

- [ ] **Step 7: Commit.**

```bash
git add repoindex/commands/refresh.py tests/test_forge_events.py
git commit -m "feat(refresh): --forge-events opt-in, dispatch fetch_events by forge_id"
```

---

## Task 11: Full-suite regression, CHANGELOG, final commit

**Files:**
- Modify: `CHANGELOG.md` (Unreleased section)

- [ ] **Step 1: Run the full suite.**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. If anything references the removed `GITHUB_EVENT_TYPES`/`scan_github_*`/old types, fix it per Task 6 Step 7 and re-run.

- [ ] **Step 2: Manual smoke (optional, needs token).**

```bash
GITHUB_TOKEN="$(gh auth token)" .venv/bin/repoindex refresh --forge-events --quiet
.venv/bin/repoindex sql "SELECT type, COUNT(*) n FROM events WHERE type IN ('release','pull_request','issue') GROUP BY type"
```

Expected: nonzero `release`/`pull_request`/`issue` counts for repos with GitHub activity.

- [ ] **Step 3: CHANGELOG.** Under `## Unreleased` in `CHANGELOG.md`, add:

```markdown
### Added

- Forge events (release, pull_request, issue) are now fetched behind a
  `GitForge.fetch_events` capability dispatched by `forge_id`, implemented for
  GitHub and Gitea. Enable during refresh with `--forge-events` (or config
  `refresh.external_sources.forge_events`). Event types are generic; forge
  provenance is the repo's `forge_id`.

### Removed

- The GitHub-specific `scan_github_*` functions and the `github_`-prefixed event
  type vocabulary. Forge event-fetching now goes through the forge abstraction.
```

- [ ] **Step 4: Commit.**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): forge events capability"
```

---

## Self-Review Notes

- **Spec coverage:** capability (Task 1), de-platformed taxonomy (Tasks 2, 6), GitHub impl (Tasks 3, 4), Gitea impl (Task 5), provenance-via-forge_id with no schema change (no migration task, by design), refresh opt-in toggle (Tasks 9, 10), events-module cleanup (Task 6), CLI `--forge` alias (Task 8), error handling (Task 10 dispatch: `NotImplementedError` skip + per-repo isolation), tests (every task), STABILITY additive method (Task 1). All spec sections map to a task.
- **Auth/transport:** GitHub via `GitHubClient` (Task 3) using the configured token; Gitea via its session (`_get_session`/`_get_token`); no `gh` CLI in the new path.
- **`event_id` reconciliation:** the spec's illustrative `{forge_id}:{owner}/{name}` format is realized through the existing `Event.id` property (`repo_name`-based), keeping forge event ids consistent with `commit`/`git_tag` ids. `INSERT OR IGNORE` in `insert_events` provides idempotent re-fetch.
- **Type consistency:** `fetch_events(repo_record, since, config)` signature is identical across the ABC and both forges; event `data` keys (`tag`, `number`, `title`, `state`, `url`, `author`) match the `Event.id` property's expectations (`tag` for release, `number` for pull_request/issue).
