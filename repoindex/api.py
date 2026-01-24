"""
High-level Python API for repoindex.

Provides a fluent interface for repository discovery, event scanning,
tag management, and queries.

Example:
    import repoindex

    # Create instance (uses config defaults)
    ri = repoindex.RepoIndex()

    # Or with explicit configuration
    ri = repoindex.RepoIndex(
        paths=["~/projects", "~/work/**"],
        github_token="ghp_...",
    )

    # Discover repositories
    for repo in ri.repos():
        print(repo.name, repo.language)

    # Filter with queries
    for repo in ri.repos(query="language == 'Python'"):
        print(repo.name)

    # Filter by tags
    for repo in ri.repos(tags=["lang:python", "topic:ml"]):
        print(repo.name)

    # Scan events (local by default)
    for event in ri.events(since="7d"):
        print(event.type, event.repo_name)

    # Include GitHub events
    for event in ri.events(since="7d", github=True):
        print(event.type, event.data)

    # Include everything
    for event in ri.events(since="7d", all_types=True):
        print(event.to_jsonl())

    # Tag management
    ri.tag("myrepo", "alex/beta")
    ri.untag("myrepo", "alex/beta")

    # Low-level access to services
    ri.repository_service
    ri.event_service
    ri.tag_service
"""

from typing import Generator, List, Optional, Dict, Any, Union, Iterable
from datetime import datetime
from pathlib import Path
import logging

from .domain import Repository, Event
from .services import RepositoryService, EventService, TagService
from .infra import GitClient, GitHubClient, FileStore
from .config import load_config

logger = logging.getLogger(__name__)


