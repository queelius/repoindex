"""Tests for the refresh_log module."""

import json
import pytest

from repoindex.database.connection import Database
from repoindex.database.refresh_log import (
    ensure_refresh_log_table,
    record_refresh,
    get_latest_refresh,
    get_refresh_log,
    prune_refresh_log,
)
from repoindex.config import get_default_config


@pytest.fixture
def db():
    """Create an in-memory database with schema for testing."""
    config = get_default_config()
    config['database'] = {'path': ':memory:'}
    with Database(config=config) as database:
        yield database


class TestEnsureTable:
    def test_creates_table(self, db):
        ensure_refresh_log_table(db)
        db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='refresh_log'"
        )
        assert db.fetchone() is not None

    def test_idempotent(self, db):
        ensure_refresh_log_table(db)
        ensure_refresh_log_table(db)
        db.execute("SELECT COUNT(*) as c FROM refresh_log")
        assert db.fetchone()['c'] == 0

    def test_creates_index(self, db):
        ensure_refresh_log_table(db)
        db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_refresh_log_started'"
        )
        assert db.fetchone() is not None


class TestRecordRefresh:
    def test_basic_insert(self, db):
        row_id = record_refresh(
            db,
            started_at="2025-01-01T10:00:00",
            finished_at="2025-01-01T10:05:00",
            sources=["git"],
        )
        assert row_id > 0

    def test_all_fields(self, db):
        record_refresh(
            db,
            started_at="2025-01-01T10:00:00",
            finished_at="2025-01-01T10:05:00",
            sources=["git", "github", "pypi"],
            full_scan=True,
            scan_roots=["/home/user/github"],
            repos_total=100,
            repos_scanned=90,
            repos_skipped=10,
            repos_added=5,
            repos_removed=2,
            errors=1,
            duration_seconds=300.5,
            cli_version="0.10.2",
        )

        entry = get_latest_refresh(db)
        assert entry is not None
        assert entry['full_scan'] == 1
        assert entry['sources'] == ["git", "github", "pypi"]
        assert entry['scan_roots'] == ["/home/user/github"]
        assert entry['repos_total'] == 100
        assert entry['repos_scanned'] == 90
        assert entry['repos_skipped'] == 10
        assert entry['repos_added'] == 5
        assert entry['repos_removed'] == 2
        assert entry['errors'] == 1
        assert entry['duration_seconds'] == pytest.approx(300.5)
        assert entry['cli_version'] == "0.10.2"

    def test_sources_stored_as_json(self, db):
        record_refresh(
            db,
            started_at="2025-01-01T10:00:00",
            finished_at="2025-01-01T10:05:00",
            sources=["git", "github"],
        )
        # Read raw value
        db.execute("SELECT sources FROM refresh_log ORDER BY id DESC LIMIT 1")
        raw = db.fetchone()['sources']
        assert json.loads(raw) == ["git", "github"]


class TestGetLatestRefresh:
    def test_empty_table(self, db):
        result = get_latest_refresh(db)
        assert result is None

    def test_returns_most_recent(self, db):
        record_refresh(
            db,
            started_at="2025-01-01T10:00:00",
            finished_at="2025-01-01T10:05:00",
            sources=["git"],
        )
        record_refresh(
            db,
            started_at="2025-01-02T10:00:00",
            finished_at="2025-01-02T10:05:00",
            sources=["git", "github"],
        )

        latest = get_latest_refresh(db)
        assert latest['started_at'] == "2025-01-02T10:00:00"
        assert latest['sources'] == ["git", "github"]


class TestGetRefreshLog:
    def test_empty(self, db):
        entries = get_refresh_log(db)
        assert entries == []

    def test_returns_most_recent_first(self, db):
        for i in range(5):
            record_refresh(
                db,
                started_at=f"2025-01-0{i+1}T10:00:00",
                finished_at=f"2025-01-0{i+1}T10:05:00",
                sources=["git"],
            )

        entries = get_refresh_log(db, limit=3)
        assert len(entries) == 3
        assert entries[0]['started_at'] == "2025-01-05T10:00:00"
        assert entries[2]['started_at'] == "2025-01-03T10:00:00"

    def test_respects_limit(self, db):
        for i in range(10):
            record_refresh(
                db,
                started_at=f"2025-01-{i+1:02d}T10:00:00",
                finished_at=f"2025-01-{i+1:02d}T10:05:00",
                sources=["git"],
            )

        entries = get_refresh_log(db, limit=5)
        assert len(entries) == 5


class TestPruneRefreshLog:
    def test_prunes_oldest(self, db):
        ensure_refresh_log_table(db)
        for i in range(5):
            record_refresh(
                db,
                started_at=f"2025-01-0{i+1}T10:00:00",
                finished_at=f"2025-01-0{i+1}T10:05:00",
                sources=["git"],
                max_rows=999,  # Don't prune during insert
            )

        deleted = prune_refresh_log(db, max_rows=3)
        assert deleted == 2

        entries = get_refresh_log(db, limit=10)
        assert len(entries) == 3
        # Should keep the most recent
        assert entries[0]['started_at'] == "2025-01-05T10:00:00"
        assert entries[2]['started_at'] == "2025-01-03T10:00:00"

    def test_auto_prune_on_insert(self, db):
        for i in range(5):
            record_refresh(
                db,
                started_at=f"2025-01-0{i+1}T10:00:00",
                finished_at=f"2025-01-0{i+1}T10:05:00",
                sources=["git"],
                max_rows=3,
            )

        entries = get_refresh_log(db, limit=10)
        assert len(entries) == 3

    def test_no_prune_when_below_limit(self, db):
        ensure_refresh_log_table(db)
        record_refresh(
            db,
            started_at="2025-01-01T10:00:00",
            finished_at="2025-01-01T10:05:00",
            sources=["git"],
            max_rows=999,
        )

        deleted = prune_refresh_log(db, max_rows=10)
        assert deleted == 0


class TestJsonParsing:
    def test_sources_parsed(self, db):
        record_refresh(
            db,
            started_at="2025-01-01T10:00:00",
            finished_at="2025-01-01T10:05:00",
            sources=["git", "github", "pypi"],
        )
        entry = get_latest_refresh(db)
        assert isinstance(entry['sources'], list)
        assert entry['sources'] == ["git", "github", "pypi"]

    def test_scan_roots_parsed(self, db):
        record_refresh(
            db,
            started_at="2025-01-01T10:00:00",
            finished_at="2025-01-01T10:05:00",
            sources=["git"],
            scan_roots=["/home/user/github", "/home/user/projects"],
        )
        entry = get_latest_refresh(db)
        assert isinstance(entry['scan_roots'], list)
        assert len(entry['scan_roots']) == 2

    def test_null_scan_roots(self, db):
        record_refresh(
            db,
            started_at="2025-01-01T10:00:00",
            finished_at="2025-01-01T10:05:00",
            sources=["git"],
        )
        entry = get_latest_refresh(db)
        assert entry['scan_roots'] is None
