"""
GitHub platform provider for repoindex.

Wraps the existing GitHubClient infrastructure to provide
repo-level metadata enrichment (stars, forks, topics, etc.)
via the PlatformProvider ABC.
"""

import json
import logging
import os
import re
from typing import Optional, Tuple

from . import PlatformProvider
from ..infra.github_client import GitHubClient

logger = logging.getLogger(__name__)

# Matches github.com:owner/name or github.com/owner/name, with optional .git suffix
# and optional trailing slash. Preserves dots in the name (e.g., three.js, Chart.js).
_GITHUB_REMOTE_RE = re.compile(r'github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$')


def _parse_github_remote(url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract (owner, name) from a GitHub remote URL.

    Handles HTTPS, SSH, and URLs with or without .git suffix.
    Preserves dots in repo names (three.js, Chart.js, etc.).
    Returns (None, None) for non-GitHub URLs or empty/None input.
    """
    if not url:
        return None, None
    m = _GITHUB_REMOTE_RE.search(url)
    if m:
        return m.group(1), m.group(2)
    return None, None


class GitHubPlatformProvider(PlatformProvider):
    """GitHub hosting platform provider."""

    platform_id = "github"
    name = "GitHub"
    prefix = "github"

    def __init__(self):
        # Cache clients by token to avoid per-call 'gh auth status' subprocess cost
        self._client_cache: dict = {}

    def _get_client(self, token: Optional[str]) -> GitHubClient:
        """Return a cached GitHubClient for the given token."""
        if token not in self._client_cache:
            self._client_cache[token] = GitHubClient(token=token)
        return self._client_cache[token]

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        """Detect whether this repo has a GitHub remote."""
        url = (repo_record or {}).get('remote_url', '')
        owner, name = _parse_github_remote(url)
        return owner is not None

    def enrich(self, repo_path: str, repo_record: Optional[dict] = None,
               config: Optional[dict] = None) -> Optional[dict]:
        """Fetch GitHub metadata and return prefixed fields."""
        url = (repo_record or {}).get('remote_url', '')
        owner, name = _parse_github_remote(url)
        if not owner or not name:
            return None

        config = config or {}
        token = config.get('github', {}).get('token')
        if not token:
            token = os.environ.get('GITHUB_TOKEN') or os.environ.get('REPOINDEX_GITHUB_TOKEN')

        client = self._get_client(token)
        repo = client.get_repo(owner, name)
        if not repo:
            return None

        # Always include identity fields so record_to_domain() can reconstruct
        # GitHubMetadata (it gates on the presence of github_owner).
        result = {
            'github_owner': owner,
            'github_name': name,
            'github_stars': repo.stars,
            'github_forks': repo.forks,
            'github_watchers': repo.watchers,
            'github_open_issues': repo.open_issues,
            'github_is_fork': int(repo.is_fork),
            'github_is_private': int(repo.is_private),
            'github_is_archived': int(repo.is_archived),
            'github_description': repo.description or '',
            'github_created_at': repo.created_at,
            'github_updated_at': repo.updated_at,
        }

        # Also populate the top-level description column (used for FTS5 search)
        if repo.description:
            result['description'] = repo.description

        if repo.topics:
            result['github_topics'] = json.dumps(repo.topics)

        if repo.pushed_at:
            result['github_pushed_at'] = repo.pushed_at

        for attr in ('has_issues', 'has_wiki', 'has_pages'):
            result[f'github_{attr}'] = int(getattr(repo, attr, False))

        return result


platform = GitHubPlatformProvider()
