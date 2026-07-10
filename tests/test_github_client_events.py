"""Paginated, since-aware GitHub list iterators for events."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from repoindex.infra.github_client import GitHubClient


def _resp(json_data, status=200, headers=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data
    r.headers = headers or {}
    return r


def test_iter_releases_stops_before_since():
    # Releases are sorted by created_at desc, so the early-stop keys on it.
    client = GitHubClient(token="t")
    page1 = [
        {"tag_name": "v3", "name": "v3", "created_at": "2026-05-01T00:00:00Z",
         "published_at": "2026-05-01T00:00:00Z", "html_url": "u3",
         "author": {"login": "a"}},
        {"tag_name": "v2", "name": "v2", "created_at": "2026-01-01T00:00:00Z",
         "published_at": "2026-01-01T00:00:00Z", "html_url": "u2",
         "author": {"login": "a"}},
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


def test_iter_pulls_stops_before_since():
    client = GitHubClient(token="t")
    page1 = [
        {"number": 10, "title": "newer", "created_at": "2026-05-01T00:00:00Z",
         "html_url": "u", "state": "open", "user": {"login": "a"}},
        {"number": 9, "title": "older", "created_at": "2025-01-01T00:00:00Z",
         "html_url": "u", "state": "closed", "user": {"login": "a"}},
    ]
    with patch("repoindex.infra.github_client.requests.get",
               return_value=_resp(page1)) as g:
        out = list(client.iter_pulls("o", "n", since=datetime(2026, 3, 1)))
    assert [p["number"] for p in out] == [10]
    assert g.call_count == 1


def test_rate_limit_raises_instead_of_silent_truncation():
    client = GitHubClient(token="t")
    with patch("repoindex.infra.github_client.requests.get",
               return_value=_resp([], status=403)):
        with pytest.raises(RuntimeError):
            list(client.iter_releases("o", "n", since=datetime(2026, 1, 1)))


def test_non_200_returns_empty():
    client = GitHubClient(token="t")
    with patch("repoindex.infra.github_client.requests.get",
               return_value=_resp([], status=404)):
        out = list(client.iter_issues("o", "n", since=datetime(2026, 1, 1)))
    assert out == []


def test_network_error_mid_pagination_raises():
    # A silent return here records a truncated event stream as success;
    # INSERT OR IGNORE dedup means the gap is never backfilled.
    import requests as requests_lib
    client = GitHubClient(token="t")
    page1 = [{"tag_name": f"v{i}", "name": f"v{i}",
              "created_at": "2026-05-01T00:00:00Z",
              "html_url": "u", "author": {"login": "a"}} for i in range(100)]
    with patch("repoindex.infra.github_client.requests.get",
               side_effect=[_resp(page1),
                            requests_lib.exceptions.ConnectionError("boom")]):
        with pytest.raises(RuntimeError):
            list(client.iter_releases("o", "n", since=datetime(2026, 1, 1)))


def test_server_error_raises():
    client = GitHubClient(token="t")
    with patch("repoindex.infra.github_client.requests.get",
               return_value=_resp([], status=500)):
        with pytest.raises(RuntimeError):
            list(client.iter_releases("o", "n", since=datetime(2026, 1, 1)))


def test_gh_cli_token_fallback_for_pagination(monkeypatch):
    # A user authenticated only via `gh auth login` must not paginate
    # unauthenticated at 60 req/hr.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("REPOINDEX_GITHUB_TOKEN", raising=False)
    with patch.object(GitHubClient, "_check_gh_cli", return_value=True):
        client = GitHubClient()
    gh_token = MagicMock(returncode=0, stdout="ghtok\n")
    with patch("repoindex.infra.github_client.subprocess.run",
               return_value=gh_token), \
            patch("repoindex.infra.github_client.requests.get",
                  return_value=_resp([])) as g:
        list(client.iter_releases("o", "n", since=datetime(2026, 1, 1)))
    headers = g.call_args.kwargs["headers"]
    assert headers["Authorization"] == "token ghtok"


def test_pagination_updates_rate_limit_status():
    client = GitHubClient(token="t")
    hdrs = {"X-RateLimit-Remaining": "42", "X-RateLimit-Limit": "5000",
            "X-RateLimit-Reset": "0", "X-RateLimit-Used": "8"}
    with patch("repoindex.infra.github_client.requests.get",
               return_value=_resp([], headers=hdrs)):
        list(client.iter_releases("o", "n", since=datetime(2026, 1, 1)))
    assert client._rate_limit_status is not None
    assert client._rate_limit_status.remaining == 42


def test_since_none_paginates_until_short_page():
    client = GitHubClient(token="t")
    page1 = [{"tag_name": f"v{i}", "name": f"v{i}",
              "created_at": "2026-05-01T00:00:00Z",
              "published_at": "2026-05-01T00:00:00Z",
              "html_url": "u", "author": {"login": "a"}} for i in range(100)]
    page2 = [{"tag_name": "v100", "name": "v100",
              "created_at": "2026-04-01T00:00:00Z",
              "published_at": "2026-04-01T00:00:00Z",
              "html_url": "u", "author": {"login": "a"}}]
    with patch("repoindex.infra.github_client.requests.get",
               side_effect=[_resp(page1), _resp(page2)]) as g:
        out = list(client.iter_releases("o", "n", since=None))
    assert len(out) == 101
    assert g.call_count == 2


def test_timezone_aware_since_does_not_crash():
    client = GitHubClient(token="t")
    page1 = [{"tag_name": "v1", "name": "v1",
              "created_at": "2026-05-01T00:00:00Z",
              "published_at": "2026-05-01T00:00:00Z",
              "html_url": "u", "author": {"login": "a"}}]
    with patch("repoindex.infra.github_client.requests.get",
               side_effect=[_resp(page1), _resp([])]):
        out = list(client.iter_releases(
            "o", "n", since=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert [r["tag_name"] for r in out] == ["v1"]
