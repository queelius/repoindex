"""
Event domain object for ghops.

Events represent something that happened in or related to a repository:
- git_tag: New git tag created
- commit: New commit pushed
- (future) pypi_publish, github_release, etc.

Events are timestamped, have stable IDs, and are serializable for JSONL output.
"""

from dataclasses import dataclass, field
from typing import Dict, Any
from datetime import datetime
import json


@dataclass
class Event:
    """
    Represents an event detected in a repository.

    Events are immutable records of something that happened.
    They have stable IDs for deduplication and are optimized
    for JSONL streaming output.

    Attributes:
        type: Event type (git_tag, commit, etc.)
        timestamp: When the event occurred (naive datetime, local time)
        repo_name: Repository name (directory name)
        repo_path: Absolute path to repository
        data: Type-specific data (tag name, commit hash, etc.)
    """

    type: str
    timestamp: datetime
    repo_name: str
    repo_path: str
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """
        Generate a unique, stable ID for this event.

        The ID is stable across scans, allowing deduplication
        in watch mode and external tools.
        """
        if self.type == 'git_tag':
            tag = self.data.get('tag', 'unknown')
            return f"git_tag_{self.repo_name}_{tag}"
        elif self.type == 'commit':
            hash_short = self.data.get('hash', 'unknown')[:8]
            return f"commit_{self.repo_name}_{hash_short}"
        else:
            ts = self.timestamp.strftime('%Y%m%d%H%M%S')
            return f"{self.type}_{self.repo_name}_{ts}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'type': self.type,
            'timestamp': self.timestamp.isoformat(),
            'repo': self.repo_name,
            'path': self.repo_path,
            'data': self.data
        }

    def to_jsonl(self) -> str:
        """Convert to single-line JSON for streaming output."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def __str__(self) -> str:
        return f"{self.type} in {self.repo_name} at {self.timestamp.isoformat()}"

    def __repr__(self) -> str:
        return f"Event(type={self.type!r}, repo={self.repo_name!r}, id={self.id!r})"

    def __hash__(self) -> int:
        """Hash based on stable ID for use in sets."""
        return hash(self.id)

    def __eq__(self, other) -> bool:
        """Equality based on stable ID."""
        if not isinstance(other, Event):
            return False
        return self.id == other.id
