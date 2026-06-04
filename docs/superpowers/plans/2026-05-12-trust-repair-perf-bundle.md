# Trust-Repair + Perf Bundle (v2.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the confirmed correctness and trust defects in repoindex v2.0 and remove the largest refresh bottleneck, across nine isolated commits (eight in the package, one in the plugin), with no new feature surface.

**Architecture:** Bite-sized TDD tasks grouped one theme per commit; the riskiest change (the schema v10 preserve-and-restore migration) is isolated in its own group. The plan respects the v2.0 grain (path is identity, the database is a materialized view, SQL is the read API, no query DSL, no broad MCP mutation) and STABILITY.md (additive only: no signature removals, renames, or type changes).

**Tech Stack:** Python 3.10+, Click, SQLite (schema v10), pytest, hatchling, mkdocs. MCP via FastMCP. The plugin lives in a separate repo (Claude Code plugin markdown).

**Spec:** `docs/superpowers/specs/2026-05-12-trust-repair-perf-bundle-design.md`

**Execution order:** perf, mcp, schema-v10, footguns-cli, footguns-timespec, footguns-data, packaging, docs, plugin. The schema-v10 group bumps `CURRENT_VERSION` to 10; run its migration test before proceeding. The release version bump to 2.1.0 plus tag is a final step after all nine groups, not part of any group. PyPI upload is held for burn-in per project cadence.

**Shared interfaces (must stay consistent across groups):**
- `repoindex/services/timespec.py` `parse_since(spec, now=None) -> datetime` (defined and routed entirely within the footguns-timespec group; `m`=months, `min`=minutes, raises `ValueError` on invalid).
- `concept_doi` nullable column on `publications` and `PackageMetadata.concept_doi` field (schema-v10 group).
- Schema `CURRENT_VERSION = 10` (schema-v10 group).
- `tests/test_version_consistency.py` version-equality check (packaging group).

---

## Commit group: perf

This group has four tasks. Tasks 1 to 3 add characterization and behavior tests plus the three rewrites (language detection, batched event inserts, batched cleanup). Task 4 is the single commit for the group. All test files are real pytest files; the characterization test is written and made to pass against the CURRENT code FIRST (it must stay green across the rewrite, that is the whole point of a characterization test). The two DB tasks add a failing assertion that pins the post-rewrite contract (`executemany` issued once, single chunked `DELETE`).

### Task 1: Characterization test for `_detect_languages`, then rewrite to a single `os.walk`

Files:
- Create: `/home/spinoza/github/beta/repoindex/tests/test_repository_service_languages.py` (new file)
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/services/repository_service.py` (`_detect_languages`, lines 433-480; uses `EXCLUDE_DIRS` at lines 23-26 and `import os` already present at line 11)
- Test path: `/home/spinoza/github/beta/repoindex/tests/test_repository_service_languages.py`

Steps:

- [ ] Write the characterization test file that pins TODAY's output of the existing glob-based `_detect_languages` exactly. Create `/home/spinoza/github/beta/repoindex/tests/test_repository_service_languages.py` with:

```python
"""Characterization tests for RepositoryService._detect_languages.

These tests pin the EXACT current output of the language detector so that
the os.walk rewrite (perf commit, v2.1) is byte-identical in behavior.

Pinned quirks:
- R is counted only from ``.R`` files: the loop overwrites ``counts['R']``
  per extension, so the ``.r`` count is lost (last-write-wins on the
  ``{'.r': 'R', '.R': 'R'}`` insertion order).
- Primary language is ``max(counts, key=counts.get)``, which keeps the
  FIRST key at the max count under Python's stable dict ordering (the
  extensions-dict insertion order).
- EXCLUDE_DIRS basenames (``.venv``, ``node_modules``, ...) are pruned.
- The exclusion is a path-substring test today: a file under a directory
  literally named ``build`` is pruned, and so is a file whose own ancestor
  path contains an EXCLUDE_DIRS token as a substring.
- An empty repo (no recognized source files) returns ``(None, [])``.
"""

from pathlib import Path

import pytest

from repoindex.services.repository_service import RepositoryService


def _svc():
    return RepositoryService(config={})


def _touch(base: Path, rel: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


def test_empty_repo_returns_none_and_empty_list(tmp_path):
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary is None
    assert all_langs == []


def test_single_language(tmp_path):
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "pkg/b.py")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python"]


def test_primary_is_most_files(tmp_path):
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "b.py")
    _touch(tmp_path, "c.py")
    _touch(tmp_path, "x.rs")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python", "Rust"]


def test_r_counts_only_capital_R_extension(tmp_path):
    # Three lowercase .r and one uppercase .R: current code overwrites
    # counts['R'] with the .R count (1), discarding the .r count (3).
    _touch(tmp_path, "one.r")
    _touch(tmp_path, "two.r")
    _touch(tmp_path, "three.r")
    _touch(tmp_path, "four.R")
    _touch(tmp_path, "s1.py")
    _touch(tmp_path, "s2.py")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    # R is pinned at 1 (the .R count), Python at 2, so Python wins.
    assert primary == "Python"
    assert all_langs == ["Python", "R"]


def test_tie_break_keeps_first_extension_dict_order(tmp_path):
    # One .py and one .rs: equal counts. max() keeps the first key seen,
    # and Python (.py) is inserted before Rust (.rs) in the extensions map.
    _touch(tmp_path, "a.py")
    _touch(tmp_path, "b.rs")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    # all_langs is sorted by count desc; on a tie it preserves the
    # dict iteration order produced by sorted(...) (stable sort), which
    # is the counts insertion order: Python then Rust.
    assert all_langs == ["Python", "Rust"]


def test_exclude_dirs_are_pruned(tmp_path):
    _touch(tmp_path, "real.py")
    _touch(tmp_path, ".venv/lib/vendored.py")
    _touch(tmp_path, "node_modules/dep/index.js")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python"]


def test_path_substring_exclusion_prunes_dir_named_build(tmp_path):
    # A directory literally named 'build' is an EXCLUDE_DIRS token, so
    # files beneath it are pruned by the current substring test.
    _touch(tmp_path, "keep.py")
    _touch(tmp_path, "build/generated.py")
    primary, all_langs = _svc()._detect_languages(str(tmp_path))
    assert primary == "Python"
    assert all_langs == ["Python"]
```

- [ ] Run the characterization test against the CURRENT (glob-based) implementation. It MUST pass now, because it pins existing behavior.

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_repository_service_languages.py -v
```

Expected: all 7 tests PASS (characterization baseline established against the existing glob implementation).

- [ ] Add the post-rewrite contract test that pins the substring-exclusion bug guard the spec demands: a repo whose ABSOLUTE path contains an EXCLUDE_DIRS token as a parent must still be scanned (the rewrite walks from `path` itself, so ancestors of `path` are never inspected, fixing the false-prune). Append to `/home/spinoza/github/beta/repoindex/tests/test_repository_service_languages.py`:

```python
def test_repo_under_dir_named_build_is_not_wrongly_pruned(tmp_path):
    # A repo whose own path lives under a directory named 'build' (an
    # EXCLUDE_DIRS token) must still have its sources counted. The rewrite
    # walks from the repo root, so it never inspects ancestor segments.
    repo = tmp_path / "build" / "myproj"
    _touch(repo, "main.py")
    _touch(repo, "lib/util.py")
    primary, all_langs = _svc()._detect_languages(str(repo))
    assert primary == "Python"
    assert all_langs == ["Python"]
```

- [ ] Run the new guard test against the CURRENT implementation to confirm it FAILS (the current substring test wrongly prunes everything because `str(m)` contains `/build/`).

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_repository_service_languages.py::test_repo_under_dir_named_build_is_not_wrongly_pruned -v
```

Expected: FAIL with `assert None == 'Python'` (current code returns `(None, [])` because every match path contains the `build` substring and is filtered out).

- [ ] Rewrite `_detect_languages` to a single `os.walk` that prunes `EXCLUDE_DIRS` from `dirnames` in place, preserving the byte-identical primary/all_langs output (including the `.r`/`.R` last-write-wins quirk and the dict-insertion-order tie-break). Replace lines 433-480 of `/home/spinoza/github/beta/repoindex/repoindex/services/repository_service.py`:

```python
    def _detect_languages(self, path: str) -> tuple:
        """Detect primary language and all languages.

        Single ``os.walk`` pass that prunes ``EXCLUDE_DIRS`` from
        ``dirnames`` in place (so excluded subtrees are never descended)
        instead of ~19 per-extension ``glob`` calls. Output is
        byte-identical to the previous glob implementation, including the
        ``.r``/``.R`` last-write-wins quirk (R is counted from ``.R`` only)
        and the insertion-order tie-break for the primary language.
        """
        extensions = {
            '.py': 'Python',
            '.js': 'JavaScript',
            '.ts': 'TypeScript',
            '.go': 'Go',
            '.rs': 'Rust',
            '.java': 'Java',
            '.c': 'C',
            '.cpp': 'C++',
            '.rb': 'Ruby',
            '.php': 'PHP',
            '.swift': 'Swift',
            '.kt': 'Kotlin',
            '.scala': 'Scala',
            '.r': 'R',
            '.R': 'R',
            '.jl': 'Julia',
            '.sh': 'Shell',
            '.lua': 'Lua',
            '.pl': 'Perl',
        }

        # Per-extension counts (keyed by file extension), so the
        # subsequent per-language collapse preserves the original
        # "last extension wins" overwrite (e.g. .R count replaces .r).
        ext_counts = {ext: 0 for ext in extensions}

        try:
            for dirpath, dirnames, filenames in os.walk(path):
                # Prune excluded directories in place so os.walk never
                # descends into them (.venv, node_modules, build, ...).
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for fname in filenames:
                    _, ext = os.path.splitext(fname)
                    if ext in ext_counts:
                        ext_counts[ext] += 1
        except Exception:
            pass

        # Collapse extensions to languages with the original
        # overwrite semantics: iterate the extensions map in order and
        # assign counts[lang] = count, so a later extension for the same
        # language (".R" after ".r") replaces the earlier value.
        counts: Dict[str, int] = {}
        for ext, lang in extensions.items():
            if ext_counts[ext]:
                counts[lang] = ext_counts[ext]

        if not counts:
            return None, []

        # Primary language is the one with most files (first on ties).
        primary = max(counts, key=counts.get)
        all_langs = sorted(counts.keys(), key=lambda x: counts[x], reverse=True)

        return primary, all_langs
```

- [ ] Run the full language test file. The characterization tests MUST still pass (byte-identical), and the previously-failing guard test MUST now pass.

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_repository_service_languages.py -v
```

Expected: all 8 tests PASS (7 characterization + 1 guard).

- [ ] Manual timed-refresh verification note (owner-witnessed, not a CI assertion): on the real collection, time `repoindex refresh` before and after this change on a repo set with a fat `.venv`. Run:

```
cd /home/spinoza/github/beta/repoindex && time .venv/bin/repoindex refresh
```

Expected: per-repo language detection drops from roughly 0.8s to near-instant; total refresh wall time visibly lower than the v2.0 baseline. Record the before/after seconds in the PR description. No assertion is added for this (timing is environment-dependent); the byte-identical characterization tests are the regression guard.

### Task 2: Batched event inserts via `executemany` with correct `events_added` count

Files:
- Create: `/home/spinoza/github/beta/repoindex/tests/test_events_batch_insert.py` (new file)
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/database/events.py` (`insert_events`, lines 44-61; `json` and `Database` already imported at lines 7 and 12)
- Test path: `/home/spinoza/github/beta/repoindex/tests/test_events_batch_insert.py`

Steps:

- [ ] Write the failing test that pins the batched-insert contract: the return value counts only newly-inserted rows under `INSERT OR IGNORE` dedup (overlapping batch inserted twice), and `executemany` is issued exactly once per call. Create `/home/spinoza/github/beta/repoindex/tests/test_events_batch_insert.py`:

```python
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
        batch = [_commit("test-repo", f"hash{i:08d}") for i in range(5)]
        with patch.object(Database, "executemany", wraps=db.executemany) as spy:
            added = insert_events(db, batch, repo_id)
        assert added == 5
        assert spy.call_count == 1
```

- [ ] Run the new test against the CURRENT row-at-a-time implementation to confirm the executemany contract FAILS.

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_events_batch_insert.py -v
```

Expected: `test_insert_events_uses_single_executemany` FAILS (`assert 0 == 1`: current code never calls `executemany`). The other three pass under the old loop.

- [ ] Rewrite `insert_events` to build param tuples and issue one `executemany`, reporting the newly-inserted count via a `total_changes` delta (correct under `INSERT OR IGNORE` dedup). Replace lines 44-61 of `/home/spinoza/github/beta/repoindex/repoindex/database/events.py`:

```python
def insert_events(db: Database, events: List[Event], repo_id: int) -> int:
    """
    Insert multiple events efficiently.

    Issues a single ``executemany`` (INSERT OR IGNORE) instead of one
    statement per event. The returned count reflects only newly inserted
    rows, measured via a ``conn.total_changes`` delta, so dedup-by
    ``event_id`` does not over-count.

    Args:
        db: Database connection
        events: List of Event domain objects
        repo_id: ID of the associated repository

    Returns:
        Number of events actually inserted (excludes ignored duplicates)
    """
    if not events:
        return 0

    rows = [
        (
            repo_id,
            event.id,  # Stable event ID for deduplication
            event.type,
            event.timestamp.isoformat(),
            event.data.get('ref') or event.data.get('tag') or event.data.get('branch'),
            event.data.get('message'),
            event.data.get('author'),
            json.dumps(event.data),
        )
        for event in events
    ]

    before = db.conn.total_changes
    db.executemany("""
        INSERT OR IGNORE INTO events
        (repo_id, event_id, type, timestamp, ref, message, author, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    return db.conn.total_changes - before
```

- [ ] Run the test file again. All four tests MUST pass.

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_events_batch_insert.py -v
```

Expected: all 4 tests PASS (including the single-`executemany` spy and the dedup delta count).

### Task 3: Batched `cleanup_missing_repos` via chunked `DELETE ... WHERE id IN (...)`

Files:
- Create: `/home/spinoza/github/beta/repoindex/tests/test_repository_cleanup.py` (new file)
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/database/repository.py` (`cleanup_missing_repos`, lines 381-396; `Path` imported at line 10, `Database` at line 15)
- Test path: `/home/spinoza/github/beta/repoindex/tests/test_repository_cleanup.py`

Steps:

- [ ] Write the failing test that pins the batched-delete contract: missing repos are removed, survivors are untouched (exists()-semantics preserved: only repos gone from disk are pruned), and the deletes are issued as chunked `DELETE ... WHERE id IN (...)` rather than one DELETE per row. Create `/home/spinoza/github/beta/repoindex/tests/test_repository_cleanup.py`:

```python
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
```

- [ ] Run the new test against the CURRENT per-row implementation to confirm the batched-delete contract FAILS.

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_repository_cleanup.py -v
```

Expected: `test_deletes_are_batched_not_per_row` FAILS (`assert 5 == 1`: current code calls `delete_repo` which issues one DELETE per missing row). `test_removes_only_missing_repos` and `test_no_missing_repos_is_noop` pass under the old loop.

- [ ] Rewrite `cleanup_missing_repos` to collect missing ids (keeping the `Path(...).exists()` check) and issue one chunked `DELETE ... WHERE id IN (...)` per chunk. Replace lines 381-396 of `/home/spinoza/github/beta/repoindex/repoindex/database/repository.py`:

```python
def cleanup_missing_repos(db: Database, chunk_size: int = 500) -> int:
    """
    Remove repos from database that no longer exist on disk.

    Behavior-preserving exists()-semantics: a repo is pruned only when its
    on-disk path is gone (NOT set-difference against a fresh scan). The
    deletes are issued as chunked ``DELETE ... WHERE id IN (...)`` rather
    than one statement per row.

    Args:
        db: Database connection
        chunk_size: Maximum number of ids per DELETE statement.

    Returns:
        Number of repos removed
    """
    db.execute("SELECT id, path FROM repos")
    missing_ids = [row['id'] for row in db.fetchall() if not Path(row['path']).exists()]

    if not missing_ids:
        return 0

    removed = 0
    for start in range(0, len(missing_ids), chunk_size):
        chunk = missing_ids[start:start + chunk_size]
        placeholders = ', '.join('?' for _ in chunk)
        db.execute(
            f"DELETE FROM repos WHERE id IN ({placeholders})",
            tuple(chunk),
        )
        removed += len(chunk)

    return removed
```

- [ ] Run the test file again. All three tests MUST pass.

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_repository_cleanup.py -v
```

Expected: all 3 tests PASS (single chunked DELETE, survivors intact, noop on no-missing).

### Task 4: Run the perf-touched suite and commit the group

Files:
- (no new files; commits the three rewrites and three test files from Tasks 1-3)

Steps:

- [ ] Run the full set of files touched or added by this group to confirm no regression in the neighboring suites.

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_repository_service_languages.py tests/test_events_batch_insert.py tests/test_repository_cleanup.py tests/test_database.py tests/test_events.py tests/test_repository_service_excludes.py -q
```

Expected: all PASS (the new files plus the existing `test_database.py`, `test_events.py`, and `test_repository_service_excludes.py` which exercise `insert_events`, `cleanup_missing_repos`, and `_detect_languages` paths).

- [ ] Run the full suite to confirm the 1848 baseline holds plus the new tests.

```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest -q
```

Expected: previous baseline (1848) plus the 15 new tests in this group all pass; 0 failures.

- [ ] Stage and commit the perf group as a single commit.

```
cd /home/spinoza/github/beta/repoindex && git add repoindex/services/repository_service.py repoindex/database/events.py repoindex/database/repository.py tests/test_repository_service_languages.py tests/test_events_batch_insert.py tests/test_repository_cleanup.py && git commit -m "perf: single os.walk language detection, batched event inserts and repo cleanup

Replace the ~19 per-extension glob calls in _detect_languages with one
os.walk that prunes EXCLUDE_DIRS from dirnames in place (byte-identical
output, including the .r/.R last-write-wins quirk and the insertion-order
tie-break; characterization test pins this). Fixes the path-substring
false-prune for repos living under a dir named build/target/etc.

insert_events now issues a single executemany (INSERT OR IGNORE) and
reports newly inserted rows via a total_changes delta, keeping
events_added correct under dedup.

cleanup_missing_repos collects missing ids (exists()-semantics preserved)
and deletes them with chunked DELETE ... WHERE id IN (...) instead of one
DELETE per row.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

Expected: one commit created on the current branch containing the three rewrites and three new test files.

---

Notes for the assembler:
- The `Database` class already exposes `executemany` (connection.py:155) and `db.conn` (connection.py:143), and `db.conn.total_changes` is the stdlib sqlite3 connection attribute, so no infra signature change is needed (STABILITY.md clean: all changes are additive or internal-body-only).
- `cleanup_missing_repos` gains an additive keyword-only-default `chunk_size: int = 500`; existing zero-arg callers are unaffected (additive, 2.x-legal).
- Tests use `.venv/bin/python -m pytest`; if the assembler prefers `make test`, substitute `make test` for the full-suite step. The per-file runs need the venv interpreter directly.

---

## Commit group: mcp

This group modifies `repoindex/mcp/server.py` only: `_get_schema_impl` (expose views and `repos_fts`), `_get_manifest_impl` (additive `summary` aggregates), and the `run_sql` tool docstring (FTS + canonical exemplars, `current_version` fix). All tests go in `tests/test_mcp.py`. The existing `patch_db` fixture mocks the DB; these new tests build a real schema in a tmp DB and patch `_open_db` to yield a read-only `Database` over it, because the assertions require the real `sqlite_master` contents (views, FTS shadow tables). The schema defines exactly three views (`v_active_repos`, `v_stale_repos`, `v_repo_stats`); there is no `v_repo_health`. The FTS shadow tables are `repos_fts_config`, `repos_fts_data`, `repos_fts_docsize`, `repos_fts_idx` (all match `%_fts_%`), while `repos_fts` itself does not (no trailing underscore after `fts`), and `sqlite_sequence` is already excluded by the existing `name NOT LIKE 'sqlite_%'` filter.

### Task 1: Add a real-DB test fixture to tests/test_mcp.py

**Files**
- Modify: `tests/test_mcp.py` (add a fixture after the existing `patch_db` fixture, which ends at line 27)
- Test path: `tests/test_mcp.py`

This task adds shared infrastructure (a fixture) plus its first consumer test, so it is independently runnable.

- [ ] Add the fixture and a smoke test. Insert the following immediately after the `patch_db` fixture (after line 27, before `class TestGetManifest`):

```python
@pytest.fixture
def real_db(tmp_path):
    """Build a real schema-backed DB on disk and route _open_db to it.

    Unlike patch_db (which mocks the cursor), this yields the open
    read-write Database so a test can seed rows, then patches
    _open_db to hand the MCP _impl functions a read-only connection
    over the same file. Needed for assertions about sqlite_master
    contents (views, FTS shadow tables) that a MagicMock cannot fake.
    """
    from repoindex.database.connection import Database

    db_path = tmp_path / 'index.db'
    # Connecting read-write applies the current schema via ensure_schema.
    seed = Database(db_path=db_path)
    seed.__enter__()

    @contextmanager
    def _fake_open_db():
        with Database(db_path=db_path, read_only=True) as ro:
            yield ro, {}

    patcher = patch('repoindex.mcp.server._open_db', _fake_open_db)
    patcher.start()
    try:
        yield seed
    finally:
        patcher.stop()
        seed.__exit__(None, None, None)
```

- [ ] Add a smoke test asserting the fixture wires a real schema. Add this class immediately after the `real_db` fixture:

```python
class TestRealDbFixture:
    def test_schema_built(self, real_db):
        real_db.execute("SELECT COUNT(*) AS n FROM repos")
        assert real_db.fetchone()['n'] == 0
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl()
        assert 'ddl' in result
        assert len(result['ddl']) > 0
```

