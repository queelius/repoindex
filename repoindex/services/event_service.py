"""
Event service for repoindex.

Provides stateless event scanning across repositories.
Delegates to the events module scanner functions.

Local events (fast, default):
- git_tag, commit, branch, merge

Remote events (opt-in):
- github_release, pr, issue, workflow_run (--github)
- pypi_publish (--pypi)
- cran_publish (--cran)
"""

from typing import Generator, List, Optional, Iterable, Union
from datetime import datetime, timedelta
import logging

from ..domain import Repository, Event
from ..infra import GitClient
from .. import events as events_module

logger = logging.getLogger(__name__)


class EventService:
    """
    Service for scanning repository events.

    Events are detected statelessly - each scan is independent.
    Use time-based filtering to find events since a point in time.

    Example:
        service = EventService()

        # Scan with defaults (local events only)
        for event in service.scan(repos, since="7d"):
            print(f"{event.type}: {event.repo_name}")

        # Include GitHub events
        for event in service.scan(repos, since="7d", github=True):
            print(f"{event.type}: {event.data}")

        # Include everything
        for event in service.scan(repos, since="7d", all_types=True):
            print(event.to_jsonl())
    """

    # Event type categories (exposed for users)
    LOCAL_TYPES = events_module.LOCAL_EVENT_TYPES
    GITHUB_TYPES = events_module.GITHUB_EVENT_TYPES
    PYPI_TYPES = events_module.PYPI_EVENT_TYPES
    CRAN_TYPES = events_module.CRAN_EVENT_TYPES
    ALL_TYPES = events_module.ALL_EVENT_TYPES

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
        since: Optional[Union[datetime, str]] = None,
        until: Optional[Union[datetime, str]] = None,
        limit: Optional[int] = None,
        repo_filter: Optional[str] = None,
        github: bool = False,
        pypi: bool = False,
        cran: bool = False,
        all_types: bool = False
    ) -> Generator[Event, None, None]:
        """
        Scan repositories for events.

        Args:
            repos: Repositories to scan
            types: Specific event types (overrides flags if provided)
            since: Events after this time (datetime or string like "7d")
            until: Events before this time
            limit: Maximum total events to return
            repo_filter: Only scan repos matching this name
            github: Include GitHub events (releases, PRs, issues, workflows)
            pypi: Include PyPI publish events
            cran: Include CRAN publish events
            all_types: Include all event types

        Yields:
            Event objects sorted by timestamp (newest first)
        """
        # Parse time specs if strings
        since_dt = self._parse_time(since) if since else None
        until_dt = self._parse_time(until) if until else None

        # Build types list from flags
        scan_types = self._build_types(types, github, pypi, cran, all_types)

        # Convert repos to list of paths for the events module
        repos_list = list(repos)
        repo_paths = [r.path for r in repos_list]

        # Use the events module scanner
        yield from events_module.scan_events(
            repo_paths,
            types=scan_types,
            since=since_dt,
            until=until_dt,
            limit=limit,
            repo_filter=repo_filter
        )

    def _parse_time(self, spec: Union[datetime, str]) -> datetime:
        """Parse time specification."""
        if isinstance(spec, datetime):
            return spec
        return events_module.parse_timespec(spec)

    def _build_types(
        self,
        types: Optional[List[str]],
        github: bool,
        pypi: bool,
        cran: bool,
        all_types: bool
    ) -> List[str]:
        """Build list of event types from flags."""
        if types:
            return list(types)

        if all_types:
            return self.ALL_TYPES.copy()

        # Start with local types (default)
        result = self.LOCAL_TYPES.copy()

        if github:
            result.extend(self.GITHUB_TYPES)
        if pypi:
            result.extend(self.PYPI_TYPES)
        if cran:
            result.extend(self.CRAN_TYPES)

        return result

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
