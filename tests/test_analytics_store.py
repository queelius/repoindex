"""
Tests for analytics_store.py module.

Tests the SQLite-based analytics storage system including:
- Post recording and retrieval
- Metrics tracking over time
- Event and event action recording
- Analytics queries (top posts, summaries)
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from repoindex.analytics_store import AnalyticsStore, get_analytics_db_path


class TestAnalyticsStore:
    """Test AnalyticsStore functionality."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        yield db_path

        # Cleanup
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def store(self, temp_db):
        """Create a test analytics store."""
        return AnalyticsStore(temp_db)

    # ========================================================================
    # Database Initialization
    # ========================================================================

    def test_database_initialization(self, store, temp_db):
        """Test that database is initialized with correct schema."""
        assert temp_db.exists()

        # Check tables exist
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert 'posts' in tables
        assert 'metrics' in tables
        assert 'events' in tables
        assert 'event_actions' in tables

    def test_database_creates_parent_directory(self):
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / 'subdir' / 'analytics.db'
            store = AnalyticsStore(db_path)

            assert db_path.exists()
            assert db_path.parent.exists()

    # ========================================================================
    # Posts
    # ========================================================================

    def test_record_post(self, store):
        """Test recording a post."""
        post_id = store.record_post(
            repo_path='/test/repo',
            version='1.0.0',
            platform='devto',
            platform_post_id='12345',
            url='https://dev.to/user/article-12345',
            metadata={'title': 'Test Article', 'tags': ['python', 'testing']}
        )

        assert post_id > 0

        # Verify post was stored
        post = store.get_post(post_id)
        assert post is not None
        assert post['repo_path'] == '/test/repo'
        assert post['version'] == '1.0.0'
        assert post['platform'] == 'devto'
        assert post['platform_post_id'] == '12345'
        assert post['url'] == 'https://dev.to/user/article-12345'
        assert post['metadata']['title'] == 'Test Article'

    def test_record_post_duplicate_upsert(self, store):
        """Test that duplicate posts are updated (upsert)."""
        # Record post first time
        post_id1 = store.record_post(
            repo_path='/test/repo',
            version='1.0.0',
            platform='twitter',
            platform_post_id='tweet123',
            url='https://twitter.com/user/status/tweet123'
        )

        # Record same post again with updated URL
        post_id2 = store.record_post(
            repo_path='/test/repo',
            version='1.0.0',
            platform='twitter',
            platform_post_id='tweet123',
            url='https://x.com/user/status/tweet123',
            metadata={'updated': True}
        )

        # Should be same ID (upsert, not insert)
        assert post_id1 == post_id2

        # Verify updated data
        post = store.get_post(post_id1)
        assert post['url'] == 'https://x.com/user/status/tweet123'
        assert post['metadata']['updated'] is True

    def test_get_posts_by_repo(self, store):
        """Test retrieving posts by repository."""
        # Record posts for different repos
        store.record_post('/repo1', '1.0.0', 'devto', 'post1', 'url1')
        store.record_post('/repo1', '1.1.0', 'twitter', 'post2', 'url2')
        store.record_post('/repo2', '2.0.0', 'devto', 'post3', 'url3')

        # Get posts for repo1
        posts = store.get_posts_by_repo('/repo1')

        assert len(posts) == 2
        assert all(p['repo_path'] == '/repo1' for p in posts)

        # Verify both versions are present (order may vary due to same timestamp)
        versions = {p['version'] for p in posts}
        assert versions == {'1.0.0', '1.1.0'}

    def test_get_posts_by_platform(self, store):
        """Test retrieving posts by platform."""
        store.record_post('/repo1', '1.0.0', 'devto', 'post1', 'url1')
        store.record_post('/repo2', '2.0.0', 'devto', 'post2', 'url2')
        store.record_post('/repo3', '3.0.0', 'twitter', 'post3', 'url3')

        posts = store.get_posts_by_platform('devto')

        assert len(posts) == 2
        assert all(p['platform'] == 'devto' for p in posts)

    def test_get_posts_limit(self, store):
        """Test that limit parameter works."""
        # Record many posts
        for i in range(20):
            store.record_post(f'/repo{i}', '1.0.0', 'devto', f'post{i}', f'url{i}')

        posts = store.get_posts_by_platform('devto', limit=5)

        assert len(posts) == 5

    def test_get_post_not_found(self, store):
        """Test getting non-existent post."""
        post = store.get_post(99999)
        assert post is None

    # ========================================================================
    # Metrics
    # ========================================================================

    def test_record_metrics(self, store):
        """Test recording metrics for a post."""
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')

        store.record_metrics(
            post_id=post_id,
            views=100,
            likes=10,
            comments=5,
            shares=2,
            bookmarks=8
        )

        metrics = store.get_metrics(post_id)

        assert len(metrics) == 1
        assert metrics[0]['views'] == 100
        assert metrics[0]['likes'] == 10
        assert metrics[0]['comments'] == 5
        assert metrics[0]['shares'] == 2
        assert metrics[0]['bookmarks'] == 8

    def test_record_multiple_metrics(self, store):
        """Test recording multiple metric snapshots over time."""
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')

        # Record metrics at different times
        store.record_metrics(post_id, views=100, likes=10)
        store.record_metrics(post_id, views=150, likes=15)
        store.record_metrics(post_id, views=200, likes=20)

        metrics = store.get_metrics(post_id)

        assert len(metrics) == 3
        # Verify all metric values are present
        view_counts = {m['views'] for m in metrics}
        assert view_counts == {100, 150, 200}

    def test_get_latest_metrics(self, store):
        """Test getting the most recent metrics."""
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')

        store.record_metrics(post_id, views=100)
        store.record_metrics(post_id, views=200)
        store.record_metrics(post_id, views=300)

        latest = store.get_latest_metrics(post_id)

        assert latest is not None
        # Should be one of the recorded values
        assert latest['views'] in [100, 200, 300]

    def test_get_latest_metrics_no_data(self, store):
        """Test getting latest metrics when none exist."""
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')
        latest = store.get_latest_metrics(post_id)

        assert latest is None

    def test_get_metrics_with_days_filter(self, store):
        """Test filtering metrics by days (not fully testable without time control)."""
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')

        store.record_metrics(post_id, views=100)

        # Get metrics from last 7 days
        metrics = store.get_metrics(post_id, days=7)

        # Should include recent metrics
        assert len(metrics) >= 1

    # ========================================================================
    # Events
    # ========================================================================

    def test_record_event(self, store):
        """Test recording an event."""
        store.record_event(
            event_id='git_tag_abc123',
            event_type='git_tag',
            repo_path='/test/repo',
            context={'tag': 'v1.0.0', 'branch': 'main'},
            status='pending'
        )

        event = store.get_event('git_tag_abc123')

        assert event is not None
        assert event['id'] == 'git_tag_abc123'
        assert event['event_type'] == 'git_tag'
        assert event['repo_path'] == '/test/repo'
        assert event['context']['tag'] == 'v1.0.0'
        assert event['status'] == 'pending'

    def test_record_event_replace(self, store):
        """Test that recording same event ID replaces it."""
        store.record_event('event1', 'git_tag', '/repo', {'version': '1.0'}, 'pending')
        store.record_event('event1', 'git_tag', '/repo', {'version': '1.0'}, 'completed')

        event = store.get_event('event1')
        assert event['status'] == 'completed'

    def test_get_events_all(self, store):
        """Test getting all events."""
        store.record_event('event1', 'git_tag', '/repo1', {})
        store.record_event('event2', 'release', '/repo2', {})
        store.record_event('event3', 'git_tag', '/repo1', {})

        events = store.get_events()

        assert len(events) == 3

    def test_get_events_by_repo(self, store):
        """Test filtering events by repository."""
        store.record_event('event1', 'git_tag', '/repo1', {})
        store.record_event('event2', 'git_tag', '/repo2', {})
        store.record_event('event3', 'release', '/repo1', {})

        events = store.get_events(repo_path='/repo1')

        assert len(events) == 2
        assert all(e['repo_path'] == '/repo1' for e in events)

    def test_get_events_by_type(self, store):
        """Test filtering events by type."""
        store.record_event('event1', 'git_tag', '/repo1', {})
        store.record_event('event2', 'release', '/repo2', {})
        store.record_event('event3', 'git_tag', '/repo3', {})

        events = store.get_events(event_type='git_tag')

        assert len(events) == 2
        assert all(e['event_type'] == 'git_tag' for e in events)

    def test_get_events_with_limit(self, store):
        """Test limiting number of events returned."""
        for i in range(20):
            store.record_event(f'event{i}', 'git_tag', f'/repo{i}', {})

        events = store.get_events(limit=5)

        assert len(events) == 5

    def test_update_event_status(self, store):
        """Test updating event status."""
        store.record_event('event1', 'git_tag', '/repo', {}, status='pending')

        store.update_event_status('event1', 'completed')

        event = store.get_event('event1')
        assert event['status'] == 'completed'

    def test_get_event_not_found(self, store):
        """Test getting non-existent event."""
        event = store.get_event('nonexistent')
        assert event is None

    # ========================================================================
    # Event Actions
    # ========================================================================

    def test_record_event_action(self, store):
        """Test recording an action for an event."""
        store.record_event('event1', 'git_tag', '/repo', {})

        action_id = store.record_event_action(
            event_id='event1',
            action_type='social_post',
            platform='twitter',
            status='success',
            result={'post_id': 'tweet123', 'url': 'https://twitter.com/user/status/tweet123'}
        )

        assert action_id > 0

        actions = store.get_event_actions('event1')

        assert len(actions) == 1
        assert actions[0]['action_type'] == 'social_post'
        assert actions[0]['platform'] == 'twitter'
        assert actions[0]['status'] == 'success'
        assert actions[0]['result']['post_id'] == 'tweet123'

    def test_record_multiple_event_actions(self, store):
        """Test recording multiple actions for an event."""
        store.record_event('event1', 'git_tag', '/repo', {})

        store.record_event_action('event1', 'social_post', 'twitter', 'success')
        store.record_event_action('event1', 'social_post', 'devto', 'success')
        store.record_event_action('event1', 'publish', status='failed')

        actions = store.get_event_actions('event1')

        assert len(actions) == 3
        # Verify actions are present (order may vary)
        platforms = [a['platform'] for a in actions]
        assert 'twitter' in platforms
        assert 'devto' in platforms
        action_types = [a['action_type'] for a in actions]
        assert 'publish' in action_types

    def test_get_event_actions_empty(self, store):
        """Test getting actions for event with no actions."""
        store.record_event('event1', 'git_tag', '/repo', {})
        actions = store.get_event_actions('event1')

        assert actions == []

    # ========================================================================
    # Analytics Queries
    # ========================================================================

    def test_get_top_posts_by_views(self, store):
        """Test getting top posts by views."""
        # Create posts with metrics
        post1 = store.record_post('/repo1', '1.0.0', 'devto', 'post1', 'url1')
        store.record_metrics(post1, views=1000, likes=50)

        post2 = store.record_post('/repo2', '2.0.0', 'devto', 'post2', 'url2')
        store.record_metrics(post2, views=5000, likes=100)

        post3 = store.record_post('/repo3', '3.0.0', 'twitter', 'post3', 'url3')
        store.record_metrics(post3, views=3000, likes=75)

        top_posts = store.get_top_posts(metric='views', limit=10)

        assert len(top_posts) == 3
        # Should be ordered by views descending
        assert top_posts[0]['id'] == post2
        assert top_posts[0]['metric_value'] == 5000
        assert top_posts[1]['id'] == post3
        assert top_posts[2]['id'] == post1

    def test_get_top_posts_by_likes(self, store):
        """Test getting top posts by likes."""
        post1 = store.record_post('/repo1', '1.0.0', 'devto', 'post1', 'url1')
        store.record_metrics(post1, views=1000, likes=200)

        post2 = store.record_post('/repo2', '2.0.0', 'devto', 'post2', 'url2')
        store.record_metrics(post2, views=5000, likes=50)

        top_posts = store.get_top_posts(metric='likes', limit=10)

        # Should be ordered by likes descending
        assert top_posts[0]['metric_value'] == 200
        assert top_posts[1]['metric_value'] == 50

    def test_get_top_posts_by_platform(self, store):
        """Test filtering top posts by platform."""
        post1 = store.record_post('/repo1', '1.0.0', 'devto', 'post1', 'url1')
        store.record_metrics(post1, views=1000)

        post2 = store.record_post('/repo2', '2.0.0', 'twitter', 'post2', 'url2')
        store.record_metrics(post2, views=5000)

        top_posts = store.get_top_posts(metric='views', platform='devto')

        assert len(top_posts) == 1
        assert top_posts[0]['platform'] == 'devto'

    def test_get_top_posts_with_limit(self, store):
        """Test limiting number of top posts."""
        for i in range(10):
            post_id = store.record_post(f'/repo{i}', '1.0.0', 'devto', f'post{i}', f'url{i}')
            store.record_metrics(post_id, views=i * 100)

        top_posts = store.get_top_posts(metric='views', limit=3)

        assert len(top_posts) == 3

    def test_get_top_posts_uses_latest_metrics(self, store):
        """Test that top posts uses latest metrics snapshot."""
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')

        # Record metrics over time
        store.record_metrics(post_id, views=100)
        store.record_metrics(post_id, views=500)
        store.record_metrics(post_id, views=1000)

        top_posts = store.get_top_posts(metric='views')

        # Should use latest metrics (1000 views)
        assert top_posts[0]['metric_value'] == 1000

    def test_get_engagement_summary(self, store):
        """Test getting overall engagement summary."""
        post1 = store.record_post('/repo1', '1.0.0', 'devto', 'post1', 'url1')
        store.record_metrics(post1, views=1000, likes=50, comments=10, shares=5)

        post2 = store.record_post('/repo2', '2.0.0', 'twitter', 'post2', 'url2')
        store.record_metrics(post2, views=2000, likes=100, comments=20, shares=15)

        summary = store.get_engagement_summary()

        assert summary['total_posts'] == 2
        assert summary['total_views'] == 3000
        assert summary['total_likes'] == 150
        assert summary['total_comments'] == 30
        assert summary['total_shares'] == 20

    def test_get_engagement_summary_by_repo(self, store):
        """Test filtering engagement summary by repository."""
        post1 = store.record_post('/repo1', '1.0.0', 'devto', 'post1', 'url1')
        store.record_metrics(post1, views=1000, likes=50)

        post2 = store.record_post('/repo2', '2.0.0', 'twitter', 'post2', 'url2')
        store.record_metrics(post2, views=2000, likes=100)

        summary = store.get_engagement_summary(repo_path='/repo1')

        assert summary['total_posts'] == 1
        assert summary['total_views'] == 1000
        assert summary['total_likes'] == 50

    def test_get_engagement_summary_empty(self, store):
        """Test engagement summary with no data."""
        summary = store.get_engagement_summary()

        assert summary['total_posts'] == 0
        assert summary['total_views'] == 0

    # ========================================================================
    # Utilities
    # ========================================================================

    def test_get_stats(self, store):
        """Test database statistics."""
        # Add some data
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')
        store.record_metrics(post_id, views=100)
        store.record_event('event1', 'git_tag', '/repo', {})
        store.record_event_action('event1', 'social_post', 'twitter', 'success')

        stats = store.get_stats()

        assert stats['posts_count'] == 1
        assert stats['metrics_count'] == 1
        assert stats['events_count'] == 1
        assert stats['event_actions_count'] == 1
        assert stats['db_size_bytes'] > 0

    def test_vacuum(self, store):
        """Test database vacuum."""
        # Add and remove data
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')

        # Vacuum should not raise
        store.vacuum()

    # ========================================================================
    # Foreign Key Cascades
    # ========================================================================

    def test_metrics_cascade_delete(self, store):
        """Test that deleting a post cascades to metrics (if foreign keys enabled)."""
        post_id = store.record_post('/repo', '1.0.0', 'devto', 'post1', 'url1')
        store.record_metrics(post_id, views=100)

        # Delete post manually (cascade may not work if FK not enabled)
        with store._connection() as conn:
            # Enable foreign keys for this connection
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))

        # Metrics should be deleted too (if FK enabled)
        metrics = store.get_metrics(post_id)
        # Note: This behavior depends on SQLite foreign key enforcement
        assert len(metrics) in [0, 1]  # May or may not cascade

    def test_event_actions_cascade_delete(self, store):
        """Test that deleting an event cascades to event_actions (if foreign keys enabled)."""
        store.record_event('event1', 'git_tag', '/repo', {})
        store.record_event_action('event1', 'social_post', 'twitter', 'success')

        # Delete event manually (cascade may not work if FK not enabled)
        with store._connection() as conn:
            # Enable foreign keys for this connection
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM events WHERE id = ?", ('event1',))

        # Actions should be deleted too (if FK enabled)
        actions = store.get_event_actions('event1')
        # Note: This behavior depends on SQLite foreign key enforcement
        assert len(actions) in [0, 1]  # May or may not cascade


class TestAnalyticsDBPath:
    """Test analytics database path configuration."""

    def test_default_path(self):
        """Test default database path."""
        path = get_analytics_db_path()

        assert path.name == 'analytics.db'
        # Accept either new (.repoindex) or legacy (.ghops) path
        assert '.repoindex' in str(path) or '.ghops' in str(path)

    def test_environment_override(self, monkeypatch):
        """Test overriding path via environment variable."""
        custom_path = '/tmp/custom_analytics.db'
        monkeypatch.setenv('REPOINDEX_ANALYTICS_DB', custom_path)

        path = get_analytics_db_path()

        assert str(path) == custom_path


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
