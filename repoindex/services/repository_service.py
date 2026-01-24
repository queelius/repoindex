"""
Repository service for repoindex.

Provides high-level operations for repository discovery, status, and filtering.
This is the primary API for working with repositories.
"""

from typing import Generator, List, Optional, Dict, Any, Iterable, Set
from pathlib import Path
import logging
import os
import re

from ..domain import Repository, GitStatus, GitHubMetadata, PackageMetadata
from ..domain.repository import LicenseInfo
from ..infra import GitClient, GitHubClient

logger = logging.getLogger(__name__)


# Directories to exclude from repository discovery
EXCLUDE_DIRS = {
    '_deps', 'build', 'node_modules', '.git', '__pycache__',
    'venv', '.venv', 'env', '.env', 'dist', 'target'
}


class RepositoryService:
    """
    Service for discovering and querying repositories.

    Example:
        service = RepositoryService()
        for repo in service.discover(["/home/user/projects"]):
            print(f"{repo.name}: {repo.branch}")
    """

    def __init__(
        self,
        git_client: Optional[GitClient] = None,
        github_client: Optional[GitHubClient] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize RepositoryService.

        Args:
            git_client: Git client instance (creates default if None)
            github_client: GitHub client instance (creates default if None)
            config: Configuration dict (loads from file if None)
        """
        self.git = git_client or GitClient()
        self.github = github_client or GitHubClient()
        self.config = config or {}

    def discover(
        self,
        paths: Optional[List[str]] = None,
        recursive: bool = True,
        exclude_patterns: Optional[List[str]] = None
    ) -> Generator[Repository, None, None]:
        """
        Discover git repositories from paths.

        Args:
            paths: Paths to search (uses config if None)
            recursive: Search subdirectories
            exclude_patterns: Patterns to exclude

        Yields:
            Repository objects for each found repo
        """
        if paths is None:
            paths = self.config.get('repository_directories', [])

        exclude = set(exclude_patterns or [])
        exclude.update(EXCLUDE_DIRS)

        seen_paths: Set[str] = set()

        for path in paths:
            path = os.path.expanduser(path)

            # Handle glob patterns
            if '**' in path or '*' in path:
                import glob
                for expanded in glob.glob(path, recursive=True):
                    yield from self._discover_path(
                        expanded, recursive, exclude, seen_paths
                    )
            else:
                yield from self._discover_path(
                    path, recursive, exclude, seen_paths
                )

    def _discover_path(
        self,
        path: str,
        recursive: bool,
        exclude: Set[str],
        seen_paths: Set[str]
    ) -> Generator[Repository, None, None]:
        """
        Discover repos from a single path.

        v0.10.0: Filesystem path IS the canonical identity. No remote-URL deduplication.
        Each local path is an independent entry even if multiple paths point to same remote.
        """
        path = str(Path(path).resolve())

        if not os.path.isdir(path):
            return

        # Check if path itself is a git repo
        if self.git.is_git_repo(path):
            if path not in seen_paths:
                repo = self._create_repo(path)
                seen_paths.add(path)
                yield repo
            return

        if not recursive:
            return

        # Search subdirectories
        try:
            for entry in os.scandir(path):
                if not entry.is_dir():
                    continue

                name = entry.name
                if name.startswith('.') and name != '.git':
                    continue
                if name in exclude:
                    continue

                yield from self._discover_path(
                    entry.path, recursive, exclude, seen_paths
                )
        except PermissionError:
            logger.debug(f"Permission denied: {path}")

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        url = url.rstrip('/')
        url = re.sub(r'\.git$', '', url)
        url = re.sub(r'^git@github\.com:', 'https://github.com/', url)
        url = re.sub(r'^git@gitlab\.com:', 'https://gitlab.com/', url)
        return url.lower()

    def _create_repo(self, path: str) -> Repository:
        """Create a minimal Repository from path."""
        path = str(Path(path).resolve())
        name = Path(path).name
        remote_url = self.git.remote_url(path)

        owner = None
        if remote_url:
            owner = self._parse_owner(remote_url)

        return Repository(
            path=path,
            name=name,
            remote_url=remote_url,
            owner=owner
        )

    def _parse_owner(self, url: str) -> Optional[str]:
        """Parse owner from remote URL."""
        # GitHub SSH: git@github.com:owner/repo.git
        ssh_match = re.match(r'git@github\.com:([^/]+)/', url)
        if ssh_match:
            return ssh_match.group(1)

        # HTTPS: https://github.com/owner/repo
        https_match = re.match(r'https?://github\.com/([^/]+)/', url)
        if https_match:
            return https_match.group(1)

        return None

    def get_status(
        self,
        repo: Repository,
        fetch_github: bool = False,
        fetch_pypi: bool = False,
        fetch_cran: bool = False
    ) -> Repository:
        """
        Enrich repository with current status.

        Args:
            repo: Repository to enrich
            fetch_github: Whether to fetch GitHub metadata
            fetch_pypi: Whether to fetch PyPI package status
            fetch_cran: Whether to fetch CRAN package status

        Returns:
            New Repository with status information
        """
        from dataclasses import replace

        # Get git status
        git_status = self.git.status(repo.path)
        status = GitStatus(
            branch=git_status.branch,
            clean=git_status.clean,
            ahead=git_status.ahead,
            behind=git_status.behind,
            has_upstream=git_status.has_upstream,
            uncommitted_changes=git_status.uncommitted_changes,
            untracked_files=git_status.untracked_files
        )

        # Detect license
        license_info = self._detect_license(repo.path)

        # Detect language
        language, languages = self._detect_languages(repo.path)

        # Update repo with status
        updated = replace(
            repo,
            status=status,
            license=license_info,
            language=language,
            languages=tuple(languages)
        )

        # Fetch GitHub metadata if requested
        if fetch_github and repo.owner and repo.name:
            github_metadata = self._fetch_github_metadata(repo.owner, repo.name)
            if github_metadata:
                updated = replace(updated, github=github_metadata)

        # Fetch PyPI package status if requested
        if fetch_pypi:
            package_metadata = self._fetch_pypi_metadata(repo.path)
            if package_metadata:
                updated = replace(updated, package=package_metadata)

        # Fetch CRAN package status if requested
        if fetch_cran:
            cran_metadata = self._fetch_cran_metadata(repo.path)
            if cran_metadata:
                # Merge with existing package metadata or use CRAN data
                if updated.package:
                    # Repo already has Python package info, add CRAN as separate field
                    # For now, prefer PyPI if both exist
                    pass
                else:
                    updated = replace(updated, package=cran_metadata)

        return updated

    def _detect_license(self, path: str) -> Optional[LicenseInfo]:
        """Detect license from repository."""
        license_files = ['LICENSE', 'LICENSE.txt', 'LICENSE.md', 'LICENCE', 'COPYING']

        for filename in license_files:
            filepath = Path(path) / filename
            if filepath.exists():
                try:
                    content = filepath.read_text(errors='ignore')[:2000]
                    key = self._identify_license(content)
                    return LicenseInfo(key=key, file=filename)
                except Exception:
                    pass

        return None

    def _identify_license(self, content: str) -> str:
        """Identify license type from content."""
        content_lower = content.lower()

        if 'mit license' in content_lower or 'permission is hereby granted, free of charge' in content_lower:
            return 'mit'
        if 'apache license' in content_lower and 'version 2.0' in content_lower:
            return 'apache-2.0'
        if 'gnu general public license' in content_lower:
            if 'version 3' in content_lower:
                return 'gpl-3.0'
            if 'version 2' in content_lower:
                return 'gpl-2.0'
            return 'gpl'
        if 'bsd' in content_lower:
            if '3-clause' in content_lower or 'three-clause' in content_lower:
                return 'bsd-3-clause'
            if '2-clause' in content_lower or 'two-clause' in content_lower:
                return 'bsd-2-clause'
            return 'bsd'
        if 'mozilla public license' in content_lower:
            return 'mpl-2.0'
        if 'unlicense' in content_lower:
            return 'unlicense'
        if 'creative commons' in content_lower:
            return 'cc'

        return 'other'

    def _detect_languages(self, path: str) -> tuple:
        """Detect primary language and all languages."""
        extensions = {
            '.py': 'Python',
            '.js': 'JavaScript',
            '.ts': 'TypeScript',
            '.go': 'Go',
            '.rs': 'Rust',
            '.java': 'Java',
            '.c': 'C',
            '.cpp': 'C++',
            '.rb': 'Ruby',
            '.php': 'PHP',
            '.swift': 'Swift',
            '.kt': 'Kotlin',
            '.scala': 'Scala',
            '.r': 'R',
            '.R': 'R',
            '.jl': 'Julia',
            '.sh': 'Shell',
            '.lua': 'Lua',
            '.pl': 'Perl',
        }

        counts = {}

        try:
            for ext, lang in extensions.items():
                pattern = f"**/*{ext}"
                matches = list(Path(path).glob(pattern))
                # Exclude common non-source directories
                matches = [
                    m for m in matches
                    if not any(excl in str(m) for excl in EXCLUDE_DIRS)
                ]
                if matches:
                    counts[lang] = len(matches)
        except Exception:
            pass

        if not counts:
            return None, []

        # Primary language is the one with most files
        primary = max(counts, key=counts.get)
        all_langs = sorted(counts.keys(), key=lambda x: counts[x], reverse=True)

        return primary, all_langs

    def _fetch_github_metadata(self, owner: str, name: str) -> Optional[GitHubMetadata]:
        """Fetch GitHub metadata for repository."""
        repo_data = self.github.get_repo(owner, name)
        if not repo_data:
            return None

        return GitHubMetadata(
            owner=repo_data.owner,
            name=repo_data.name,
            description=repo_data.description,
            homepage=repo_data.homepage,
            stars=repo_data.stars,
            forks=repo_data.forks,
            watchers=repo_data.watchers,
            is_fork=repo_data.is_fork,
            is_private=repo_data.is_private,
            is_archived=repo_data.is_archived,
            default_branch=repo_data.default_branch,
            topics=tuple(repo_data.topics),
            language=repo_data.language,
            license_key=repo_data.license_key,
            has_issues=repo_data.has_issues,
            has_wiki=repo_data.has_wiki,
            has_pages=repo_data.has_pages,
            open_issues_count=repo_data.open_issues,
            created_at=repo_data.created_at,
            updated_at=repo_data.updated_at,
            pushed_at=repo_data.pushed_at,
        )

    def _fetch_pypi_metadata(self, path: str) -> Optional[PackageMetadata]:
        """Fetch PyPI package metadata for repository."""
        try:
            from ..pypi import detect_pypi_package

            pypi_info = detect_pypi_package(path)
            if not pypi_info.get('package_name'):
                return None

            return PackageMetadata(
                name=pypi_info.get('package_name', ''),
                version=pypi_info.get('local_version') or pypi_info.get('pypi_info', {}).get('version'),
                registry='pypi',
                published=pypi_info.get('is_published', False),
                url=pypi_info.get('pypi_info', {}).get('url'),
            )
        except Exception as e:
            logger.debug(f"Failed to fetch PyPI metadata for {path}: {e}")
            return None

    def _fetch_cran_metadata(self, path: str) -> Optional[PackageMetadata]:
        """Fetch CRAN/Bioconductor package metadata for repository."""
        try:
            from ..cran import detect_r_package

            r_info = detect_r_package(path)
            if not r_info.get('package_name'):
                return None

            # Use the detected registry (cran or bioconductor)
            registry = r_info.get('registry', 'cran')
            registry_info = r_info.get('cran_info') or r_info.get('bioconductor_info') or {}

            return PackageMetadata(
                name=r_info.get('package_name', ''),
                version=r_info.get('local_version') or registry_info.get('version'),
                registry=registry,
                published=r_info.get('is_published', False),
                url=registry_info.get('url'),
            )
        except Exception as e:
            logger.debug(f"Failed to fetch CRAN/R metadata for {path}: {e}")
            return None

    def filter_by_query(
        self,
        repos: Iterable[Repository],
        query: str
    ) -> Generator[Repository, None, None]:
        """
        Filter repositories by query expression.

        Args:
            repos: Repositories to filter
            query: Query expression (e.g., "language == 'Python'")

        Yields:
            Matching repositories
        """
        # Simple query parsing for common patterns
        query = query.strip()

        for repo in repos:
            if self._matches_query(repo, query):
                yield repo

    def _matches_query(self, repo: Repository, query: str) -> bool:
        """Check if repository matches query."""
        query_lower = query.lower()

        # Handle common patterns
        if query_lower.startswith('language'):
            match = re.search(r"language\s*[=~]+\s*['\"]?(\w+)['\"]?", query, re.I)
            if match:
                lang = match.group(1).lower()
                return bool(repo.language and repo.language.lower() == lang)

        if query_lower.startswith('lang:'):
            lang = query[5:].strip().lower()
            return bool(repo.language and repo.language.lower() == lang)

        if query_lower.startswith('tag:'):
            tag_pattern = query[4:].strip()
            return repo.has_tag(tag_pattern)

        if query_lower.startswith('owner:'):
            owner = query[6:].strip().lower()
            return bool(repo.owner and repo.owner.lower() == owner)

        if query_lower.startswith('name:'):
            name = query[5:].strip().lower()
            return repo.name.lower() == name or name in repo.name.lower()

        # Default: check if query is in name
        return query_lower in repo.name.lower()

    def filter_by_tags(
        self,
        repos: Iterable[Repository],
        patterns: List[str]
    ) -> Generator[Repository, None, None]:
        """
        Filter repositories by tag patterns.

        Args:
            repos: Repositories to filter
            patterns: Tag patterns to match

        Yields:
            Repositories matching any pattern
        """
        for repo in repos:
            for pattern in patterns:
                if repo.has_tag(pattern):
                    yield repo
                    break
