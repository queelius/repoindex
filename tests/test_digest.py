"""
Tests for the digest command.

Covers:
- parse_commit_prefix: conventional commit parsing
- pick_representative: message selection and dedup
- _build_digest: full digest construction against in-memory DB
"""

import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from repoindex.commands.digest import (
    parse_commit_prefix,
    pick_representative,
    _build_digest,
)


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestParseCommitPrefix:
    """Test conventional commit message parsing."""

    def test_feat_with_scope(self):
        assert parse_commit_prefix("feat(papermill): rewrite review skill") == ("feat", "papermill")

    def test_fix_no_scope(self):
        assert parse_commit_prefix("fix: resolve crash on empty input") == ("fix", None)

    def test_docs_with_scope(self):
        assert parse_commit_prefix("docs(readme): update installation guide") == ("docs", "readme")

    def test_freeform_message(self):
        assert parse_commit_prefix("Add support for new format") == ("other", None)

    def test_empty_string(self):
        assert parse_commit_prefix("") == ("other", None)

    def test_breaking_change_bang(self):
        assert parse_commit_prefix("feat(api)!: remove deprecated endpoint") == ("feat", "api")

    def test_all_conventional_prefixes(self):
        prefixes = ["feat", "fix", "docs", "refactor", "test", "chore",
                     "ci", "style", "perf", "build", "revert"]
        for p in prefixes:
            typ, scope = parse_commit_prefix(f"{p}: do something")
            assert typ == p, f"Failed for prefix '{p}'"
            assert scope is None

    def test_multiline_uses_first_line(self):
        msg = "feat(core): add feature\n\nDetailed description here"
        assert parse_commit_prefix(msg) == ("feat", "core")

    def test_non_conventional_with_colon(self):
        """A colon in a non-conventional message should be 'other'."""
        assert parse_commit_prefix("Update config: add new field") == ("other", None)

    def test_scope_with_hyphen(self):
        assert parse_commit_prefix("fix(pub-pipeline): correct path") == ("fix", "pub-pipeline")

    def test_whitespace_stripping(self):
        assert parse_commit_prefix("  feat: trimmed  \n") == ("feat", None)


class TestPickRepresentative:
    """Test representative message selection."""

    def test_basic_selection(self):
        msgs = ["feat: add X", "fix: repair Y", "Update Z"]
        result = pick_representative(msgs, limit=5)
        assert len(result) == 3

    def test_dedup(self):
        msgs = ["feat: add X", "feat: add X", "fix: repair Y"]
        result = pick_representative(msgs)
        assert len(result) == 2

    def test_limit(self):
        msgs = [f"commit {i}" for i in range(20)]
        result = pick_representative(msgs, limit=5)
        assert len(result) == 5

    def test_conventional_preferred(self):
        """Conventional commits should appear before freeform ones."""
        msgs = ["Update readme", "Add thing", "feat: new feature", "fix: bug fix"]
        result = pick_representative(msgs, limit=5)
        # Conventional should come first
        assert result[0] == "feat: new feature"
        assert result[1] == "fix: bug fix"

    def test_multiline_messages(self):
        msgs = ["feat: add feature\n\nLong description", "fix: bug\n\nMore details"]
        result = pick_representative(msgs)
        assert result == ["feat: add feature", "fix: bug"]

    def test_empty_input(self):
        assert pick_representative([]) == []

    def test_empty_strings_filtered(self):
        msgs = ["", "  ", "feat: real commit"]
        result = pick_representative(msgs)
        assert result == ["feat: real commit"]


# ---------------------------------------------------------------------------
# In-memory DB tests
# ---------------------------------------------------------------------------


# Minimal schema — only the tables/columns digest actually uses
_TEST_SCHEMA = """
CREATE TABLE repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT UNIQUE NOT NULL,
    language TEXT,
    is_clean BOOLEAN DEFAULT 1
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    event_id TEXT UNIQUE,
    type TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    ref TEXT,
    message TEXT,
    author TEXT,
    metadata TEXT,
    FOREIGN KEY (repo_id) REFERENCES repos(id)
);

CREATE INDEX idx_events_repo_type_ts ON events(repo_id, type, timestamp);
"""


def _make_db(conn):
    """Wrap a raw sqlite3 connection in a Database-like object for _build_digest."""
    db = MagicMock()
    db.conn = conn
    conn.row_factory = sqlite3.Row

    cursor_holder = {"cur": None}

    def execute(sql, params=()):
        cursor_holder["cur"] = conn.execute(sql, params)

    def fetchone():
        return cursor_holder["cur"].fetchone()

    def fetchall():
        return cursor_holder["cur"].fetchall()

    db.execute = execute
    db.fetchone = fetchone
    db.fetchall = fetchall
    return db


def _insert_repo(conn, repo_id, name, language="Python", is_clean=True):
    conn.execute(
        "INSERT INTO repos (id, name, path, language, is_clean) VALUES (?, ?, ?, ?, ?)",
        (repo_id, name, f"/home/user/{name}", language, int(is_clean)),
    )


def _insert_event(conn, repo_id, etype, msg, ts, ref=None):
    conn.execute(
        "INSERT INTO events (repo_id, type, message, timestamp, ref) VALUES (?, ?, ?, ?, ?)",
        (repo_id, etype, msg, ts, ref),
    )