- [ ] Run the smoke test, expect PASS (the fixture exercises only existing code):
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestRealDbFixture -q
```
Expected output ends with: `1 passed`.

### Task 2: get_schema exposes views via type IN ('table','view')

**Files**
- Modify: `repoindex/mcp/server.py` `_get_schema_impl`, the all-tables branch query at lines 109-112
- Test path: `tests/test_mcp.py`

- [ ] Write the failing test. Add this class to `tests/test_mcp.py` after `class TestGetSchema` (after line 102):

```python
class TestGetSchemaViews:
    def test_views_present(self, real_db):
        from repoindex.mcp.server import _get_schema_impl
        ddl = '\n'.join(_get_schema_impl()['ddl'])
        assert 'v_active_repos' in ddl
        assert 'v_stale_repos' in ddl
        assert 'v_repo_stats' in ddl

    def test_core_tables_still_present(self, real_db):
        from repoindex.mcp.server import _get_schema_impl
        ddl = '\n'.join(_get_schema_impl()['ddl'])
        assert 'CREATE TABLE' in ddl and 'repos' in ddl
        assert 'events' in ddl
        assert 'publications' in ddl

    def test_sqlite_internal_tables_absent(self, real_db):
        from repoindex.mcp.server import _get_schema_impl
        ddl = '\n'.join(_get_schema_impl()['ddl'])
        assert 'sqlite_sequence' not in ddl
```

- [ ] Run it, expect FAIL on `test_views_present` (current query filters `type='table'`, so views never appear):
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestGetSchemaViews -q
```
Expected: `test_views_present` FAILS with an `AssertionError` on `'v_active_repos' in ddl`; the other two pass.

- [ ] Implement: in `repoindex/mcp/server.py`, change the all-tables branch query (lines 109-112). Replace:

```python
            db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' ORDER BY name"
            )
            return {'ddl': [r['sql'] for r in db.fetchall() if r['sql']]}
```

with:

```python
            db.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type IN ('table','view') "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts_%' ORDER BY name"
            )
            return {
                'ddl': [r['sql'] for r in db.fetchall() if r['sql']],
                'hint': (
                    'Views (v_active_repos, v_stale_repos, v_repo_stats) and the '
                    'repos_fts full-text table are queryable. Use repos_fts MATCH '
                    'for full-text search instead of LIKE.'
                ),
            }
```

- [ ] Run the test, expect PASS:
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestGetSchemaViews -q
```
Expected output ends with: `3 passed`.

### Task 3: get_schema exposes repos_fts and adds a MATCH hint

**Files**
- Modify: none beyond Task 2 (the `%_fts_%` exclusion and the `hint` key were both added in Task 2's edit); this task pins that behavior with tests
- Test path: `tests/test_mcp.py`

- [ ] Write the failing-then-passing test. Add this class to `tests/test_mcp.py` after `class TestGetSchemaViews`:

```python
class TestGetSchemaFts:
    def test_repos_fts_present(self, real_db):
        from repoindex.mcp.server import _get_schema_impl
        ddl = '\n'.join(_get_schema_impl()['ddl'])
        assert 'repos_fts' in ddl

    def test_fts_shadow_tables_absent(self, real_db):
        from repoindex.mcp.server import _get_schema_impl
        ddl = '\n'.join(_get_schema_impl()['ddl'])
        assert 'repos_fts_data' not in ddl
        assert 'repos_fts_idx' not in ddl
        assert 'repos_fts_config' not in ddl
        assert 'repos_fts_docsize' not in ddl

    def test_match_hint_present(self, real_db):
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl()
        assert 'MATCH' in result['hint']
```

- [ ] Run it, expect PASS (Task 2's edit already changed the exclusion to `%_fts_%` and added the `hint` key, so `repos_fts` is shown, the shadow tables stay hidden, and the hint mentions MATCH):
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestGetSchemaFts -q
```
Expected output ends with: `3 passed`.

- [ ] Guard the single-table branch against regression: confirm the `test_single_table` and `test_unknown_table` cases (using the mocked `patch_db` fixture) still pass, since the single-table branch query at lines 94-97 was intentionally not changed:
```
source .venv/bin/activate && python -m pytest "tests/test_mcp.py::TestGetSchema" -q
```
Expected output ends with: `5 passed`.

### Task 4: get_manifest gains additive summary aggregates

**Files**
- Modify: `repoindex/mcp/server.py` `_get_manifest_impl` (lines 48-85); add a module-level threshold constant near `MAX_ROWS` (line 116)
- Test path: `tests/test_mcp.py`

The new `summary` keys are additive: `dirty`, `unpushed`, `published`, `unpublished`, `doi_count`, `stale`, `by_forge_id`, and `refresh_stale`. Definitions reuse existing semantics: `dirty` = `is_clean = 0` (matches `flag_query.py`), `unpushed` = `ahead > 0` (matches `git_ops_service.py:447`), `published` / `unpublished` from `publications.published`, `doi_count` = publications with a non-NULL `doi`, `stale` = rows in the existing `v_stale_repos` view, `by_forge_id` = count grouped by `forge_id` (NULL excluded). `refresh_stale` is a boolean: True when the newest `refresh_log.started_at` is older than `_REFRESH_STALE_DAYS`, or when there is no refresh row.

- [ ] Write the failing test. Add this class to `tests/test_mcp.py` after `class TestGetManifest` (after line 59):

```python
class TestGetManifestAggregates:
    def _seed(self, db):
        # 3 repos: 2 dirty, 1 clean; 1 unpushed; forge_id mix.
        db.execute(
            "INSERT INTO repos (name, path, is_clean, ahead, forge_id) "
            "VALUES ('a', '/a', 0, 0, 'github')"
        )
        db.execute(
            "INSERT INTO repos (name, path, is_clean, ahead, forge_id) "
            "VALUES ('b', '/b', 0, 2, 'github')"
        )
        db.execute(
            "INSERT INTO repos (name, path, is_clean, ahead, forge_id) "
            "VALUES ('c', '/c', 1, 0, 'gitea')"
        )
        # publications: 1 published+doi, 1 unpublished, no doi.
        db.execute(
            "INSERT INTO publications (repo_id, registry, package_name, published, doi) "
            "VALUES (1, 'pypi', 'a', 1, '10.5281/zenodo.1')"
        )
        db.execute(
            "INSERT INTO publications (repo_id, registry, package_name, published, doi) "
            "VALUES (2, 'pypi', 'b', 0, NULL)"
        )
        db.commit()

    def test_aggregate_keys_and_counts(self, real_db):
        self._seed(real_db)
        with patch('repoindex.mcp.server.get_db_path', return_value=Path('/fake/path')):
            from repoindex.mcp.server import _get_manifest_impl
            summary = _get_manifest_impl()['summary']
        assert summary['dirty'] == 2
        assert summary['unpushed'] == 1
        assert summary['published'] == 1
        assert summary['unpublished'] == 1
        assert summary['doi_count'] == 1
        # No commit events seeded, so all 3 repos are stale (v_stale_repos).
        assert summary['stale'] == 3
        assert summary['by_forge_id'] == {'github': 2, 'gitea': 1}
        # Existing keys still present.
        assert 'languages' in summary
        assert 'last_refresh' in summary

    def test_refresh_stale_true_when_no_refresh(self, real_db):
        with patch('repoindex.mcp.server.get_db_path', return_value=Path('/fake/path')):
            from repoindex.mcp.server import _get_manifest_impl
            summary = _get_manifest_impl()['summary']
        assert summary['refresh_stale'] is True

    def test_refresh_stale_false_when_recent(self, real_db):
        real_db.execute(
            "INSERT INTO refresh_log (started_at, finished_at, full_scan, sources) "
            "VALUES (datetime('now'), datetime('now'), 0, '[]')"
        )
        real_db.commit()
        with patch('repoindex.mcp.server.get_db_path', return_value=Path('/fake/path')):
            from repoindex.mcp.server import _get_manifest_impl
            summary = _get_manifest_impl()['summary']
        assert summary['refresh_stale'] is False
```

- [ ] Run it, expect FAIL (current `summary` only has `languages` and `last_refresh`):
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestGetManifestAggregates -q
```
Expected: 3 failures with `KeyError: 'dirty'` (and similar missing keys).

- [ ] Implement the threshold constant. In `repoindex/mcp/server.py`, immediately before `MAX_ROWS = 500` (line 116), add:

```python
# A refresh older than this many days is reported as stale in get_manifest's
# summary so an LLM knows the materialized view may be behind the filesystem.
_REFRESH_STALE_DAYS = 7
```

- [ ] Implement the aggregates. In `_get_manifest_impl`, replace the block from the `db.execute("SELECT started_at ...")` call through the `last_refresh = ...` assignment and the `return` statement (lines 71-85). Replace:

```python
        db.execute(
            "SELECT started_at FROM refresh_log ORDER BY started_at DESC LIMIT 1"
        )
        refresh_rows = db.fetchall()
        last_refresh = refresh_rows[0]['started_at'] if refresh_rows else None

    return {
        'description': 'repoindex filesystem git catalog',
        'database': str(get_db_path(config)),
        'tables': tables,
        'summary': {
            'languages': languages,
            'last_refresh': last_refresh,
        },
    }
```

with:

```python
        db.execute(
            "SELECT started_at FROM refresh_log ORDER BY started_at DESC LIMIT 1"
        )
        refresh_rows = db.fetchall()
        last_refresh = refresh_rows[0]['started_at'] if refresh_rows else None

        db.execute("SELECT COUNT(*) AS c FROM repos WHERE is_clean = 0")
        dirty = db.fetchone()['c']

        db.execute("SELECT COUNT(*) AS c FROM repos WHERE ahead > 0")
        unpushed = db.fetchone()['c']

        db.execute("SELECT COUNT(*) AS c FROM publications WHERE published = 1")
        published = db.fetchone()['c']

        db.execute("SELECT COUNT(*) AS c FROM publications WHERE COALESCE(published, 0) = 0")
        unpublished = db.fetchone()['c']

        db.execute("SELECT COUNT(*) AS c FROM publications WHERE doi IS NOT NULL")
        doi_count = db.fetchone()['c']

        db.execute("SELECT COUNT(*) AS c FROM v_stale_repos")
        stale = db.fetchone()['c']

        db.execute(
            "SELECT forge_id, COUNT(*) AS c FROM repos "
            "WHERE forge_id IS NOT NULL GROUP BY forge_id ORDER BY c DESC"
        )
        by_forge_id = {r['forge_id']: r['c'] for r in db.fetchall()}

        refresh_stale = _is_refresh_stale(last_refresh)

    return {
        'description': 'repoindex filesystem git catalog',
        'database': str(get_db_path(config)),
        'tables': tables,
        'summary': {
            'languages': languages,
            'last_refresh': last_refresh,
            'dirty': dirty,
            'unpushed': unpushed,
            'published': published,
            'unpublished': unpublished,
            'doi_count': doi_count,
            'stale': stale,
            'by_forge_id': by_forge_id,
            'refresh_stale': refresh_stale,
        },
    }
```

- [ ] Implement the `_is_refresh_stale` helper. In `repoindex/mcp/server.py`, add this function immediately before `def _get_manifest_impl()` (before line 48):

```python
def _is_refresh_stale(last_refresh) -> bool:
    """True if the newest refresh is older than _REFRESH_STALE_DAYS (or absent)."""
    if not last_refresh:
        return True
    from datetime import datetime
    try:
        started = datetime.fromisoformat(str(last_refresh))
    except (ValueError, TypeError):
        return True
    age_days = (datetime.now() - started).total_seconds() / 86400
    return age_days > _REFRESH_STALE_DAYS
```

- [ ] Move the threshold constant above the helper. The `_is_refresh_stale` helper (added before line 48) references `_REFRESH_STALE_DAYS`, but the constant was added at line 116. Since `_is_refresh_stale` is only called at runtime (not at import time), module-level ordering does not break import; the name resolves when the function executes. Confirm import still works:
```
source .venv/bin/activate && python -c "import repoindex.mcp.server"
```
Expected: no output, exit code 0.

- [ ] Run the manifest test, expect PASS:
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestGetManifestAggregates -q
```
Expected output ends with: `3 passed`.

- [ ] Confirm the existing `TestGetManifest` mocked tests still pass. They drive `fetchone.side_effect` with exactly four `{'count': ...}` rows then `fetchall.side_effect` for languages and refresh; the new aggregate queries use `fetchone()` after the four counts, so the mock side_effect list must still satisfy them. Run:
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestGetManifest -q
```
Expected: if these FAIL with `StopIteration` (the mock ran out of `fetchone` values for the new aggregate queries), update both `test_structure` and `test_empty_db` in `tests/test_mcp.py` to extend the mocked side effects. For `test_structure`, change the `fetchone.side_effect` list and `fetchall.side_effect` to:

```python
        patch_db.fetchone.side_effect = [
            {'count': 143}, {'count': 2841}, {'count': 312}, {'count': 28},
            {'c': 5},   # dirty
            {'c': 3},   # unpushed
            {'c': 10},  # published
            {'c': 2},   # unpublished
            {'c': 7},   # doi_count
            {'c': 9},   # stale
        ]
        patch_db.fetchall.side_effect = [
            [{'language': 'Python', 'cnt': 45}, {'language': 'R', 'cnt': 12}],
            [{'started_at': '2026-02-28T10:00:00'}],
            [{'forge_id': 'github', 'c': 100}, {'forge_id': 'gitea', 'c': 20}],
        ]
```

and for `test_empty_db`, change them to:

```python
        patch_db.fetchone.side_effect = [
            {'count': 0}, {'count': 0}, {'count': 0}, {'count': 0},
            {'c': 0}, {'c': 0}, {'c': 0}, {'c': 0}, {'c': 0}, {'c': 0},
        ]
        patch_db.fetchall.side_effect = [[], [], []]
```

Then re-run and expect PASS:
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestGetManifest -q
```
Expected output ends with: `2 passed`.

### Task 5: run_sql docstring gains FTS and canonical exemplars, fixes current_version

**Files**
- Modify: `repoindex/mcp/server.py` `run_sql` tool docstring inside `create_server` (line 417)
- Test path: `tests/test_mcp.py`

The publications column is `current_version` (schema line 162), not `version`; the new docstring uses `current_version` and never the bare token `version`.

- [ ] Write the failing test. Add this class to `tests/test_mcp.py` after `class TestRunSql` (after line 171):

```python
class TestRunSqlDocstring:
    def _docstring(self):
        from repoindex.mcp.server import create_server
        server = create_server()
        # FastMCP registers tools; reach the underlying run_sql function.
        import repoindex.mcp.server as mod
        # The tool wraps _run_sql_impl; assert the documented guidance lives
        # on the registered tool's docstring via the module-level helper text.
        return mod.RUN_SQL_DOC

    def test_mentions_match_fts(self):
        doc = self._docstring()
        assert 'MATCH' in doc
        assert 'repos_fts' in doc

    def test_uses_current_version_not_version(self):
        doc = self._docstring()
        assert 'current_version' in doc
        # The publications column is current_version; the bare token must
        # not appear as a column reference (would mislead the LLM's query).
        assert 'p.version' not in doc
        assert 'publications.version' not in doc

    def test_has_canonical_exemplars(self):
        doc = self._docstring()
        assert 'published' in doc
        assert 'citation' in doc.lower()
```

- [ ] Run it, expect FAIL with `AttributeError: module 'repoindex.mcp.server' has no attribute 'RUN_SQL_DOC'`:
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestRunSqlDocstring -q
```
Expected: 3 errors/failures referencing missing `RUN_SQL_DOC`.

- [ ] Implement the shared docstring constant. In `repoindex/mcp/server.py`, add this module-level constant immediately before `def create_server():` (before line 393):

```python
RUN_SQL_DOC = """Execute read-only SQL (SELECT/WITH only). Returns up to 500 rows as JSON.

Full-text search: the repos_fts table is FTS5-indexed on name, description,
and readme_content. Use MATCH, not LIKE, for text search:
    SELECT r.name FROM repos_fts f JOIN repos r ON r.id = f.rowid
    WHERE repos_fts MATCH 'bayesian';

Canonical examples:
- Published packages missing a citation file:
    SELECT r.name, p.registry, p.package_name
    FROM publications p JOIN repos r ON r.id = p.repo_id
    WHERE p.published = 1 AND r.has_citation = 0;
- Latest published version per repo (column is current_version):
    SELECT r.name, p.registry, p.current_version
    FROM publications p JOIN repos r ON r.id = p.repo_id
    WHERE p.published = 1;
- Stale repos (no commit in 180 days) via the v_stale_repos view:
    SELECT name, language FROM v_stale_repos ORDER BY name;
"""
```

- [ ] Wire the constant into the `run_sql` tool. In `repoindex/mcp/server.py`, replace the `run_sql` tool definition (lines 415-418):

```python
    @mcp.tool()
    def run_sql(query: str) -> dict:
        """Execute read-only SQL (SELECT/WITH only). Returns up to 500 rows as JSON."""
        return _run_sql_impl(query)
```

with:

```python
    @mcp.tool()
    def run_sql(query: str) -> dict:
        return _run_sql_impl(query)

    run_sql.__doc__ = RUN_SQL_DOC
```

- [ ] Run the docstring test, expect PASS:
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py::TestRunSqlDocstring -q
```
Expected output ends with: `3 passed`.

### Task 6: Run the full MCP suite and commit the group

**Files**
- No new edits; this task verifies the whole file and commits.

- [ ] Run the entire MCP test file, expect all PASS (64 baseline + new tests from Tasks 1-5):
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py -q
```
Expected output ends with a single `passed` summary line (no failures, no errors). Count is the 64 baseline plus the new tests: `TestRealDbFixture` (1), `TestGetSchemaViews` (3), `TestGetSchemaFts` (3), `TestGetManifestAggregates` (3), `TestRunSqlDocstring` (3).

- [ ] Confirm no regressions outside this file by running the database and CLI suites that touch the schema and manifest paths:
```
source .venv/bin/activate && python -m pytest tests/test_mcp.py tests/test_core.py -q
```
Expected: ends with `passed`, zero failures.

- [ ] Commit the group (single commit for the whole mcp group):
```
git add repoindex/mcp/server.py tests/test_mcp.py && git commit -m "$(cat <<'EOF'
feat(mcp): expose views/repos_fts in get_schema, add manifest aggregates

get_schema now lists views (v_active_repos, v_stale_repos, v_repo_stats)
and the repos_fts full-text table by selecting type IN ('table','view')
and excluding only the %_fts_% shadow tables, with a MATCH hint.
get_manifest gains additive summary aggregates (dirty, unpushed,
published, unpublished, doi_count, stale, by_forge_id, refresh_stale).
The run_sql docstring gains FTS and canonical exemplars and references
the real publications.current_version column.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit succeeds; `git log -1 --oneline` shows the new commit.

---

Files referenced (all absolute):
- `/home/spinoza/github/beta/repoindex/repoindex/mcp/server.py`
- `/home/spinoza/github/beta/repoindex/tests/test_mcp.py`
- `/home/spinoza/github/beta/repoindex/repoindex/database/schema.py` (read-only confirmation of view names and the `current_version` column)

---

## Commit group: schema-v10

This group bumps `CURRENT_VERSION` 9 to 10, makes `apply_schema` preserve-and-restore `events` and `refresh_log` across migration (instead of dropping them), adds a nullable `concept_doi` column to `publications`, adds a `concept_doi` field to the `PackageMetadata` domain dataclass, threads the dual DOI through the zenodo source and the `_upsert_publication` write path, and makes the bibtex/jsonld citation exporters and the arkiv publications record prefer the concept DOI. All changes are additive and 2.x-legal (no signature removals/renames/type changes).

This group's single commit is the LAST task below.

### Task 1: Add `concept_doi` field to `PackageMetadata` domain dataclass

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/domain/repository.py` (dataclass at lines 95-124: add field after `doi` at line 108, add to `to_dict` after line 120)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_domain.py`

Steps:

- [ ] Confirm the test file exists and find a spot near other `PackageMetadata` tests:
  ```
  cd /home/spinoza/github/beta/repoindex && grep -n "PackageMetadata" tests/test_domain.py
  ```
  Expected: at least one line referencing `PackageMetadata`. (If the file does not exist, create it with `from repoindex.domain.repository import PackageMetadata` at top and a single `class TestPackageMetadataConceptDoi:` body.)

- [ ] Write a failing test. Append to `/home/spinoza/github/beta/repoindex/tests/test_domain.py`:
  ```python
  class TestPackageMetadataConceptDoi:
      def test_concept_doi_defaults_none(self):
          from repoindex.domain.repository import PackageMetadata
          pkg = PackageMetadata(registry='zenodo', name='x')
          assert pkg.concept_doi is None

      def test_concept_doi_set_and_serialized(self):
          from repoindex.domain.repository import PackageMetadata
          pkg = PackageMetadata(
              registry='zenodo',
              name='x',
              doi='10.5281/zenodo.123',
              concept_doi='10.5281/zenodo.100',
          )
          assert pkg.concept_doi == '10.5281/zenodo.100'
          d = pkg.to_dict()
          assert d['doi'] == '10.5281/zenodo.123'
          assert d['concept_doi'] == '10.5281/zenodo.100'
  ```

- [ ] Run the test, expect FAIL:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_domain.py -k concept_doi -q
  ```
  Expected: failure (`TypeError: __init__() got an unexpected keyword argument 'concept_doi'` on the second test, and `AttributeError`/`KeyError` on `concept_doi`).

- [ ] Implement: add the field. In `/home/spinoza/github/beta/repoindex/repoindex/domain/repository.py`, change line 108 from:
  ```python
      doi: Optional[str] = None
  ```
  to:
  ```python
      doi: Optional[str] = None  # version-specific DOI
      concept_doi: Optional[str] = None  # version-independent (concept) DOI
  ```

- [ ] Implement: add to `to_dict`. In the same file, change the `'doi': self.doi,` line (line 119) inside `PackageMetadata.to_dict` from:
  ```python
              'doi': self.doi,
  ```
  to:
  ```python
              'doi': self.doi,
              'concept_doi': self.concept_doi,
  ```

- [ ] Run the test, expect PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_domain.py -k concept_doi -q
  ```
  Expected: 2 passed.

### Task 2: Add nullable `concept_doi` column to the `publications` DDL and bump `CURRENT_VERSION` to 10

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/database/schema.py` (version comment block + `CURRENT_VERSION` at line 29; publications DDL at lines 157-172; schema description string at line 366)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_database.py`

Steps:

