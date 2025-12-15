"""
Event service for ghops.

Provides stateless event scanning across repositories.
This is a thin wrapper around the events module that works with
Repository domain objects.
"""

from typing import Generator, List, Optional, Iterable
from datetime import datetime, timedelta
import logging

from ..domain import Repository, Event
from ..infra import GitClient

logger = logging.getLogger(__name__)


class EventService:
    """
    Service for scanning repository events.

    Events are detected statelessly - each scan is independent.
    Use time-based filtering to find events since a point in time.

    Example:
        service = EventService()
        for event in service.scan(repos, since=datetime.now() - timedelta(days=7)):
            print(f"{event.type}: {event.repo_name}")
    """

    def __init__(self, git_client: Optional[GitClient] = None):
        """
        Initialize EventService.

        Args:
            git_client: Git client instance (creates default if None)
        """
        self.git = git_client or GitClient()

    def scan(
        self,
        repos: Iterable[Repository],
        types: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: Optional[int] = None,
        repo_filter: Optional[str] = None
    ) -> Generator[Event, None, None]:
        """
        Scan repositories for events.

        Args:
            repos: Repositories to scan
            types: Event types to scan for (default: ['git_tag'])
            since: Only events after this time
            until: Only events before this time
            limit: Maximum total events to return
            repo_filter: Only scan repos matching this name

        Yields:
            Event objects sorted by timestamp (newest first)
        """
        if types is None:
            types = ['git_tag']

        all_events = []

        for repo in repos:
            # Apply repo filter
            if repo_filter and repo.name != repo_filter:
                continue

            # Scan for each type
            if 'git_tag' in types:
                for event in self._scan_tags(repo, since, until):
                    all_events.append(event)

            if 'commit' in types:
                # Limit commits per repo to avoid explosion
                for event in self._scan_commits(repo, since, until, limit=50):
                    all_events.append(event)

        # Sort by timestamp (newest first)
        all_events.sort(key=lambda e: e.timestamp, reverse=True)

        # Apply global limit
        count = 0
        for event in all_events:
            yield event
            count += 1
            if limit and count >= limit:
                break

    def _scan_tags(
        self,
        repo: Repository,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None
    ) -> Generator[Event, None, None]:
        """Scan repository for git tags."""
        tags = self.git.tags(repo.path, since=since)

        for tag in tags:
            if until and tag.date > until:
                continue

            yield Event(
                type='git_tag',
                timestamp=tag.date,
                repo_name=repo.name,
                repo_path=repo.path,
                data={
                    'tag': tag.name,
                    'commit': tag.commit,
                    'tagger': tag.tagger,
                    'message': tag.message
                }
            )

    def _scan_commits(
        self,
        repo: Repository,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50
    ) -> Generator[Event, None, None]:
        """Scan repository for commits."""
        commits = self.git.log(repo.path, since=since, until=until, limit=limit)

        for commit in commits:
            yield Event(
                type='commit',
                timestamp=commit.date,
                repo_name=repo.name,
                repo_path=repo.path,
                data={
                    'hash': commit.hash,
                    'author': commit.author,
                    'email': commit.email,
                    'message': commit.message
                }
            )

    def scan_from_paths(
        self,
        paths: List[str],
        types: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: Optional[int] = None,
        repo_filter: Optional[str] = None
    ) -> Generator[Event, None, None]:
        """
        Scan events from repository paths (convenience method).

        Args:
            paths: Repository paths to scan
            types: Event types
            since: Start time
            until: End time
            limit: Max events
            repo_filter: Filter by repo name

        Yields:
            Event objects
        """
        repos = [Repository.from_path(p) for p in paths]
        yield from self.scan(repos, types, since, until, limit, repo_filter)

    def get_recent(
        self,
        repos: Iterable[Repository],
        days: int = 7,
        types: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[Event]:
        """
        Get recent events as a list.

        Convenience method for common use case.

        Args:
            repos: Repositories to scan
            days: Look back this many days
            types: Event types (default: ['git_tag'])
            limit: Maximum events

        Returns:
            List of Event objects
        """
        since = datetime.now() - timedelta(days=days)
        return list(self.scan(repos, types, since=since, limit=limit))

    def watch(
        self,
        repos: Iterable[Repository],
        types: Optional[List[str]] = None,
        interval: int = 300,
        callback=None
    ) -> Generator[Event, None, None]:
        """
        Continuously watch for new events.

        This is a blocking generator that yields new events as they're detected.
        Use in a separate thread or with async handling.

        Args:
            repos: Repositories to watch
            types: Event types to watch for
            interval: Seconds between scans
            callback: Optional callback for each event

        Yields:
            New Event objects as they're detected
        """
        import time

        seen_ids = set()
        repos_list = list(repos)  # Materialize for repeated iteration
        last_check = datetime.now()

        while True:
            try:
                events = list(self.scan(repos_list, types, since=last_check))

                for event in events:
                    if event.id not in seen_ids:
                        seen_ids.add(event.id)
                        if callback:
                            callback(event)
                        yield event

                last_check = datetime.now()
                time.sleep(interval)

            except KeyboardInterrupt:
                break
