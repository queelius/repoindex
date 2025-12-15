"""
File modification polling system - simpler alternative to watchdog.

Instead of using inotify/watchdog, this polls repositories periodically
to detect file changes by comparing modification timestamps.
"""

import asyncio
from pathlib import Path
from typing import Dict, Set, Optional
from datetime import datetime, timezone
import os

from .activity import ActivityFeed, ActivityEvent, EventType, RepositoryStats, debug_log


class FileModificationPoller:
    """Polls repositories for file modifications using timestamps."""

    def __init__(
        self,
        activity_feed: ActivityFeed,
        stats: RepositoryStats,
        poll_interval: int = 5,  # seconds
        ignore_patterns: Optional[Set[str]] = None
    ):
        """Initialize file modification poller.

        Args:
            activity_feed: Activity feed to add events to
            stats: Stats tracker
            poll_interval: Seconds between polls (default: 5)
            ignore_patterns: Patterns to ignore (default: common build/cache dirs)
        """
        self.activity_feed = activity_feed
        self.stats = stats
        self.poll_interval = poll_interval
        self.repos: Set[str] = set()
        self.is_polling = False
        self._task: Optional[asyncio.Task] = None

        # Track last known modification time for each repo
        self._repo_max_mtime: Dict[str, float] = {}

        # Default ignore patterns
        self.ignore_patterns = ignore_patterns or {
            '.git',
            '__pycache__',
            'node_modules',
            '.venv',
            'venv',
            'build',
            'dist',
            '.pytest_cache',
            '.mypy_cache',
            '.tox',
            '.eggs',
            '*.egg-info',
            '.coverage',
            'htmlcov',
            '.idea',
            '.vscode',
            '*.pyc',
            '*.pyo',
            '*.swp',
            '*.swo',
            '*~',
            '.DS_Store',
        }

    def add_repository(self, repo_path: str):
        """Add repository to poll.

        Args:
            repo_path: Path to repository
        """
        self.repos.add(repo_path)
        # Initialize with current max mtime
        try:
            max_mtime = self._get_max_mtime(repo_path)
            self._repo_max_mtime[repo_path] = max_mtime
            debug_log(f"[FILE_POLLER] Added repo {Path(repo_path).name}, initial mtime: {max_mtime}")
        except Exception as e:
            debug_log(f"[FILE_POLLER] Error adding repo {repo_path}: {e}")

    def remove_repository(self, repo_path: str):
        """Remove repository from polling.

        Args:
            repo_path: Path to repository
        """
        self.repos.discard(repo_path)
        self._repo_max_mtime.pop(repo_path, None)

    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored.

        Args:
            path: Path to check

        Returns:
            True if should be ignored
        """
        path_str = str(path)
        path_parts = path.parts

        for pattern in self.ignore_patterns:
            # Check if pattern is in path parts (for directories)
            if pattern.replace('*', '') in path_parts:
                return True
            # Check if path matches pattern (for files)
            if pattern.startswith('*'):
                if path_str.endswith(pattern[1:]):
                    return True
            elif pattern in path_str:
                return True

        return False

    def _get_max_mtime(self, repo_path: str) -> float:
        """Get the maximum modification time of all files in repo.

        Args:
            repo_path: Path to repository

        Returns:
            Maximum modification time (seconds since epoch)
        """
        max_mtime = 0.0
        repo_path_obj = Path(repo_path)

        try:
            for root, dirs, files in os.walk(repo_path):
                root_path = Path(root)

                # Filter out ignored directories in-place to prevent walking them
                dirs[:] = [d for d in dirs if not self._should_ignore(root_path / d)]

                for file in files:
                    file_path = root_path / file
                    if self._should_ignore(file_path):
                        continue

                    try:
                        mtime = file_path.stat().st_mtime
                        if mtime > max_mtime:
                            max_mtime = mtime
                    except (OSError, PermissionError):
                        # Skip files we can't stat
                        continue

        except Exception as e:
            debug_log(f"[FILE_POLLER] Error scanning {repo_path}: {e}")

        return max_mtime

    def _get_modified_files(self, repo_path: str, since_mtime: float) -> list[tuple[str, float]]:
        """Get files modified after a certain time.

        Args:
            repo_path: Path to repository
            since_mtime: Only return files modified after this time

        Returns:
            List of (relative_path, mtime) tuples for modified files
        """
        modified_files = []
        repo_path_obj = Path(repo_path)

        try:
            for root, dirs, files in os.walk(repo_path):
                root_path = Path(root)

                # Filter out ignored directories
                dirs[:] = [d for d in dirs if not self._should_ignore(root_path / d)]

                for file in files:
                    file_path = root_path / file
                    if self._should_ignore(file_path):
                        continue

                    try:
                        mtime = file_path.stat().st_mtime
                        if mtime > since_mtime:
                            relative_path = file_path.relative_to(repo_path_obj)
                            modified_files.append((str(relative_path), mtime))
                    except (OSError, PermissionError):
                        continue

        except Exception as e:
            debug_log(f"[FILE_POLLER] Error finding modified files in {repo_path}: {e}")

        return modified_files

    async def _poll_loop(self):
        """Main polling loop."""
        debug_log(f"[FILE_POLLER] Poll loop started, interval={self.poll_interval}s, repos={len(self.repos)}")

        while self.is_polling:
            try:
                start_time = asyncio.get_event_loop().time()

                # Check repos in parallel batches to avoid blocking
                repo_list = list(self.repos)
                batch_size = 10  # Check 10 repos at a time

                for i in range(0, len(repo_list), batch_size):
                    batch = repo_list[i:i + batch_size]
                    # Run batch checks concurrently
                    await asyncio.gather(*[self._check_repo(repo) for repo in batch], return_exceptions=True)

                elapsed = asyncio.get_event_loop().time() - start_time
                debug_log(f"[FILE_POLLER] Scan completed in {elapsed:.2f}s")

                # Wait before next poll
                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log(f"[FILE_POLLER] Error in poll loop: {e}")
                # Continue polling despite errors
                await asyncio.sleep(self.poll_interval)

    async def _check_repo(self, repo_path: str):
        """Check a single repository for changes.

        Args:
            repo_path: Path to repository
        """
        try:
            repo_name = Path(repo_path).name
            old_mtime = self._repo_max_mtime.get(repo_path, 0.0)

            # Get current max mtime (run in thread pool to avoid blocking)
            loop = asyncio.get_event_loop()
            new_mtime = await loop.run_in_executor(None, self._get_max_mtime, repo_path)

            if new_mtime > old_mtime:
                debug_log(f"[FILE_POLLER] {repo_name}: mtime changed {old_mtime} -> {new_mtime}")

                # Find which files were modified
                modified_files = self._get_modified_files(repo_path, old_mtime)

                debug_log(f"[FILE_POLLER] {repo_name}: {len(modified_files)} files modified")

                # Create events for modified files (limit to first 10 to avoid spam)
                for file_path, mtime in modified_files[:10]:
                    event = ActivityEvent(
                        timestamp=datetime.now(timezone.utc),
                        repo_path=repo_path,
                        repo_name=repo_name,
                        event_type=EventType.FILE_MODIFIED,
                        file_path=file_path,
                        message=f"{file_path} modified"
                    )
                    await self.activity_feed.add_event(event)

                # If more than 10 files changed, create a summary event
                if len(modified_files) > 10:
                    event = ActivityEvent(
                        timestamp=datetime.now(timezone.utc),
                        repo_path=repo_path,
                        repo_name=repo_name,
                        event_type=EventType.FILE_MODIFIED,
                        message=f"{len(modified_files) - 10} more files modified"
                    )
                    await self.activity_feed.add_event(event)

                # Update stats
                await self.stats.mark_dirty(repo_path)
                await self.stats.mark_active(repo_path)

                # Update stored mtime
                self._repo_max_mtime[repo_path] = new_mtime

        except Exception as e:
            debug_log(f"[FILE_POLLER] Error checking {repo_path}: {e}")

    def start(self):
        """Start polling."""
        if not self.is_polling:
            self.is_polling = True
            self._task = asyncio.create_task(self._poll_loop())
            debug_log(f"[FILE_POLLER] Started polling {len(self.repos)} repos every {self.poll_interval}s")

    def stop(self):
        """Stop polling."""
        if self.is_polling:
            self.is_polling = False
            if self._task:
                self._task.cancel()
            debug_log("[FILE_POLLER] Stopped polling")

    def set_poll_interval(self, interval: int):
        """Change polling interval.

        Args:
            interval: New interval in seconds
        """
        self.poll_interval = interval
        debug_log(f"[FILE_POLLER] Poll interval changed to {interval}s")
