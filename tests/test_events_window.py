"""Event-scan window: config-driven `since` and no per-repo commit-count cap.

The git-event scanner used to hard-cap at 50 commits per repo, so commit
counts saturated and history was truncated regardless of the time window.
These tests pin the new behavior: a single config-driven time window
(events.since, default 6m) bounds the scan, and there is no count cap.
"""

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from repoindex.config import get_events_since, get_default_config
from repoindex.events import scan_events


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _make_repo(path: Path, n_commits: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "Test")
    for i in range(n_commits):
        _git(path, "commit", "--allow-empty", "-m", f"feat: commit {i}")


class TestEventsSinceConfig:
    def test_default_is_six_months(self):
        assert get_events_since({}) == "6m"

    def test_default_config_has_events_since(self):
        assert get_default_config()["events"]["since"] == "6m"

    def test_config_override(self):
        assert get_events_since({"events": {"since": "1y"}}) == "1y"

    def test_empty_or_missing_events_falls_back(self):
        assert get_events_since({"events": {}}) == "6m"
        assert get_events_since({"events": None}) == "6m"


class TestNoCommitCountCap:
    def test_scan_returns_more_than_fifty_commits(self, tmp_path):
        # 55 > the old hard cap of 50; all must come through within the window.
        repo = tmp_path / "busy"
        _make_repo(repo, 55)
        since = datetime.now() - timedelta(days=365)
        events = list(scan_events([str(repo)], types=["commit"], since=since))
        commits = [e for e in events if e.type == "commit"]
        assert len(commits) == 55, (
            f"expected 55 commits, got {len(commits)} "
            "(per-repo count cap should be removed)"
        )

    def test_since_window_still_bounds_the_scan(self, tmp_path):
        # With a future `since`, no commits fall in the window.
        repo = tmp_path / "future"
        _make_repo(repo, 10)
        since = datetime.now() + timedelta(days=1)
        events = list(scan_events([str(repo)], types=["commit"], since=since))
        assert [e for e in events if e.type == "commit"] == []
