"""
repoindex - A collection-aware metadata index for git repositories.

repoindex provides a unified view across all your repositories, enabling
queries, organization, and integration with LLM tools like Claude Code.

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
        - release, pull_request, issue (forge=True, via GitForge.fetch_events)
        - pypi_publish (pypi=True)
        - cran_publish (cran=True)
"""

__version__ = "2.1.0"

# Domain objects
from .domain import (
    Repository,
    Event,
    Tag,
    TagSource,
    GitStatus,
    ForgeMetadata,
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
    FORGE_EVENT_TYPES,
    PYPI_EVENT_TYPES,
    CRAN_EVENT_TYPES,
    ALL_EVENT_TYPES,
)

# Configuration
from .config import load_config, save_config

__all__ = [
    # Version
    "__version__",
    # Domain objects
    "Repository",
    "Event",
    "Tag",
    "TagSource",
    "GitStatus",
    "ForgeMetadata",
    "PackageMetadata",
    # Services
    "RepositoryService",
    "EventService",
    "TagService",
    # Event types
    "LOCAL_EVENT_TYPES",
    "FORGE_EVENT_TYPES",
    "PYPI_EVENT_TYPES",
    "CRAN_EVENT_TYPES",
    "ALL_EVENT_TYPES",
    # Configuration
    "load_config",
    "save_config",
]
