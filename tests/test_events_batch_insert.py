"""Tests for the batched (executemany) insert_events path (perf commit, v2.1).

Pins:
- insert_events returns the count of NEWLY inserted rows under
  INSERT OR IGNORE (a re-inserted overlapping batch counts only new rows).
- insert_events issues a single executemany call (not row-at-a-time).
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from repoindex.database.connection import Database
from repoindex.database.events import insert_events, count_events
from repoindex.domain.event import Event


def _commit(repo_name, h):
    return Event(
        type="commit",
        timestamp=datetime.now(),
        repo_name=repo_name,
        repo_path="/test/path",
        data={"hash": h, "message": f"msg {h}"},
    )


def _seed_repo(db):
    db.execute("INSERT INTO repos (name, path) VALUES (?, ?)", ("test-repo", "/test/path"))
    return db.lastrowid


def test_insert_events_returns_new_row_count(tmp_path):
    db_path = Path(tmp_path) / "test.db"
    with Database(db_path=db_path) as db:
        repo_id = _seed_repo(db)
        batch = [_commit("test-repo", "aaaaaaaa1"), _commit("test-repo", "bbbbbbbb2")]
        added = insert_events(db, batch, repo_id)
        assert added == 2
        assert count_events(db, repo_id=repo_id) == 2


def test_insert_events_dedup_counts_only_new(tmp_path):
    db_path = Path(tmp_path) / "test.db"
    with Database(db_path=db_path) as db:
        repo_id = _seed_repo(db)
        first = [_commit("test-repo", "aaaaaaaa1"), _commit("test-repo", "bbbbbbbb2")]
        assert insert_events(db, first, repo_id) == 2
        # Overlapping batch: one duplicate (aaaaaaaa1), one new (cccccccc3).
        second = [_commit("test-repo", "aaaaaaaa1"), _commit("test-repo", "cccccccc3")]
        added = insert_events(db, second, repo_id)
        assert added == 1
        assert count_events(db, repo_id=repo_id) == 3


def test_insert_events_empty_batch_returns_zero(tmp_path):
    db_path = Path(tmp_path) / "test.db"
    with Database(db_path=db_path) as db:
        repo_id = _seed_repo(db)
        assert insert_events(db, [], repo_id) == 0


def test_insert_events_uses_single_executemany(tmp_path):
    db_path = Path(tmp_path) / "test.db"
    with Database(db_path=db_path) as db:
        repo_id = _seed_repo(db)
        # Event.id derives from hash[:8], so the first 8 chars must be
        # distinct to produce 5 distinct event_ids (no INSERT OR IGNORE dedup).
        batch = [_commit("test-repo", f"{i:08d}hash") for i in range(5)]
        with patch.object(Database, "executemany", wraps=db.executemany) as spy:
            added = insert_events(db, batch, repo_id)
        assert added == 5
        assert spy.call_count == 1
