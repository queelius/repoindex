"""GitHub platform metadata source for repoindex.

Wraps the existing GitHubClient infrastructure to provide
repo-level metadata enrichment (stars, forks, topics, etc.).
"""

import json
import logging
import os
import re
from typing import Optional, Tuple

from ...infra.github_client import GitHubClient
from .. import GitForge

logger = logging.getLogger(__name__)

# Matches github.com:owner/name or github.com/owner/name, with optional .git suffix
# and optional trailing slash. Preserves dots in the name (e.g., three.js, Chart.js).
_GITHUB_REMOTE_RE = re.compile(r'github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$')


def _parse_github_remote(url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Extract (owner, name) from a GitHub remote URL.

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


class GitHubSource(GitForge):
    """GitHub hosting platform source."""

    source_id = "github"
    name = "GitHub"
    batch = False

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

    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        """Fetch GitHub metadata and return generic forge fields.

        The dispatcher in ``commands/refresh.py`` adds ``forge_id`` and
        ``forge_host`` based on the repo's remote_url; this method returns
        only the per-platform fields in their unified form.
        """
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

        # Generic forge fields (Wave V2.B). The dispatcher fills in
        # forge_id and forge_host from the remote URL.
        result = {
            'forge_owner': owner,
            'forge_name': name,
            'stars': repo.stars,
            'forks_count': repo.forks,
            'watchers': repo.watchers,
            'open_issues': repo.open_issues,
            'is_fork': int(repo.is_fork),
            'is_private': int(repo.is_private),
            'is_archived': int(repo.is_archived),
            'forge_description': repo.description or '',
            'forge_created_at': repo.created_at,
            'forge_updated_at': repo.updated_at,
        }

        # Default branch and pages_url come straight from the API.
        default_branch = getattr(repo, 'default_branch', None)
        if default_branch:
            result['default_branch'] = default_branch
        pages_url = getattr(repo, 'pages_url', None)
        if pages_url:
            result['pages_url'] = pages_url

        # Also populate the top-level description column (used for FTS5 search).
        if repo.description:
            result['description'] = repo.description

        if repo.topics:
            result['topics'] = json.dumps(repo.topics)

        if repo.pushed_at:
            result['forge_pushed_at'] = repo.pushed_at

        for attr in ('has_issues', 'has_wiki', 'has_pages'):
            result[attr] = int(getattr(repo, attr, False))

        return result


source = GitHubSource()