- [ ] Write a failing test. Append to the `TestSchemaOperations` class in `/home/spinoza/github/beta/repoindex/tests/test_database.py` (the class containing `test_schema_version_updated` at line 176). Add these methods:
  ```python
      def test_current_version_is_10(self):
          self.assertEqual(CURRENT_VERSION, 10)

      def test_publications_has_concept_doi_column(self):
          conn = sqlite3.connect(str(self.db_path))
          conn.row_factory = sqlite3.Row
          ensure_schema(conn)
          cols = [r['name'] for r in conn.execute("PRAGMA table_info(publications)")]
          self.assertIn('concept_doi', cols)
          self.assertIn('doi', cols)
          conn.close()
  ```

- [ ] Run the test, expect FAIL:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py -k "current_version_is_10 or publications_has_concept_doi" -q
  ```
  Expected: failure (`AssertionError: 9 != 10` and `concept_doi` not in column list).

- [ ] Implement: add the column to the publications DDL. In `/home/spinoza/github/beta/repoindex/repoindex/database/schema.py`, change the `doi TEXT` line at line 165 from:
  ```python
      doi TEXT,  -- DOI identifier (e.g., "10.5281/zenodo.1234567")
  ```
  to:
  ```python
      doi TEXT,  -- version-specific DOI (e.g., "10.5281/zenodo.1234567")
      concept_doi TEXT,  -- version-independent (concept) DOI; what a paper cites
  ```

- [ ] Implement: bump the version. In the same file, change line 29 from:
  ```python
  CURRENT_VERSION = 9
  ```
  to:
  ```python
  CURRENT_VERSION = 10
  ```

- [ ] Implement: extend the version-history comment. Insert a comment line directly above the `CURRENT_VERSION = 10` line (after line 28, the last existing `#` comment). Change:
  ```python
  #     Run `repoindex refresh --external` after upgrade to repopulate.
  CURRENT_VERSION = 10
  ```
  to:
  ```python
  #     Run `repoindex refresh --external` after upgrade to repopulate.
  # v10: preserve events + refresh_log across migration (no longer dropped);
  #      added nullable concept_doi column to publications (version-independent DOI).
  CURRENT_VERSION = 10
  ```

- [ ] Implement: update the `_schema_info` description string. Change line 366 from:
  ```python
          (CURRENT_VERSION, "v2.0 (Wave V2.B): unified forge schema (forge_id + generic columns)")
  ```
  to:
  ```python
          (CURRENT_VERSION, "v10: preserve events + refresh_log on migration; concept_doi on publications")
  ```

- [ ] Run the test, expect PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py -k "current_version_is_10 or publications_has_concept_doi" -q
  ```
  Expected: 2 passed.

### Task 3: Preserve-and-restore `events` and `refresh_log` in `apply_schema`

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/database/schema.py` (`apply_schema` at lines 333-369: the drop-all block at lines 345-360)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_database.py`

Steps:

- [ ] Write a failing migration test. Append to the `TestSchemaOperations` class in `/home/spinoza/github/beta/repoindex/tests/test_database.py`:
  ```python
      def test_apply_schema_preserves_external_events_and_refresh_log(self):
          # Seed a v9 database directly: minimal repos + events + refresh_log,
          # then stamp it as version 9 so apply_schema treats it as a migration.
          conn = sqlite3.connect(str(self.db_path))
          conn.row_factory = sqlite3.Row
          ensure_schema(conn)  # builds current schema
          # Insert a repo (events.repo_id FK), external-sourced events, refresh_log row.
          conn.execute(
              "INSERT INTO repos (name, path) VALUES (?, ?)",
              ('demo', '/tmp/demo'),
          )
          repo_id = conn.execute("SELECT id FROM repos WHERE name='demo'").fetchone()['id']
          for ev_id, ev_type in [
              ('gh-rel-1', 'github_release'),
              ('gh-pr-2', 'pull_request'),
              ('gh-star-3', 'star'),
          ]:
              conn.execute(
                  "INSERT INTO events (repo_id, event_id, type, timestamp, message) "
                  "VALUES (?, ?, ?, ?, ?)",
                  (repo_id, ev_id, ev_type, '2024-01-01T00:00:00', 'seed'),
              )
          conn.execute(
              "INSERT INTO refresh_log (started_at, finished_at, full_scan, sources) "
              "VALUES (?, ?, ?, ?)",
              ('2024-01-01T00:00:00', '2024-01-01T00:01:00', 1, '["git","github"]'),
          )
          # Force the stored version back to 9 so apply_schema migrates.
          conn.execute("DELETE FROM _schema_info")
          conn.execute(
              "INSERT INTO _schema_info (version, description) VALUES (9, 'seeded v9')"
          )
          conn.commit()

          from repoindex.database.schema import apply_schema
          apply_schema(conn, CURRENT_VERSION)

          surviving = {r['event_id'] for r in conn.execute("SELECT event_id FROM events")}
          self.assertEqual(surviving, {'gh-rel-1', 'gh-pr-2', 'gh-star-3'})
          rl = conn.execute("SELECT COUNT(*) AS c FROM refresh_log").fetchone()['c']
          self.assertEqual(rl, 1)
          self.assertEqual(get_schema_version(conn), CURRENT_VERSION)
          conn.close()
  ```

- [ ] Run the test, expect FAIL:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py -k apply_schema_preserves -q
  ```
  Expected: failure (`AssertionError: set() != {'gh-rel-1', 'gh-pr-2', 'gh-star-3'}` because the current drop-all block discards `events` and `refresh_log`).

- [ ] Implement: rewrite the migration body to preserve-and-restore. In `/home/spinoza/github/beta/repoindex/repoindex/database/schema.py`, replace the entire `if current != 0 and current < CURRENT_VERSION:` block (lines 345-360, from `if current != 0` through the closing `""")`) with:
  ```python
      if current != 0 and current < CURRENT_VERSION:
          import logging
          logger = logging.getLogger(__name__)
          logger.info(f"Schema version {current} -> {CURRENT_VERSION}, rebuilding cache")

          # Preserve append-only tables across the rebuild. Local commit/tag
          # events re-scan from git, but external-sourced events (releases, PRs,
          # stars, publishes) and the entire refresh_log are not recoverable, so
          # copy them to temp tables, drop/recreate, and re-insert. INSERT OR
          # IGNORE dedupes events by their UNIQUE event_id.
          def _table_exists(name: str) -> bool:
              row = conn.execute(
                  "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                  (name,),
              ).fetchone()
              return row is not None

          preserve = [t for t in ('events', 'refresh_log') if _table_exists(t)]
          for table in preserve:
              conn.execute(f"DROP TABLE IF EXISTS _preserve_{table}")
              conn.execute(
                  f"CREATE TEMP TABLE _preserve_{table} AS SELECT * FROM {table}"
              )

          # Drop all tables (cascade will handle FKs)
          conn.executescript("""
              DROP TABLE IF EXISTS repos_fts;
              DROP TABLE IF EXISTS tags;
              DROP TABLE IF EXISTS events;
              DROP TABLE IF EXISTS publications;
              DROP TABLE IF EXISTS scan_errors;
              DROP TABLE IF EXISTS refresh_log;
              DROP TABLE IF EXISTS repos;
              DROP TABLE IF EXISTS _schema_info;
          """)

          # Recreate the current schema before re-inserting preserved rows.
          conn.executescript(SCHEMA_V1)

          for table in preserve:
              cols = [
                  r[1] for r in conn.execute(f"PRAGMA table_info({table})")
              ]
              old_cols = [
                  r[1] for r in conn.execute(
                      f"PRAGMA table_info(_preserve_{table})"
                  )
              ]
              shared = [c for c in cols if c in old_cols]
              col_list = ", ".join(shared)
              conn.execute(
                  f"INSERT OR IGNORE INTO {table} ({col_list}) "
                  f"SELECT {col_list} FROM _preserve_{table}"
              )
              conn.execute(f"DROP TABLE IF EXISTS _preserve_{table}")
  ```

  Note: this block now runs `conn.executescript(SCHEMA_V1)` itself before restore. Because the unconditional `conn.executescript(SCHEMA_V1)` at line 363 (just after the `if` block) is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, etc.), re-running it is harmless and keeps the fresh-DB path (where `current == 0`) working unchanged. Leave that line 363 in place.

- [ ] Run the migration test, expect PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py -k apply_schema_preserves -q
  ```
  Expected: 1 passed.

- [ ] Run the full database + schema suite to confirm no regression (fresh-DB path, reset, version-updated tests):
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py -q
  ```
  Expected: all passed (existing tests plus the new ones from Tasks 2 and 3).

### Task 4: Store dual DOIs in the zenodo source (version DOI in `doi`, concept DOI in `concept_doi`)

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/sources/registries/zenodo.py` (`_to_metadata` at lines 106-116)
- Modify (existing-test re-point): `/home/spinoza/github/beta/repoindex/tests/test_sources/test_zenodo_source.py` (assertions at lines 91 and 156, which currently assert the collapsed behavior)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_sources/test_zenodo_source.py`

Steps:

- [ ] Write a failing test. Append to the `TestZenodoMatch` class in `/home/spinoza/github/beta/repoindex/tests/test_sources/test_zenodo_source.py`:
  ```python
      def test_match_stores_both_dois(self, tmp_path):
          s = ZenodoSource()
          s._records = [
              ZenodoRecord(
                  doi="10.5281/zenodo.123",
                  concept_doi="10.5281/zenodo.100",
                  title="My Repo",
                  version="1.0.0",
                  url="https://zenodo.org/records/123",
                  github_url="https://github.com/owner/my-repo",
              )
          ]
          result = s.match(
              str(tmp_path),
              repo_record={'remote_url': 'https://github.com/owner/my-repo', 'name': 'my-repo'},
          )
          assert result is not None
          assert result.doi == "10.5281/zenodo.123"
          assert result.concept_doi == "10.5281/zenodo.100"

      def test_match_concept_doi_none_keeps_version_doi(self, tmp_path):
          s = ZenodoSource()
          s._records = [
              ZenodoRecord(
                  doi="10.5281/zenodo.123",
                  concept_doi=None,
                  title="My Repo",
                  url="https://zenodo.org/records/123",
                  github_url="https://github.com/owner/my-repo",
              )
          ]
          result = s.match(
              str(tmp_path),
              repo_record={'remote_url': 'https://github.com/owner/my-repo', 'name': 'my-repo'},
          )
          assert result is not None
          assert result.doi == "10.5281/zenodo.123"
          assert result.concept_doi is None
  ```

- [ ] Run the new tests, expect FAIL:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_sources/test_zenodo_source.py -k "stores_both_dois or concept_doi_none_keeps" -q
  ```
  Expected: failure (`test_match_stores_both_dois`: `result.doi == "10.5281/zenodo.100"` due to the current collapse, so the `result.doi == "10.5281/zenodo.123"` assert fails; `concept_doi` attribute is also wrong/absent until the field exists from Task 1).

- [ ] Implement: stop collapsing. In `/home/spinoza/github/beta/repoindex/repoindex/sources/registries/zenodo.py`, change the `_to_metadata` return (lines 109-116) from:
  ```python
          return PackageMetadata(
              registry='zenodo',
              name=record.title or '',
              version=record.version,
              published=True,
              url=record.url,
              doi=record.concept_doi or record.doi,
          )
  ```
  to:
  ```python
          return PackageMetadata(
              registry='zenodo',
              name=record.title or '',
              version=record.version,
              published=True,
              url=record.url,
              doi=record.doi,
              concept_doi=record.concept_doi,
          )
  ```

- [ ] Re-point the existing assertion at line 91 in `test_match_by_github_url`. Change:
  ```python
          assert result.doi == "10.5281/zenodo.100"
  ```
  to:
  ```python
          assert result.doi == "10.5281/zenodo.123"
          assert result.concept_doi == "10.5281/zenodo.100"
  ```

- [ ] Re-point the existing assertion at line 156 in `test_fetch_returns_match_dict`. Change:
  ```python
          assert result['doi'] == '10.5281/zenodo.400'
  ```
  to:
  ```python
          assert result['doi'] == '10.5281/zenodo.456'
          assert result['concept_doi'] == '10.5281/zenodo.400'
  ```

- [ ] Run the full zenodo source suite, expect PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_sources/test_zenodo_source.py -q
  ```
  Expected: all passed (the two new tests plus the two re-pointed ones plus the rest).

### Task 5: Store dual DOIs in the repository_service zenodo path

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/services/repository_service.py` (`_zenodo_record_to_metadata` at lines 548-557)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_repository_service.py`

Steps:

- [ ] Confirm the service test file and a matching test class exist:
  ```
  cd /home/spinoza/github/beta/repoindex && grep -n "match_zenodo_record\|_zenodo_record_to_metadata\|class Test" tests/test_repository_service.py | head -20
  ```
  Expected: lines referencing the service test classes. (If `match_zenodo_record` is not referenced, the test below still works because it constructs the service directly.)

- [ ] Write a failing test. Append to `/home/spinoza/github/beta/repoindex/tests/test_repository_service.py`:
  ```python
  class TestRepositoryServiceZenodoDualDoi:
      def test_zenodo_metadata_keeps_both_dois(self):
          from repoindex.services.repository_service import RepositoryService
          from repoindex.infra.zenodo_client import ZenodoRecord
          svc = RepositoryService(config={})
          record = ZenodoRecord(
              doi="10.5281/zenodo.456",
              concept_doi="10.5281/zenodo.400",
              title="demo",
              version="2.0.0",
              url="https://zenodo.org/records/456",
          )
          meta = svc._zenodo_record_to_metadata(record)
          assert meta.doi == "10.5281/zenodo.456"
          assert meta.concept_doi == "10.5281/zenodo.400"
  ```

  Note: verify the `RepositoryService` constructor accepts `config={}` by checking a neighbor test; if existing tests instantiate it differently (for example `RepositoryService(config)` with a positional dict), match that exact call form.

- [ ] Run the test, expect FAIL:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_repository_service.py -k zenodo_metadata_keeps_both_dois -q
  ```
  Expected: failure (`meta.doi == "10.5281/zenodo.400"` from the current `record.concept_doi or record.doi` collapse, so `meta.doi == "10.5281/zenodo.456"` fails).

- [ ] Implement: stop collapsing. In `/home/spinoza/github/beta/repoindex/repoindex/services/repository_service.py`, change `_zenodo_record_to_metadata` (lines 550-557) from:
  ```python
          return PackageMetadata(
              registry='zenodo',
              name=record.title or '',
              version=record.version,
              published=True,
              url=record.url,
              doi=record.concept_doi or record.doi,
          )
  ```
  to:
  ```python
          return PackageMetadata(
              registry='zenodo',
              name=record.title or '',
              version=record.version,
              published=True,
              url=record.url,
              doi=record.doi,
              concept_doi=record.concept_doi,
          )
  ```

- [ ] Run the test, expect PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_repository_service.py -k zenodo_metadata_keeps_both_dois -q
  ```
  Expected: 1 passed.

### Task 6: Persist `concept_doi` through the publications write path

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/database/repository.py` (`_upsert_publication` at lines 186-248: UPDATE at 207-229 and INSERT at 232-248)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_database.py`

Steps:

- [ ] Write a failing test. Append to the `TestRepositoryOperations` class in `/home/spinoza/github/beta/repoindex/tests/test_database.py` (the class with `test_upsert_repo_with_package_metadata` at line 337):
  ```python
      def test_upsert_publication_stores_concept_doi(self):
          package = PackageMetadata(
              registry='zenodo',
              name='demo',
              version='1.0.0',
              published=True,
              doi='10.5281/zenodo.456',
              concept_doi='10.5281/zenodo.400',
          )
          repo = Repository(
              path=str(self.repo_path),
              name='test-repo',
              package=package,
          )
          with Database(db_path=self.db_path) as db:
              repo_id = upsert_repo(db, repo)
              db.execute("SELECT * FROM publications WHERE repo_id = ?", (repo_id,))
              row = db.fetchone()
              self.assertEqual(row['doi'], '10.5281/zenodo.456')
              self.assertEqual(row['concept_doi'], '10.5281/zenodo.400')

      def test_upsert_publication_updates_concept_doi(self):
          repo = Repository(
              path=str(self.repo_path),
              name='test-repo',
              package=PackageMetadata(
                  registry='zenodo', name='demo', doi='10.5281/zenodo.1',
                  concept_doi='10.5281/zenodo.0',
              ),
          )
          with Database(db_path=self.db_path) as db:
              repo_id = upsert_repo(db, repo)
              repo2 = Repository(
                  path=str(self.repo_path),
                  name='test-repo',
                  package=PackageMetadata(
                      registry='zenodo', name='demo', doi='10.5281/zenodo.2',
                      concept_doi='10.5281/zenodo.0',
                  ),
              )
              upsert_repo(db, repo2)
              db.execute("SELECT * FROM publications WHERE repo_id = ?", (repo_id,))
              row = db.fetchone()
              self.assertEqual(row['doi'], '10.5281/zenodo.2')
              self.assertEqual(row['concept_doi'], '10.5281/zenodo.0')
  ```

- [ ] Run the tests, expect FAIL:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py -k "upsert_publication_stores_concept_doi or upsert_publication_updates_concept_doi" -q
  ```
  Expected: failure (`concept_doi` column is never written, so `row['concept_doi']` is `None`, not the expected value).

- [ ] Implement: write `concept_doi` in the UPDATE branch. In `/home/spinoza/github/beta/repoindex/repoindex/database/repository.py`, change the UPDATE statement (lines 207-229) so the SET list and param tuple include `concept_doi`. Replace:
  ```python
          db.execute("""
              UPDATE publications SET
                  package_name = ?,
                  current_version = ?,
                  published = ?,
                  url = ?,
                  doi = ?,
                  downloads_total = ?,
                  downloads_30d = ?,
                  last_published = ?,
                  scanned_at = CURRENT_TIMESTAMP
              WHERE id = ?
          """, (
              package.name,
              package.version,
              package.published,
              package.url,
              getattr(package, 'doi', None),
              package.downloads,
              getattr(package, 'downloads_30d', None),
              package.last_updated,
              existing['id']
          ))
  ```
  with:
  ```python
          db.execute("""
              UPDATE publications SET
                  package_name = ?,
                  current_version = ?,
                  published = ?,
                  url = ?,
                  doi = ?,
                  concept_doi = ?,
                  downloads_total = ?,
                  downloads_30d = ?,
                  last_published = ?,
                  scanned_at = CURRENT_TIMESTAMP
              WHERE id = ?
          """, (
              package.name,
              package.version,
              package.published,
              package.url,
              getattr(package, 'doi', None),
              getattr(package, 'concept_doi', None),
              package.downloads,
              getattr(package, 'downloads_30d', None),
              package.last_updated,
              existing['id']
          ))
  ```

- [ ] Implement: write `concept_doi` in the INSERT branch. In the same file, change the INSERT statement (lines 232-248). Replace:
  ```python
          db.execute("""
              INSERT INTO publications (
                  repo_id, registry, package_name, current_version,
                  published, url, doi, downloads_total, downloads_30d, last_published
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """, (
              repo_id,
              package.registry,
              package.name,
              package.version,
              package.published,
              package.url,
              getattr(package, 'doi', None),
              package.downloads,
              getattr(package, 'downloads_30d', None),
              package.last_updated
          ))
  ```
  with:
  ```python
          db.execute("""
              INSERT INTO publications (
                  repo_id, registry, package_name, current_version,
                  published, url, doi, concept_doi,
                  downloads_total, downloads_30d, last_published
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """, (
              repo_id,
              package.registry,
              package.name,
              package.version,
              package.published,
              package.url,
              getattr(package, 'doi', None),
              getattr(package, 'concept_doi', None),
              package.downloads,
              getattr(package, 'downloads_30d', None),
              package.last_updated
          ))
  ```

- [ ] Run the tests, expect PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py -k "upsert_publication_stores_concept_doi or upsert_publication_updates_concept_doi" -q
  ```
  Expected: 2 passed.

### Task 7: Prefer `concept_doi` in the bibtex and jsonld citation exporters

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/exporters/bibtex.py` (DOI selection at line 97)
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/exporters/jsonld.py` (DOI selection at line 37)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_exporters/test_exporters.py`

Steps:

- [ ] Write a failing test. Append to the `TestBibTeXExporter` class in `/home/spinoza/github/beta/repoindex/tests/test_exporters/test_exporters.py` (class at line 95):
  ```python
      def test_export_prefers_concept_doi(self):
          e = BibTeXExporter()
          out = io.StringIO()
          repo = {
              'name': 'gamma',
              'concept_doi': '10.5281/zenodo.100',
              'citation_doi': '10.5281/zenodo.123',
          }
          e.export([repo], out)
          assert 'doi = {10.5281/zenodo.100}' in out.getvalue()

      def test_export_falls_back_to_citation_doi(self):
          e = BibTeXExporter()
          out = io.StringIO()
          repo = {'name': 'delta', 'citation_doi': '10.5281/zenodo.123'}
          e.export([repo], out)
          assert 'doi = {10.5281/zenodo.123}' in out.getvalue()
  ```
  Also append to the `TestJSONLDExporter` class (find it: it lives in the same file; the `JSONLDExporter` import is at line 12). Add:
  ```python
      def test_jsonld_prefers_concept_doi(self):
          e = JSONLDExporter()
          out = io.StringIO()
          repo = {
              'name': 'gamma',
              'concept_doi': '10.5281/zenodo.100',
              'citation_doi': '10.5281/zenodo.123',
          }
          e.export([repo], out)
          assert 'https://doi.org/10.5281/zenodo.100' in out.getvalue()
  ```

  Before writing, confirm the JSONL-D test class name:
  ```
  cd /home/spinoza/github/beta/repoindex && grep -n "class TestJSONLD\|class.*JSONLD" tests/test_exporters/test_exporters.py
  ```
  Use whatever class name exists; if the class is absent, create `class TestJSONLDExporter:` with the single method above.

- [ ] Run the tests, expect FAIL:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_exporters/test_exporters.py -k "prefers_concept_doi or falls_back_to_citation_doi" -q
  ```
  Expected: failure on the two `prefers_concept_doi` cases (current code reads only `citation_doi`, so it emits `...zenodo.123` instead of the concept DOI); `test_export_falls_back_to_citation_doi` should already pass.

