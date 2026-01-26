"""
Operation result domain objects for repoindex.

Provides standardized result types for write operations (ops commands)
that modify repositories or generate files.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


class OperationStatus(Enum):
    """Status of an individual operation."""
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    DRY_RUN = "dry_run"


@dataclass
class OperationDetail:
    """
    Details of a single operation on one repository.

    Used to track what happened to each repo during bulk operations.
    """
    repo_path: str
    repo_name: str
    status: OperationStatus
    action: str  # e.g., "pushed", "pulled", "generated", "would_push"
    message: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'path': self.repo_path,
            'name': self.repo_name,
            'status': self.status.value,
            'action': self.action,
        }
        if self.message:
            result['message'] = self.message
        if self.error:
            result['error'] = self.error
        if self.metadata:
            result.update(self.metadata)
        return result


@dataclass
class GitPushResult(OperationDetail):
    """Result of a git push operation."""
    commits_pushed: int = 0
    remote: str = "origin"
    branch: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result['commits_pushed'] = self.commits_pushed
        result['remote'] = self.remote
        if self.branch:
            result['branch'] = self.branch
        return result


@dataclass
class GitPullResult(OperationDetail):
    """Result of a git pull operation."""
    commits_pulled: int = 0
    remote: str = "origin"
    branch: Optional[str] = None
    fast_forward: bool = True

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result['commits_pulled'] = self.commits_pulled
        result['remote'] = self.remote
        result['fast_forward'] = self.fast_forward
        if self.branch:
            result['branch'] = self.branch
        return result


@dataclass
class FileGenerationResult(OperationDetail):
    """Result of generating a file (citation, codemeta, license)."""
    file_path: Optional[str] = None
    file_type: str = "unknown"  # citation, codemeta, license
    overwritten: bool = False

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.file_path:
            result['file_path'] = self.file_path
        result['file_type'] = self.file_type
        result['overwritten'] = self.overwritten
        return result


@dataclass
class OperationSummary:
    """
    Summary of a bulk operation across multiple repositories.

    Collects statistics and details from operations performed
    by ops commands (git push/pull, generate citation, etc.)
    """
    operation: str  # e.g., "git_push", "git_pull", "generate_citation"
    total: int = 0
    successful: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run: bool = False
    details: List[OperationDetail] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """True if no failures occurred."""
        return self.failed == 0

    def add_detail(self, detail: OperationDetail) -> None:
        """Add an operation detail and update counts."""
        self.details.append(detail)
        self.total += 1

        if detail.status == OperationStatus.SUCCESS:
            self.successful += 1
        elif detail.status == OperationStatus.SKIPPED:
            self.skipped += 1
        elif detail.status == OperationStatus.FAILED:
            self.failed += 1
            if detail.error:
                self.errors.append(f"{detail.repo_name}: {detail.error}")
        elif detail.status == OperationStatus.DRY_RUN:
            self.successful += 1  # Count dry-run as successful

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'type': 'summary',
            'operation': self.operation,
            'total': self.total,
            'successful': self.successful,
            'skipped': self.skipped,
            'failed': self.failed,
            'dry_run': self.dry_run,
            'errors': self.errors,
        }
