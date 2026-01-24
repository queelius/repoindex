"""
SQLite-based analytics store for repoindex.

Tracks published posts, metrics over time, and event history.
Uses raw SQLite queries (no ORM) for simplicity and performance.
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# Singleton instance
_analytics_store: Optional['AnalyticsStore'] = None


def get_analytics_db_path() -> Path:
    """Get path to analytics database."""
    import os

    # Allow override via environment variable
    if 'REPOINDEX_ANALYTICS_DB' in os.environ:
        return Path(os.environ['REPOINDEX_ANALYTICS_DB'])

    # Default location
    from .config import get_config_path
    config_dir = get_config_path().parent
    return config_dir / 'analytics.db'


class AnalyticsStore:
    """
    SQLite-based storage for analytics data.

    Tracks:
    - Published posts across platforms
    - Metrics collected over time (views, likes, comments, etc.)
    - Events triggered (git tags, releases, etc.)
    - Actions taken in response to events
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize analytics store.

        Args:
            db_path: Path to SQLite database file (default: ~/.repoindex/analytics.db)
        """
        if db_path is None:
            db_path = get_analytics_db_path()

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database schema
        self._init_schema()

        logger.info(f"Analytics store initialized at {self.db_path}")

    @contextmanager
    def _connection(self):
        """Get a database connection context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        """Create database tables if they don't exist."""
        with self._connection() as conn:
            conn.executescript("""
                -- Posts published to platforms
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_path TEXT NOT NULL,
                    version TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    platform_post_id TEXT NOT NULL,
                    url TEXT,
                    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT,  -- JSON
                    UNIQUE(platform, platform_post_id)
                );

                -- Metrics collected over time
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    views INTEGER DEFAULT 0,
                    likes INTEGER DEFAULT 0,
                    comments INTEGER DEFAULT 0,
                    shares INTEGER DEFAULT 0,
                    bookmarks INTEGER DEFAULT 0,
                    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
                );

                -- Events detected
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    repo_path TEXT NOT NULL,
                    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    context TEXT,  -- JSON
                    status TEXT DEFAULT 'pending'  -- pending, processing, completed, failed
                );

                -- Actions taken in response to events
                CREATE TABLE IF NOT EXISTS event_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    platform TEXT,
                    status TEXT,  -- pending, success, failed
                    result TEXT,  -- JSON
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
                );

                -- Indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_posts_repo ON posts(repo_path, published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_posts_platform ON posts(platform, published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_metrics_post ON metrics(post_id, collected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_repo ON events(repo_path, triggered_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, triggered_at DESC);
                CREATE INDEX IF NOT EXISTS idx_actions_event ON event_actions(event_id, created_at DESC);
            """)

    # ============================================================================
    # POSTS
    # ============================================================================

    def record_post(self, repo_path: str, version: str, platform: str,
                   platform_post_id: str, url: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> int:
        """
        Record a published post.

        Args:
            repo_path: Absolute path to repository
            version: Version string (e.g., "0.8.0")
            platform: Platform name (devto, twitter, mastodon, etc.)
            platform_post_id: ID from the platform
            url: URL to the published post
            metadata: Additional metadata (title, tags, etc.)

        Returns:
            Post ID in the database
        """
        metadata_json = json.dumps(metadata) if metadata else None

        with self._connection() as conn:
            cursor = conn.execute("""
                INSERT INTO posts (repo_path, version, platform, platform_post_id, url, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, platform_post_id) DO UPDATE SET
                    url = excluded.url,
                    metadata = excluded.metadata
                RETURNING id
            """, (repo_path, version, platform, platform_post_id, url, metadata_json))

            post_id = cursor.fetchone()[0]
            logger.info(f"Recorded post: {platform}/{platform_post_id} (ID: {post_id})")
            return post_id

    def get_post(self, post_id: int) -> Optional[Dict[str, Any]]:
        """Get a post by ID."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT id, repo_path, version, platform, platform_post_id, url,
                       published_at, metadata
                FROM posts
                WHERE id = ?
            """, (post_id,))

            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row, parse_json=['metadata'])
            return None

    def get_posts_by_repo(self, repo_path: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all posts for a repository."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT id, repo_path, version, platform, platform_post_id, url,
                       published_at, metadata
                FROM posts
                WHERE repo_path = ?
                ORDER BY published_at DESC
                LIMIT ?
            """, (repo_path, limit))

            return [self._row_to_dict(row, parse_json=['metadata'])
                   for row in cursor.fetchall()]

    def get_posts_by_platform(self, platform: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all posts for a platform."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT id, repo_path, version, platform, platform_post_id, url,
                       published_at, metadata
                FROM posts
                WHERE platform = ?
                ORDER BY published_at DESC
                LIMIT ?
            """, (platform, limit))

            return [self._row_to_dict(row, parse_json=['metadata'])
                   for row in cursor.fetchall()]

    # ============================================================================
    # METRICS
    # ============================================================================

    def record_metrics(self, post_id: int, views: int = 0, likes: int = 0,
                      comments: int = 0, shares: int = 0, bookmarks: int = 0):
        """
        Record metrics for a post.

        Args:
            post_id: Post ID from database
            views: View count
            likes: Like/reaction count
            comments: Comment count
            shares: Share/repost count
            bookmarks: Bookmark count
        """
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO metrics (post_id, views, likes, comments, shares, bookmarks)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (post_id, views, likes, comments, shares, bookmarks))

            logger.debug(f"Recorded metrics for post {post_id}: "
                        f"views={views}, likes={likes}, comments={comments}")

    def get_metrics(self, post_id: int, days: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get metrics for a post.

        Args:
            post_id: Post ID
            days: Only return metrics from last N days (default: all)

        Returns:
            List of metric snapshots ordered by collection time
        """
        params: tuple[Any, ...]
        if days:
            cutoff = datetime.now() - timedelta(days=days)
            query = """
                SELECT id, post_id, collected_at, views, likes, comments, shares, bookmarks
                FROM metrics
                WHERE post_id = ? AND collected_at >= ?
                ORDER BY collected_at
            """
            params = (post_id, cutoff)
        else:
            query = """
                SELECT id, post_id, collected_at, views, likes, comments, shares, bookmarks
                FROM metrics
                WHERE post_id = ?
                ORDER BY collected_at
            """
            params = (post_id,)

        with self._connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_latest_metrics(self, post_id: int) -> Optional[Dict[str, Any]]:
        """Get the most recent metrics for a post."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT id, post_id, collected_at, views, likes, comments, shares, bookmarks
                FROM metrics
                WHERE post_id = ?
                ORDER BY collected_at DESC
                LIMIT 1
            """, (post_id,))

            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    # ============================================================================
    # EVENTS
    # ============================================================================

    def record_event(self, event_id: str, event_type: str, repo_path: str,
                    context: Optional[Dict[str, Any]] = None,
                    status: str = 'pending'):
        """
        Record an event.

        Args:
            event_id: Unique event identifier
            event_type: Type of event (git_tag, release_published, etc.)
            repo_path: Repository path
            context: Event context data
            status: Event status (pending, processing, completed, failed)
        """
        context_json = json.dumps(context) if context else None

        with self._connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO events (id, event_type, repo_path, context, status)
                VALUES (?, ?, ?, ?, ?)
            """, (event_id, event_type, repo_path, context_json, status))

            logger.info(f"Recorded event: {event_type} for {repo_path} (ID: {event_id})")

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get an event by ID."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT id, event_type, repo_path, triggered_at, context, status
                FROM events
                WHERE id = ?
            """, (event_id,))

            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row, parse_json=['context'])
            return None

    def get_events(self, repo_path: Optional[str] = None,
                   event_type: Optional[str] = None,
                   limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get events with optional filtering.

        Args:
            repo_path: Filter by repository
            event_type: Filter by event type
            limit: Maximum number of events

        Returns:
            List of events ordered by triggered time (newest first)
        """
        query = """
            SELECT id, event_type, repo_path, triggered_at, context, status
            FROM events
            WHERE 1=1
        """
        params: List[Any] = []

        if repo_path:
            query += " AND repo_path = ?"
            params.append(repo_path)

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        query += " ORDER BY triggered_at DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row, parse_json=['context'])
                   for row in cursor.fetchall()]

    def update_event_status(self, event_id: str, status: str):
        """Update event status."""
        with self._connection() as conn:
            conn.execute("""
                UPDATE events
                SET status = ?
                WHERE id = ?
            """, (status, event_id))

    def record_event_action(self, event_id: str, action_type: str,
                           platform: Optional[str] = None,
                           status: str = 'success',
                           result: Optional[Dict[str, Any]] = None) -> int:
        """
        Record an action taken in response to an event.

        Args:
            event_id: Event ID
            action_type: Type of action (social_post, publish, etc.)
            platform: Platform name (for social posts)
            status: Action status (pending, success, failed)
            result: Action result data

        Returns:
            Action ID
        """
        result_json = json.dumps(result) if result else None

        with self._connection() as conn:
            cursor = conn.execute("""
                INSERT INTO event_actions (event_id, action_type, platform, status, result)
                VALUES (?, ?, ?, ?, ?)
                RETURNING id
            """, (event_id, action_type, platform, status, result_json))

            action_id = cursor.fetchone()[0]
            logger.info(f"Recorded action: {action_type} for event {event_id}")
            return action_id

    def get_event_actions(self, event_id: str) -> List[Dict[str, Any]]:
        """Get all actions for an event."""
        with self._connection() as conn:
            cursor = conn.execute("""
                SELECT id, event_id, action_type, platform, status, result, created_at
                FROM event_actions
                WHERE event_id = ?
                ORDER BY created_at
            """, (event_id,))

            return [self._row_to_dict(row, parse_json=['result'])
                   for row in cursor.fetchall()]

    # ============================================================================
    # ANALYTICS QUERIES
    # ============================================================================

    def get_top_posts(self, metric: str = 'views', platform: Optional[str] = None,
                     limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get top performing posts by a metric.

        Args:
            metric: Metric to sort by (views, likes, comments, shares)
            platform: Filter by platform
            limit: Number of posts to return

        Returns:
            List of posts with their latest metrics
        """
        query = f"""
            SELECT
                p.id,
                p.repo_path,
                p.version,
                p.platform,
                p.url,
                p.published_at,
                m.{metric} as metric_value,
                m.views,
                m.likes,
                m.comments,
                m.shares,
                m.bookmarks,
                m.collected_at as metrics_updated_at
            FROM posts p
            INNER JOIN (
                SELECT post_id, MAX(collected_at) as max_collected
                FROM metrics
                GROUP BY post_id
            ) latest ON p.id = latest.post_id
            INNER JOIN metrics m ON p.id = m.post_id AND m.collected_at = latest.max_collected
        """

        params: List[Any] = []
        if platform:
            query += " WHERE p.platform = ?"
            params.append(platform)

        query += f" ORDER BY m.{metric} DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_engagement_summary(self, repo_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Get overall engagement summary.

        Args:
            repo_path: Filter by repository (optional)

        Returns:
            Dict with total views, likes, comments, shares, posts
        """
        query = """
            SELECT
                COUNT(DISTINCT p.id) as total_posts,
                COALESCE(SUM(m.views), 0) as total_views,
                COALESCE(SUM(m.likes), 0) as total_likes,
                COALESCE(SUM(m.comments), 0) as total_comments,
                COALESCE(SUM(m.shares), 0) as total_shares
            FROM posts p
            LEFT JOIN (
                SELECT post_id, MAX(collected_at) as max_collected
                FROM metrics
                GROUP BY post_id
            ) latest ON p.id = latest.post_id
            LEFT JOIN metrics m ON p.id = m.post_id AND m.collected_at = latest.max_collected
        """

        params = []
        if repo_path:
            query += " WHERE p.repo_path = ?"
            params.append(repo_path)

        with self._connection() as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else {}

    # ============================================================================
    # UTILITIES
    # ============================================================================

    def _row_to_dict(self, row: sqlite3.Row,
                     parse_json: Optional[List[str]] = None) -> Dict[str, Any]:
        """Convert a SQLite row to a dictionary."""
        result = dict(row)

        # Parse JSON fields
        if parse_json:
            for field in parse_json:
                if field in result and result[field]:
                    try:
                        result[field] = json.loads(result[field])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse JSON field: {field}")
                        result[field] = None

        return result

    def vacuum(self):
        """Vacuum the database to reclaim space."""
        with self._connection() as conn:
            conn.execute("VACUUM")
        logger.info("Database vacuumed")

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._connection() as conn:
            stats = {}

            # Table counts
            for table in ['posts', 'metrics', 'events', 'event_actions']:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f'{table}_count'] = cursor.fetchone()[0]

            # Database size
            cursor = conn.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
            stats['db_size_bytes'] = cursor.fetchone()[0]

            return stats


def get_analytics_store() -> AnalyticsStore:
    """Get the singleton analytics store instance."""
    global _analytics_store
    if _analytics_store is None:
        _analytics_store = AnalyticsStore()
    return _analytics_store