- [ ] Implement: bibtex preference chain. In `/home/spinoza/github/beta/repoindex/repoindex/exporters/bibtex.py`, change line 96-97 from:
  ```python
              # DOI
              doi = repo.get('citation_doi') or ''
  ```
  to:
  ```python
              # DOI: the concept (version-independent) DOI is what a paper cites,
              # so prefer it, then the citation file DOI, then the publication DOI.
              doi = repo.get('concept_doi') or repo.get('citation_doi') or repo.get('doi') or ''
  ```

- [ ] Implement: jsonld preference chain. In `/home/spinoza/github/beta/repoindex/repoindex/exporters/jsonld.py`, change line 37 from:
  ```python
      doi = repo.get('citation_doi')
  ```
  to:
  ```python
      doi = repo.get('concept_doi') or repo.get('citation_doi') or repo.get('doi')
  ```

- [ ] Run the tests, expect PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_exporters/test_exporters.py -k "prefers_concept_doi or falls_back_to_citation_doi" -q
  ```
  Expected: 3 passed.

### Task 8: Emit `concept_doi` in the arkiv publications record

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/exporters/arkiv.py` (`_publication_to_record`, metadata loop at line 207)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_export_arkiv.py`

Steps:

- [ ] Confirm the helper name and a callable entry point for the test:
  ```
  cd /home/spinoza/github/beta/repoindex && grep -n "_publication_to_record\|def export_arkiv\|publications.jsonl" repoindex/exporters/arkiv.py tests/test_export_arkiv.py | head -20
  ```
  Expected: the `_publication_to_record` definition (around line 165-212) and how the arkiv test invokes exporting. Use `_publication_to_record` directly in the test (it takes a single `pub` dict and returns a record dict).

- [ ] Write a failing test. Append to `/home/spinoza/github/beta/repoindex/tests/test_export_arkiv.py`:
  ```python
  def test_publication_record_includes_concept_doi():
      from repoindex.exporters.arkiv import _publication_to_record
      pub = {
          'registry': 'zenodo',
          'package_name': 'demo',
          'current_version': '1.0.0',
          'published': 1,
          'doi': '10.5281/zenodo.456',
          'concept_doi': '10.5281/zenodo.400',
          'url': 'https://zenodo.org/records/456',
      }
      record = _publication_to_record(pub)
      assert record['metadata']['doi'] == '10.5281/zenodo.456'
      assert record['metadata']['concept_doi'] == '10.5281/zenodo.400'
  ```

  Note: confirm `_publication_to_record`'s exact signature from the grep above; if it requires extra arguments, supply matching defaults in the test call.

- [ ] Run the test, expect FAIL:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_export_arkiv.py -k publication_record_includes_concept_doi -q
  ```
  Expected: failure (`KeyError: 'concept_doi'` on `record['metadata']['concept_doi']` because the metadata loop at line 207 does not include `concept_doi`).

- [ ] Implement: add `concept_doi` to the copied metadata keys. In `/home/spinoza/github/beta/repoindex/repoindex/exporters/arkiv.py`, change line 207 from:
  ```python
      for key in ('doi', 'downloads_total', 'downloads_30d', 'last_published'):
  ```
  to:
  ```python
      for key in ('doi', 'concept_doi', 'downloads_total', 'downloads_30d', 'last_published'):
  ```

- [ ] Run the test, expect PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_export_arkiv.py -k publication_record_includes_concept_doi -q
  ```
  Expected: 1 passed.

### Task 9: Run the affected suites and commit the group

Files:
- Commit: all files modified in Tasks 1-8.

Steps:

- [ ] Run every suite touched by this group together, expect all PASS:
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_domain.py tests/test_database.py tests/test_sources/test_zenodo_source.py tests/test_repository_service.py tests/test_exporters/test_exporters.py tests/test_export_arkiv.py -q
  ```
  Expected: all passed, no failures, no errors.

- [ ] Run the full suite to confirm no cross-cutting regression (baseline was 1848 passing; this group adds tests):
  ```
  cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest -q
  ```
  Expected: all passed (1848 baseline plus the new tests from this group), 0 failed.

- [ ] Stage and commit the group:
  ```
  cd /home/spinoza/github/beta/repoindex && git add repoindex/database/schema.py repoindex/database/repository.py repoindex/domain/repository.py repoindex/sources/registries/zenodo.py repoindex/services/repository_service.py repoindex/exporters/bibtex.py repoindex/exporters/jsonld.py repoindex/exporters/arkiv.py tests/test_domain.py tests/test_database.py tests/test_sources/test_zenodo_source.py tests/test_repository_service.py tests/test_exporters/test_exporters.py tests/test_export_arkiv.py && git commit -m "$(cat <<'EOF'
schema(v10): preserve events + refresh_log on migration; dual Zenodo DOIs

Bump CURRENT_VERSION 9->10. apply_schema now copies events and refresh_log
to temp tables, recreates the schema, and re-inserts (INSERT OR IGNORE so
events dedupe by event_id), instead of dropping append-only external history.

Add a nullable concept_doi column to publications and a concept_doi field to
PackageMetadata. The Zenodo source and repository_service now store the
version DOI in doi and the concept DOI in concept_doi (no longer collapsed).
The bibtex and jsonld citation exporters prefer concept_doi (the DOI a paper
cites), falling back to citation_doi then doi; the arkiv publications record
emits concept_doi.

CHANGELOG: schema v10 migration preserves external-sourced events and the
refresh_log across upgrades.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
  ```

Notes for the assembler / implementer (grounded in the real code):
- `apply_schema` already runs an unconditional `conn.executescript(SCHEMA_V1)` at the line directly after the migration `if` block (current line 363); the new restore logic re-runs `SCHEMA_V1` inside the block before re-inserting, which is safe because all DDL is `IF NOT EXISTS`. Do not delete the trailing unconditional `executescript`/`_schema_info` insert/`commit` (current lines 363-369): the fresh-DB path (`current == 0`) depends on them.
- The existing zenodo source tests at `tests/test_sources/test_zenodo_source.py:91` and `:156` assert the old collapsed behavior and MUST be re-pointed (Task 4); leaving them unchanged will turn the suite red.
- `PackageMetadata` is `@dataclass(frozen=True)`; adding `concept_doi` with a default keeps all existing positional/keyword constructions valid (STABILITY-legal additive change). The write path uses `getattr(package, 'concept_doi', None)` to stay tolerant of any third-party `PackageMetadata`-like object.
- The bibtex/jsonld exporters consume flat repo dicts (e.g. `repo.get('citation_doi')`); they do not currently receive publication `doi`/`concept_doi` unless the export row-builder joins publications. The preference chain added here is forward-compatible: it prefers `concept_doi`, then `citation_doi`, then `doi`, so it is correct whether or not the row carries a joined publication DOI.

---

## Commit group: footguns-cli

All work is in `/home/spinoza/github/beta/repoindex/repoindex/commands/ops.py`. Tests go in `/home/spinoza/github/beta/repoindex/tests/test_commands/test_footguns_cli.py` (new) and reuse the CliRunner patterns in `/home/spinoza/github/beta/repoindex/tests/test_commands/test_set_actions.py`. The 13 handlers that still declare the dead positional `query_string` (`ops_audit_handler`, `git_push_handler`, `git_pull_handler`, `git_status_handler`, `generate_codemeta_handler`, `generate_license_handler`, `generate_gitignore_handler`, `generate_code_of_conduct_handler`, `generate_contributing_handler`, `generate_citation_handler`, `generate_zenodo_handler`, `generate_mkdocs_handler`, `wip_snapshot_handler`) all route repo selection through one of two functions: `_resolve_repos()` (which calls `_get_repos_from_query()`) for 12 of them, and `wip_snapshot_handler` which calls `_get_repos_from_query()` directly. A single guard in `_get_repos_from_query()` therefore covers every affected handler. `mirror_handler` and the `set-*` helpers pass a literal `''`, so they are unaffected. The six `set-*` handlers (`set-topics`, `set-description`, `set-archived`, `set-visibility`, `set-default-branch`, `set-pages`) get a shared confirmation gate; only the first five have `--all` (so only they can reach N>1), but `--yes/-y` is added to all six for surface uniformity.

Critical test mechanic confirmed against the real environment: under `CliRunner`, `sys.stdout.isatty()` returns `False` and `patch('sys.stdout.isatty', ...)` does NOT reach the swapped stream. The fix introduces a module-level `_stdout_isatty()` seam that tests patch via `patch('repoindex.commands.ops._stdout_isatty', ...)`, which works reliably. No existing test passes a non-empty positional query string, so the guard introduces no regressions (verified: `pytest tests/test_commands/test_set_actions.py tests/test_ops.py -q` = `115 passed` at baseline).

### Task 1: positional query_string now raises a migration error

**Files**
- Create: `tests/test_commands/test_footguns_cli.py`
- Modify: `repoindex/commands/ops.py` (function `_get_repos_from_query`, lines 92-106)
- Test path: `tests/test_commands/test_footguns_cli.py`

Steps:

- [ ] Create `tests/test_commands/test_footguns_cli.py` with this header and first failing test:

```python
"""CLI footgun guards: dead positional query_string and set-* confirmation.

Mirrors the CliRunner patterns in tests/test_commands/test_set_actions.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner


def _runner():
    return CliRunner()


class TestQueryStringGuard:
    def test_get_repos_from_query_raises_on_nonempty(self):
        from repoindex.commands.ops import _get_repos_from_query

        with pytest.raises(click.UsageError) as exc:
            _get_repos_from_query({}, "language == 'Python'")
        msg = str(exc.value)
        assert "positional queries were removed in v0.16" in msg
        assert "--language" in msg
```

- [ ] Run it and expect FAIL (function still ignores the positional):
  `pytest tests/test_commands/test_footguns_cli.py::TestQueryStringGuard::test_get_repos_from_query_raises_on_nonempty -q`
  Expected: `1 failed` with `DID NOT RAISE <class 'click.exceptions.UsageError'>`.

- [ ] Implement the guard. In `repoindex/commands/ops.py` replace the current body of `_get_repos_from_query` (lines 92-106):

```python
def _get_repos_from_query(config, query_string: str = '', debug: bool = False, **query_flags):
    """Get repos matching the standard filter flags.

    The ``query_string`` parameter is retained for signature compatibility
    with call sites that pre-date the DSL removal; it is ignored. For complex
    selection, use ``repoindex sql`` or the MCP ``run_sql`` tool.
    """
    return fetch_repos_by_flags(
        config,
        dirty=query_flags.get('dirty', False),
        language=query_flags.get('language', None),
        tag=query_flags.get('tag', ()),
        recent=query_flags.get('recent', None),
        debug=debug,
    )
```

  with:

```python
def _get_repos_from_query(config, query_string: str = '', debug: bool = False, **query_flags):
    """Get repos matching the standard filter flags.

    The DSL was removed in v0.16. A non-empty ``query_string`` positional is
    almost always a stale DSL expression that, if silently ignored, would act
    on the WHOLE collection. Reject it loudly. For complex selection, use
    ``repoindex sql`` or the MCP ``run_sql`` tool.
    """
    if query_string:
        raise click.UsageError(
            "positional queries were removed in v0.16; use "
            "--language/--tag/--recent or `repoindex sql`"
        )
    return fetch_repos_by_flags(
        config,
        dirty=query_flags.get('dirty', False),
        language=query_flags.get('language', None),
        tag=query_flags.get('tag', ()),
        recent=query_flags.get('recent', None),
        debug=debug,
    )
```

- [ ] Run it and expect PASS:
  `pytest tests/test_commands/test_footguns_cli.py::TestQueryStringGuard::test_get_repos_from_query_raises_on_nonempty -q`
  Expected: `1 passed`.

### Task 2: positional errors end-to-end through representative handlers

**Files**
- Modify: `tests/test_commands/test_footguns_cli.py`
- Test path: `tests/test_commands/test_footguns_cli.py`

Steps:

- [ ] Add these three tests to the `TestQueryStringGuard` class. They exercise a `_resolve_repos`-routed handler (`git_status_handler`), the direct-call handler (`wip_snapshot_handler`), and the audit handler, proving the single guard covers every path. `click.UsageError` surfaces as a non-zero exit through `CliRunner`:

```python
    def test_git_status_positional_errors(self):
        from repoindex.commands.ops import git_status_handler

        with patch('repoindex.commands.ops.load_config', return_value={}):
            result = _runner().invoke(
                git_status_handler, ["language == 'Python'"]
            )
        assert result.exit_code != 0
        assert "positional queries were removed in v0.16" in result.output

    def test_wip_snapshot_positional_errors(self):
        from repoindex.commands.ops import wip_snapshot_handler

        with patch('repoindex.commands.ops.load_config', return_value={}):
            result = _runner().invoke(
                wip_snapshot_handler, ["name == 'dreamlog'"]
            )
        assert result.exit_code != 0
        assert "positional queries were removed in v0.16" in result.output

    def test_audit_positional_errors(self):
        from repoindex.commands.ops import ops_audit_handler

        with patch('repoindex.commands.ops.load_config', return_value={}):
            result = _runner().invoke(
                ops_audit_handler, ["not has_license"]
            )
        assert result.exit_code != 0
        assert "positional queries were removed in v0.16" in result.output
```

- [ ] Run and expect PASS (the Task 1 guard already covers these paths):
  `pytest tests/test_commands/test_footguns_cli.py::TestQueryStringGuard -q`
  Expected: `4 passed`.

### Task 3: flag path still works after the guard (no regression)

**Files**
- Modify: `tests/test_commands/test_footguns_cli.py`
- Test path: `tests/test_commands/test_footguns_cli.py`

Steps:

- [ ] Add this test class. With an empty positional, `_get_repos_from_query` must still pass the filter flags through to `fetch_repos_by_flags`:

```python
class TestFlagPathStillWorks:
    def test_empty_positional_passes_flags_through(self):
        from repoindex.commands.ops import _get_repos_from_query

        sentinel = [{'name': 'a', 'path': '/tmp/a'}]
        with patch(
            'repoindex.commands.ops.fetch_repos_by_flags',
            return_value=sentinel,
        ) as fake:
            repos = _get_repos_from_query(
                {}, '', language='python', dirty=True,
                tag=('work/*',), recent='7d',
            )
        assert repos is sentinel
        _, kwargs = fake.call_args
        assert kwargs['language'] == 'python'
        assert kwargs['dirty'] is True
        assert kwargs['tag'] == ('work/*',)
        assert kwargs['recent'] == '7d'
```

- [ ] Run and expect PASS:
  `pytest tests/test_commands/test_footguns_cli.py::TestFlagPathStillWorks -q`
  Expected: `1 passed`.

### Task 4: fix the misleading DSL docstring examples

**Files**
- Modify: `repoindex/commands/ops.py` (`git_cmd` docstring line 66; `generate_cmd` group docstring line 845; `git_push_handler` example line 427; `git_pull_handler` example line 510; `generate_license_handler` examples lines 973, 975; `wip_snapshot_handler` example line 1545)
- Test path: `tests/test_commands/test_footguns_cli.py`

Steps:

- [ ] Add this characterization test that grep-guards the module source against DSL residue in docstrings:

```python
class TestNoDslDocstrings:
    def test_no_dsl_examples_in_source(self):
        import inspect
        import repoindex.commands.ops as ops_mod

        src = inspect.getsource(ops_mod)
        forbidden = [
            'git push "language',
            'pull "is_clean"',
            'license "not has_license"',
            'license --license apache-2.0 "not has_license"',
            'wip-snapshot "name ==',
            'same query filters as the query command',
        ]
        offenders = [f for f in forbidden if f in src]
        assert offenders == [], f"DSL residue still present: {offenders}"
```

- [ ] Run and expect FAIL (all six strings still present):
  `pytest tests/test_commands/test_footguns_cli.py::TestNoDslDocstrings -q`
  Expected: `1 failed`, the assert listing all six offenders.

- [ ] Fix the `git_cmd` docstring. In `repoindex/commands/ops.py` replace (lines 65-66):

```python
    Push, pull, and check status across your repository collection.
    Supports the same query filters as the query command.
```

  with:

```python
    Push, pull, and check status across your repository collection.
    Filter with --language/--tag/--dirty/--recent.
```

- [ ] Fix the `git_push_handler` example. Replace (lines 426-427):

```python
        # Push with DSL query
        repoindex ops git push "language == 'Python'" --dry-run
```

  with:

```python
        # Push only repos with a tag
        repoindex ops git push --tag "work/*" --yes
```

- [ ] Fix the `git_pull_handler` example. Replace (lines 509-510):

```python
        # Pull only clean repos (no uncommitted changes)
        repoindex ops git pull "is_clean" --yes
```

  with:

```python
        # Pull repos with a tag
        repoindex ops git pull --tag "work/*" --yes
```

- [ ] Fix the `generate_cmd` group docstring example. Replace (lines 844-845):

```python
        # Generate MIT license for repos without license
        repoindex ops generate license "not has_license" --license mit --dry-run
```

  with:

```python
        # Generate MIT license for Python repos
        repoindex ops generate license --language python --license mit --dry-run
```

- [ ] Fix the `generate_license_handler` examples. Replace (lines 972-975):

```python
        # Generate MIT license for repos without license
        repoindex ops generate license "not has_license" --dry-run
        # Generate Apache 2.0 license
        repoindex ops generate license --license apache-2.0 "not has_license" --dry-run
```

  with:

```python
        # Generate MIT license for all repos
        repoindex ops generate license --dry-run
        # Generate Apache 2.0 license for Python repos
        repoindex ops generate license --license apache-2.0 --language python --dry-run
```

- [ ] Fix the `wip_snapshot_handler` example. Replace (lines 1544-1545):

```python
        # Specific repo
        repoindex ops wip-snapshot "name == 'dreamlog'"
```

  with:

```python
        # Only repos with a tag
        repoindex ops wip-snapshot --tag "work/*"
```

- [ ] Run and expect PASS:
  `pytest tests/test_commands/test_footguns_cli.py::TestNoDslDocstrings -q`
  Expected: `1 passed`.

### Task 5: bulk set-* prompt helper (gate logic)

**Files**
- Modify: `repoindex/commands/ops.py` (add `_stdout_isatty` and `_confirm_bulk_set` helpers immediately after `_set_action_output`, which ends with `sys.exit(1)` at line 2118, before the `@ops_cmd.command('set-topics')` decorator at line 2121)
- Test path: `tests/test_commands/test_footguns_cli.py`

Steps:

- [ ] Add this failing test class. It targets the helper directly so the gate logic is pinned independent of any one handler:

```python
class TestConfirmBulkSetHelper:
    def test_single_repo_never_prompts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=1, dry_run=False, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_dry_run_never_prompts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=True, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_json_never_prompts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=True, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_non_tty_never_prompts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=False), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_yes_bypasses_prompt(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=False, yes=True,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_bulk_tty_prompts_and_yes_answer_proceeds(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm', return_value=True) as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_called_once()

    def test_bulk_tty_prompts_and_no_answer_aborts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm', return_value=False) as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is False
        confirm.assert_called_once()
```

- [ ] Run and expect FAIL (helpers do not exist yet):
  `pytest tests/test_commands/test_footguns_cli.py::TestConfirmBulkSetHelper -q`
  Expected: `7 errors` with `ImportError: cannot import name '_confirm_bulk_set' from 'repoindex.commands.ops'`.

- [ ] Implement both helpers in `repoindex/commands/ops.py`. Insert them immediately after the `_set_action_output` function (after its final `sys.exit(1)` at line 2118), before the `@ops_cmd.command('set-topics')` decorator at line 2121:

```python
def _stdout_isatty() -> bool:
    """Return whether stdout is a TTY.

    Wrapped in a module-level helper so tests can patch it: ``CliRunner``
    replaces ``sys.stdout`` at invoke time, which makes the swapped stream's
    ``isatty()`` unpatchable from the outside.
    """
    return sys.stdout.isatty()


def _confirm_bulk_set(
    n: int,
    dry_run: bool,
    output_json: bool,
    yes: bool,
    action_name: str,
) -> bool:
    """Decide whether a bulk set-* action may proceed.

    Returns True to proceed, False to abort. A confirmation prompt is shown
    only for a genuine interactive bulk mutation: more than one repo, not a
    dry run, not JSON output, an interactive TTY, and ``--yes`` not given. All
    other cases proceed without prompting so scripted, piped, single-repo, and
    preview invocations never hang.
    """
    if yes or dry_run or output_json or n <= 1 or not _stdout_isatty():
        return True
    if not click.confirm(f"Apply {action_name} to {n} repositories?"):
        print("Aborted.", file=sys.stderr)
        return False
    return True
```

- [ ] Run and expect PASS:
  `pytest tests/test_commands/test_footguns_cli.py::TestConfirmBulkSetHelper -q`
  Expected: `7 passed`.

### Task 6: wire the gate into the five --all set-* handlers and set-pages

**Files**
- Modify: `repoindex/commands/ops.py` (`set_topics_handler` lines 2121-2182; `set_description_handler` lines 2185-2240; `set_archived_handler` lines 2243-2300; `set_visibility_handler` lines 2303-2358; `set_default_branch_handler` lines 2361-2412; `set_pages_handler` lines 2415-2457)
- Test path: `tests/test_commands/test_footguns_cli.py`

Steps:

- [ ] Add this failing handler-level test class. It drives `set_topics_handler` end-to-end through `CliRunner`:

