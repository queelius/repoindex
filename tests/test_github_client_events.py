"""Paginated, since-aware GitHub list iterators for events."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from repoindex.infra.github_client import GitHubClient


def _resp(json_data, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data
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
