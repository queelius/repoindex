"""Tests for batched cleanup_missing_repos (perf commit, v2.1).

Pins:
- Only repos gone from disk are removed (exists()-semantics preserved).
- Survivors on disk are untouched.
- Deletion is issued as chunked DELETE ... WHERE id IN (...) statements,
  not one DELETE per missing row.
"""

from pathlib import Path
from unittest.mock import patch

from repoindex.database.connection import Database
from repoindex.database.repository import cleanup_missing_repos, get_repo_count


def _make_repo_dir(base: Path, name: str) -> Path:
    repo = base / name
    (repo / ".git").mkdir(parents=True)
    return repo


def test_removes_only_missing_repos(tmp_path):
    db_path = Path(tmp_path) / "test.db"
    present = _make_repo_dir(tmp_path, "alive-a")
    present_b = _make_repo_dir(tmp_path, "alive-b")
    with Database(db_path=db_path) as db:
        for p, n in [
            (str(present), "alive-a"),
            (str(present_b), "alive-b"),
            (str(tmp_path / "gone-1"), "gone-1"),
            (str(tmp_path / "gone-2"), "gone-2"),
            (str(tmp_path / "gone-3"), "gone-3"),
        ]:
            db.execute("INSERT INTO repos (name, path) VALUES (?, ?)", (n, p))

        removed = cleanup_missing_repos(db)
        assert removed == 3
        assert get_repo_count(db) == 2

        db.execute("SELECT name FROM repos ORDER BY name")
        survivors = [row["name"] for row in db.fetchall()]
        assert survivors == ["alive-a", "alive-b"]


def test_no_missing_repos_is_noop(tmp_path):
    db_path = Path(tmp_path) / "test.db"
    present = _make_repo_dir(tmp_path, "alive")
    with Database(db_path=db_path) as db:
        db.execute("INSERT INTO repos (name, path) VALUES (?, ?)", ("alive", str(present)))
        removed = cleanup_missing_repos(db)
        assert removed == 0
        assert get_repo_count(db) == 1


def test_deletes_are_batched_not_per_row(tmp_path):
    db_path = Path(tmp_path) / "test.db"
    with Database(db_path=db_path) as db:
        for i in range(5):
            db.execute(
                "INSERT INTO repos (name, path) VALUES (?, ?)",
                (f"gone-{i}", str(tmp_path / f"gone-{i}")),
            )

        real_execute = db.execute
        delete_calls = []

        def _spy(sql, params=()):
            if sql.strip().upper().startswith("DELETE"):
                delete_calls.append(sql)
            return real_execute(sql, params)

        with patch.object(db, "execute", side_effect=_spy):
            removed = cleanup_missing_repos(db)

        assert removed == 5
        # All 5 missing ids removed in a single chunked DELETE ... IN (...),
        # not five individual deletes.
        assert len(delete_calls) == 1
        assert "WHERE id IN" in delete_calls[0]