class RepoIndex:
    """
    High-level API for repoindex.

    Provides a fluent interface for common operations:
    - Repository discovery and filtering
    - Event scanning (local and remote)
    - Tag management
    - Queries

    Example:
        ri = RepoIndex()

        # List Python repos
        for repo in ri.repos(query="lang:python"):
            print(repo.name)

        # Get recent events
        for event in ri.events(since="7d"):
            print(event)

        # Tag a repo
        ri.tag("myrepo", "work/active")
    """

    def __init__(
        self,
        paths: Optional[List[str]] = None,
        config_path: Optional[str] = None,
        github_token: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize RepoIndex.

        Args:
            paths: Repository paths to scan (overrides config)
            config_path: Path to config file (default: ~/.repoindex/config.json)
            github_token: GitHub API token (overrides config/env)
            config: Full config dict (overrides file if provided)
        """
        # Load configuration
        if config:
            self._config = config
        else:
            try:
                self._config = load_config(config_path)
            except Exception:
                self._config = {}

        # Override paths if provided
        if paths:
            self._config['repository_directories'] = paths

        # Override GitHub token if provided
        if github_token:
            if 'github' not in self._config:
                self._config['github'] = {}
            self._config['github']['token'] = github_token

        # Initialize infrastructure
        self._git_client = GitClient()
        self._github_client = GitHubClient(
            token=self._config.get('github', {}).get('token')
        )
        self._file_store = FileStore(
            Path(config_path or "~/.repoindex/config.json").expanduser()
        )

        # Initialize services
        self._repository_service = RepositoryService(
            git_client=self._git_client,
            github_client=self._github_client,
            config=self._config
        )
        self._event_service = EventService(git_client=self._git_client)
        self._tag_service = TagService(config_store=self._file_store)

    @property
    def repository_service(self) -> RepositoryService:
        """Access the underlying RepositoryService."""
        return self._repository_service

    @property
    def event_service(self) -> EventService:
        """Access the underlying EventService."""
        return self._event_service

    @property
    def tag_service(self) -> TagService:
        """Access the underlying TagService."""
        return self._tag_service

    @property
    def config(self) -> Dict[str, Any]:
        """Access the configuration."""
        return self._config

    # =========================================================================
    # REPOSITORY DISCOVERY
    # =========================================================================

    def repos(
        self,
        paths: Optional[List[str]] = None,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        recursive: bool = True,
        with_status: bool = False,
        with_github: bool = False,
        limit: Optional[int] = None
    ) -> Generator[Repository, None, None]:
        """
        Discover and filter repositories.

        Args:
            paths: Paths to search (uses config if None)
            query: Query expression (e.g., "language == 'Python'")
            tags: Tag patterns to filter by (e.g., ["lang:python"])
            recursive: Search subdirectories
            with_status: Enrich repos with git status
            with_github: Fetch GitHub metadata (slow, rate-limited)
            limit: Maximum repos to return

        Yields:
            Repository objects
        """
        # Discover repos
        repos = self._repository_service.discover(
            paths=paths,
            recursive=recursive
        )

        # Filter by query
        if query:
            repos = self._repository_service.filter_by_query(repos, query)

        # Filter by tags
        if tags:
            repos = self._repository_service.filter_by_tags(repos, tags)

        # Enrich and yield
        count = 0
        for repo in repos:
            if with_status or with_github:
                repo = self._repository_service.get_status(
                    repo,
                    fetch_github=with_github
                )

            yield repo
            count += 1
            if limit and count >= limit:
                break

    def get_repo(self, name_or_path: str) -> Optional[Repository]:
        """
        Get a single repository by name or path.

        Args:
            name_or_path: Repository name or absolute path

        Returns:
            Repository if found, None otherwise
        """
        # Check if it's a path
        if '/' in name_or_path and Path(name_or_path).exists():
            path = Path(name_or_path).resolve()
            if (path / '.git').exists():
                return Repository.from_path(str(path))
            return None

        # Search by name
        for repo in self.repos():
            if repo.name == name_or_path:
                return repo

        return None

    # =========================================================================
    # EVENT SCANNING
    # =========================================================================

    def events(
        self,
        repos: Optional[Iterable[Repository]] = None,
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
        Scan for events across repositories.

        Args:
            repos: Repositories to scan (discovers all if None)
            types: Specific event types to scan for
            since: Events after this time (datetime or "7d", "1h", etc.)
            until: Events before this time
            limit: Maximum events to return
            repo_filter: Filter by repository name
            github: Include GitHub events (releases, PRs, issues, workflows)
            pypi: Include PyPI publish events
            cran: Include CRAN publish events
            all_types: Include all event types

        Yields:
            Event objects sorted by timestamp (newest first)

        Event types:
            Local (default, fast):
                - git_tag: Git tags
                - commit: Git commits
                - branch: Branch creation/checkout
                - merge: Merge commits

            Remote (opt-in):
                - github_release: GitHub releases (--github)
                - pr: Pull requests (--github)
                - issue: Issues (--github)
                - workflow_run: GitHub Actions (--github)
                - pypi_publish: PyPI releases (--pypi)
                - cran_publish: CRAN releases (--cran)
        """
        # Discover repos if not provided
        if repos is None:
            repos = self.repos()

        yield from self._event_service.scan(
            repos=repos,
            types=types,
            since=since,
            until=until,
            limit=limit,
            repo_filter=repo_filter,
            github=github,
            pypi=pypi,
            cran=cran,
            all_types=all_types
        )

    def watch_events(
        self,
        repos: Optional[Iterable[Repository]] = None,
        types: Optional[List[str]] = None,
        interval: int = 300,
        callback=None,
        github: bool = False,
        pypi: bool = False,
        cran: bool = False
    ) -> Generator[Event, None, None]:
        """
        Continuously watch for new events.

        This is a blocking generator. Use in a separate thread or with async.

        Args:
            repos: Repositories to watch (discovers all if None)
            types: Event types to watch for
            interval: Seconds between scans
            callback: Optional function called for each event
            github: Include GitHub events
            pypi: Include PyPI events
            cran: Include CRAN events

        Yields:
            New Event objects as they're detected
        """
        if repos is None:
            repos = list(self.repos())

        # Build types list
        scan_types = self._event_service._build_types(
            types, github, pypi, cran, False
        )

        yield from self._event_service.watch(
            repos=repos,
            types=scan_types,
            interval=interval,
            callback=callback
        )

    # =========================================================================
    # TAG MANAGEMENT
    # =========================================================================

    def tag(self, repo_name_or_path: str, tag: str) -> bool:
        """
        Add a tag to a repository.

        Args:
            repo_name_or_path: Repository name or path
            tag: Tag to add (e.g., "alex/beta", "topic:ml")

        Returns:
            True if successful
        """
        repo = self.get_repo(repo_name_or_path)
        if not repo:
            logger.warning(f"Repository not found: {repo_name_or_path}")
            return False

        self._tag_service.add_string(repo, tag)
        return True

    def untag(self, repo_name_or_path: str, tag: str) -> bool:
        """
        Remove a tag from a repository.

        Args:
            repo_name_or_path: Repository name or path
            tag: Tag to remove

        Returns:
            True if tag was removed
        """
        repo = self.get_repo(repo_name_or_path)
        if not repo:
            logger.warning(f"Repository not found: {repo_name_or_path}")
            return False

        return self._tag_service.remove_string(repo, tag)

    def get_tags(self, repo_name_or_path: str) -> List[str]:
        """
        Get all tags for a repository.

        Args:
            repo_name_or_path: Repository name or path

        Returns:
            List of tag strings
        """
        repo = self.get_repo(repo_name_or_path)
        if not repo:
            return []

        return self._tag_service.get_tag_strings(repo)

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def stats(self, group_by: str = "language") -> Dict[str, int]:
        """
        Get repository statistics.

        Args:
            group_by: Field to group by ("language", "owner", "license")

        Returns:
            Dict mapping group values to counts
        """
        counts: Dict[str, int] = {}

        for repo in self.repos(with_status=True):
            if group_by == "language":
                key = repo.language or "Unknown"
            elif group_by == "owner":
                key = repo.owner or "Local"
            elif group_by == "license":
                key = repo.license.key if repo.license else "None"
            else:
                key = getattr(repo, group_by, "Unknown")

            counts[key] = counts.get(key, 0) + 1

        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def count(self, query: Optional[str] = None, tags: Optional[List[str]] = None) -> int:
        """
        Count repositories matching criteria.

        Args:
            query: Query expression
            tags: Tag patterns

        Returns:
            Number of matching repositories
        """
        return sum(1 for _ in self.repos(query=query, tags=tags))


# Convenience function for quick access
def create(
    paths: Optional[List[str]] = None,
    github_token: Optional[str] = None,
    **kwargs
) -> RepoIndex:
    """
    Create a RepoIndex instance.

    Convenience function for:
        ri = repoindex.create(paths=["~/projects"])

    Args:
        paths: Repository paths to scan
        github_token: GitHub API token
        **kwargs: Additional arguments passed to RepoIndex

    Returns:
        Configured RepoIndex instance
    """
    return RepoIndex(paths=paths, github_token=github_token, **kwargs)
