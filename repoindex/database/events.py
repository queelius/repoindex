"""
Event database operations for repoindex.

Provides CRUD operations for events (commits, tags, releases, etc.)
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Generator

from ..domain.event import Event
from .connection import Database


def insert_event(db: Database, event: Event, repo_id: int) -> int:
    """
    Insert an event.

    Args:
        db: Database connection
        event: Event domain object
        repo_id: ID of the associated repository

    Returns:
        Row ID of the inserted event
    """
    db.execute("""
        INSERT OR IGNORE INTO events
        (repo_id, event_id, type, timestamp, ref, message, author, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        repo_id,
        event.id,  # Stable event ID for deduplication
        event.type,
        event.timestamp.isoformat(),
        event.data.get('ref') or event.data.get('tag') or event.data.get('branch'),
        event.data.get('message'),
        event.data.get('author'),
        json.dumps(event.data),
    ))
    return db.lastrowid or 0


def insert_events(db: Database, events: List[Event], repo_id: int) -> int:
    """
    Insert multiple events efficiently.

    Args:
        db: Database connection
        events: List of Event domain objects
        repo_id: ID of the associated repository

    Returns:
        Number of events inserted
    """
    inserted = 0
    for event in events:
        result = insert_event(db, event, repo_id)
        if result:
            inserted += 1
    return inserted


