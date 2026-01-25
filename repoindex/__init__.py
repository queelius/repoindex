"""
repoindex - A collection-aware metadata index for git repositories.

repoindex provides a unified view across all your repositories, enabling
queries, organization, and integration with LLM tools like Claude Code.

Quick Start:
    import repoindex

    # Create instance
    ri = repoindex.RepoIndex()

    # Or with explicit paths
    ri = repoindex.RepoIndex(paths=["~/projects", "~/work/**"])

    # Discover repositories
    for repo in ri.repos():
        print(repo.name, repo.language)

    # Filter with queries
    for repo in ri.repos(query="language == 'Python'"):
        print(repo.name)

    # Scan events (local by default - fast)
    for event in ri.events(since="7d"):
        print(event.type, event.repo_name)

    # Include GitHub events (opt-in - uses API)
    for event in ri.events(since="7d", github=True):
        print(event.type, event.data)

    # Tag management
    ri.tag("myrepo", "work/active")
    ri.untag("myrepo", "work/active")

Domain Objects:
    Repository - Git repository with metadata
    Event - Something that happened (tag, commit, release, etc.)
    Tag - Hierarchical tag with source tracking

Services:
    RepositoryService - Discovery, status, filtering
    EventService - Event scanning
    TagService - Tag management

Event Types:
    Local (default, fast):
        - git_tag, commit, branch, merge

    Remote (opt-in):
        - github_release, pr, issue, workflow_run (github=True)
        - pypi_publish (pypi=True)
        - cran_publish (cran=True)
"""

__version__ = "0.10.1"

# High-level API
from .api import RepoIndex, create

# Domain objects
from .domain import (
    Repository,
    Event,
    Tag,
    TagSource,
    GitStatus,
    GitHubMetadata,
    PackageMetadata,
)

# Services (for advanced use)
from .services import (
    RepositoryService,
    EventService,
    TagService,
)

# Event type constants
from .events import (
    LOCAL_EVENT_TYPES,
    GITHUB_EVENT_TYPES,
    PYPI_EVENT_TYPES,
    CRAN_EVENT_TYPES,
    ALL_EVENT_TYPES,
)

# Configuration
from .config import load_config, save_config

__all__ = [
    # Version
    "__version__",
    # High-level API
    "RepoIndex",
    "create",
    # Domain objects
    "Repository",
    "Event",
    "Tag",
    "TagSource",
    "GitStatus",
    "GitHubMetadata",
    "PackageMetadata",
    # Services
    "RepositoryService",
    "EventService",
    "TagService",
    # Event types
    "LOCAL_EVENT_TYPES",
    "GITHUB_EVENT_TYPES",
    "PYPI_EVENT_TYPES",
    "CRAN_EVENT_TYPES",
    "ALL_EVENT_TYPES",
    # Configuration
    "load_config",
    "save_config",
]
