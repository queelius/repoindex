"""Tag dates come from real git output, in every supported Python.

Earlier tests fed hand-written `%(creatordate:iso8601)` strings to a mock.
That format ("2024-01-15 10:30:00 -0500") only parsed after ad-hoc string
surgery that Python 3.11+ tolerated and 3.10 rejected, and a rejected date
silently became datetime.now(). These tests run real git so the format the
code requests is the format it parses.
"""

import os
import subprocess
from datetime import datetime

import pytest

from repoindex.events import scan_git_tags
from repoindex.infra.git_client import GitClient

TAG_DATE = "2024-01-15T10:30:00-05:00"


@pytest.fixture
def tagged_repo(tmp_path):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": TAG_DATE, "GIT_COMMITTER_DATE": TAG_DATE,
    }

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "init")
    git("tag", "-a", "v1.0.0", "-m", "Release v1.0.0")
    return tmp_path


def test_scan_git_tags_parses_the_real_tag_date(tagged_repo):
    [event] = list(scan_git_tags(str(tagged_repo)))
    assert event.timestamp == datetime(2024, 1, 15, 10, 30)


def test_scan_git_tags_since_filter_uses_the_real_date(tagged_repo):
    assert list(scan_git_tags(str(tagged_repo), since=datetime(2024, 2, 1))) == []
    assert len(list(scan_git_tags(str(tagged_repo), since=datetime(2024, 1, 1)))) == 1


def test_git_client_tags_parses_the_real_tag_date(tagged_repo):
    [tag] = GitClient().tags(str(tagged_repo))
    assert tag.date == datetime(2024, 1, 15, 10, 30)
