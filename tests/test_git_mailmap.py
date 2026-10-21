"""Commit authors are reported through the repo's mailmap.

One person often commits under several names and emails (an HPC node with no
git identity set, a work address, a formal name). git's mailmap is the standard
way to say they are the same person, and `%aN`/`%aE` are the format codes that
honor it; `%an`/`%ae` report the raw header and would split one author in two.
"""

import os
import subprocess

import pytest

from repoindex.events import scan_commits, scan_merges
from repoindex.infra.git_client import GitClient

CANONICAL = ("Alex Example", "alex@example.com")


@pytest.fixture
def mailmapped_repo(tmp_path):
    def git(*args, name="t", email="t@example.com"):
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
        }
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (tmp_path / ".mailmap").write_text(
        f"{CANONICAL[0]} <{CANONICAL[1]}> atowell <atowell@node7.hpc.example.edu>\n"
    )
    git("add", ".mailmap")
    git("commit", "-q", "-m", "init", name="atowell", email="atowell@node7.hpc.example.edu")
    git("checkout", "-q", "-b", "side")
    git("commit", "-q", "--allow-empty", "-m", "side work",
        name="atowell", email="atowell@node7.hpc.example.edu")
    git("checkout", "-q", "main")
    git("merge", "-q", "--no-ff", "-m", "merge side", "side",
        name="atowell", email="atowell@node7.hpc.example.edu")
    return tmp_path


def test_scan_commits_reports_the_mailmapped_author(mailmapped_repo):
    events = list(scan_commits(str(mailmapped_repo)))
    assert events
    assert {(e.data["author"], e.data["email"]) for e in events} == {CANONICAL}


def test_scan_merges_reports_the_mailmapped_author(mailmapped_repo):
    [event] = list(scan_merges(str(mailmapped_repo)))
    assert (event.data["author"], event.data["email"]) == CANONICAL


def test_git_client_log_reports_the_mailmapped_author(mailmapped_repo):
    commits = GitClient().log(str(mailmapped_repo))
    assert commits
    assert {(c.author, c.email) for c in commits} == {CANONICAL}