```python
class TestSetTopicsConfirmation:
    def _bulk_patches(self):
        fake = MagicMock()
        fake.source_id = 'github'
        repos = [
            {'name': 'a', 'path': '/tmp/a', 'forge_id': 'github'},
            {'name': 'b', 'path': '/tmp/b', 'forge_id': 'github'},
        ]
        return fake, repos

    def test_bulk_aborts_on_no(self):
        from repoindex.commands.ops import set_topics_handler

        fake, repos = self._bulk_patches()
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.commands.ops._get_repos_from_query', return_value=repos), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm', return_value=False), \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['--all', 'python', 'cli'],
            )
        assert 'Aborted.' in result.output
        fake.set_topics.assert_not_called()

    def test_bulk_prompts_and_proceeds_on_yes_answer(self):
        from repoindex.commands.ops import set_topics_handler

        fake, repos = self._bulk_patches()
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.commands.ops._get_repos_from_query', return_value=repos), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm', return_value=True) as confirm, \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['--all', 'python', 'cli'],
            )
        assert result.exit_code == 0, result.output
        confirm.assert_called_once()
        assert fake.set_topics.call_count == 2

    def test_yes_flag_bypasses_prompt(self):
        from repoindex.commands.ops import set_topics_handler

        fake, repos = self._bulk_patches()
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.commands.ops._get_repos_from_query', return_value=repos), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm, \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['--all', '--yes', 'python', 'cli'],
            )
        assert result.exit_code == 0, result.output
        confirm.assert_not_called()
        assert fake.set_topics.call_count == 2

    def test_single_repo_does_not_prompt(self):
        from repoindex.commands.ops import set_topics_handler

        fake = MagicMock()
        fake.source_id = 'github'
        repo = {'name': 'myrepo', 'path': '/tmp/myrepo', 'forge_id': 'github'}
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.database.repository.get_repo_by_name', return_value=repo), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm, \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['myrepo', 'python'],
            )
        assert result.exit_code == 0, result.output
        confirm.assert_not_called()
        fake.set_topics.assert_called_once()

    def test_json_bulk_does_not_prompt(self):
        from repoindex.commands.ops import set_topics_handler

        fake, repos = self._bulk_patches()
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.commands.ops._get_repos_from_query', return_value=repos), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm, \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['--all', '--json', 'python', 'cli'],
            )
        assert result.exit_code == 0, result.output
        confirm.assert_not_called()
        assert '"summary"' in result.output
```

- [ ] Run and expect FAIL (handlers do not call the gate yet, and `--yes` is not a recognized option):
  `pytest tests/test_commands/test_footguns_cli.py::TestSetTopicsConfirmation -q`
  Expected: `failed` on `test_bulk_aborts_on_no` (no `Aborted.` printed because no prompt fires) and on `test_yes_flag_bypasses_prompt` (`--yes` is rejected by Click with `No such option: --yes`, non-zero exit).

- [ ] Add the `--yes/-y` option and the gate to `set_topics_handler`. In `repoindex/commands/ops.py`, add the option decorator right after the `--dry-run` decorator (the two-line `@click.option('--dry-run', ...)` ending at line 2127), so the decorator stack reads:

```python
@click.option('--dry-run', is_flag=True,
              help='Preview without making API calls')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
```

  Add `yes: bool,` to the signature right after `dry_run: bool,` (line 2135-2136):

```python
    apply_all: bool,
    dry_run: bool,
    yes: bool,
    output_json: bool,
```

  Insert the gate in the body after `config, repos = resolved` (line 2172), before `topic_list = list(topics)`:

```python
    config, repos = resolved

    if not _confirm_bulk_set(
        len(repos), dry_run, output_json, yes, 'set_topics',
    ):
        return

    topic_list = list(topics)
```

- [ ] Apply the identical three-part change to the other four `--all` handlers. For each, add `@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')` after its `--dry-run` decorator, add `yes: bool,` after `dry_run: bool,` in the signature, and insert the gate immediately after that handler's `config, repos = resolved` line. The gate block is:

```python
    if not _confirm_bulk_set(
        len(repos), dry_run, output_json, yes, '<ACTION_NAME>',
    ):
        return
```

  with per-handler insertion points and action names:
  - `set_description_handler`: gate inserted after `config, repos = resolved` (line 2232), before `def invoke(...)`; `<ACTION_NAME>` = `'set_description'`.
  - `set_archived_handler`: gate inserted after `config, repos = resolved` (line 2290), before `archived = value.lower() == 'true'`; `<ACTION_NAME>` = `'set_archived'`.
  - `set_visibility_handler`: gate inserted after `config, repos = resolved` (line 2348), before `public = value.lower() == 'public'`; `<ACTION_NAME>` = `'set_visibility'`.
  - `set_default_branch_handler`: gate inserted after `config, repos = resolved` (line 2404), before `def invoke(...)`; `<ACTION_NAME>` = `'set_default_branch'`.

- [ ] Add `--yes/-y` to `set_pages_handler` for surface consistency (it has no `--all`, so N is always 1 and the gate never prompts; the flag is accepted and inert). Add the decorator after its `--dry-run` option (ending at line 2421):

```python
@click.option('--dry-run', is_flag=True,
              help='Preview without making API calls')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
```

  Add `yes: bool,` to its signature after `dry_run: bool,` (line 2428):

```python
    path: str,
    dry_run: bool,
    yes: bool,
    output_json: bool,
    debug: bool,
```

  No gate call is added in `set_pages_handler` (single-repo only).

- [ ] Run and expect PASS:
  `pytest tests/test_commands/test_footguns_cli.py::TestSetTopicsConfirmation -q`
  Expected: `5 passed`.

- [ ] Add a smoke test that every set-* handler accepts `--yes` (covers the four handlers not driven above plus set-pages). Append to the test file:

```python
class TestYesFlagAccepted:
    @pytest.mark.parametrize('handler_name', [
        'set_topics_handler',
        'set_description_handler',
        'set_archived_handler',
        'set_visibility_handler',
        'set_default_branch_handler',
        'set_pages_handler',
    ])
    def test_handler_has_yes_param(self, handler_name):
        import repoindex.commands.ops as ops_mod

        handler = getattr(ops_mod, handler_name)
        params = [p.name for p in handler.params]
        assert 'yes' in params
```

- [ ] Run and expect PASS:
  `pytest tests/test_commands/test_footguns_cli.py::TestYesFlagAccepted -q`
  Expected: `6 passed`.

### Task 7: run group suite, confirm no regressions, commit

**Files**
- Test paths: `tests/test_commands/test_footguns_cli.py`, `tests/test_ops.py`, `tests/test_commands/test_set_actions.py`

Steps:

- [ ] Run the new file plus the two suites most likely affected:
  `pytest tests/test_commands/test_footguns_cli.py tests/test_ops.py tests/test_commands/test_set_actions.py -q`
  Expected: all pass. The new file contributes 26 tests (1 + 3 + 1 + 1 + 7 + 5 + 6 across Tasks 1-6) and the 115 existing tests stay green: the existing set-* tests never trip the gate because `CliRunner` is non-tty, and their cases are single-repo, `--dry-run`, or `--json`.

- [ ] Run the full suite to confirm baseline plus new tests are green:
  `pytest -q`
  Expected: the 1848-test baseline plus the new tests, all passing (e.g. `1874 passed`), no failures or errors.

- [ ] Commit the group:

```bash
git add repoindex/commands/ops.py tests/test_commands/test_footguns_cli.py
git commit -m "$(cat <<'EOF'
fix(cli): reject dead positional query and gate bulk set-* with confirm

The removed-DSL positional query_string was silently ignored, so a stale
expression like `ops git push "language=='Python'"` acted on the whole
collection. Raise a clear migration error from _get_repos_from_query
(covers all 13 handlers, including wip-snapshot's direct call) and scrub
the misleading DSL examples from the docstrings.

Add --yes/-y plus a click.confirm gate to the six ops set-* handlers,
fired only for an interactive bulk mutation (N>1, not --dry-run, not
--json, stdout is a TTY, --yes absent) so scripted, piped, single-repo,
and preview runs never hang.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

  Expected: one commit created on the current branch.

---

## Commit group: footguns-timespec

This group creates `repoindex/services/timespec.py` with the unified `parse_since(spec, now=None) -> datetime` per the shared contract (tokens: `s`/`sec`=seconds, `min`=minutes, `h`=hours, `d`=days, `w`=weeks, `m`/`M`=months, `y`=years; raises `ValueError` on invalid input; no silent default), then routes all four existing duration parsers through it.

Current state established by reading the code:
- `repoindex/events/__init__.py:199` `parse_timespec` (m=minutes, M=months, h, d, w; raises on invalid). Consumed by `commands/digest.py:302`, `services/event_service.py:122`.
- `repoindex/commands/events.py:17` `_parse_since` (d, h, w, m=minutes; silent default 7d).
- `repoindex/commands/refresh.py:679` `_parse_since` (d, w, m=months*30, y=years*365; silent default 90d).
- `repoindex/services/flag_query.py:51` `_parse_recent_duration` (d, w, m=months*30, y, h; silent default 30d).
- All four return the cutoff datetime (`now - duration`), so the shared `parse_since` return shape matches every caller directly. No timedelta/SQL helper is needed.
- Existing matrix tests for the old `parse_timespec` live in `tests/test_events.py:26` (`class TestParseTimespec`), notably `test_parse_minutes` asserts `30m` is minutes (must be re-pointed) and `test_parse_months` asserts `1M`.
- No `CHANGELOG.md` exists yet.

All four callers keep their public names and signatures (STABILITY: additive only); their bodies delegate to the new module. `parse_timespec` stays exported from `repoindex.events` as a thin wrapper so external importers keep working.

### Task 1: Create timespec module with full token matrix tests

Files:
- Create: `/home/spinoza/github/beta/repoindex/repoindex/services/timespec.py`
- Test: `/home/spinoza/github/beta/repoindex/tests/test_timespec.py` (create)

Steps:

- [ ] Write the failing test file. Create `/home/spinoza/github/beta/repoindex/tests/test_timespec.py` with:
  ```python
  """Tests for the unified duration parser in repoindex.services.timespec."""

  import pytest
  from datetime import datetime, timedelta

  from repoindex.services.timespec import parse_since


  FIXED_NOW = datetime(2026, 6, 4, 12, 0, 0)


  class TestParseSinceRelative:
      """Relative duration tokens resolve to now minus the duration."""

      def test_seconds_s(self):
          assert parse_since("30s", now=FIXED_NOW) == FIXED_NOW - timedelta(seconds=30)

      def test_seconds_sec(self):
          assert parse_since("30sec", now=FIXED_NOW) == FIXED_NOW - timedelta(seconds=30)

      def test_minutes_min(self):
          assert parse_since("15min", now=FIXED_NOW) == FIXED_NOW - timedelta(minutes=15)

      def test_hours_h(self):
          assert parse_since("24h", now=FIXED_NOW) == FIXED_NOW - timedelta(hours=24)

      def test_days_d(self):
          assert parse_since("7d", now=FIXED_NOW) == FIXED_NOW - timedelta(days=7)

      def test_weeks_w(self):
          assert parse_since("2w", now=FIXED_NOW) == FIXED_NOW - timedelta(weeks=2)

      def test_months_m_lower(self):
          # 'm' is MONTHS (not minutes): 6 months == 6 * 30 days.
          assert parse_since("6m", now=FIXED_NOW) == FIXED_NOW - timedelta(days=6 * 30)

      def test_months_M_alias(self):
          assert parse_since("6M", now=FIXED_NOW) == FIXED_NOW - timedelta(days=6 * 30)

      def test_years_y(self):
          assert parse_since("1y", now=FIXED_NOW) == FIXED_NOW - timedelta(days=365)

      def test_whitespace_and_quotes_stripped(self):
          assert parse_since("  '7d'  ", now=FIXED_NOW) == FIXED_NOW - timedelta(days=7)


  class TestParseSinceAbsolute:
      """ISO dates and datetimes parse to themselves."""

      def test_iso_date(self):
          result = parse_since("2024-01-15", now=FIXED_NOW)
          assert (result.year, result.month, result.day) == (2024, 1, 15)

      def test_iso_datetime(self):
          result = parse_since("2024-01-15T10:30:00", now=FIXED_NOW)
          assert (result.year, result.month, result.day) == (2024, 1, 15)
          assert (result.hour, result.minute) == (10, 30)


  class TestParseSinceInvalid:
      """Invalid input raises ValueError: no silent default."""

      @pytest.mark.parametrize("spec", ["", "   ", "invalid", "abc123", "7x", "d", "1.5d"])
      def test_raises(self, spec):
          with pytest.raises(ValueError):
              parse_since(spec, now=FIXED_NOW)


  class TestParseSinceDefaultNow:
      """now defaults to datetime.now() when omitted."""

      def test_now_defaults(self):
          before = datetime.now()
          result = parse_since("1d")
          after = datetime.now()
          assert before - timedelta(days=1, seconds=1) <= result <= after - timedelta(days=1) + timedelta(seconds=1)
  ```

- [ ] Run the test and expect failure (module does not exist yet):
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_timespec.py -q 2>&1 | tail -5
  ```
  Expected: collection error `ModuleNotFoundError: No module named 'repoindex.services.timespec'` (FAIL).

- [ ] Implement the module. Create `/home/spinoza/github/beta/repoindex/repoindex/services/timespec.py` with:
  ```python
  """Unified duration / timestamp parser for repoindex.

  Single source of truth for the ``--since`` / ``--recent`` style strings used by
  events, digest, refresh, and the flag-query builder. Returns the cutoff
  datetime (now minus the parsed duration), or the parsed absolute datetime for
  ISO inputs.

  Token semantics (locked, v2.1):
      s, sec   seconds
      min      minutes
      h        hours
      d        days
      w        weeks
      m, M     months (approximated as 30 days)
      y        years  (approximated as 365 days)

  Note: ``m`` means MONTHS (not minutes); use ``min`` for minutes. Invalid input
  raises ``ValueError`` with no silent fallback.
  """

  import re
  from datetime import datetime, timedelta
  from typing import Optional

  # Order matters: longer suffixes ('sec', 'min') are matched before single
  # letters so '30sec' is seconds and '15min' is minutes.
  _RELATIVE_RE = re.compile(r"^(\d+)\s*(sec|min|s|h|d|w|m|M|y)$")

  _UNIT_TO_TIMEDELTA = {
      "s": lambda n: timedelta(seconds=n),
      "sec": lambda n: timedelta(seconds=n),
      "min": lambda n: timedelta(minutes=n),
      "h": lambda n: timedelta(hours=n),
      "d": lambda n: timedelta(days=n),
      "w": lambda n: timedelta(weeks=n),
      "m": lambda n: timedelta(days=n * 30),
      "M": lambda n: timedelta(days=n * 30),
      "y": lambda n: timedelta(days=n * 365),
  }


  def parse_since(spec: str, now: Optional[datetime] = None) -> datetime:
      """Parse a duration or ISO timestamp into a cutoff datetime.

      Args:
          spec: A relative duration ('7d', '6m', '15min', '24h', '1y') or an ISO
              date / datetime ('2024-01-15', '2024-01-15T10:30:00').
          now: Reference time for relative durations. Defaults to ``datetime.now()``.

      Returns:
          For a relative duration, ``now - duration``. For an ISO input, the
          parsed datetime.

      Raises:
          ValueError: If ``spec`` is empty or cannot be parsed. There is no
              silent default.
      """
      if now is None:
          now = datetime.now()

      if spec is None:
          raise ValueError("Cannot parse empty time specification")

      s = spec.strip().strip("'\"")
      if not s:
          raise ValueError("Cannot parse empty time specification")

      match = _RELATIVE_RE.match(s)
      if match:
          amount = int(match.group(1))
          unit = match.group(2)
          return now - _UNIT_TO_TIMEDELTA[unit](amount)

      # Absolute ISO datetime (handles both date and datetime forms).
      try:
          return datetime.fromisoformat(s)
      except ValueError:
          pass

      try:
          return datetime.strptime(s, "%Y-%m-%d")
      except ValueError:
          pass

      raise ValueError(f"Cannot parse time specification: {spec}")
  ```

- [ ] Run the test and expect pass:
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_timespec.py -q 2>&1 | tail -5
  ```
  Expected: all timespec tests pass (e.g. `23 passed`), no failures.

### Task 2: Route `events.parse_timespec` through timespec and re-point its matrix tests

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/events/__init__.py` (`parse_timespec`, lines 199-247)
- Modify: `/home/spinoza/github/beta/repoindex/tests/test_events.py` (`class TestParseTimespec`, lines 26-95)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_events.py`

Steps:

- [ ] Re-point the existing matrix tests to the new month semantics. In `/home/spinoza/github/beta/repoindex/tests/test_events.py`, replace the `test_parse_minutes` method (lines 55-59) with an explicit `min`-token test and update `test_parse_months`. Replace:
  ```python
      def test_parse_minutes(self):
          """Test parsing minute specifications."""
          result = parse_timespec('30m')
          expected = datetime.now() - timedelta(minutes=30)
          assert abs((result - expected).total_seconds()) < 1

      def test_parse_months(self):
          """Test parsing month specifications (approximate)."""
          result = parse_timespec('1M')
          expected = datetime.now() - timedelta(days=30)
          assert abs((result - expected).total_seconds()) < 1
  ```
  with:
  ```python
      def test_parse_minutes(self):
          """'min' parses as minutes ('m' is now months)."""
          result = parse_timespec('30min')
          expected = datetime.now() - timedelta(minutes=30)
          assert abs((result - expected).total_seconds()) < 1

      def test_parse_months_lower(self):
          """'m' now means months (six months ~= 180 days)."""
          result = parse_timespec('6m')
          expected = datetime.now() - timedelta(days=6 * 30)
          assert abs((result - expected).total_seconds()) < 1

      def test_parse_months(self):
          """'M' is the months alias."""
          result = parse_timespec('1M')
          expected = datetime.now() - timedelta(days=30)
          assert abs((result - expected).total_seconds()) < 1
  ```

- [ ] Run those tests and expect failure (old body still treats `m` as minutes and rejects `min`):
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest "tests/test_events.py::TestParseTimespec" -q 2>&1 | tail -8
  ```
  Expected: `test_parse_minutes` and `test_parse_months_lower` FAIL (`min` raises / `6m` resolves to minutes, not 180 days).

- [ ] Route `parse_timespec` through the new module. In `/home/spinoza/github/beta/repoindex/repoindex/events/__init__.py`, replace the body of `parse_timespec` (lines 217-247, from `spec = spec.strip()` through the final `raise`) with a delegation, and update the docstring units line. Replace:
  ```python
      spec = spec.strip()

      # Try relative time (e.g., "1h", "2d", "7d", "30m", "1w")
      relative_match = re.match(r'^(\d+)([mhdwM])$', spec)
      if relative_match:
          amount = int(relative_match.group(1))
          unit = relative_match.group(2)

          units = {
              'm': timedelta(minutes=amount),
              'h': timedelta(hours=amount),
              'd': timedelta(days=amount),
              'w': timedelta(weeks=amount),
              'M': timedelta(days=amount * 30),  # Approximate month
          }

          return datetime.now() - units[unit]

      # Try ISO format with time
      try:
          return datetime.fromisoformat(spec)
      except ValueError:
          pass

      # Try date only (YYYY-MM-DD)
      try:
          return datetime.strptime(spec, '%Y-%m-%d')
      except ValueError:
          pass

      raise ValueError(f"Cannot parse time specification: {spec}")
  ```
  with:
  ```python
      from ..services.timespec import parse_since
      return parse_since(spec)
  ```
  Also update the docstring `Supports:` block (lines 203-206) to read:
  ```python
      Supports:
          - Relative: "1h", "2d", "7d", "1w", "6m" (months), "15min", "1y"
          - ISO format: "2024-01-15", "2024-01-15T10:30:00"

      Note: "m" means MONTHS; use "min" for minutes. See services.timespec.
  ```

- [ ] Run the matrix tests and the full events suite and expect pass:
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_events.py -q 2>&1 | tail -5
  ```
  Expected: all `tests/test_events.py` tests pass (no failures).

### Task 3: Route `commands/events._parse_since` through timespec (preserve empty-default for `--until`)

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/commands/events.py` (`_parse_since`, lines 17-40; call sites lines 92-93)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_events_command.py` (create)

Note: `_parse_since` is called twice (line 92 with the `--since` value, default `'7d'`; line 93 only when `until` is truthy). To preserve the no-arg default behavior (`--since` default already comes from Click as `'7d'`), keep the empty-string short-circuit returning the 7d cutoff so an explicit empty string does not crash, but route everything else through `parse_since` (which now raises on truly invalid input instead of silently returning 7d).

Steps:

- [ ] Write the failing test. Create `/home/spinoza/github/beta/repoindex/tests/test_events_command.py` with:
  ```python
  """Tests for the events command's _parse_since delegation."""

  import pytest
  from datetime import datetime, timedelta

  from repoindex.commands.events import _parse_since


  def test_days_token():
      result = _parse_since("7d")
      expected = datetime.now() - timedelta(days=7)
      assert abs((result - expected).total_seconds()) < 2


  def test_m_is_months_now():
      # Previously 'm' meant minutes here; it now means months.
      result = _parse_since("6m")
      expected = datetime.now() - timedelta(days=6 * 30)
      assert abs((result - expected).total_seconds()) < 2


  def test_min_is_minutes():
      result = _parse_since("15min")
      expected = datetime.now() - timedelta(minutes=15)
      assert abs((result - expected).total_seconds()) < 2


  def test_invalid_raises():
      with pytest.raises(ValueError):
          _parse_since("nonsense")
  ```

- [ ] Run and expect failure (old body treats `m` as minutes, rejects `min`, and swallows invalid into a 7d default):
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_events_command.py -q 2>&1 | tail -8
  ```
  Expected: `test_m_is_months_now`, `test_min_is_minutes`, `test_invalid_raises` FAIL.

- [ ] Route through the new module. In `/home/spinoza/github/beta/repoindex/repoindex/commands/events.py`, replace the `_parse_since` body (lines 18-40) with:
  ```python
      """Parse a --since value into a cutoff datetime via the shared parser."""
      from ..services.timespec import parse_since
      if not since_str:
          return datetime.now() - timedelta(days=7)
      return parse_since(since_str)
  ```

