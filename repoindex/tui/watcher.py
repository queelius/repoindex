"""
File system watcher for repository activity monitoring.
"""

import asyncio
from pathlib import Path
from typing import Dict, Set, Optional, List
from datetime import datetime, timezone
import subprocess
import sys

# Debug log file
DEBUG_LOG = open("/tmp/repoindex_watcher_debug.log", "a")

def debug_log(msg: str):
    """Write to debug log."""
    DEBUG_LOG.write(f"{msg}\n")
    DEBUG_LOG.flush()

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None
    FileSystemEvent = None

from .activity import ActivityFeed, ActivityEvent, EventType, RepositoryStats


class RepositoryEventHandler(FileSystemEventHandler):
    """Handles file system events for a single repository."""

    def __init__(self, repo_path: str, repo_name: str, activity_feed: ActivityFeed, stats: RepositoryStats, loop: asyncio.AbstractEventLoop):
        """Initialize event handler.

        Args:
            repo_path: Path to repository
            repo_name: Repository name
            activity_feed: Activity feed to add events to
            stats: Stats tracker
            loop: Event loop to use for async operations
        """
        super().__init__()
        self.repo_path = repo_path
        self.repo_name = repo_name
        self.activity_feed = activity_feed
        self.stats = stats
        self.loop = loop

        # Track git status
        self._last_git_check = None
        self._is_dirty = False

    def _should_ignore(self, path: str) -> bool:
        """Check if path should be ignored.

        Args:
            path: File path to check

        Returns:
            True if should be ignored
        """
        ignore_patterns = [
            '/.git/',
            '/__pycache__/',
            '/node_modules/',
            '/.venv/',
            '/venv/',
            '/build/',
            '/dist/',
            '/.pytest_cache/',
            '/.mypy_cache/',
            '/.tox/',
            '.pyc',
            '.pyo',
            '.swp',
            '.tmp',
            '~',
        ]

        for pattern in ignore_patterns:
            if pattern in path or path.endswith(pattern.lstrip('/')):
                return True

        return False

    def _get_relative_path(self, full_path: str) -> str:
        """Get path relative to repository root.

        Args:
            full_path: Full file path

        Returns:
            Relative path
        """
        try:
            return str(Path(full_path).relative_to(self.repo_path))
        except ValueError:
            return full_path

    def _add_event(self, event_type: EventType, file_path: Optional[str] = None, message: str = ""):
        """Add event to activity feed.

        Args:
            event_type: Type of event
            file_path: Optional file path
            message: Event message
        """
        debug_log(f"[WATCHER] _add_event called: {event_type} {self.repo_name}/{file_path or message}")

        event = ActivityEvent(
            timestamp=datetime.now(timezone.utc),
            repo_path=self.repo_path,
            repo_name=self.repo_name,
            event_type=event_type,
            file_path=file_path,
            message=message
        )

        debug_log(f"[WATCHER] Event created, adding to feed (loop={self.loop})")

        # Add to feed asynchronously
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.activity_feed.add_event(event),
                self.loop
            )
            debug_log(f"[WATCHER] Scheduled add_event, future={future}")
            # Don't wait for result to avoid blocking the watchdog thread
        except Exception as e:
            debug_log(f"[WATCHER] ERROR scheduling add_event: {e}")

        # Update stats
        if event_type in [EventType.FILE_MODIFIED, EventType.FILE_CREATED, EventType.FILE_DELETED]:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.stats.mark_dirty(self.repo_path),
                    self.loop
                )
                asyncio.run_coroutine_threadsafe(
                    self.stats.mark_active(self.repo_path),
                    self.loop
                )
            except Exception as e:
                debug_log(f"[WATCHER] ERROR scheduling stats update: {e}")

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification."""
        # Debug logging
        debug_log(f"[WATCHER] on_modified: {event.src_path}")

        if event.is_directory:
            debug_log(f"[WATCHER] Ignoring directory: {event.src_path}")
            return

        if self._should_ignore(event.src_path):
            debug_log(f"[WATCHER] Ignoring pattern match: {event.src_path}")
            return

        relative_path = self._get_relative_path(event.src_path)
        debug_log(f"[WATCHER] Adding FILE_MODIFIED event: {self.repo_name}/{relative_path}")
        self._add_event(
            EventType.FILE_MODIFIED,
            relative_path,
            f"{relative_path} modified"
        )

    def on_created(self, event: FileSystemEvent):
        """Handle file creation."""
        if event.is_directory or self._should_ignore(event.src_path):
            return

        relative_path = self._get_relative_path(event.src_path)
        self._add_event(
            EventType.FILE_CREATED,
            relative_path,
            f"{relative_path} created"
        )

    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion."""
        if event.is_directory or self._should_ignore(event.src_path):
            return

        relative_path = self._get_relative_path(event.src_path)
        self._add_event(
            EventType.FILE_DELETED,
            relative_path,
            f"{relative_path} deleted"
        )


