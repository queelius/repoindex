"""
Repository domain object for repoindex.

Repository represents a git repository with its metadata.
It's designed to be immutable and serializable for JSONL output.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, FrozenSet
from pathlib import Path


@dataclass(frozen=True)
class GitStatus:
    """Git repository status information."""
    branch: str = "main"
    clean: bool = True
    ahead: int = 0
    behind: int = 0
    has_upstream: bool = False
    uncommitted_changes: bool = False
    untracked_files: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'branch': self.branch,
            'clean': self.clean,
            'ahead': self.ahead,
            'behind': self.behind,
            'has_upstream': self.has_upstream,
            'uncommitted_changes': self.uncommitted_changes,
            'untracked_files': self.untracked_files
        }


@dataclass(frozen=True)
class GitHubMetadata:
    """GitHub-specific repository metadata."""
    owner: str
    name: str
    description: Optional[str] = None
    homepage: Optional[str] = None
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    is_fork: bool = False
    is_private: bool = False
    is_archived: bool = False
    default_branch: str = "main"
    topics: tuple = ()  # Immutable tuple instead of list
    language: Optional[str] = None
    license_key: Optional[str] = None
    has_issues: bool = True
    has_wiki: bool = True
    has_pages: bool = False
    pages_url: Optional[str] = None
    open_issues_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pushed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'owner': self.owner,
            'name': self.name,
            'description': self.description,
            'homepage': self.homepage,
            'stars': self.stars,
            'forks': self.forks,
            'watchers': self.watchers,
            'is_fork': self.is_fork,
            'is_private': self.is_private,
            'is_archived': self.is_archived,
            'default_branch': self.default_branch,
            'topics': list(self.topics),
            'language': self.language,
            'license_key': self.license_key,
            'has_issues': self.has_issues,
            'has_wiki': self.has_wiki,
            'has_pages': self.has_pages,
            'pages_url': self.pages_url,
            'open_issues_count': self.open_issues_count,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'pushed_at': self.pushed_at,
        }


@dataclass(frozen=True)
class PackageMetadata:
    """Package registry metadata (PyPI, CRAN, npm, etc.)."""
    registry: str  # pypi, cran, npm, cargo, etc.
    name: str
    version: Optional[str] = None
    published: bool = False
    url: Optional[str] = None
    downloads: Optional[int] = None
    last_updated: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'registry': self.registry,
            'name': self.name,
            'version': self.version,
            'published': self.published,
            'url': self.url,
            'downloads': self.downloads,
            'last_updated': self.last_updated
        }


@dataclass(frozen=True)
class LicenseInfo:
    """License information."""
    key: str  # mit, apache-2.0, gpl-3.0, etc.
    name: Optional[str] = None
    file: Optional[str] = None
    year: Optional[int] = None
    holder: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'name': self.name,
            'file': self.file,
            'year': self.year,
            'holder': self.holder
        }


@dataclass(frozen=True)
class Repository:
    """
    Immutable representation of a git repository.

    This is the core domain object for repoindex. It contains:
    - Basic info: path, name
    - Git state: branch, clean status, remote URL
    - Derived metadata: language, license
    - Tags: both explicit and implicit
    - External metadata: GitHub info, package registry status

    All fields are immutable. To "update" a Repository, create a new
    instance with the changed fields using dataclasses.replace().

    Example:
        repo = Repository.from_path("/path/to/repo")
        repo_with_github = dataclasses.replace(repo, github=github_metadata)
    """

    # Required fields
    path: str
    name: str

    # Git state
    status: GitStatus = field(default_factory=GitStatus)
    remote_url: Optional[str] = None

    # Derived metadata
    owner: Optional[str] = None  # Derived from remote_url
    language: Optional[str] = None
    languages: tuple = ()  # All detected languages as immutable tuple
    license: Optional[LicenseInfo] = None

    # Tags (immutable frozenset)
    tags: FrozenSet[str] = field(default_factory=frozenset)

    # External metadata (optional, fetched on demand)
    github: Optional[GitHubMetadata] = None
    package: Optional[PackageMetadata] = None

    # Timestamps
    last_updated: Optional[str] = None  # ISO format

    @classmethod
    def from_path(cls, path: str) -> 'Repository':
        """
        Create a minimal Repository from a filesystem path.

        This creates a Repository with only the path and name set.
        Use RepositoryService to enrich with status, GitHub data, etc.

        Args:
            path: Absolute path to the git repository

        Returns:
            Minimal Repository instance
        """
        path = str(Path(path).resolve())
        name = Path(path).name

        return cls(path=path, name=name)

    def with_status(self, status: GitStatus) -> 'Repository':
        """Create a new Repository with updated status."""
        from dataclasses import replace
        return replace(self, status=status)

    def with_github(self, github: GitHubMetadata) -> 'Repository':
        """Create a new Repository with GitHub metadata."""
        from dataclasses import replace
        return replace(self, github=github)

    def with_tags(self, tags: FrozenSet[str]) -> 'Repository':
        """Create a new Repository with updated tags."""
        from dataclasses import replace
        return replace(self, tags=tags)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.

        This produces a flat structure suitable for JSONL output.
        """
        result = {
            'path': self.path,
            'name': self.name,
            'remote_url': self.remote_url,
            'owner': self.owner,
            'language': self.language,
            'languages': list(self.languages),
            'tags': list(self.tags),
            'status': self.status.to_dict() if self.status else None,
            'license': self.license.to_dict() if self.license else None,
            'github': self.github.to_dict() if self.github else None,
            'package': self.package.to_dict() if self.package else None,
            'last_updated': self.last_updated,
        }

        # Remove None values for cleaner output
        return {k: v for k, v in result.items() if v is not None}

    def to_jsonl(self) -> str:
        """Convert to single-line JSON for streaming output."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def has_tag(self, pattern: str) -> bool:
        """
        Check if repository has a tag matching the pattern.

        Args:
            pattern: Tag pattern (e.g., "lang:python", "topic:*")

        Returns:
            True if any tag matches
        """
        from .tag import Tag
        for tag_str in self.tags:
            tag = Tag.parse(tag_str)
            if tag.matches(pattern):
                return True
        return False

    @property
    def is_clean(self) -> bool:
        """Convenience property for git clean status."""
        return self.status.clean if self.status else True

    @property
    def branch(self) -> str:
        """Convenience property for current branch."""
        return self.status.branch if self.status else "unknown"

    def __str__(self) -> str:
        return f"{self.name} ({self.path})"

    def __repr__(self) -> str:
        return f"Repository(name={self.name!r}, path={self.path!r})"