- [ ] Run and expect pass:
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_events_command.py -q 2>&1 | tail -5
  ```
  Expected: all 4 tests pass.

### Task 4: Route `commands/refresh._parse_since` through timespec

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/commands/refresh.py` (`_parse_since`, lines 679-704)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_refresh_since.py` (create)

Note: `--since` default is `'90d'` (line 123), supplied by Click, so the old silent 90d fallback inside the parser was only reachable on garbage input. Routing through `parse_since` makes garbage raise instead, which is the locked behavior.

Steps:

- [ ] Write the failing test. Create `/home/spinoza/github/beta/repoindex/tests/test_refresh_since.py` with:
  ```python
  """Tests for the refresh command's _parse_since delegation."""

  import pytest
  from datetime import datetime, timedelta

  from repoindex.commands.refresh import _parse_since


  def test_days_token():
      result = _parse_since("30d")
      expected = datetime.now() - timedelta(days=30)
      assert abs((result - expected).total_seconds()) < 2


  def test_months_token():
      result = _parse_since("6m")
      expected = datetime.now() - timedelta(days=6 * 30)
      assert abs((result - expected).total_seconds()) < 2


  def test_years_token():
      result = _parse_since("1y")
      expected = datetime.now() - timedelta(days=365)
      assert abs((result - expected).total_seconds()) < 2


  def test_invalid_raises():
      # Previously fell back silently to 90 days; now raises.
      with pytest.raises(ValueError):
          _parse_since("garbage")
  ```

- [ ] Run and expect failure (old body silently returns a 90d cutoff for `"garbage"`):
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_refresh_since.py -q 2>&1 | tail -8
  ```
  Expected: `test_invalid_raises` FAILS (no exception raised); the others pass since `m`/`y` semantics already match.

- [ ] Route through the new module. In `/home/spinoza/github/beta/repoindex/repoindex/commands/refresh.py`, replace the entire `_parse_since` function body (lines 680-704, from the docstring through the final `return now - timedelta(days=90)`) with:
  ```python
      """Parse a since string ('7d', '30d', '6m', '1y', ISO date) into a datetime."""
      from ..services.timespec import parse_since
      return parse_since(since_str)
  ```
  (The local `from datetime import timedelta` import at line 681 and the `now = datetime.now()` line are removed as part of this replacement; `datetime` remains imported at module level, line 14.)

- [ ] Run and expect pass:
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_refresh_since.py -q 2>&1 | tail -5
  ```
  Expected: all 4 tests pass.

### Task 5: Route `flag_query._parse_recent_duration` through timespec

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/services/flag_query.py` (`_parse_recent_duration`, lines 51-90; module docstring line 15)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_flag_query_recent.py` (create)

Note: `--recent` has no Click default that protects the parser, so this parser's silent 30d fallback was reachable from user input. Routing through `parse_since` makes invalid `--recent` raise. The contract value matches: callers consume the returned cutoff datetime as `.isoformat()` (line 148), unchanged.

Steps:

- [ ] Write the failing test. Create `/home/spinoza/github/beta/repoindex/tests/test_flag_query_recent.py` with:
  ```python
  """Tests for flag_query._parse_recent_duration delegation."""

  import pytest
  from datetime import datetime, timedelta

  from repoindex.services.flag_query import _parse_recent_duration


  def test_days():
      result = _parse_recent_duration("14d")
      expected = datetime.now() - timedelta(days=14)
      assert abs((result - expected).total_seconds()) < 2


  def test_hours():
      result = _parse_recent_duration("12h")
      expected = datetime.now() - timedelta(hours=12)
      assert abs((result - expected).total_seconds()) < 2


  def test_months():
      result = _parse_recent_duration("3m")
      expected = datetime.now() - timedelta(days=3 * 30)
      assert abs((result - expected).total_seconds()) < 2


  def test_quoted_value_stripped():
      result = _parse_recent_duration("'7d'")
      expected = datetime.now() - timedelta(days=7)
      assert abs((result - expected).total_seconds()) < 2


  def test_invalid_raises():
      # Previously fell back silently to 30 days; now raises.
      with pytest.raises(ValueError):
          _parse_recent_duration("not-a-duration")
  ```

- [ ] Run and expect failure (old body silently returns a 30d cutoff for invalid input):
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_flag_query_recent.py -q 2>&1 | tail -8
  ```
  Expected: `test_invalid_raises` FAILS (no exception); other tokens already match so they pass.

- [ ] Route through the new module. In `/home/spinoza/github/beta/repoindex/repoindex/services/flag_query.py`, replace the entire `_parse_recent_duration` function body (lines 52-90, docstring through the final `return now - timedelta(days=30)`) with:
  ```python
      """Parse a duration string ('30d', '2w', '3m' months, '1y', ISO date) into a cutoff datetime.

      Delegates to services.timespec.parse_since (the single duration parser).
      Raises ValueError on unparseable input: there is no silent default.
      """
      from .timespec import parse_since
      return parse_since(recent)
  ```

- [ ] Run the new test and the existing flag-query tests, expect pass:
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest tests/test_flag_query_recent.py tests/test_flag_query.py -q 2>&1 | tail -6
  ```
  Expected: all pass (`tests/test_flag_query.py` may not exist; if so the command reports it skipped/not-found and the recent tests pass with no failures).

### Task 6: Full suite green, CHANGELOG note, and commit

Files:
- Create: `/home/spinoza/github/beta/repoindex/CHANGELOG.md`
- Test: full suite

Steps:

- [ ] Run the full suite and confirm no regressions from the routed parsers:
  ```bash
  cd /home/spinoza/github/beta/repoindex && .venv/bin/pytest -q 2>&1 | tail -8
  ```
  Expected: green (baseline 1848 plus the new timespec / events_command / refresh_since / flag_query_recent tests), no failures. If any test elsewhere asserted the old `m`=minutes or silent-default behavior, it surfaces here and must be re-pointed to the new semantics before committing.

- [ ] Create the CHANGELOG note. Create `/home/spinoza/github/beta/repoindex/CHANGELOG.md` with:
  ```markdown
  # Changelog

  All notable changes to repoindex are documented here.

  ## Unreleased

  ### Changed (behavior)

  - Duration tokens are now parsed by a single shared parser
    (`repoindex/services/timespec.py`, `parse_since`). The token `m` now means
    MONTHS everywhere; use `min` for minutes. This silently changes
    `repoindex events --since 6m` and `repoindex digest --since 6m` from six
    minutes to six months. Supported tokens: `s`/`sec` (seconds), `min`
    (minutes), `h` (hours), `d` (days), `w` (weeks), `m`/`M` (months, approximated
    as 30 days), `y` (years, approximated as 365 days).
  - Invalid duration strings now raise an error instead of silently falling back
    to a default window (the old `events` 7d, `refresh` 90d, and `--recent` 30d
    silent fallbacks were footguns). Click option defaults (`events --since 7d`,
    `refresh --since 90d`, `digest --since 7d`) are unchanged.
  ```

- [ ] Verify the CHANGELOG renders as intended (sanity grep for the months note):
  ```bash
  cd /home/spinoza/github/beta/repoindex && grep -c "now means" CHANGELOG.md || grep -c "MONTHS" CHANGELOG.md
  ```
  Expected: a count of at least 1 (the months-semantics line is present).

- [ ] Stage and commit the group as one commit:
  ```bash
  cd /home/spinoza/github/beta/repoindex && git add repoindex/services/timespec.py repoindex/events/__init__.py repoindex/commands/events.py repoindex/commands/refresh.py repoindex/services/flag_query.py tests/test_timespec.py tests/test_events.py tests/test_events_command.py tests/test_refresh_since.py tests/test_flag_query_recent.py CHANGELOG.md && git commit -m "$(cat <<'EOF'
  footguns(timespec): unify duration parsing, m means months

  Create repoindex/services/timespec.py with parse_since as the single
  duration parser. Tokens: s/sec, min, h, d, w, m/M (months), y. The token
  m now means MONTHS everywhere (use min for minutes), and invalid input
  raises ValueError instead of silently defaulting.

  Route all four prior parsers through it: events.parse_timespec,
  commands/events._parse_since, commands/refresh._parse_since, and
  flag_query._parse_recent_duration. Re-point the events matrix tests and
  add tests/test_timespec.py plus per-caller delegation tests.

  events --since 6m and digest --since 6m now mean six months, not six
  minutes (CHANGELOG entry added).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```
  Expected: one commit created containing the new module, the four routed parsers, the test files, and `CHANGELOG.md`.

---

## Commit group: footguns-data

Populate the `readme_content` column (FTS-indexed and trigger-wired in `SCHEMA_V1`, but never written) during the upsert path so `repos_fts` MATCH, the audit readme check, and the arkiv export readme body all activate. The column read is added in `repoindex/database/repository.py` `_repo_to_record()` immediately after the existing README detection block (lines 122-126 today, which sets `has_readme` from the candidate list `['README.md', 'README.rst', 'README.txt', 'README']`). We cap the stored body at 100 KB to bound memory and DB size.

### Task 1: Define the README cap constant and a truncated-read helper in `repository.py`

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/database/repository.py` (add module constant after imports near line 16; add helper function before `_repo_to_record` at line 56)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_database.py`

Steps:

- [ ] Add a failing test for the helper. Append this class to the end of `/home/spinoza/github/beta/repoindex/tests/test_database.py`:
```python
class TestReadReadmeContent(unittest.TestCase):
    """Tests for the truncated README reader used during upsert."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_readme_returns_none(self):
        from repoindex.database.repository import _read_readme_content
        self.assertIsNone(_read_readme_content(self.repo_path))

    def test_reads_readme_md_first(self):
        from repoindex.database.repository import _read_readme_content
        (self.repo_path / 'README.md').write_text('# Hello world\n')
        self.assertEqual(_read_readme_content(self.repo_path), '# Hello world\n')

    def test_prefers_md_over_plain_readme(self):
        from repoindex.database.repository import _read_readme_content
        (self.repo_path / 'README.md').write_text('markdown body')
        (self.repo_path / 'README').write_text('plain body')
        self.assertEqual(_read_readme_content(self.repo_path), 'markdown body')

    def test_oversized_readme_truncated_at_cap(self):
        from repoindex.database.repository import _read_readme_content, README_CONTENT_CAP
        big = 'x' * (README_CONTENT_CAP + 5000)
        (self.repo_path / 'README.md').write_text(big)
        content = _read_readme_content(self.repo_path)
        self.assertEqual(len(content), README_CONTENT_CAP)
        self.assertEqual(content, 'x' * README_CONTENT_CAP)

    def test_cap_is_100kb(self):
        from repoindex.database.repository import README_CONTENT_CAP
        self.assertEqual(README_CONTENT_CAP, 100 * 1024)

    def test_unreadable_readme_returns_none(self):
        from repoindex.database.repository import _read_readme_content
        # A directory named README.md cannot be read as text; helper must not raise.
        (self.repo_path / 'README.md').mkdir()
        self.assertIsNone(_read_readme_content(self.repo_path))
```

- [ ] Run the test, expect FAIL (ImportError: `_read_readme_content` / `README_CONTENT_CAP` do not exist yet):
```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py::TestReadReadmeContent -v
```
Expected: collection or import error, all six tests ERROR/FAIL with `ImportError: cannot import name '_read_readme_content'`.

- [ ] Add the module constant. In `/home/spinoza/github/beta/repoindex/repoindex/database/repository.py`, after the import block (after line 15 `from .connection import Database`), insert:
```python


# README files, in preference order, checked for has_readme and read into
# readme_content for FTS. Mirrors the candidate list in _repo_to_record.
README_CANDIDATES = ('README.md', 'README.rst', 'README.txt', 'README')

# Cap on stored readme_content (bytes of text) to bound memory and DB size.
# The body feeds repos_fts (full-text search) and the arkiv export readme body.
README_CONTENT_CAP = 100 * 1024
```

- [ ] Add the helper function immediately before `def _repo_to_record` (currently line 56). Insert:
```python
def _read_readme_content(repo_path: Path) -> Optional[str]:
    """
    Read the repo's README into a truncated string for full-text indexing.

    Returns the first existing README (by README_CANDIDATES preference) read
    as UTF-8 (errors replaced), truncated to README_CONTENT_CAP characters.
    Returns None when no README exists or it cannot be read as text.
    """
    for filename in README_CANDIDATES:
        candidate = repo_path / filename
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding='utf-8', errors='replace')
        except (OSError, UnicodeError):
            return None
        return text[:README_CONTENT_CAP]
    return None


```

- [ ] Run the test, expect PASS:
```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py::TestReadReadmeContent -v
```
Expected: 6 passed.

### Task 2: Wire `readme_content` into the upsert record so FTS triggers propagate

Files:
- Modify: `/home/spinoza/github/beta/repoindex/repoindex/database/repository.py` (README detection block in `_repo_to_record`, lines 122-126)
- Test: `/home/spinoza/github/beta/repoindex/tests/test_database.py`

Steps:

- [ ] Add a failing test that exercises the full upsert path: non-NULL truncated content, FTS MATCH on README body, and oversized truncation through the DB. Append to the `TestReadReadmeContent` class in `/home/spinoza/github/beta/repoindex/tests/test_database.py`:
```python
    def test_upsert_populates_readme_content(self):
        from repoindex.database.repository import upsert_repo, get_repo_by_path
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r1'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        (repo_dir / 'README.md').write_text('# Photon Toolkit\nSupercalifragilistic indexer.\n')
        repo = Repository(path=str(repo_dir), name='r1')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(repo_dir))
        self.assertIsNotNone(record['readme_content'])
        self.assertIn('Supercalifragilistic', record['readme_content'])

    def test_upsert_no_readme_leaves_content_null(self):
        from repoindex.database.repository import upsert_repo, get_repo_by_path
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r2'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        repo = Repository(path=str(repo_dir), name='r2')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(repo_dir))
        self.assertIsNone(record['readme_content'])

    def test_fts_match_on_readme_body_returns_repo(self):
        from repoindex.database.repository import upsert_repo
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r3'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        (repo_dir / 'README.md').write_text('quokkacore is a wombat indexer\n')
        repo = Repository(path=str(repo_dir), name='r3')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            db.execute(
                "SELECT r.name FROM repos r "
                "JOIN repos_fts fts ON fts.rowid = r.id "
                "WHERE repos_fts MATCH ?",
                ('quokkacore',),
            )
            rows = db.fetchall()
        self.assertEqual([row['name'] for row in rows], ['r3'])

    def test_upsert_truncates_oversized_readme_in_db(self):
        from repoindex.database.repository import (
            upsert_repo, get_repo_by_path, README_CONTENT_CAP,
        )
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r4'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        (repo_dir / 'README.md').write_text('y' * (README_CONTENT_CAP + 4096))
        repo = Repository(path=str(repo_dir), name='r4')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(repo_dir))
        self.assertEqual(len(record['readme_content']), README_CONTENT_CAP)
```

- [ ] Run the new tests, expect FAIL (`readme_content` is still always NULL, so the non-NULL, FTS MATCH, and truncation assertions fail):
```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest "tests/test_database.py::TestReadReadmeContent::test_upsert_populates_readme_content" "tests/test_database.py::TestReadReadmeContent::test_fts_match_on_readme_body_returns_repo" "tests/test_database.py::TestReadReadmeContent::test_upsert_truncates_oversized_readme_in_db" -v
```
Expected: 3 failed (`test_upsert_no_readme_leaves_content_null` already passes since the column defaults to NULL). Failures are `AssertionError: ... is not None` and FTS returning `[]`.

- [ ] Implement the wiring. In `/home/spinoza/github/beta/repoindex/repoindex/database/repository.py`, replace the README detection block:
```python
    # Check for common files
    repo_path = Path(repo.path)
    record['has_readme'] = any(
        (repo_path / f).exists()
        for f in ['README.md', 'README.rst', 'README.txt', 'README']
    )
```
with:
```python
    # Check for common files
    repo_path = Path(repo.path)
    record['has_readme'] = any(
        (repo_path / f).exists()
        for f in README_CANDIDATES
    )
    # Read README body into readme_content so the repos_fts triggers index it.
    # Truncated to README_CONTENT_CAP; None when no README is present.
    record['readme_content'] = _read_readme_content(repo_path)
```

- [ ] Run the upsert tests, expect PASS:
```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py::TestReadReadmeContent -v
```
Expected: 10 passed.

### Task 3: Confirm the arkiv exporter emits the README body now that the column is populated

Files:
- Test: `/home/spinoza/github/beta/repoindex/tests/test_database.py`

The arkiv exporter at `/home/spinoza/github/beta/repoindex/repoindex/exporters/arkiv.py` (lines 63-65) already does `readme = repo.get('readme_content'); if readme: meta['readme'] = readme`. No exporter code change is needed; this task pins that the populated column flows into the exporter's per-repo metadata via the exporter's own record-to-metadata function.

Steps:

- [ ] Confirm the exporter's record-to-metadata function name (it builds `meta['readme']`):
```
cd /home/spinoza/github/beta/repoindex && grep -n "^def \|readme_content\|meta\['readme'\]" repoindex/exporters/arkiv.py | head
```
Expected: shows the function that contains lines 62-65 (the `_repo_to_record`-style builder in arkiv) and the `meta['readme'] = readme` assignment. Use the function name reported here in the test below (it is the module-level function whose body spans line 63).

- [ ] Add a failing test that drives a real upserted record through the arkiv metadata builder. Append to the `TestReadReadmeContent` class in `/home/spinoza/github/beta/repoindex/tests/test_database.py`:
```python
    def test_arkiv_export_emits_readme_body(self):
        from repoindex.database.repository import upsert_repo, get_repo_by_path
        from repoindex.database.connection import Database
        from repoindex.domain.repository import Repository
        from repoindex.exporters import arkiv as arkiv_mod
        db_path = self.repo_path / 'idx.db'
        repo_dir = self.repo_path / 'r5'
        repo_dir.mkdir()
        (repo_dir / '.git').mkdir()
        (repo_dir / 'README.md').write_text('# Narwhal\nA tusked indexer.\n')
        repo = Repository(path=str(repo_dir), name='r5')
        with Database(db_path=db_path) as db:
            upsert_repo(db, repo)
            record = get_repo_by_path(db, str(repo_dir))
        builder = getattr(arkiv_mod, '_repo_to_arkiv_record', None) \
            or arkiv_mod._repo_to_record
        arkiv_record = builder(record)
        self.assertEqual(
            arkiv_record['metadata']['readme'],
            '# Narwhal\nA tusked indexer.\n',
        )
```
Note: replace the `builder = ...` line with the exact function name reported by the grep step above if it differs from both `_repo_to_arkiv_record` and `_repo_to_record`.

- [ ] Run the test, expect PASS (no production change needed; this is a confirmation test that the data fix activates the export body):
```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest "tests/test_database.py::TestReadReadmeContent::test_arkiv_export_emits_readme_body" -v
```
Expected: 1 passed. If it instead fails with `KeyError: 'readme'`, that means the prior wiring task is not in effect; re-run Task 2's implementation step. If it fails on the `builder` lookup, correct the function name per the grep output.

### Task 4: Full-suite regression check and commit

Files:
- (no new files)

Steps:

- [ ] Run the affected test file in full to confirm no regression in database tests:
```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest tests/test_database.py -q
```
Expected: all pass (the prior database tests plus the 11 new `TestReadReadmeContent` tests).

- [ ] Run the whole suite to confirm the baseline holds (1848 baseline plus this group's new tests; no failures):
```
cd /home/spinoza/github/beta/repoindex && .venv/bin/python -m pytest -q
```
Expected: 0 failed; passing count is the baseline plus the new tests added by this and earlier groups.

- [ ] Commit the group (single commit, last step of the group):
```
cd /home/spinoza/github/beta/repoindex && git add repoindex/database/repository.py tests/test_database.py && git commit -m "$(cat <<'EOF'
footguns(data): populate readme_content for FTS, audit, and arkiv export

readme_content is indexed in repos_fts and trigger-wired but was never
written, so full-text README search, the audit readme check, and the
arkiv export readme body were all dead. Read the repo's README (first of
README.md/.rst/.txt/README) into the upsert record, capped at 100 KB
(README_CONTENT_CAP) to bound memory and DB size. The FTS triggers
propagate the body automatically.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: one commit created on the current branch.

Notes for the assembler:
- This group touches only `repoindex/database/repository.py` (additive: new module constants `README_CANDIDATES`, `README_CONTENT_CAP`, new private helper `_read_readme_content`, and one new key in the upsert record dict). No signatures removed/renamed/retyped, so STABILITY.md is respected.
- No schema change is needed: `readme_content` and the `repos_fts` triggers already exist in `SCHEMA_V1` (schema.py lines 63, 228-252). The schema v10 bump is owned by group 3 and is independent of this group.
- No arkiv exporter code change is needed; lines 63-65 already emit `meta['readme']` from `readme_content`. Task 3 is a confirmation test only. The exact arkiv builder function name must be taken from the grep step in Task 3.

---

## Commit group: packaging

This group makes the package metadata honest: drops the abandoned `pathlib` backport and the unused `tweepy` dependency, sets the Python floor to `>=3.10`, adds per-version trove classifiers, deletes the drift-prone `requirements.txt` (rewiring `make install` to the `dev` extra), syncs the stale `0.10.1` version in `CITATION.cff` and `codemeta.json` up to the current `pyproject` version `2.0.0` (and `codemeta` `dateModified` / `releaseNotes` / `softwareRequirements`), adds a CI matrix workflow (3.10/3.11/3.12), and adds `tests/test_version_consistency.py` so the four version sources can never drift again. `toml` stays (it is the TOML writer at `repoindex/infra/pypi_metadata.py:636`). Stale `dist/` artifacts are deleted as a local cleanup (`dist/` is gitignored, so this is not part of the commit).

Confirmed against the real tree: `grep -rn "tweepy"` over `*.py` returns no `import tweepy` (unused, safe to remove). `requirements.txt` is consumed only by the Makefile `install` target (line 21); all in-code `requirements.txt` strings are the events feature detecting *other repos'* dependency files, not consuming this project's own file.

### Task 1: Add the version-consistency test (failing first)

The test reads each of the four version sources and asserts equality. It will FAIL initially because `CITATION.cff` and `codemeta.json` are still at `0.10.1` while `pyproject.toml` and `repoindex.__version__` are `2.0.0`.

**Files**
- Create: `tests/test_version_consistency.py`
- Test path: `tests/test_version_consistency.py`

Steps:

- [ ] Write the test file `tests/test_version_consistency.py` with this exact content:

```python
"""Tests that all four version sources agree.

