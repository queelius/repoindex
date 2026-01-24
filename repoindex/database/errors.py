"""
Scan error tracking for repoindex.

Records errors that occur during repository scanning to help users
understand and diagnose problems with their repository collection.
"""

from typing import Optional, List, Dict, Any
from .connection import Database


def ensure_scan_errors_table(db: Database) -> None:
    """
    Ensure the scan_errors table exists.

    This handles migration for existing databases that don't have the table.
    """
    db.execute("""
        CREATE TABLE IF NOT EXISTS scan_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            error_type TEXT NOT NULL,
            error_message TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_errors_path ON scan_errors(path)
    """)


def record_scan_error(
    db: Database,
    path: str,
    error_type: str,
    error_message: Optional[str] = None,
) -> int:
    """
    Record a scan error for a path.

    Clears any previous errors for this path before recording.

    Args:
        db: Database connection
        path: Path that failed to scan
        error_type: Type of error (permission, corrupt, not_git, git_error)
        error_message: Detailed error message

    Returns:
        ID of the inserted error record
    """
    # Ensure table exists (migration for existing databases)
    ensure_scan_errors_table(db)

    # Clear previous errors for this path
    db.execute(
        "DELETE FROM scan_errors WHERE path = ?",
        (path,)
    )

    # Insert new error
    db.execute(
        """INSERT INTO scan_errors (path, error_type, error_message)
           VALUES (?, ?, ?)""",
        (path, error_type, error_message)
    )

    return db.lastrowid or 0


def get_scan_errors(
    db: Database,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Get all scan errors.

    Args:
        db: Database connection
        limit: Maximum number of errors to return

    Returns:
        List of error records as dictionaries
    """
    # Ensure table exists (migration for existing databases)
    ensure_scan_errors_table(db)

    sql = "SELECT * FROM scan_errors ORDER BY scanned_at DESC"
    if limit:
        sql += f" LIMIT {limit}"

    db.execute(sql)
    return [dict(row) for row in db.fetchall()]


def get_scan_error_count(db: Database) -> int:
    """Get total count of scan errors."""
    # Ensure table exists (migration for existing databases)
    ensure_scan_errors_table(db)

    db.execute("SELECT COUNT(*) as count FROM scan_errors")
    row = db.fetchone()
    return row['count'] if row else 0


def clear_scan_errors(db: Database) -> int:
    """
    Clear all scan errors.

    Returns:
        Number of errors cleared
    """
    # Ensure table exists (migration for existing databases)
    ensure_scan_errors_table(db)

    db.execute("DELETE FROM scan_errors")
    return db.rowcount


def clear_scan_error_for_path(db: Database, path: str) -> int:
    """
    Clear scan errors for a specific path.

    Args:
        db: Database connection
        path: Path to clear errors for

    Returns:
        Number of errors cleared
    """
    # Ensure table exists (migration for existing databases)
    ensure_scan_errors_table(db)

    db.execute("DELETE FROM scan_errors WHERE path = ?", (path,))
    return db.rowcount
