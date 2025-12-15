"""
Activity monitoring and event tracking for TUI.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
from enum import Enum
import json

# Debug log file
DEBUG_LOG = open("/tmp/repoindex_watcher_debug.log", "a")

def debug_log(msg: str):
    """Write to debug log."""
    DEBUG_LOG.write(f"{msg}\n")
    DEBUG_LOG.flush()


class EventType(Enum):
    """Types of repository events."""
    FILE_MODIFIED = "modified"
    FILE_CREATED = "created"
    FILE_DELETED = "deleted"
    GIT_COMMIT = "commit"
    GIT_PUSH = "push"
    GIT_PULL = "pull"
    TEST_STARTED = "test_started"
    TEST_PASSED = "test_passed"
    TEST_FAILED = "test_failed"
    BUILD_STARTED = "build_started"
    BUILD_SUCCESS = "build_success"
    BUILD_FAILED = "build_failed"


@dataclass
class ActivityEvent:
    """Represents a single activity event."""
    timestamp: datetime
    repo_path: str
    repo_name: str
    event_type: EventType
    file_path: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure timestamp is timezone-aware."""
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    @property
    def age_seconds(self) -> float:
        """Get age of event in seconds."""
        now = datetime.now(timezone.utc)
        return (now - self.timestamp).total_seconds()

    @property
    def age_display(self) -> str:
        """Get human-readable age."""
        seconds = self.age_seconds

        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds / 3600)}h ago"
        else:
            return f"{int(seconds / 86400)}d ago"

    @property
    def icon(self) -> str:
        """Get icon for event type."""
        icons = {
            EventType.FILE_MODIFIED: "🟢",
            EventType.FILE_CREATED: "🟡",
            EventType.FILE_DELETED: "🔴",
            EventType.GIT_COMMIT: "🔵",
            EventType.GIT_PUSH: "📤",
            EventType.GIT_PULL: "📥",
            EventType.TEST_STARTED: "🧪",
            EventType.TEST_PASSED: "✅",
            EventType.TEST_FAILED: "❌",
            EventType.BUILD_STARTED: "🔨",
            EventType.BUILD_SUCCESS: "✅",
            EventType.BUILD_FAILED: "❌",
        }
        return icons.get(self.event_type, "⚪")

    @property
    def color(self) -> str:
        """Get color for event type."""
        colors = {
            EventType.FILE_MODIFIED: "green",
            EventType.FILE_CREATED: "yellow",
            EventType.FILE_DELETED: "red",
            EventType.GIT_COMMIT: "blue",
            EventType.GIT_PUSH: "cyan",
            EventType.GIT_PULL: "cyan",
            EventType.TEST_STARTED: "yellow",
            EventType.TEST_PASSED: "green",
            EventType.TEST_FAILED: "red",
            EventType.BUILD_STARTED: "yellow",
            EventType.BUILD_SUCCESS: "green",
            EventType.BUILD_FAILED: "red",
        }
        return colors.get(self.event_type, "white")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "repo_path": self.repo_path,
            "repo_name": self.repo_name,
            "event_type": self.event_type.value,
            "file_path": self.file_path,
            "message": self.message,
            "details": self.details,
        }


class ActivityFeed:
    """Manages the activity feed and event history."""

    def __init__(self, max_events: int = 500):
        """Initialize activity feed.

        Args:
            max_events: Maximum number of events to keep in memory
        """
        self.max_events = max_events
        self.events: List[ActivityEvent] = []
        self.listeners: List[callable] = []
        self._lock = asyncio.Lock()

    async def add_event(self, event: ActivityEvent):
        """Add event to feed.

        Args:
            event: Event to add
        """
        debug_log(f"[FEED] add_event called: {event.repo_name}/{event.file_path or event.message}")
        async with self._lock:
            self.events.insert(0, event)  # Most recent first
            debug_log(f"[FEED] Event added to feed, total events: {len(self.events)}")

            # Trim old events
            if len(self.events) > self.max_events:
                self.events = self.events[:self.max_events]

            # Notify listeners
            debug_log(f"[FEED] Notifying {len(self.listeners)} listeners")
            for i, listener in enumerate(self.listeners):
                try:
                    debug_log(f"[FEED] Calling listener {i}")
                    if asyncio.iscoroutinefunction(listener):
                        await listener(event)
                    else:
                        listener(event)
                    debug_log(f"[FEED] Listener {i} completed")
                except Exception as e:
                    # Don't let listener errors break the feed
                    debug_log(f"[FEED] Listener {i} error: {e}")

    def add_listener(self, callback: callable):
        """Add event listener.

        Args:
            callback: Function to call when event is added
        """
        self.listeners.append(callback)

    def remove_listener(self, callback: callable):
        """Remove event listener.

        Args:
            callback: Listener to remove
        """
        if callback in self.listeners:
            self.listeners.remove(callback)

    async def get_events(
        self,
        limit: Optional[int] = None,
        repo_path: Optional[str] = None,
        event_types: Optional[Set[EventType]] = None
    ) -> List[ActivityEvent]:
        """Get events with optional filtering.

        Args:
            limit: Maximum number of events to return
            repo_path: Filter by repository path
            event_types: Filter by event types

        Returns:
            List of events
        """
        async with self._lock:
            events = self.events

            # Filter by repo
            if repo_path:
                events = [e for e in events if e.repo_path == repo_path]

            # Filter by event type
            if event_types:
                events = [e for e in events if e.event_type in event_types]

            # Limit results
            if limit:
                events = events[:limit]

            return events

    async def clear(self):
        """Clear all events."""
        async with self._lock:
            self.events.clear()

    async def export_json(self, file_path: str):
        """Export events to JSON file.

        Args:
            file_path: Path to output file
        """
        async with self._lock:
            data = [event.to_dict() for event in self.events]
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)