Guards against the drift class where pyproject.toml / repoindex.__version__ /
CITATION.cff / codemeta.json fall out of sync (they were stuck at 0.10.1 while
the package shipped 2.0.0).
"""

import json
import re
from pathlib import Path

import yaml

import repoindex
from repoindex.compat import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def _citation_version() -> str:
    with open(REPO_ROOT / "CITATION.cff", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return str(data["version"])


def _codemeta_version() -> str:
    with open(REPO_ROOT / "codemeta.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return str(data["version"])


def test_pyproject_matches_dunder_version():
    assert _pyproject_version() == repoindex.__version__


def test_citation_matches_pyproject():
    assert _citation_version() == _pyproject_version()


def test_codemeta_matches_pyproject():
    assert _codemeta_version() == _pyproject_version()


def test_all_four_versions_agree():
    versions = {
        "pyproject": _pyproject_version(),
        "__version__": repoindex.__version__,
        "CITATION.cff": _citation_version(),
        "codemeta.json": _codemeta_version(),
    }
    assert len(set(versions.values())) == 1, versions


def test_codemeta_release_notes_url_matches_version():
    with open(REPO_ROOT / "codemeta.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    version = data["version"]
    assert data["releaseNotes"].endswith(f"/v{version}")


def test_codemeta_date_modified_is_iso():
    with open(REPO_ROOT / "codemeta.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["dateModified"])
```

- [ ] Run the test and confirm it FAILS on the version-mismatch assertions:

```
.venv/bin/pytest tests/test_version_consistency.py -v
```

Expected: `test_citation_matches_pyproject`, `test_codemeta_matches_pyproject`, `test_all_four_versions_agree`, and `test_codemeta_release_notes_url_matches_version` FAIL (CITATION.cff and codemeta.json report `0.10.1` vs pyproject `2.0.0`; releaseNotes ends in `/v0.10.1`). `test_pyproject_matches_dunder_version` and `test_codemeta_date_modified_is_iso` PASS.

### Task 2: Sync `CITATION.cff` version to 2.0.0

**Files**
- Modify: `CITATION.cff` (line 4, `version: "0.10.1"`)
- Test path: `tests/test_version_consistency.py`

Steps:

- [ ] In `CITATION.cff`, replace the stale version line:

```yaml
version: "0.10.1"
```

with:

```yaml
version: "2.0.0"
```

- [ ] Run the citation portion and confirm it now PASSES:

```
.venv/bin/pytest tests/test_version_consistency.py::test_citation_matches_pyproject -v
```

Expected: `1 passed`.

### Task 3: Sync `codemeta.json` version, dateModified, releaseNotes, and Python requirement

**Files**
- Modify: `codemeta.json` (line `"version": "0.10.1"`, `"softwareRequirements": "Python >= 3.8"`, `"dateModified": "2026-01-25"`, `"releaseNotes": ".../tag/v0.10.1"`)
- Test path: `tests/test_version_consistency.py`

Steps:

- [ ] In `codemeta.json`, replace the version line:

```json
  "version": "0.10.1",
```

with:

```json
  "version": "2.0.0",
```

- [ ] In `codemeta.json`, replace the software requirement line:

```json
  "softwareRequirements": "Python >= 3.8",
```

with:

```json
  "softwareRequirements": "Python >= 3.10",
```

- [ ] In `codemeta.json`, replace the dateModified line:

```json
  "dateModified": "2026-01-25",
```

with:

```json
  "dateModified": "2026-06-04",
```

- [ ] In `codemeta.json`, replace the releaseNotes line:

```json
  "releaseNotes": "https://github.com/queelius/repoindex/releases/tag/v0.10.1"
```

with:

```json
  "releaseNotes": "https://github.com/queelius/repoindex/releases/tag/v2.0.0"
```

- [ ] Run the full version-consistency suite and confirm all PASS:

```
.venv/bin/pytest tests/test_version_consistency.py -v
```

Expected: `7 passed` (all version sources agree at `2.0.0`; releaseNotes ends in `/v2.0.0`; dateModified is ISO).

### Task 4: Drop `pathlib` and `tweepy`, set Python floor to >=3.10, add trove classifiers

**Files**
- Modify: `pyproject.toml` (line 11 `requires-python`, line 13 `classifiers`, line 14 `dependencies`)
- Test path: `tests/test_version_consistency.py` (new assertions on pyproject metadata)

Steps:

- [ ] Add three pyproject-metadata assertions to the END of `tests/test_version_consistency.py`:

```python
def test_pyproject_drops_pathlib_and_tweepy():
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    deps = data["project"]["dependencies"]
    joined = " ".join(deps)
    assert "pathlib" not in [d.split(">")[0].split("=")[0].strip() for d in deps]
    assert "tweepy" not in [d.split(">")[0].split("=")[0].strip() for d in deps]
    assert "toml" in [d.split(">")[0].split("=")[0].split(";")[0].strip() for d in deps], joined


def test_pyproject_requires_python_310():
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["requires-python"] == ">=3.10"


def test_pyproject_has_per_version_classifiers():
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    classifiers = data["project"]["classifiers"]
    for ver in ("3.10", "3.11", "3.12"):
        assert f"Programming Language :: Python :: {ver}" in classifiers, classifiers
```

- [ ] Run the new assertions and confirm they FAIL:

```
.venv/bin/pytest tests/test_version_consistency.py -k "pathlib or requires_python or classifiers" -v
```

Expected: `test_pyproject_drops_pathlib_and_tweepy` FAILS (`pathlib` and `tweepy` are still listed), `test_pyproject_requires_python_310` FAILS (`>=3.8`), `test_pyproject_has_per_version_classifiers` FAILS (no per-version trove classifiers).

- [ ] In `pyproject.toml`, replace the `requires-python` line:

```toml
requires-python = ">=3.8"
```

with:

```toml
requires-python = ">=3.10"
```

- [ ] In `pyproject.toml`, replace the classifiers line:

```toml
classifiers = [ "Development Status :: 4 - Beta", "Topic :: Software Development :: Version Control :: Git", "Operating System :: OS Independent", "Programming Language :: Python :: 3",]
```

with:

```toml
classifiers = [ "Development Status :: 4 - Beta", "Topic :: Software Development :: Version Control :: Git", "Operating System :: OS Independent", "Programming Language :: Python :: 3", "Programming Language :: Python :: 3.10", "Programming Language :: Python :: 3.11", "Programming Language :: Python :: 3.12",]
```

- [ ] In `pyproject.toml`, replace the dependencies line (removing `"pathlib"` and `"tweepy"`, keeping `"toml"` and all others):

```toml
dependencies = [ "pathlib", "toml", "requests>=2.25.0", "packaging>=21.0", "click>=8.0.0", "rich>=13.0.0", "tweepy", "rapidfuzz", "pyyaml>=5.0.0", "tomli>=1.1.0; python_version<\"3.11\"",]
```

with:

```toml
dependencies = [ "toml", "requests>=2.25.0", "packaging>=21.0", "click>=8.0.0", "rich>=13.0.0", "rapidfuzz", "pyyaml>=5.0.0", "tomli>=1.1.0; python_version<\"3.11\"",]
```

- [ ] Run the pyproject assertions and confirm they now PASS:

```
.venv/bin/pytest tests/test_version_consistency.py -k "pathlib or requires_python or classifiers" -v
```

Expected: `3 passed`.

### Task 5: Delete `requirements.txt` and rewire `make install` to the `dev` extra

The Makefile `install` target (line 21) is the only consumer of `requirements.txt`. `pip install -e ".[dev]"` already pulls every runtime dependency (from `[project.dependencies]`) plus the test/dev tooling, so the file is redundant drift (it carries a phantom `Jinja2` that pyproject never declared).

**Files**
- Delete: `requirements.txt`
- Modify: `Makefile` (lines 20-22, the `install` target)
- Test path: `tests/test_version_consistency.py` (assert the file is gone)

Steps:

- [ ] Add an assertion to the END of `tests/test_version_consistency.py`:

```python
def test_requirements_txt_is_deleted():
    assert not (REPO_ROOT / "requirements.txt").exists(), (
        "requirements.txt must not exist: pyproject extras are the source of truth"
    )
```

- [ ] Run it and confirm it FAILS:

```
.venv/bin/pytest tests/test_version_consistency.py::test_requirements_txt_is_deleted -v
```

Expected: `1 failed` (`requirements.txt` still exists).

- [ ] Delete the file:

```
git rm requirements.txt
```

- [ ] In `Makefile`, replace the `install` target body:

```makefile
install: venv
	@. .venv/bin/activate && pip install -r requirements.txt
	@. .venv/bin/activate && pip install -e .
```

with:

```makefile
install: venv
	@. .venv/bin/activate && pip install -e ".[dev]"
```

- [ ] Run the deletion assertion and confirm it now PASSES:

```
.venv/bin/pytest tests/test_version_consistency.py::test_requirements_txt_is_deleted -v
```

Expected: `1 passed`.

### Task 6: Add CI matrix workflow (3.10 / 3.11 / 3.12)

No `.github/workflows/` exists today. Add a minimal matrix that installs the package with the `dev` and `docs` extras, runs pytest, and runs `mkdocs build --strict`.

**Files**
- Create: `.github/workflows/test.yml`
- Test path: `tests/test_version_consistency.py` (assert the workflow exists and covers the matrix)

Steps:

- [ ] Add a workflow-presence assertion to the END of `tests/test_version_consistency.py`:

```python
def test_ci_workflow_covers_python_matrix():
    workflow = REPO_ROOT / ".github" / "workflows" / "test.yml"
    assert workflow.exists(), "CI workflow .github/workflows/test.yml is missing"
    with open(workflow, "r", encoding="utf-8") as f:
        ci = yaml.safe_load(f)
    # PyYAML parses the bare `on:` key as boolean True; accept either form.
    triggers = ci.get("on", ci.get(True))
    assert triggers is not None, "workflow has no triggers"
    matrix = ci["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert {"3.10", "3.11", "3.12"} <= set(str(v) for v in matrix), matrix
```

- [ ] Run it and confirm it FAILS:

```
.venv/bin/pytest tests/test_version_consistency.py::test_ci_workflow_covers_python_matrix -v
```

Expected: `1 failed` (`.github/workflows/test.yml` is missing).

- [ ] Create `.github/workflows/test.yml` with this exact content:

```yaml
name: test

on:
  push:
    branches: [ master ]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: [ "3.10", "3.11", "3.12" ]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,docs]"
      - name: Run tests
        run: pytest --maxfail=3 --disable-warnings -q
      - name: Build docs (strict)
        run: mkdocs build --strict
```

- [ ] Run the workflow assertion and confirm it now PASSES:

```
.venv/bin/pytest tests/test_version_consistency.py::test_ci_workflow_covers_python_matrix -v
```

Expected: `1 passed`.

### Task 7: Delete stale `dist/` artifacts and verify the full group green

`dist/` holds stale `repoindex-0.15.3` wheel and sdist. The directory is gitignored (`.gitignore` line 4), so deletion is a local cleanup that does not enter the commit, but it removes confusing 0.15.3 artifacts before any rebuild.

**Files**
- Local cleanup only: `dist/repoindex-0.15.3-py3-none-any.whl`, `dist/repoindex-0.15.3.tar.gz`
- Test path: `tests/test_version_consistency.py` (full file re-run)

Steps:

- [ ] Delete the stale build artifacts:

```
rm -f dist/repoindex-0.15.3-py3-none-any.whl dist/repoindex-0.15.3.tar.gz
```

- [ ] Run the entire version-consistency test file and confirm all PASS:

```
.venv/bin/pytest tests/test_version_consistency.py -v
```

Expected: `12 passed` (the four version-equality / release-note / date tests, the three pyproject-metadata tests, the requirements-deletion test, the CI matrix test).

- [ ] Confirm the package still imports cleanly with the trimmed dependency set:

```
.venv/bin/python -c "import repoindex; import repoindex.infra.pypi_metadata; print(repoindex.__version__)"
```

Expected: `2.0.0` (no `ModuleNotFoundError` from removing `pathlib`/`tweepy`; `toml` still importable for `pypi_metadata`).

- [ ] Run the full suite to confirm no regressions against the 1848 baseline (new tests added on top):

```
.venv/bin/pytest --maxfail=3 -q
```

Expected: all pass, count = 1848 baseline plus the 12 new `test_version_consistency.py` tests.

- [ ] Commit the group (one commit for the whole group):

```
git add pyproject.toml CITATION.cff codemeta.json Makefile .github/workflows/test.yml tests/test_version_consistency.py
git rm --cached requirements.txt 2>/dev/null || true
git commit -m "$(cat <<'EOF'
packaging: drop pathlib/tweepy, py>=3.10, delete requirements.txt, sync versions, add CI

Remove the abandoned pathlib backport and unused tweepy from dependencies
(toml stays as the TOML writer in pypi_metadata.py). Set requires-python to
>=3.10 and add per-version trove classifiers (3.10/3.11/3.12). Delete the
drift-prone requirements.txt and rewire `make install` to `pip install -e
".[dev]"`. Sync CITATION.cff and codemeta.json from the stale 0.10.1 up to
the current pyproject version 2.0.0 (also codemeta dateModified, releaseNotes,
softwareRequirements). Add a CI matrix (3.10/3.11/3.12: install, pytest,
mkdocs build --strict) and tests/test_version_consistency.py asserting the
four version sources agree, so the drift class cannot recur.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit created on the working branch. `requirements.txt` shows as deleted in the commit; `dist/` artifacts are not part of the commit (gitignored).

---

Notes for the assembler:
- All paths absolute under `/home/spinoza/github/beta/repoindex`. Real current state confirmed: `pyproject.toml` line 11 `requires-python = ">=3.8"`, line 14 deps include `"pathlib"`/`"tweepy"`/`"toml"`; `CITATION.cff` line 4 `version: "0.10.1"`; `codemeta.json` `version`/`dateModified`/`releaseNotes`/`softwareRequirements` all stale; `repoindex/__init__.py:27` `__version__ = "2.0.0"`; `Makefile` line 21 uses `requirements.txt`; no `.github/` dir; `dist/` holds untracked 0.15.3 artifacts.
- `tweepy` confirmed unused (no `import tweepy`). `toml` confirmed used at `repoindex/infra/pypi_metadata.py:636` (`toml.dump`), so it is retained.
- This group depends on the Group 7 contract note in the orchestrator brief (requires-python `>=3.10`, version-consistency test). The brief assigns the version-consistency test and the Python floor to this packaging group; it is implemented here in full. If a separate group also touches `requires-python`, dedupe to one editor.
- The version-consistency test uses `repoindex.compat.tomllib` (stdlib on 3.11+, `tomli` backport on 3.10) and `yaml.safe_load` (PyYAML is already a runtime dep). Both import cleanly on the 3.10 floor.

---

## Commit group: docs

This group repairs documentation and onboarding strings that point at removed
commands and a nonexistent plugin marketplace, and fixes the mkdocs nav so
`mkdocs build --strict` passes. All changes are in the Python repo
(`/home/spinoza/github/beta/repoindex`). The verifier `mkdocs` (1.6.1) and
`mkdocs-material` are already installed at `/home/spinoza/venv/bin/mkdocs`; the
`pip install` is listed for portability but is a no-op in this environment.

Repo root for tests: `tests/` sits directly under the repo root, so
`Path(__file__).resolve().parent.parent` is the project root.

### Task 1: Add a doc-string guard test that the removed-command and bad-marketplace breadcrumbs are gone

Files:
- Create: `tests/test_doc_breadcrumbs.py` (new)
- Modify: none yet
- Test path: `tests/test_doc_breadcrumbs.py`

Steps:

- [ ] Write the failing guard test. Create `tests/test_doc_breadcrumbs.py` with this exact content:

```python
"""Guard tests: removed-command breadcrumbs and bad marketplace refs must stay gone.

These assert against the real on-disk source/docs so that the v2.x trust-repair
fixes (removing `repoindex query` / `repoindex init` onboarding hints and the
nonexistent `claude-code-marketplace`) cannot silently regress.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def test_config_init_footer_has_no_removed_query_command():
    text = _read("repoindex/commands/config.py")
    assert "repoindex query" not in text


def test_status_footer_has_no_removed_query_command():
    text = _read("repoindex/commands/status.py")
    assert "repoindex query" not in text


def test_refresh_hint_has_no_removed_init_command():
    text = _read("repoindex/commands/refresh.py")
    assert "repoindex init" not in text


def test_readme_has_no_bad_marketplace_ref():
    text = _read("README.md")
    assert "claude-code-marketplace" not in text
    assert "queelius/claude-anvil" in text


def test_docs_index_has_no_bad_marketplace_ref():
    text = _read("docs/index.md")
    assert "claude-code-marketplace" not in text
    assert "queelius/claude-anvil" in text
```

- [ ] Run the test, expecting FAIL (all five assertions trip on the current strings):

```
pytest tests/test_doc_breadcrumbs.py -v
```

Expected: 5 tests collected, all FAIL. `test_config_init_footer_has_no_removed_query_command` and `test_status_footer_has_no_removed_query_command` fail on `assert "repoindex query" not in text`; `test_refresh_hint_has_no_removed_init_command` fails on `assert "repoindex init" not in text`; both marketplace tests fail on `assert "claude-code-marketplace" not in text`.

### Task 2: Fix the `config init` onboarding footer to cite a real command

Files:
- Modify: `repoindex/commands/config.py` (line 134, the "Next steps" footer)
- Test path: `tests/test_doc_breadcrumbs.py`

Steps:

- [ ] Replace the removed-`query` breadcrumb. In `repoindex/commands/config.py`, change the third "Next steps" line.

Old:
```python
    console.print("  3. Run [cyan]repoindex query \"language == 'Python'\"[/cyan] to search")
```

New:
```python
    console.print("  3. Run [cyan]repoindex sql \"SELECT name FROM repos WHERE language = 'Python'\"[/cyan] to search")
```

- [ ] Run the config guard test, expecting it to PASS now:

```
pytest tests/test_doc_breadcrumbs.py::test_config_init_footer_has_no_removed_query_command -v
```

Expected: 1 passed. (`repoindex sql` is the documented query layer; `repoindex query` is removed.)

### Task 3: Fix the `status` dashboard footer to cite a real command

Files:
- Modify: `repoindex/commands/status.py` (line 150, the no-suggestions footer)
- Test path: `tests/test_doc_breadcrumbs.py`

Steps:

- [ ] Replace the removed-`query` breadcrumb. In `repoindex/commands/status.py`, change the final footer branch.

Old:
```python
        else:
            console.print("[dim]Run 'repoindex query' to search your repositories.[/dim]")
```

New:
```python
        else:
            console.print("[dim]Run 'repoindex sql' to search your repositories.[/dim]")
```

- [ ] Run the status guard test, expecting it to PASS now:

```
pytest tests/test_doc_breadcrumbs.py::test_status_footer_has_no_removed_query_command -v
```

Expected: 1 passed.

### Task 4: Fix the `refresh` no-directories hint to cite a real command

Files:
- Modify: `repoindex/commands/refresh.py` (line 222, the "No repository directories configured" hint)
- Test path: `tests/test_doc_breadcrumbs.py`

Steps:

- [ ] Replace the removed-`init` breadcrumb. In `repoindex/commands/refresh.py`, change the hint string in the no-directories error block.

Old:
```python
            click.echo(json.dumps({
                "error": "No repository directories configured",
                "hint": "Use 'repoindex init' or provide --dir"
            }))
```

New:
```python
            click.echo(json.dumps({
                "error": "No repository directories configured",
                "hint": "Use 'repoindex config init' or provide --dir"
            }))