def get_events(
    db: Database,
    repo_id: Optional[int] = None,
    event_type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Query events with optional filters.

    Args:
        db: Database connection
        repo_id: Filter by repository ID
        event_type: Filter by event type
        since: Filter events after this time
        until: Filter events before this time
        limit: Maximum number of events to return

    Yields:
        Event records as dictionaries
    """
    conditions: List[str] = []
    params: List[Any] = []

    if repo_id is not None:
        conditions.append("e.repo_id = ?")
        params.append(repo_id)

    if event_type is not None:
        conditions.append("e.type = ?")
        params.append(event_type)

    if since is not None:
        conditions.append("e.timestamp >= ?")
        params.append(since.isoformat())

    if until is not None:
        conditions.append("e.timestamp <= ?")
        params.append(until.isoformat())

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    limit_clause = f"LIMIT {limit}" if limit else ""

    sql = f"""
        SELECT e.*, r.name as repo_name, r.path as repo_path
        FROM events e
        JOIN repos r ON r.id = e.repo_id
        WHERE {where_clause}
        ORDER BY e.timestamp DESC
        {limit_clause}
    """

    db.execute(sql, tuple(params))
    for row in db.fetchall():
        record = dict(row)
        # Parse metadata JSON
        if record.get('metadata'):
            try:
                record['data'] = json.loads(record['metadata'])
            except json.JSONDecodeError:
                record['data'] = {}
        else:
            record['data'] = {}
        yield record


def get_events_for_repo(
    db: Database,
    repo_id: int,
    event_type: Optional[str] = None,
    limit: int = 100
) -> Generator[Dict[str, Any], None, None]:
    """Get events for a specific repository."""
    yield from get_events(
        db,
        repo_id=repo_id,
        event_type=event_type,
        limit=limit
    )


def get_recent_events(
    db: Database,
    days: int = 7,
    event_type: Optional[str] = None,
    limit: int = 100
) -> Generator[Dict[str, Any], None, None]:
    """Get events from the last N days."""
    since = datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Subtract days (simple approach)
    from datetime import timedelta
    since = since - timedelta(days=days)

    yield from get_events(
        db,
        event_type=event_type,
        since=since,
        limit=limit
    )


def count_events(
    db: Database,
    repo_id: Optional[int] = None,
    event_type: Optional[str] = None,
    since: Optional[datetime] = None,
) -> int:
    """Count events matching criteria."""
    conditions: List[str] = []
    params: List[Any] = []

    if repo_id is not None:
        conditions.append("repo_id = ?")
        params.append(repo_id)

    if event_type is not None:
        conditions.append("type = ?")
        params.append(event_type)

    if since is not None:
        conditions.append("timestamp >= ?")
        params.append(since.isoformat())

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    db.execute(f"SELECT COUNT(*) FROM events WHERE {where_clause}", tuple(params))
    row = db.fetchone()
    return row[0] if row else 0


def delete_events_for_repo(db: Database, repo_id: int) -> int:
    """Delete all events for a repository."""
    db.execute("DELETE FROM events WHERE repo_id = ?", (repo_id,))
    return db.rowcount


def get_event_types(db: Database) -> List[str]:
    """Get list of distinct event types in database."""
    db.execute("SELECT DISTINCT type FROM events ORDER BY type")
    return [row['type'] for row in db.fetchall()]


def get_event_summary(db: Database, days: int = 30) -> Dict[str, Any]:
    """
    Get summary of events for the last N days.

    Returns:
        Dictionary with event type counts and totals
    """
    from datetime import timedelta
    since = datetime.now() - timedelta(days=days)

    db.execute("""
        SELECT type, COUNT(*) as count
        FROM events
        WHERE timestamp >= ?
        GROUP BY type
        ORDER BY count DESC
    """, (since.isoformat(),))

    by_type = {row['type']: row['count'] for row in db.fetchall()}

    db.execute("""
        SELECT COUNT(*) as total, COUNT(DISTINCT repo_id) as repos
        FROM events
        WHERE timestamp >= ?
    """, (since.isoformat(),))
    row = db.fetchone()

    return {
        'period_days': days,
        'total_events': row['total'] if row else 0,
        'repos_with_events': row['repos'] if row else 0,
        'by_type': by_type,
    }


def record_to_domain(record: Dict[str, Any]) -> Event:
    """
    Convert a database record to an Event domain object.

    Args:
        record: Database row as dictionary

    Returns:
        Event domain object
    """
    timestamp = record['timestamp']
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)

    data = record.get('data', {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}

    return Event(
        type=record['type'],
        timestamp=timestamp,
        repo_name=record.get('repo_name', ''),
        repo_path=record.get('repo_path', ''),
        data=data,
    )


def has_event(
    db: Database,
    repo_id: int,
    event_type: str,
    since: Optional[datetime] = None
) -> bool:
    """
    Check if a repository has any matching events.

    This is used for cross-domain queries like:
    "repos where has_event('commit', since='30d')"

    Args:
        db: Database connection
        repo_id: Repository ID
        event_type: Type of event to check for
        since: Optional minimum timestamp

    Returns:
        True if matching event exists
    """
    conditions = ["repo_id = ?", "type = ?"]
    params = [repo_id, event_type]

    if since:
        conditions.append("timestamp >= ?")
        params.append(since.isoformat())

    where_clause = " AND ".join(conditions)
    db.execute(
        f"SELECT 1 FROM events WHERE {where_clause} LIMIT 1",
        tuple(params)
    )
    return db.fetchone() is not None


def event_count(
    db: Database,
    repo_id: int,
    event_type: str,
    since: Optional[datetime] = None
) -> int:
    """
    Count matching events for a repository.

    This is used for cross-domain queries like:
    "repos where event_count('commit', since='30d') > 10"

    Args:
        db: Database connection
        repo_id: Repository ID
        event_type: Type of event to count
        since: Optional minimum timestamp

    Returns:
        Count of matching events
    """
    conditions = ["repo_id = ?", "type = ?"]
    params = [repo_id, event_type]

    if since:
        conditions.append("timestamp >= ?")
        params.append(since.isoformat())

    where_clause = " AND ".join(conditions)
    db.execute(
        f"SELECT COUNT(*) FROM events WHERE {where_clause}",
        tuple(params)
    )
    row = db.fetchone()
    return row[0] if row else 0


def last_event_timestamp(
    db: Database,
    repo_id: int,
    event_type: str
) -> Optional[datetime]:
    """
    Get timestamp of most recent matching event.

    Args:
        db: Database connection
        repo_id: Repository ID
        event_type: Type of event

    Returns:
        Timestamp of most recent event, or None
    """
    db.execute("""
        SELECT MAX(timestamp) as ts
        FROM events
        WHERE repo_id = ? AND type = ?
    """, (repo_id, event_type))

    row = db.fetchone()
    if row and row['ts']:
        return datetime.fromisoformat(row['ts'])
    return None
