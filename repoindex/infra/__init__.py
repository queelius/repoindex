"""
Infrastructure layer for repoindex.

Contains abstractions for external systems:
- GitClient: Git command execution
- GitHubClient: GitHub API access
- ZenodoClient: Zenodo API access (DOI enrichment)
- FileStore: JSON/YAML file persistence

These provide clean interfaces that can be mocked for testing.
"""

from .git_client import GitClient, GitStatus as GitStatusResult
from .github_client import GitHubClient, RateLimitStatus
from .zenodo_client import ZenodoClient, ZenodoRecord
from .file_store import FileStore

__all__ = [
    'GitClient',
    'GitStatusResult',
    'GitHubClient',
    'RateLimitStatus',
    'ZenodoClient',
    'ZenodoRecord',
    'FileStore',
]
