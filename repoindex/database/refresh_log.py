"""
Refresh log tracking for repoindex.

Records metadata about each refresh run — timing, sources, stats —
so that the status dashboard and Claude Code plugin can determine
data staleness without guessing from MAX(scanned_at).
"""

import json
from typing import Any, Dict, List, Optional

from .connection import Database


def ensure_refresh_log_table(db: Database) -> None:
    """
    Ensure the refresh_log table exists.

    Uses CREATE TABLE IF NOT EXISTS so it's safe to call on every refresh.
    Handles migration for existing databases that predate this feature.
    """
    db.execute("""
        CREATE TABLE IF NOT EXISTS refresh_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            full_scan BOOLEAN NOT NULL DEFAULT 0,
            sources TEXT NOT NULL,
            scan_roots TEXT,
            repos_total INTEGER,
            repos_scanned INTEGER,
            repos_skipped INTEGER,
            repos_added INTEGER DEFAULT 0,
            repos_removed INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0,
            duration_seconds REAL,
            cli_version TEXT
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_refresh_log_started
        ON refresh_log(started_at)
    """)


def record_refresh(
    db: Database,
    started_at: str,
    finished_at: str,
    sources: List[str],
    full_scan: bool = False,
    scan_roots: Optional[List[str]] = None,
    repos_total: int = 0,
    repos_scanned: int = 0,
    repos_skipped: int = 0,
    repos_added: int = 0,
    repos_removed: int = 0,
    errors: int = 0,
    duration_seconds: Optional[float] = None,
    cli_version: Optional[str] = None,
    max_rows: int = 100,
) -> int:
    """
    Record a completed refresh run and prune old entries.

    Args:
        db: Database connection
        started_at: ISO timestamp when refresh started
        finished_at: ISO timestamp when refresh finished
        sources: List of sources used (e.g. ["git", "github", "pypi"])
        full_scan: Whether --full was used
        scan_roots: List of scanned directory paths
        repos_total: Total repos in DB after refresh
        repos_scanned: Repos that were scanned this run
        repos_skipped: Repos skipped (unchanged)
        repos_added: New repos added (updated count)
        repos_removed: Repos removed (missing from disk)
        errors: Number of errors during refresh
        duration_seconds: Wall-clock duration
        cli_version: repoindex version string
        max_rows: Maximum log entries to keep (prunes oldest beyond this)

    Returns:
        ID of the inserted log entry
    """
    ensure_refresh_log_table(db)

    db.execute(
        """INSERT INTO refresh_log (
            started_at, finished_at, full_scan, sources, scan_roots,
            repos_total, repos_scanned, repos_skipped, repos_added,
            repos_removed, errors, duration_seconds, cli_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            started_at,
            finished_at,
            full_scan,
            json.dumps(sources),
            json.dumps(scan_roots) if scan_roots else None,
            repos_total,
            repos_scanned,
            repos_skipped,
            repos_added,
            repos_removed,
            errors,
            duration_seconds,
            cli_version,
        ),
    )
    row_id = db.lastrowid or 0

    # Prune old entries
    if max_rows > 0:
        prune_refresh_log(db, max_rows)

    return row_id


def get_latest_refresh(db: Database) -> Optional[Dict[str, Any]]:
    """
    Get the most recent refresh log entry.

    Returns:
        Dict with refresh data, or None if no entries exist.
    """
    ensure_refresh_log_table(db)

    db.execute("SELECT * FROM refresh_log ORDER BY id DESC LIMIT 1")
    row = db.fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def get_refresh_log(db: Database, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent refresh log entries.

    Args:
        db: Database connection
        limit: Maximum entries to return (most recent first)

    Returns:
        List of refresh log entries as dicts
    """
    ensure_refresh_log_table(db)

    db.execute(
        "SELECT * FROM refresh_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [_row_to_dict(row) for row in db.fetchall()]


def prune_refresh_log(db: Database, max_rows: int) -> int:
    """
    Delete oldest entries beyond max_rows.

    Args:
        db: Database connection
        max_rows: Maximum number of rows to keep

    Returns:
        Number of rows deleted
    """
    db.execute(
        """DELETE FROM refresh_log
           WHERE id NOT IN (
               SELECT id FROM refresh_log
               ORDER BY id DESC
               LIMIT ?
           )""",
        (max_rows,),
    )
    return db.rowcount


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a database row to a dict, parsing JSON fields."""
    d = dict(row)
    # Parse JSON array fields
    for key in ('sources', 'scan_roots'):
        if d.get(key) and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
