"""GitHub platform metadata source for repoindex.

Wraps the existing GitHubClient infrastructure to provide
repo-level metadata enrichment (stars, forks, topics, etc.) and
the write capabilities defined on the GitForge ABC (Wave V2.C).
"""

import json
import logging
import os
import re
from typing import Iterator, List, Optional, Tuple

from ...infra.github_client import GitHubClient
from .. import GitForge, RemoteRepo

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

    # ------------------------------------------------------------------
    # Write capabilities (Wave V2.C)
    # ------------------------------------------------------------------

    def _resolve_token(self, config: Optional[dict]) -> Optional[str]:
        """Resolve the GitHub API token from config or environment."""
        config = config or {}
        token = config.get('github', {}).get('token')
        if not token:
            token = (
                os.environ.get('GITHUB_TOKEN')
                or os.environ.get('REPOINDEX_GITHUB_TOKEN')
            )
        return token or None

    def _resolve_owner_name(
        self, repo_record: dict
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve (owner, name) for an action, preferring DB columns.

        ``forge_owner`` and ``forge_name`` are populated by Wave V2.B's
        refresh dispatcher; falling back to remote_url parsing keeps the
        action path working for unrefreshed records.
        """
        owner = repo_record.get('forge_owner') if repo_record else None
        name = repo_record.get('forge_name') if repo_record else None
        if owner and name:
            return owner, name
        return _parse_github_remote((repo_record or {}).get('remote_url', ''))

    def enumerate_user_repos(self, config: dict) -> Iterator[RemoteRepo]:
        """Yield RemoteRepo records for every repo the authenticated user owns.

        Filters to owner-only repos by passing ``affiliation=owner`` to the
        GitHub API. If ``config['author']['github']`` is set we additionally
        filter the response to that login (defensive: tokens scoped wider
        than the configured user shouldn't pollute sync).
        """
        token = self._resolve_token(config)
        client = self._get_client(token)
        author_login = (config or {}).get('author', {}).get('github') or None
        for repo in client.iter_user_repos(owner=author_login):
            yield RemoteRepo(
                name=repo.get('name') or '',
                clone_url=repo.get('clone_url') or '',
                default_branch=repo.get('default_branch'),
                is_archived=bool(repo.get('archived', False)),
                description=repo.get('description'),
            )

    def set_topics(
        self, repo_record: dict, topics: List[str], config: dict
    ) -> None:
        """PUT /repos/{owner}/{name}/topics with the full topic list."""
        owner, name = self._resolve_owner_name(repo_record)
        if not owner or not name:
            raise ValueError("Cannot resolve owner/name for GitHub repo")
        client = self._get_client(self._resolve_token(config))
        ok, err = client.replace_topics(owner, name, list(topics))
        if not ok:
            raise RuntimeError(err or "set_topics failed")

    def set_description(
        self, repo_record: dict, description: str, config: dict
    ) -> None:
        """PATCH /repos/{owner}/{name} with ``description``."""
        owner, name = self._resolve_owner_name(repo_record)
        if not owner or not name:
            raise ValueError("Cannot resolve owner/name for GitHub repo")
        client = self._get_client(self._resolve_token(config))
        ok, err = client.set_repo_field(owner, name, 'description', description)
        if not ok:
            raise RuntimeError(err or "set_description failed")

    def set_archived(
        self, repo_record: dict, archived: bool, config: dict
    ) -> None:
        """PATCH /repos/{owner}/{name} with ``archived``."""
        owner, name = self._resolve_owner_name(repo_record)
        if not owner or not name:
            raise ValueError("Cannot resolve owner/name for GitHub repo")
        client = self._get_client(self._resolve_token(config))
        ok, err = client.set_repo_field(owner, name, 'archived', bool(archived))
        if not ok:
            raise RuntimeError(err or "set_archived failed")

    def set_visibility(
        self, repo_record: dict, public: bool, config: dict
    ) -> None:
        """PATCH /repos/{owner}/{name} with ``private`` (the inverse)."""
        owner, name = self._resolve_owner_name(repo_record)
        if not owner or not name:
            raise ValueError("Cannot resolve owner/name for GitHub repo")
        client = self._get_client(self._resolve_token(config))
        ok, err = client.set_repo_field(
            owner, name, 'private', not bool(public)
        )
        if not ok:
            raise RuntimeError(err or "set_visibility failed")

    def set_default_branch(
        self, repo_record: dict, branch: str, config: dict
    ) -> None:
        """PATCH /repos/{owner}/{name} with ``default_branch``."""
        owner, name = self._resolve_owner_name(repo_record)
        if not owner or not name:
            raise ValueError("Cannot resolve owner/name for GitHub repo")
        client = self._get_client(self._resolve_token(config))
        ok, err = client.set_repo_field(owner, name, 'default_branch', branch)
        if not ok:
            raise RuntimeError(err or "set_default_branch failed")

    def enable_pages(
        self, repo_record: dict, branch: str, path: str, config: dict
    ) -> None:
        """POST /repos/{owner}/{name}/pages enabling a static-site source.

        Falls back to PUT if Pages is already configured (handled by the
        GitHubClient layer).
        """
        owner, name = self._resolve_owner_name(repo_record)
        if not owner or not name:
            raise ValueError("Cannot resolve owner/name for GitHub repo")
        client = self._get_client(self._resolve_token(config))
        ok, err = client.create_pages_site(owner, name, branch, path or '/')
        if not ok:
            raise RuntimeError(err or "enable_pages failed")


source = GitHubSource()
