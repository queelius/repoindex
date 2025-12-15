"""
Domain layer for repoindex.

Contains pure domain objects with no I/O or side effects:
- Repository: Represents a git repository with metadata
- Tag: Structured tag with optional hierarchy
- Event: Something that happened in/to a repository

These objects are immutable where possible and provide
serialization methods for JSONL output.
"""

from .repository import Repository, GitStatus, GitHubMetadata, PackageMetadata
from .tag import Tag, TagSource
from .event import Event

__all__ = [
    'Repository',
    'GitStatus',
    'GitHubMetadata',
    'PackageMetadata',
    'Tag',
    'TagSource',
    'Event',
]
