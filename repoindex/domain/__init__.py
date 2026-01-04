"""
Domain layer for repoindex.

Contains pure domain objects with no I/O or side effects:
- Repository: Represents a git repository with metadata
- Tag: Structured tag with optional hierarchy
- Event: Something that happened in/to a repository
- View: Curated, ordered collections of repositories

These objects are immutable where possible and provide
serialization methods for JSONL output.
"""

from .repository import Repository, GitStatus, GitHubMetadata, PackageMetadata
from .tag import Tag, TagSource
from .event import Event
from .view import (
    View, ViewSpec, ViewEntry, ViewTemplate,
    Overlay, Annotation, ViewMetadata,
    OrderSpec, OrderDirection, ViewOperator
)

__all__ = [
    'Repository',
    'GitStatus',
    'GitHubMetadata',
    'PackageMetadata',
    'Tag',
    'TagSource',
    'Event',
    # View system
    'View',
    'ViewSpec',
    'ViewEntry',
    'ViewTemplate',
    'Overlay',
    'Annotation',
    'ViewMetadata',
    'OrderSpec',
    'OrderDirection',
    'ViewOperator',
]
