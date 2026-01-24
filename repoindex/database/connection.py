"""
Database connection management for repoindex.

Provides connection pooling, context managers, and configuration.
Uses SQLite with WAL mode for better concurrent access.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Generator

from .schema import ensure_schema


def get_db_path(config: Optional[dict] = None) -> Path:
    """
    Get the database file path.

    Checks in order:
    1. REPOINDEX_DB environment variable
    2. config['database']['path'] if provided
    3. Default: ~/.repoindex/index.db

    Args:
        config: Optional configuration dictionary

    Returns:
        Path to database file
    """
    # Environment variable override
    if 'REPOINDEX_DB' in os.environ:
        return Path(os.environ['REPOINDEX_DB'])

    # Config override
    if config and 'database' in config and 'path' in config['database']:
        return Path(config['database']['path']).expanduser()

    # Default location
    return Path.home() / '.repoindex' / 'index.db'


def get_connection(
    db_path: Optional[Path] = None,
    config: Optional[dict] = None,
    read_only: bool = False
) -> sqlite3.Connection:
    """
    Get a database connection.

    Creates the database and applies schema if it doesn't exist.
    Uses WAL mode for better concurrent access.

    Args:
        db_path: Optional explicit path to database
        config: Optional configuration dictionary
        read_only: If True, open in read-only mode

    Returns:
        SQLite connection
    """
    if db_path is None:
        db_path = get_db_path(config)

    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Build connection URI
    if read_only:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(db_path))

    # Configure connection
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    conn.execute("PRAGMA foreign_keys = ON")  # Enforce foreign keys

    # Use WAL mode for better concurrent access (unless read-only)
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")  # Good performance/safety balance
        conn.execute("PRAGMA cache_size = -64000")  # 64MB cache

    # Ensure schema is current
    if not read_only:
        ensure_schema(conn)

    return conn


class Database:
    """
    Database context manager for repoindex.

    Provides a clean interface for database operations with
    automatic connection management and transaction handling.

    Usage:
        with Database() as db:
            db.execute("SELECT * FROM repos")
            for row in db.fetchall():
                print(row['name'])

        # Or with explicit config
        with Database(config=my_config) as db:
            ...

        # Read-only mode
        with Database(read_only=True) as db:
            ...
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        config: Optional[dict] = None,
        read_only: bool = False
    ):
        self.db_path = db_path
        self.config = config
        self.read_only = read_only
        self._conn: Optional[sqlite3.Connection] = None
        self._cursor: Optional[sqlite3.Cursor] = None

    def __enter__(self) -> 'Database':
        self._conn = get_connection(
            db_path=self.db_path,
            config=self.config,
            read_only=self.read_only
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._cursor:
            self._cursor.close()
        if self._conn:
            if exc_type is None and not self.read_only:
                self._conn.commit()
            self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the underlying connection."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Use 'with Database() as db:'")
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL statement."""
        self._cursor = self.conn.execute(sql, params)
        return self._cursor

    def executemany(self, sql: str, params_seq) -> sqlite3.Cursor:
        """Execute SQL statement with multiple parameter sets."""
        self._cursor = self.conn.executemany(sql, params_seq)
        return self._cursor

    def executescript(self, sql: str) -> sqlite3.Cursor:
        """Execute multiple SQL statements."""
        self._cursor = self.conn.executescript(sql)
        return self._cursor

    def fetchone(self) -> Optional[sqlite3.Row]:
        """Fetch one row from last query."""
        if self._cursor is None:
            return None
        return self._cursor.fetchone()

    def fetchall(self) -> list:
        """Fetch all rows from last query."""
        if self._cursor is None:
            return []
        return self._cursor.fetchall()

    def fetchmany(self, size: int = 100) -> list:
        """Fetch multiple rows from last query."""
        if self._cursor is None:
            return []
        return self._cursor.fetchmany(size)

    def commit(self) -> None:
        """Commit current transaction."""
        self.conn.commit()

    def rollback(self) -> None:
        """Rollback current transaction."""
        self.conn.rollback()

    @property
    def lastrowid(self) -> Optional[int]:
        """Get last inserted row ID."""
        if self._cursor is None:
            return None
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        """Get number of rows affected by last statement."""
        if self._cursor is None:
            return 0
        return self._cursor.rowcount


@contextmanager
def transaction(db: Database) -> Generator[None, None, None]:
    """
    Context manager for explicit transactions.

    Usage:
        with Database() as db:
            with transaction(db):
                db.execute("INSERT ...")
                db.execute("UPDATE ...")
                # Commits on success, rolls back on exception
    """
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


def reset_database(config: Optional[dict] = None) -> None:
    """
    Delete and recreate the database.

    Use with caution - this destroys all data!

    Args:
        config: Optional configuration dictionary
    """
    db_path = get_db_path(config)
    if db_path.exists():
        db_path.unlink()

    # Recreate with fresh schema
    with Database(config=config) as _db:
        pass  # Schema is applied on connection


def get_database_info(config: Optional[dict] = None) -> dict:
    """
    Get information about the database.

    Returns:
        Dictionary with database stats
    """
    db_path = get_db_path(config)

    if not db_path.exists():
        return {
            'exists': False,
            'path': str(db_path),
        }

    with Database(config=config, read_only=True) as db:
        # Get counts
        db.execute("SELECT COUNT(*) FROM repos")
        row = db.fetchone()
        repo_count = row[0] if row else 0

        db.execute("SELECT COUNT(*) FROM events")
        row = db.fetchone()
        event_count = row[0] if row else 0

        db.execute("SELECT COUNT(*) FROM tags")
        row = db.fetchone()
        tag_count = row[0] if row else 0

        db.execute("SELECT COUNT(*) FROM publications")
        row = db.fetchone()
        pub_count = row[0] if row else 0

        # Get schema version
        db.execute("SELECT MAX(version) FROM _schema_info")
        row = db.fetchone()
        schema_version = row[0] if row else 0

        # Get file size
        file_size = db_path.stat().st_size

        return {
            'exists': True,
            'path': str(db_path),
            'size_bytes': file_size,
            'size_human': _human_size(file_size),
            'schema_version': schema_version,
            'repos': repo_count,
            'events': event_count,
            'tags': tag_count,
            'publications': pub_count,
        }


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    size: float = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
