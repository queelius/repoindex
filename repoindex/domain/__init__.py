"""
Domain layer for repoindex.

Contains pure domain objects with no I/O or side effects:
- Repository: Represents a git repository with metadata
- Tag: Structured tag with optional hierarchy
- Event: Something that happened in/to a repository
- Operation: Results from write operations (ops commands)
- Audit: Metadata completeness checks

These objects are immutable where possible and provide
serialization methods for JSONL output.
"""

from .repository import Repository, GitStatus, GitHubMetadata, PackageMetadata
from .tag import Tag, TagSource
from .event import Event
from .operation import (
    OperationStatus,
    OperationDetail,
    OperationSummary,
    GitPushResult,
    GitPullResult,
    FileGenerationResult,
)
from .audit import (
    Severity,
    Category,
    AuditCheck,
    CheckResult,
    CategoryScore,
    RepoAuditResult,
    AuditSummary,
)

__all__ = [
    'Repository',
    'GitStatus',
    'GitHubMetadata',
    'PackageMetadata',
    'Tag',
    'TagSource',
    'Event',
    # Operation results
    'OperationStatus',
    'OperationDetail',
    'OperationSummary',
    'GitPushResult',
    'GitPullResult',
    'FileGenerationResult',
    # Audit
    'Severity',
    'Category',
    'AuditCheck',
    'CheckResult',
    'CategoryScore',
    'RepoAuditResult',
    'AuditSummary',
]
