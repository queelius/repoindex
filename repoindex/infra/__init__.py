"""
Infrastructure layer for repoindex.

Contains abstractions for external systems:
- GitClient: Git command execution
- GitHubClient: GitHub API access
- FileStore: JSON/YAML file persistence

These provide clean interfaces that can be mocked for testing.
"""

from .git_client import GitClient, GitStatus as GitStatusResult
from .github_client import GitHubClient, RateLimitStatus
from .file_store import FileStore

__all__ = [
    'GitClient',
    'GitStatusResult',
    'GitHubClient',
    'RateLimitStatus',
    'FileStore',
]