class RepositoryStats:
    """Track repository statistics for the dashboard."""

    def __init__(self):
        """Initialize stats tracker."""
        self.dirty_repos: Set[str] = set()
        self.unpushed_repos: Set[str] = set()
        self.active_repos: Set[str] = set()  # Active in last 5 minutes
        self.failing_tests: Set[str] = set()
        self.repo_last_activity: Dict[str, datetime] = {}  # Track last activity time
        self._lock = asyncio.Lock()

    async def mark_dirty(self, repo_path: str, activity_time: Optional[datetime] = None):
        """Mark repository as having uncommitted changes."""
        async with self._lock:
            self.dirty_repos.add(repo_path)
            if activity_time:
                self.repo_last_activity[repo_path] = activity_time

    async def mark_clean(self, repo_path: str):
        """Mark repository as clean."""
        async with self._lock:
            self.dirty_repos.discard(repo_path)

    async def mark_unpushed(self, repo_path: str, activity_time: Optional[datetime] = None):
        """Mark repository as having unpushed commits."""
        async with self._lock:
            self.unpushed_repos.add(repo_path)
            if activity_time:
                self.repo_last_activity[repo_path] = activity_time

    async def mark_pushed(self, repo_path: str):
        """Mark repository as pushed."""
        async with self._lock:
            self.unpushed_repos.discard(repo_path)

    async def mark_active(self, repo_path: str):
        """Mark repository as recently active."""
        async with self._lock:
            self.active_repos.add(repo_path)

    async def mark_test_failed(self, repo_path: str):
        """Mark repository as having failing tests."""
        async with self._lock:
            self.failing_tests.add(repo_path)

    async def mark_test_passed(self, repo_path: str):
        """Mark repository tests as passing."""
        async with self._lock:
            self.failing_tests.discard(repo_path)

    async def get_stats(self) -> Dict[str, Any]:
        """Get current statistics.

        Returns:
            Dictionary of stats
        """
        async with self._lock:
            return {
                "dirty": len(self.dirty_repos),
                "unpushed": len(self.unpushed_repos),
                "active": len(self.active_repos),
                "failing_tests": len(self.failing_tests),
            }

    async def get_attention_repos(self) -> List[Dict[str, Any]]:
        """Get repositories that need attention.

        Returns:
            List of repo info dicts
        """
        async with self._lock:
            attention = []

            # Add dirty repos
            for repo in self.dirty_repos:
                attention.append({
                    "path": repo,
                    "name": Path(repo).name,
                    "issues": ["uncommitted changes"],
                    "priority": 2,
                    "last_activity": self.repo_last_activity.get(repo, datetime.min.replace(tzinfo=timezone.utc))
                })

            # Add unpushed repos
            for repo in self.unpushed_repos:
                existing = next((a for a in attention if a["path"] == repo), None)
                if existing:
                    existing["issues"].append("unpushed commits")
                    existing["priority"] = max(existing["priority"], 2)
                else:
                    attention.append({
                        "path": repo,
                        "name": Path(repo).name,
                        "issues": ["unpushed commits"],
                        "priority": 2,
                        "last_activity": self.repo_last_activity.get(repo, datetime.min.replace(tzinfo=timezone.utc))
                    })

            # Add failing tests (highest priority)
            for repo in self.failing_tests:
                existing = next((a for a in attention if a["path"] == repo), None)
                if existing:
                    existing["issues"].append("tests failing")
                    existing["priority"] = 1  # Highest priority
                else:
                    attention.append({
                        "path": repo,
                        "name": Path(repo).name,
                        "issues": ["tests failing"],
                        "priority": 1,
                        "last_activity": self.repo_last_activity.get(repo, datetime.min.replace(tzinfo=timezone.utc))
                    })

            # Sort by priority (highest first), then by most recent activity
            attention.sort(key=lambda x: (x["priority"], -x["last_activity"].timestamp()))

            return attention