@pytest.fixture
def mem_db():
    """Create an in-memory SQLite database with test schema."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_TEST_SCHEMA)
    yield conn
    conn.close()


class TestBuildDigest:
    """Test _build_digest against an in-memory database."""

    def _now(self):
        return datetime(2026, 2, 24, 12, 0, 0)

    def _recent(self, days_ago=1):
        return (self._now() - timedelta(days=days_ago)).isoformat()

    def _old(self):
        return (self._now() - timedelta(days=30)).isoformat()

    def test_basic_structure(self, mem_db):
        _insert_repo(mem_db, 1, "alpha", "Python")
        _insert_event(mem_db, 1, "commit", "feat: add thing", self._recent())
        _insert_event(mem_db, 1, "commit", "fix: repair bug", self._recent())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        assert "period" in data
        assert "summary" in data
        assert "projects" in data
        assert "releases" in data
        assert "languages" in data

        assert data["summary"]["total_commits"] == 2
        assert data["summary"]["repos_active"] == 1
        assert len(data["projects"]) == 1
        assert data["projects"][0]["name"] == "alpha"
        assert data["projects"][0]["commits"] == 2

    def test_by_type_counts(self, mem_db):
        _insert_repo(mem_db, 1, "beta", "R")
        _insert_event(mem_db, 1, "commit", "feat: feature one", self._recent())
        _insert_event(mem_db, 1, "commit", "feat(core): feature two", self._recent())
        _insert_event(mem_db, 1, "commit", "fix: bug", self._recent())
        _insert_event(mem_db, 1, "commit", "Add stuff", self._recent())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        proj = data["projects"][0]
        assert proj["by_type"]["feat"] == 2
        assert proj["by_type"]["fix"] == 1
        assert proj["by_type"]["other"] == 1

    def test_scopes_extraction(self, mem_db):
        _insert_repo(mem_db, 1, "plugins", "Shell")
        _insert_event(mem_db, 1, "commit", "feat(papermill): add draft", self._recent())
        _insert_event(mem_db, 1, "commit", "docs(worldsmith): update readme", self._recent())
        _insert_event(mem_db, 1, "commit", "feat(papermill): fix review", self._recent())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        proj = data["projects"][0]
        assert sorted(proj["scopes"]) == ["papermill", "worldsmith"]

    def test_top_limiting(self, mem_db):
        _insert_repo(mem_db, 1, "busy-repo", "Python")
        _insert_repo(mem_db, 2, "medium-repo", "R")
        _insert_repo(mem_db, 3, "quiet-repo", "Go")

        for i in range(10):
            _insert_event(mem_db, 1, "commit", f"commit {i}", self._recent())
        for i in range(5):
            _insert_event(mem_db, 2, "commit", f"commit {i}", self._recent())
        _insert_event(mem_db, 3, "commit", "single commit", self._recent())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=2)

        assert len(data["projects"]) == 2
        assert data["projects"][0]["name"] == "busy-repo"
        assert data["projects"][1]["name"] == "medium-repo"

    def test_releases_list(self, mem_db):
        _insert_repo(mem_db, 1, "mylib", "Python")
        _insert_event(mem_db, 1, "git_tag", None, self._recent(), ref="v1.0.0")
        _insert_event(mem_db, 1, "git_tag", None, self._recent(), ref="v1.1.0")
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        assert len(data["releases"]) == 2
        tags = [r["tag"] for r in data["releases"]]
        assert "v1.0.0" in tags
        assert "v1.1.0" in tags

    def test_tags_annotated_on_project(self, mem_db):
        """Tags should also appear in the project's tags list."""
        _insert_repo(mem_db, 1, "mylib", "Python")
        _insert_event(mem_db, 1, "commit", "feat: initial", self._recent())
        _insert_event(mem_db, 1, "git_tag", None, self._recent(), ref="v2.0.0")
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        assert data["projects"][0]["tags"] == ["v2.0.0"]

    def test_empty_period(self, mem_db):
        _insert_repo(mem_db, 1, "alpha", "Python")
        _insert_event(mem_db, 1, "commit", "old commit", self._old())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        assert data["projects"] == []
        assert data["summary"]["total_commits"] == 0

    def test_language_distribution(self, mem_db):
        _insert_repo(mem_db, 1, "py1", "Python")
        _insert_repo(mem_db, 2, "py2", "Python")
        _insert_repo(mem_db, 3, "r1", "R")

        _insert_event(mem_db, 1, "commit", "commit", self._recent())
        _insert_event(mem_db, 2, "commit", "commit", self._recent())
        _insert_event(mem_db, 3, "commit", "commit", self._recent())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        # Python should be first (2 repos)
        assert data["languages"][0] == ["Python", 2]
        assert data["languages"][1] == ["R", 1]

    def test_dirty_flag(self, mem_db):
        _insert_repo(mem_db, 1, "dirty-repo", "Python", is_clean=False)
        _insert_event(mem_db, 1, "commit", "change", self._recent())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        assert data["projects"][0]["is_dirty"] is True

    def test_merge_count(self, mem_db):
        _insert_repo(mem_db, 1, "alpha", "Python")
        _insert_event(mem_db, 1, "merge", "Merge branch main", self._recent())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        assert data["summary"]["total_merges"] == 1

    def test_multiple_repos_ordering(self, mem_db):
        """Projects should be ordered by commit count descending."""
        _insert_repo(mem_db, 1, "few-commits", "Python")
        _insert_repo(mem_db, 2, "many-commits", "Python")

        _insert_event(mem_db, 1, "commit", "one", self._recent())
        for i in range(5):
            _insert_event(mem_db, 2, "commit", f"commit {i}", self._recent())
        mem_db.commit()

        db = _make_db(mem_db)
        since = self._now() - timedelta(days=7)
        data = _build_digest(db, since, self._now(), top=None)

        assert data["projects"][0]["name"] == "many-commits"
        assert data["projects"][1]["name"] == "few-commits"