class RepositoryWatcher:
    """Watches multiple repositories for file system changes."""

    def __init__(self, activity_feed: ActivityFeed, stats: RepositoryStats):
        """Initialize repository watcher.

        Args:
            activity_feed: Activity feed to add events to
            stats: Stats tracker
        """
        if not WATCHDOG_AVAILABLE:
            raise ImportError("watchdog library not installed. Install with: pip install watchdog")

        self.activity_feed = activity_feed
        self.stats = stats
        self.observer = Observer()
        self.watched_repos: Dict[str, RepositoryEventHandler] = {}
        self.is_watching = False

    def add_repository(self, repo_path: str):
        """Add repository to watch list.

        Args:
            repo_path: Path to repository
        """
        if repo_path in self.watched_repos:
            return  # Already watching

        repo_name = Path(repo_path).name

        # Get the current event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, get the default one
            loop = asyncio.get_event_loop()

        handler = RepositoryEventHandler(
            repo_path,
            repo_name,
            self.activity_feed,
            self.stats,
            loop
        )

        # Watch repository (recursive)
        self.observer.schedule(handler, repo_path, recursive=True)
        self.watched_repos[repo_path] = handler

    def remove_repository(self, repo_path: str):
        """Remove repository from watch list.

        Args:
            repo_path: Path to repository
        """
        if repo_path in self.watched_repos:
            # Note: watchdog doesn't have a clean way to remove individual watches
            # We'd need to restart the observer
            del self.watched_repos[repo_path]

    def start(self):
        """Start watching repositories."""
        if not self.is_watching:
            debug_log(f"[WATCHER] Starting observer, watching {len(self.watched_repos)} repos:")
            for repo_path in self.watched_repos.keys():
                debug_log(f"[WATCHER]   - {Path(repo_path).name}")
            self.observer.start()
            self.is_watching = True
            debug_log(f"[WATCHER] Observer started successfully")

    def stop(self):
        """Stop watching repositories."""
        if self.is_watching:
            self.observer.stop()
            self.observer.join()
            self.is_watching = False

    def pause(self):
        """Pause watching (same as stop for now)."""
        self.stop()

    def resume(self):
        """Resume watching (same as start for now)."""
        self.start()

    def get_watch_count(self) -> int:
        """Get number of watched repositories."""
        return len(self.watched_repos)


class GitStatusPoller:
    """Polls git status periodically for changes."""

    def __init__(
        self,
        activity_feed: ActivityFeed,
        stats: RepositoryStats,
        poll_interval: int = 10
    ):
        """Initialize git status poller.

        Args:
            activity_feed: Activity feed
            stats: Stats tracker
            poll_interval: Seconds between polls
        """
        self.activity_feed = activity_feed
        self.stats = stats
        self.poll_interval = poll_interval
        self.repos: Set[str] = set()
        self.is_polling = False
        self._task: Optional[asyncio.Task] = None
        self._repo_states: Dict[str, Dict] = {}

    def add_repository(self, repo_path: str):
        """Add repository to poll."""
        self.repos.add(repo_path)

    def remove_repository(self, repo_path: str):
        """Remove repository from polling."""
        self.repos.discard(repo_path)

    async def _check_git_status(self, repo_path: str) -> Dict[str, any]:
        """Check git status for a repository.

        Args:
            repo_path: Path to repository

        Returns:
            Status dict
        """
        try:
            # Check if repo is dirty
            result = await asyncio.create_subprocess_exec(
                'git', 'status', '--porcelain',
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            is_dirty = len(stdout.decode().strip()) > 0

            # Check for unpushed commits
            result = await asyncio.create_subprocess_exec(
                'git', 'log', '@{u}..HEAD', '--oneline',
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            unpushed_count = len(stdout.decode().strip().split('\n')) if stdout.decode().strip() else 0

            return {
                "dirty": is_dirty,
                "unpushed": unpushed_count > 0,
                "unpushed_count": unpushed_count
            }

        except Exception:
            return {"dirty": False, "unpushed": False, "unpushed_count": 0}

    async def _poll_loop(self):
        """Main polling loop."""
        while self.is_polling:
            for repo_path in list(self.repos):
                status = await self._check_git_status(repo_path)
                prev_status = self._repo_states.get(repo_path, {})

                repo_name = Path(repo_path).name

                # Check for status changes
                if status["dirty"] and not prev_status.get("dirty"):
                    await self.stats.mark_dirty(repo_path)

                elif not status["dirty"] and prev_status.get("dirty"):
                    # Repo became clean - likely committed
                    await self.stats.mark_clean(repo_path)
                    await self.activity_feed.add_event(ActivityEvent(
                        timestamp=datetime.now(timezone.utc),
                        repo_path=repo_path,
                        repo_name=repo_name,
                        event_type=EventType.GIT_COMMIT,
                        message="Changes committed"
                    ))

                if status["unpushed"] and not prev_status.get("unpushed"):
                    await self.stats.mark_unpushed(repo_path)

                elif not status["unpushed"] and prev_status.get("unpushed"):
                    # Commits were pushed
                    await self.stats.mark_pushed(repo_path)
                    await self.activity_feed.add_event(ActivityEvent(
                        timestamp=datetime.now(timezone.utc),
                        repo_path=repo_path,
                        repo_name=repo_name,
                        event_type=EventType.GIT_PUSH,
                        message="Commits pushed"
                    ))

                self._repo_states[repo_path] = status

            # Wait before next poll
            await asyncio.sleep(self.poll_interval)

    def start(self):
        """Start polling."""
        if not self.is_polling:
            self.is_polling = True
            self._task = asyncio.create_task(self._poll_loop())

    def stop(self):
        """Stop polling."""
        if self.is_polling:
            self.is_polling = False
            if self._task:
                self._task.cancel()