```

- [ ] Run the refresh guard test, expecting it to PASS now:

```
pytest tests/test_doc_breadcrumbs.py::test_refresh_hint_has_no_removed_init_command -v
```

Expected: 1 passed. (`repoindex init` does not exist; the real subcommand is `repoindex config init`, registered in `config.py`. The substring `repoindex init` is absent because the new string is `repoindex config init`.)

### Task 5: Fix the `claude-code-marketplace` reference in README.md

Files:
- Modify: `README.md` (line 76, the plugin install block)
- Test path: `tests/test_doc_breadcrumbs.py`

Steps:

- [ ] Replace the nonexistent marketplace. In `README.md`, change the marketplace-add line.

Old:
```
/plugin marketplace add queelius/claude-code-marketplace
```

New:
```
/plugin marketplace add queelius/claude-anvil
```

- [ ] Run the README guard test, expecting it to PASS now:

```
pytest tests/test_doc_breadcrumbs.py::test_readme_has_no_bad_marketplace_ref -v
```

Expected: 1 passed.

### Task 6: Fix the `claude-code-marketplace` reference in docs/index.md

Files:
- Modify: `docs/index.md` (line 185, the "Claude Code Plugin" block)
- Test path: `tests/test_doc_breadcrumbs.py`

Steps:

- [ ] Replace the nonexistent marketplace. In `docs/index.md`, change the marketplace-add line.

Old:
```
/plugin marketplace add queelius/claude-code-marketplace
```

New:
```
/plugin marketplace add queelius/claude-anvil
```

- [ ] Run the docs/index guard test, expecting it to PASS now:

```
pytest tests/test_doc_breadcrumbs.py::test_docs_index_has_no_bad_marketplace_ref -v
```

Expected: 1 passed.

- [ ] Run the whole guard file to confirm all five pass together:

```
pytest tests/test_doc_breadcrumbs.py -v
```

Expected: 5 passed.

### Task 7: Add a mkdocs-nav guard test asserting the nav is internally consistent

Files:
- Create: `tests/test_mkdocs_nav.py` (new)
- Modify: none yet
- Test path: `tests/test_mkdocs_nav.py`

Steps:

- [ ] Write the failing nav test. Create `tests/test_mkdocs_nav.py` with this exact content (PyYAML is already a dependency; `repoindex/commands/config.py` imports `yaml`):

```python
"""Guard tests for mkdocs nav consistency.

Asserts every nav target file exists under docs/ and that the dead
`catalog-query.md` / `render.md` entries are gone while `export.md` is present.
A standalone unit test cannot exercise `mkdocs build --strict` portably, so this
validates the same invariant strict mode enforces (no nav reference to a missing
page) directly against mkdocs.yml.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"


def _nav_targets(nav):
    """Yield every leaf doc path referenced in a mkdocs nav structure."""
    if isinstance(nav, str):
        yield nav
    elif isinstance(nav, list):
        for item in nav:
            yield from _nav_targets(item)
    elif isinstance(nav, dict):
        for value in nav.values():
            yield from _nav_targets(value)


def _load_nav():
    text = (PROJECT_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    # mkdocs.yml uses no custom python tags in this project, so safe_load works.
    data = yaml.safe_load(text)
    return list(_nav_targets(data.get("nav", [])))


def test_every_nav_target_exists():
    for target in _load_nav():
        assert (DOCS_DIR / target).is_file(), f"nav target missing: {target}"


def test_dead_nav_entries_removed():
    targets = _load_nav()
    assert "catalog-query.md" not in targets
    assert "render.md" not in targets


def test_export_doc_is_in_nav():
    assert "export.md" in _load_nav()
```

- [ ] Run the nav test, expecting FAIL (current nav references the two missing files and omits export.md):

```
pytest tests/test_mkdocs_nav.py -v
```

Expected: 3 tests collected, all FAIL. `test_every_nav_target_exists` fails on `nav target missing: catalog-query.md`; `test_dead_nav_entries_removed` fails on `assert "catalog-query.md" not in targets`; `test_export_doc_is_in_nav` fails on `assert "export.md" in _load_nav()`.

### Task 8: Repoint the mkdocs nav (drop catalog-query, swap render to export)

Files:
- Modify: `mkdocs.yml` (lines 34-39, the `nav:` block)
- Test path: `tests/test_mkdocs_nav.py`

Steps:

- [ ] Edit the nav block. In `mkdocs.yml`, replace the nav section.

Old:
```yaml
nav:
  - Home: index.md
  - Tags & Queries: catalog-query.md
  - Events: events.md
  - Ops & Audit: ops.md
  - Render Formats: render.md
```

New:
```yaml
nav:
  - Home: index.md
  - Events: events.md
  - Ops & Audit: ops.md
  - Export: export.md
```

- [ ] Run the nav guard test, expecting it to PASS now:

```
pytest tests/test_mkdocs_nav.py -v
```

Expected: 3 passed. (`catalog-query.md` and `render.md` no longer exist on disk and are dropped; `export.md` exists at `docs/export.md` with title "# Export" and is now reachable.)

### Task 9: Verify `mkdocs build --strict` passes end to end

Files:
- Modify: none
- Test path: shell verification (no new test file)

Steps:

- [ ] Ensure the build toolchain is present (no-op here; mkdocs 1.6.1 and mkdocs-material are already installed at `/home/spinoza/venv/bin/mkdocs`):

```
pip install mkdocs mkdocs-material
```

Expected: "Requirement already satisfied" for both.

- [ ] Run the strict build from the repo root and confirm it succeeds:

```
mkdocs build --strict
```

Expected: build completes with exit status 0 and NO `WARNING -  A reference to 'catalog-query.md' ...` or `... 'render.md' ...` lines, and NO `Aborted ... in strict mode!`. Final line is the build success (`INFO  -  Documentation built in ...`). Note: the `INFO` lines listing `plans/*.md` and `superpowers/specs/*.md` as "not included in nav" are informational only and do not abort strict mode; only nav-references-to-missing-pages are WARNINGs, and those are now resolved.

### Task 10: Run the affected suites and commit the docs group

Files:
- Modify: none (commit only)
- Test path: `tests/test_doc_breadcrumbs.py`, `tests/test_mkdocs_nav.py`, plus existing config/status/refresh suites

Steps:

- [ ] Run the new tests plus the existing command suites this group touched, expecting all PASS:

```
pytest tests/test_doc_breadcrumbs.py tests/test_mkdocs_nav.py tests/test_config.py tests/test_init_command.py tests/test_refresh_flags.py -v
```

Expected: all collected tests pass (8 new tests in the two new files all green; no regressions in the config/init/refresh suites, which assert on behavior, not on the changed footer/hint wording).

- [ ] Stage and commit the docs group as a single commit:

```
git add mkdocs.yml repoindex/commands/config.py repoindex/commands/status.py repoindex/commands/refresh.py README.md docs/index.md tests/test_doc_breadcrumbs.py tests/test_mkdocs_nav.py
git commit -m "$(cat <<'EOF'
docs: repair broken nav and removed-command breadcrumbs

mkdocs nav pointed at deleted catalog-query.md and render.md and omitted
export.md, so `mkdocs build --strict` aborted. Drop the dead entries and
add Export. Onboarding strings in config/status/refresh cited the removed
`repoindex query` / `repoindex init` commands; repoint them at the real
`repoindex sql` and `repoindex config init`. README and docs/index referenced
a nonexistent `claude-code-marketplace`; replace with queelius/claude-anvil.
Add grep-style guard tests so the breadcrumbs and nav cannot regress.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit created on the current branch containing the eight listed paths.
```

---

## Commit group: plugin

This group's commit happens in the SEPARATE plugin repo at `/home/spinoza/github/alex-claude-plugins` (git root; the repoindex plugin lives at `repoindex/` inside it). All four edits are documentation/config only. The plugin repo has no pytest suite, so verification is grep-based. The `plugin.json` at `repoindex/.claude-plugin/plugin.json` is already at 2.0.0 with the correct `repository` URL (`queelius/claude-anvil`) and a good description, so it needs no change; only `.claude-plugin/marketplace.json` (at the git root) is stale.

### Task 1: Remove dead `gitea_forks` line from repo-explorer.md

Files:
- Modify: `/home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-explorer.md` (line 60)
- Verify (no pytest in plugin repo): grep guard

The current `repos` table doc block (lines 56-61) lists unified forge fields correctly on lines 58-59, then has a stale leftover line 60 referencing the removed `gitea_forks` column and a "(if Gitea source enabled)" qualifier. The line is dead (the schema has no `gitea_forks` column; forks are the unified `forks_count`, already covered on line 58). The `keywords` line 61 must remain.

- [ ] Confirm the exact current text of the dead line and its correct neighbors:
  ```bash
  grep -n "gitea_forks\|forks_count\|keywords" /home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-explorer.md
  ```
  Expected output (line 58 already has the correct `forks_count`, line 60 is the dead duplicate):
  ```
  58:- `stars`, `forks_count`, `topics`, `forge_description`,
  60:- `stars`, `gitea_forks`, `topics` (if Gitea source enabled)
  61:- `keywords` (JSON array from pyproject.toml/Cargo.toml/package.json)
  ```
- [ ] Delete the dead line via exact-string Edit. old_string (the full line 60 plus its trailing newline so the surrounding lines stay intact):
  ```
  - `stars`, `is_fork`, `is_private`, `is_archived`
  - `stars`, `gitea_forks`, `topics` (if Gitea source enabled)
  - `keywords` (JSON array from pyproject.toml/Cargo.toml/package.json)
  ```
  new_string (line 60 removed, the two real lines kept):
  ```
  - `stars`, `is_fork`, `is_private`, `is_archived`
  - `keywords` (JSON array from pyproject.toml/Cargo.toml/package.json)
  ```
- [ ] Verify the dead reference is gone and the correct unified field survives:
  ```bash
  grep -c "gitea_forks" /home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-explorer.md; grep -n "forks_count" /home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-explorer.md
  ```
  Expected output (count 0 for the dead token, line 58 unified field still present):
  ```
  0
  58:- `stars`, `forks_count`, `topics`, `forge_description`,
  ```

### Task 2: Bump marketplace.json repoindex entry to 2.0.0 and refresh its description

Files:
- Modify: `/home/spinoza/github/alex-claude-plugins/.claude-plugin/marketplace.json` (lines 47-55, the repoindex plugin entry)
- Verify (no pytest in plugin repo): grep guard plus JSON parse

The repoindex entry is stale at `0.16.0` with a description (`"Agent-driven repository intelligence. MCP-first with repo-doctor, repo-polish, repo-explorer agents."`) that predates the v2.0 surface. The package and `plugin.json` are both at 2.0.0 today; the move to 2.1.0 happens later at the release step, not in this commit. Refresh the description to match the current `plugin.json` description (the canonical source for this plugin).

- [ ] Confirm the current stale entry:
  ```bash
  grep -n "0.16.0\|Agent-driven repository intelligence" /home/spinoza/github/alex-claude-plugins/.claude-plugin/marketplace.json
  ```
  Expected output:
  ```
  50:      "description": "Agent-driven repository intelligence. MCP-first with repo-doctor, repo-polish, repo-explorer agents.",
  51:      "version": "0.16.0",
  ```
- [ ] Update the description and version together via exact-string Edit. old_string:
  ```
      {
        "name": "repoindex",
        "source": "./repoindex",
        "description": "Agent-driven repository intelligence. MCP-first with repo-doctor, repo-polish, repo-explorer agents.",
        "version": "0.16.0",
        "author": {
          "name": "Alexander Towell"
        }
      },
  ```
  new_string (description mirrors the current `repoindex/.claude-plugin/plugin.json` description; version bumped to 2.0.0):
  ```
      {
        "name": "repoindex",
        "source": "./repoindex",
        "description": "Repository intelligence for Claude Code. MCP-first access to a local git catalog, three specialized agents (repo-doctor, repo-polish, repo-explorer), and five slash commands (/repo-week, /repo-status, /repo-audit, /repo-sprint, /repo-mirror) for recurring workflows.",
        "version": "2.0.0",
        "author": {
          "name": "Alexander Towell"
        }
      },
  ```
- [ ] Verify the version is correct, the stale string is gone, and the file is still valid JSON:
  ```bash
  python3 -c "import json; d=json.load(open('/home/spinoza/github/alex-claude-plugins/.claude-plugin/marketplace.json')); e=[p for p in d['plugins'] if p['name']=='repoindex'][0]; print(e['version']); assert e['version']=='2.0.0'; assert 'Agent-driven' not in e['description']; print('OK')"
  ```
  Expected output:
  ```
  2.0.0
  OK
  ```
- [ ] Verify no `0.16.0` remains anywhere in marketplace.json:
  ```bash
  grep -c "0.16.0" /home/spinoza/github/alex-claude-plugins/.claude-plugin/marketplace.json
  ```
  Expected output:
  ```
  0
  ```

### Task 3: Replace dead `@tag-name` DSL with the `--tag` flag in workflows/SKILL.md

Files:
- Modify: `/home/spinoza/github/alex-claude-plugins/repoindex/skills/workflows/SKILL.md` (line 101)
- Verify (no pytest in plugin repo): grep guard

Line 101 tells the LLM that "Filtering by tag uses the DSL: `@tag-name`". The DSL was removed in v0.16.0. The real surfaces are the `--tag` filter flag (accepted by `copy`, `link`, `ops` subcommands, and `export`, with `*` wildcard support) and SQL via an `EXISTS` subquery. Rewrite to point at those.

- [ ] Confirm the current dead-DSL line:
  ```bash
  grep -n "@tag-name\|uses the DSL" /home/spinoza/github/alex-claude-plugins/repoindex/skills/workflows/SKILL.md
  ```
  Expected output:
  ```
  101:Use `mcp__repoindex__tag` to add/remove user tags. Filtering by tag uses the DSL: `@tag-name` or the SQL `EXISTS (SELECT 1 FROM tags WHERE ...)` pattern.
  ```
- [ ] Replace the DSL reference with the `--tag` flag via exact-string Edit. old_string:
  ```
  Use `mcp__repoindex__tag` to add/remove user tags. Filtering by tag uses the DSL: `@tag-name` or the SQL `EXISTS (SELECT 1 FROM tags WHERE ...)` pattern.
  ```
  new_string:
  ```
  Use `mcp__repoindex__tag` to add/remove user tags. Filter by tag with the `--tag` flag (accepted by `copy`, `link`, `ops` subcommands, and `export`; supports `*` wildcards, for example `--tag 'work/*'`), or from `run_sql` with the `EXISTS (SELECT 1 FROM tags WHERE t.repo_id = r.id AND t.tag = '...')` pattern.
  ```
- [ ] Verify the dead DSL token is gone and the `--tag` flag is now documented:
  ```bash
  grep -c "@tag-name\|uses the DSL" /home/spinoza/github/alex-claude-plugins/repoindex/skills/workflows/SKILL.md; grep -n "the \`--tag\` flag" /home/spinoza/github/alex-claude-plugins/repoindex/skills/workflows/SKILL.md
  ```
  Expected output:
  ```
  0
  101:Use `mcp__repoindex__tag` to add/remove user tags. Filter by tag with the `--tag` flag (accepted by `copy`, `link`, `ops` subcommands, and `export`; supports `*` wildcards, for example `--tag 'work/*'`), or from `run_sql` with the `EXISTS (SELECT 1 FROM tags WHERE t.repo_id = r.id AND t.tag = '...')` pattern.
  ```

### Task 4: Remove false `"name == 'REPO'"` DSL targeting from repo-polish.md (doc-only, no new selector)

Files:
- Modify: `/home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-polish.md` (Step 1 SQL lines 79 and 87, the Step 3 command block lines 114-133, the Key flags table line 193)
- Verify (no pytest in plugin repo): grep guard

The agent currently promises single-repo targeting via a removed-DSL string (`"name == 'REPO'"`). Those positional args are now silently ignored (Commit 4 of this bundle will make them raise), so following this doc would scaffold across ALL repos. This is a minimal doc-only fix per the locked decision in the spec: do NOT introduce a new `--name`/`--path` selector (that full single-repo rewrite is deferred to a separate feature). Rewrite the examples to use the supported filter flags (`--language`/`--tag`/`--recent`) for collection-scoped runs, and a per-repo `cd` plus `-d <path>` for single-repo runs. Also fix the two Step 1 SQL queries that filter `WHERE name = ?` (they are fine as MCP `run_sql` queries, but reference `repo_id = ?` in a way that needs the resolved id; leave the SQL as-is since it is run_sql, not the removed CLI DSL) and the Key flags table row that documents the dead DSL.

- [ ] Confirm every dead-DSL occurrence in the file:
  ```bash
  grep -n "name == '" /home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-polish.md
  ```
  Expected output:
  ```
  116:repoindex ops generate citation --dry-run "name == 'REPO'"
  117:repoindex ops generate zenodo --dry-run "name == 'REPO'"
  118:repoindex ops generate codemeta --dry-run "name == 'REPO'"
  121:repoindex ops generate mkdocs --dry-run "name == 'REPO'"
  129:repoindex ops generate license --license mit --dry-run "name == 'REPO'"
  130:repoindex ops generate gitignore --lang python --dry-run "name == 'REPO'"
  131:repoindex ops generate code-of-conduct --dry-run "name == 'REPO'"
  132:repoindex ops generate contributing --dry-run "name == 'REPO'"
  193:| `"name == 'foo'"` | Target specific repo (DSL expression) |
  ```
- [ ] Rewrite the Step 3 deterministic-fixes command block via exact-string Edit. old_string (the full fenced block, lines 110-133):
  ```
  ### Step 3: Deterministic fixes

  Run each with `--dry-run` first, show the user, execute on approval:

  ```bash
  # Citation metadata (reads pyproject.toml + config author)
  repoindex ops generate citation --dry-run "name == 'REPO'"
  repoindex ops generate zenodo --dry-run "name == 'REPO'"
  repoindex ops generate codemeta --dry-run "name == 'REPO'"

  # Documentation scaffolding
  repoindex ops generate mkdocs --dry-run "name == 'REPO'"
  repoindex ops set-pages REPO --branch gh-pages --path / --dry-run

  # Forge metadata (cross-platform; dispatches through forge_id)
  repoindex ops set-topics REPO topic1 topic2 --dry-run
  repoindex ops set-description REPO "..." --dry-run

  # Missing boilerplate
  repoindex ops generate license --license mit --dry-run "name == 'REPO'"
  repoindex ops generate gitignore --lang python --dry-run "name == 'REPO'"
  repoindex ops generate code-of-conduct --dry-run "name == 'REPO'"
  repoindex ops generate contributing --dry-run "name == 'REPO'"
  ```
  ```
  new_string (positional DSL removed; single-repo runs use `cd` plus `-d <path>`; collection runs use filter flags. The `set-topics`/`set-description`/`set-pages` commands already take a repo name argument and stay as-is):
  ```
  ### Step 3: Deterministic fixes

  Run each with `--dry-run` first, show the user, execute on approval.
  `ops generate` has no single-repo selector yet, so for a single repo run
  it from inside the repo (or with `-d <path>`); use the filter flags
  (`--language`/`--tag`/`--recent`) only when you intend a collection-wide run.

  ```bash
  # Single repo: run from the repo's path so generation is scoped to it
  cd /path/to/REPO

  # Citation metadata (reads pyproject.toml + config author)
  repoindex ops generate citation --dry-run -d /path/to/REPO
  repoindex ops generate zenodo --dry-run -d /path/to/REPO
  repoindex ops generate codemeta --dry-run -d /path/to/REPO

  # Documentation scaffolding
  repoindex ops generate mkdocs --dry-run -d /path/to/REPO
  repoindex ops set-pages REPO --branch gh-pages --path / --dry-run

  # Forge metadata (cross-platform; dispatches through forge_id)
  repoindex ops set-topics REPO topic1 topic2 --dry-run
  repoindex ops set-description REPO "..." --dry-run

  # Missing boilerplate
  repoindex ops generate license --license mit --dry-run -d /path/to/REPO
  repoindex ops generate gitignore --lang python --dry-run -d /path/to/REPO
  repoindex ops generate code-of-conduct --dry-run -d /path/to/REPO
  repoindex ops generate contributing --dry-run -d /path/to/REPO
  ```
  ```
- [ ] Rewrite the Key flags table row that documents the removed DSL via exact-string Edit. old_string:
  ```
  | `"name == 'foo'"` | Target specific repo (DSL expression) |
  ```
  new_string:
  ```
  | `-d <path>` | Scope generation to a single repo by path |
  | `--language`/`--tag`/`--recent` | Scope a collection-wide run to a filtered subset |
  ```
- [ ] Verify all dead-DSL targeting is gone and the replacement flags are present:
  ```bash
  grep -c "name == '" /home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-polish.md; grep -n "Scope generation to a single repo by path" /home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-polish.md
  ```
  Expected output (zero DSL strings; new flag row present):
  ```
  0
  194:| `-d <path>` | Scope generation to a single repo by path |
  ```
- [ ] Confirm no new `--name`/`--path` selector was introduced (the deferred feature must not leak in):
  ```bash
  grep -c "ops generate --name\|ops generate --path\|generate.*--name\b" /home/spinoza/github/alex-claude-plugins/repoindex/agents/repo-polish.md
  ```
  Expected output:
  ```
  0
  ```

### Task 5: Whole-group verification and single commit (plugin repo)

Files:
- No file changes; verification plus the group's one commit in `/home/spinoza/github/alex-claude-plugins`.

This is the last task of the group: one commit covering all four doc/config fixes. The plugin repo has no pytest suite, so the gate is the consolidated grep guard from the spec's Verification Strategy ("no `gitea_forks`, no `name ==` DSL, no `@tag-name` remain; marketplace.json version updated").

- [ ] Run the consolidated grep guard across all four edited files:
  ```bash
  cd /home/spinoza/github/alex-claude-plugins && echo "gitea_forks: $(grep -rc gitea_forks repoindex/ | grep -v ':0' | wc -l)"; echo "name==DSL: $(grep -rc \"name == '\" repoindex/ | grep -v ':0' | wc -l)"; echo "@tag-name: $(grep -rc @tag-name repoindex/ | grep -v ':0' | wc -l)"; echo "stale 0.16.0: $(grep -c 0.16.0 .claude-plugin/marketplace.json)"; echo "marketplace version:"; python3 -c "import json;d=json.load(open('.claude-plugin/marketplace.json'));print([p['version'] for p in d['plugins'] if p['name']=='repoindex'][0])"
  ```
  Expected output (every dead-string file count zero; marketplace at 2.0.0):
  ```
  gitea_forks: 0
  name==DSL: 0
  @tag-name: 0
  stale 0.16.0: 0
  marketplace version:
  2.0.0
  ```
- [ ] Confirm marketplace.json is still valid JSON (guards against a malformed edit):
  ```bash
  cd /home/spinoza/github/alex-claude-plugins && python3 -m json.tool .claude-plugin/marketplace.json > /dev/null && echo "JSON OK"
  ```
  Expected output:
  ```
  JSON OK
  ```
- [ ] Stage only this group's four files (the repo has unrelated dirty files under `bookwright/`, `research-agent/`, etc.; do not stage those):
  ```bash
  cd /home/spinoza/github/alex-claude-plugins && git add repoindex/agents/repo-explorer.md repoindex/agents/repo-polish.md repoindex/skills/workflows/SKILL.md .claude-plugin/marketplace.json && git status --short -- repoindex/agents/repo-explorer.md repoindex/agents/repo-polish.md repoindex/skills/workflows/SKILL.md .claude-plugin/marketplace.json
  ```
  Expected output (all four staged):
  ```
  M  .claude-plugin/marketplace.json
  M  repoindex/agents/repo-explorer.md
  M  repoindex/agents/repo-polish.md
  M  repoindex/skills/workflows/SKILL.md
  ```
- [ ] Commit the group with a message describing all four fixes:
  ```bash
  cd /home/spinoza/github/alex-claude-plugins && git commit -m "docs(repoindex): repair stale plugin surface for v2.x

Remove dead gitea_forks column reference from repo-explorer.md (unified
forks_count already documented). Replace removed @tag-name DSL in
workflows/SKILL.md with the --tag filter flag. Remove the false
\"name == 'REPO'\" DSL targeting from repo-polish.md (those positional
queries were removed in v0.16 and now scaffold across the whole
collection); scope single-repo runs via -d <path> instead. No new
--name/--path selector is added (deferred). Bump the marketplace.json
repoindex entry from 0.16.0 to 2.0.0 and refresh its description.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
  Expected: one new commit on `master`; `git log --oneline -1` shows the `docs(repoindex): repair stale plugin surface` subject.

---

Notes for the assembler:
- This is the only group whose commit lands in the plugin repo (`/home/spinoza/github/alex-claude-plugins`), not the Python repo. It corresponds to Commit 9 (`plugin`) in the spec.
- The marketplace.json file is at the git-root path `/home/spinoza/github/alex-claude-plugins/.claude-plugin/marketplace.json` (NOT under the `repoindex/` subdirectory, as the task brief's path suggested).
- `repoindex/.claude-plugin/plugin.json` needs no change: it is already at 2.0.0 with the correct `repository` URL (`queelius/claude-anvil`) and an accurate description. The spec's optional line-10 fix is already in place.
- The move of marketplace.json and plugin.json to 2.1.0 is deferred to the final release step (after all nine commits), per the spec's "Release step" section, and is out of scope for this group.
