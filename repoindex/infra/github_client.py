"""
GitHub API client infrastructure for repoindex.

Provides a clean abstraction over GitHub API access:
- Uses `gh` CLI when available for authentication
- Falls back to requests with token
- Handles rate limiting with exponential backoff
"""

import subprocess
import json
import os
import time
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


@dataclass
class RateLimitStatus:
    """GitHub API rate limit status."""
    remaining: int
    limit: int
    reset_time: int  # Unix timestamp
    used: int

    @property
    def reset_datetime(self) -> datetime:
        """Get reset time as datetime."""
        return datetime.fromtimestamp(self.reset_time)

    @property
    def minutes_until_reset(self) -> int:
        """Minutes until rate limit resets."""
        now = int(time.time())
        return max(0, (self.reset_time - now) // 60)

    @property
    def is_low(self) -> bool:
        """Check if rate limit is getting low (< 100 remaining)."""
        return self.remaining < 100


@dataclass
class GitHubRepo:
    """GitHub repository metadata."""
    owner: str
    name: str
    full_name: str
    description: Optional[str]
    homepage: Optional[str]
    language: Optional[str]
    stars: int
    forks: int
    watchers: int
    open_issues: int
    is_fork: bool
    is_private: bool
    is_archived: bool
    default_branch: str
    topics: List[str]
    license_key: Optional[str]
    has_issues: bool
    has_wiki: bool
    has_pages: bool
    created_at: Optional[str]
    updated_at: Optional[str]
    pushed_at: Optional[str]

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'GitHubRepo':
        """Create from GitHub API response."""
        owner = data.get('owner', {})
        license_info = data.get('license', {})

        return cls(
            owner=owner.get('login', '') if isinstance(owner, dict) else str(owner),
            name=data.get('name', ''),
            full_name=data.get('full_name', ''),
            description=data.get('description'),
            homepage=data.get('homepage'),
            language=data.get('language'),
            stars=data.get('stargazers_count', 0),
            forks=data.get('forks_count', 0),
            watchers=data.get('watchers_count', 0),
            open_issues=data.get('open_issues_count', 0),
            is_fork=data.get('fork', False),
            is_private=data.get('private', False),
            is_archived=data.get('archived', False),
            default_branch=data.get('default_branch', 'main'),
            topics=data.get('topics', []),
            license_key=license_info.get('key') if isinstance(license_info, dict) else None,
            has_issues=data.get('has_issues', True),
            has_wiki=data.get('has_wiki', True),
            has_pages=data.get('has_pages', False),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            pushed_at=data.get('pushed_at'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'owner': self.owner,
            'name': self.name,
            'full_name': self.full_name,
            'description': self.description,
            'homepage': self.homepage,
            'language': self.language,
            'stars': self.stars,
            'forks': self.forks,
            'watchers': self.watchers,
            'open_issues': self.open_issues,
            'is_fork': self.is_fork,
            'is_private': self.is_private,
            'is_archived': self.is_archived,
            'default_branch': self.default_branch,
            'topics': self.topics,
            'license_key': self.license_key,
            'has_issues': self.has_issues,
            'has_wiki': self.has_wiki,
            'has_pages': self.has_pages,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'pushed_at': self.pushed_at,
        }


class GitHubClient:
    """
    GitHub API client with rate limiting.

    Uses `gh` CLI for authentication when available,
    with fallback to direct API calls with token.

    Example:
        client = GitHubClient()
        repo = client.get_repo("owner", "repo")
        if repo:
            print(f"Stars: {repo.stars}")
    """

    def __init__(
        self,
        token: Optional[str] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        """
        Initialize GitHubClient.

        Args:
            token: GitHub token (defaults to REPOINDEX_GITHUB_TOKEN or GITHUB_TOKEN env var)
            max_retries: Maximum retry attempts for rate-limited requests
            base_delay: Base delay for exponential backoff
            max_delay: Maximum delay between retries
        """
        self.token = token or os.environ.get('REPOINDEX_GITHUB_TOKEN') or os.environ.get('GITHUB_TOKEN')
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._use_gh_cli = self._check_gh_cli()
        self._rate_limit_status: Optional[RateLimitStatus] = None

    def _update_rate_limit_from_headers(self, headers: Dict[str, str]) -> None:
        """Update rate limit status from response headers."""
        try:
            remaining = int(headers.get('X-RateLimit-Remaining', -1))
            limit = int(headers.get('X-RateLimit-Limit', -1))
            reset_time = int(headers.get('X-RateLimit-Reset', 0))
            used = int(headers.get('X-RateLimit-Used', 0))

            if remaining >= 0 and limit >= 0:
                self._rate_limit_status = RateLimitStatus(
                    remaining=remaining,
                    limit=limit,
                    reset_time=reset_time,
                    used=used
                )

                if self._rate_limit_status.is_low:
                    logger.warning(
                        f"GitHub API rate limit low: {remaining}/{limit} remaining, "
                        f"resets in {self._rate_limit_status.minutes_until_reset} minutes"
                    )
        except (ValueError, TypeError):
            pass  # Ignore parsing errors

    def get_rate_limit_status(self) -> Optional[RateLimitStatus]:
        """
        Get current rate limit status.

        Returns the cached status from the last API call, or fetches
        fresh status if no cached data is available.

        Returns:
            RateLimitStatus or None if unavailable
        """
        if self._rate_limit_status is None:
            # Fetch fresh rate limit status
            self._fetch_rate_limit()
        return self._rate_limit_status

    def _fetch_rate_limit(self) -> None:
        """Fetch rate limit status from GitHub API."""
        if self._use_gh_cli:
            try:
                result = subprocess.run(
                    ['gh', 'api', 'rate_limit'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0 and result.stdout:
                    data = json.loads(result.stdout)
                    core = data.get('rate', {})
                    self._rate_limit_status = RateLimitStatus(
                        remaining=core.get('remaining', 0),
                        limit=core.get('limit', 0),
                        reset_time=core.get('reset', 0),
                        used=core.get('used', 0)
                    )
                    return
            except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
                pass

        # Fall back to requests
        try:
            import requests
            url = "https://api.github.com/rate_limit"
            headers = {'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'repoindex'}
            if self.token:
                headers['Authorization'] = f'token {self.token}'

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                core = data.get('rate', {})
                self._rate_limit_status = RateLimitStatus(
                    remaining=core.get('remaining', 0),
                    limit=core.get('limit', 0),
                    reset_time=core.get('reset', 0),
                    used=core.get('used', 0)
                )
        except Exception:
            pass

    def _check_gh_cli(self) -> bool:
        """Check if gh CLI is available and authenticated."""
        try:
            result = subprocess.run(
                ['gh', 'auth', 'status'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _gh_api(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Call GitHub API using gh CLI."""
        try:
            result = subprocess.run(
                ['gh', 'api', endpoint],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 and result.stdout:
                return json.loads(result.stdout)
            return None
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
            logger.debug(f"gh api call failed for {endpoint}: {e}")
            return None

    def _requests_api(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Call GitHub API using requests library."""
        try:
            import requests
        except ImportError:
            logger.warning("requests library not available for GitHub API")
            return None

        url = f"https://api.github.com/{endpoint}"
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'repoindex'
        }

        if self.token:
            headers['Authorization'] = f'token {self.token}'

        for attempt in range(self.max_retries):
            try:
                response = requests.get(url, headers=headers, timeout=30)

                # Track rate limit from headers
                self._update_rate_limit_from_headers(response.headers)

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 403:
                    # Rate limited
                    reset_time = response.headers.get('X-RateLimit-Reset')
                    if reset_time:
                        wait_time = int(reset_time) - int(time.time())
                        if wait_time > 0 and wait_time < self.max_delay:
                            logger.info(f"Rate limited, waiting {wait_time}s")
                            time.sleep(wait_time)
                            continue

                    # Exponential backoff
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                    logger.info(f"Rate limited, waiting {delay}s (attempt {attempt + 1})")
                    time.sleep(delay)
                    continue

                if response.status_code == 404:
                    return None

                logger.warning(f"GitHub API error {response.status_code} for {endpoint}")
                return None

            except requests.RequestException as e:
                logger.warning(f"GitHub API request failed: {e}")
                if attempt < self.max_retries - 1:
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                    time.sleep(delay)
                continue

        return None

    def _api(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Call GitHub API using best available method."""
        if self._use_gh_cli:
            result = self._gh_api(endpoint)
            if result is not None:
                return result

        return self._requests_api(endpoint)

    def get_repo(self, owner: str, name: str) -> Optional[GitHubRepo]:
        """
        Get repository metadata.

        Args:
            owner: Repository owner
            name: Repository name

        Returns:
            GitHubRepo or None if not found
        """
        data = self._api(f"repos/{owner}/{name}")
        if data:
            return GitHubRepo.from_api_response(data)
        return None

    def get_topics(self, owner: str, name: str) -> List[str]:
        """
        Get repository topics.

        Args:
            owner: Repository owner
            name: Repository name

        Returns:
            List of topic strings
        """
        data = self._api(f"repos/{owner}/{name}/topics")
        if data:
            return data.get('names', [])
        return []

    def repo_exists(self, owner: str, name: str) -> bool:
        """Check if repository exists and is accessible."""
        return self.get_repo(owner, name) is not None

    def get_releases(self, owner: str, name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get repository releases.

        Args:
            owner: Repository owner
            name: Repository name
            limit: Maximum releases to return

        Returns:
            List of release data dictionaries
        """
        data = self._api(f"repos/{owner}/{name}/releases?per_page={limit}")
        if data and isinstance(data, list):
            return data[:limit]
        return []

    def _resolve_request_token(self) -> Optional[str]:
        """Token for direct requests calls: explicit/env token, else gh CLI.

        The gh CLI fallback exists so a user authenticated only via
        ``gh auth login`` doesn't paginate unauthenticated at 60 req/hr.
        Cached on self.token after first resolution.
        """
        if self.token:
            return self.token
        if self._use_gh_cli:
            try:
                result = subprocess.run(
                    ['gh', 'auth', 'token'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    self.token = result.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        return self.token

    def _iter_pages(self, endpoint: str, ts_key: str, since):
        """Yield items from a paginated list endpoint, newest-first.

        The endpoint MUST return items sorted by ``ts_key`` descending: the
        first item older than ``since`` means every later one is too, so
        pagination stops there. ``since`` may be None to fetch all pages; a
        timezone-aware ``since`` is normalized to naive (GitHub timestamps are
        compared as naive UTC).

        Errors raise RuntimeError rather than silently truncating the
        stream — a truncated fetch recorded as success can never be
        backfilled (events dedup via INSERT OR IGNORE). Callers (the refresh
        dispatch) isolate failures per repo. 404/410 mean the endpoint has
        nothing to list (repo gone, issues disabled) and end the stream.
        Full rate-limit backoff reuse is a follow-up.
        """
        if since is not None and since.tzinfo is not None:
            since = since.replace(tzinfo=None)
        headers = {"Accept": "application/vnd.github.v3+json",
                   "User-Agent": "repoindex"}
        token = self._resolve_request_token()
        if token:
            headers["Authorization"] = f"token {token}"
        page = 1
        while True:
            sep = "&" if "?" in endpoint else "?"
            url = f"https://api.github.com/{endpoint}{sep}per_page=100&page={page}"
            try:
                resp = requests.get(url, headers=headers, timeout=30)
            except requests.RequestException as e:
                raise RuntimeError(
                    f"GitHub request failed for {endpoint} (page {page}): {e}"
                ) from e
            self._update_rate_limit_from_headers(resp.headers)
            if resp.status_code in (403, 429):
                raise RuntimeError(
                    f"GitHub rate limited or forbidden (HTTP {resp.status_code}) "
                    f"for {endpoint}"
                )
            if resp.status_code in (404, 410):
                return
            if resp.status_code != 200:
                raise RuntimeError(
                    f"GitHub API error (HTTP {resp.status_code}) for {endpoint}"
                )
            items = resp.json()
            if not isinstance(items, list) or not items:
                return
            for item in items:
                if since is not None:
                    raw = item.get(ts_key)
                    if raw:
                        try:
                            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                            if when.replace(tzinfo=None) < since:
                                return
                        except (ValueError, TypeError):
                            pass
                yield item
            if len(items) < 100:
                return
            page += 1

    def iter_releases(self, owner: str, name: str, since=None):
        """Yield release dicts for owner/name, newest-first, stopping at since.

        The releases endpoint is sorted by ``created_at`` descending, so the
        early-stop keys on ``created_at`` (not ``published_at``, which can be
        out of order for late-published drafts and cause a false stop).
        """
        yield from self._iter_pages(
            f"repos/{owner}/{name}/releases", "created_at", since)

    def iter_pulls(self, owner: str, name: str, since=None):
        """Yield pull-request dicts, newest-first by creation, stopping at since."""
        yield from self._iter_pages(
            f"repos/{owner}/{name}/pulls?state=all&sort=created&direction=desc",
            "created_at", since)

    def iter_issues(self, owner: str, name: str, since=None):
        """Yield issue dicts (excluding PRs), newest-first, stopping at since."""
        for item in self._iter_pages(
                f"repos/{owner}/{name}/issues?state=all&sort=created&direction=desc",
                "created_at", since):
            if "pull_request" not in item:
                yield item

    def get_pages_info(self, owner: str, name: str) -> Optional[Dict[str, Any]]:
        """
        Get GitHub Pages information.

        Args:
            owner: Repository owner
            name: Repository name

        Returns:
            Pages info dict or None if not enabled
        """
        return self._api(f"repos/{owner}/{name}/pages")

    # ------------------------------------------------------------------
    # Write API (Wave V2.C)
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Optional[Dict[str, Any]]]:
        """Issue an authenticated HTTP request and return (status, json).

        Uses requests directly (not the gh CLI) to keep the JSON body path
        uniform across PATCH/PUT/POST. Status code is always returned even
        on non-2xx so callers can surface forge error messages cleanly.
        """
        try:
            import requests
        except ImportError:
            logger.warning("requests library not available for GitHub API")
            return 0, None

        url = f"https://api.github.com/{endpoint.lstrip('/')}"
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'repoindex',
        }
        if self.token:
            headers['Authorization'] = f'token {self.token}'

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=30,
            )
        except requests.RequestException as e:
            logger.warning("GitHub API %s %s failed: %s", method, endpoint, e)
            return 0, None

        self._update_rate_limit_from_headers(response.headers)

        body: Optional[Dict[str, Any]]
        try:
            body = response.json() if response.text else None
        except ValueError:
            body = None
        return response.status_code, body

    @staticmethod
    def _check_response(
        status: int, body: Optional[Dict[str, Any]],
    ) -> Tuple[bool, Optional[str]]:
        """Translate (status, body) into (ok, error_message)."""
        if 200 <= status < 300:
            return True, None
        msg = (body or {}).get('message') if isinstance(body, dict) else None
        return False, msg or f"HTTP {status}"

    def set_repo_field(
        self,
        owner: str,
        name: str,
        field: str,
        value: Any,
    ) -> Tuple[bool, Optional[str]]:
        """PATCH /repos/{owner}/{name} with a single field.

        Returns (ok, error_message). On success, error_message is None.
        """
        status, body = self._request(
            'PATCH', f"repos/{owner}/{name}", {field: value}
        )
        return self._check_response(status, body)

    def replace_topics(
        self,
        owner: str,
        name: str,
        topics: List[str],
    ) -> Tuple[bool, Optional[str]]:
        """PUT /repos/{owner}/{name}/topics with the full topic list."""
        status, body = self._request(
            'PUT', f"repos/{owner}/{name}/topics", {'names': topics}
        )
        return self._check_response(status, body)

    def create_pages_site(
        self,
        owner: str,
        name: str,
        branch: str,
        path: str = '/',
    ) -> Tuple[bool, Optional[str]]:
        """POST /repos/{owner}/{name}/pages to enable Pages on a branch.

        If Pages is already enabled (409 Conflict), fall back to PUT to
        update the source.
        """
        payload = {'source': {'branch': branch, 'path': path}}
        endpoint = f"repos/{owner}/{name}/pages"
        status, body = self._request('POST', endpoint, payload)
        if status == 409:
            status, body = self._request('PUT', endpoint, payload)
        return self._check_response(status, body)

    def iter_user_repos(
        self,
        owner: Optional[str] = None,
        per_page: int = 100,
    ) -> List[Dict[str, Any]]:
        """GET /user/repos paginated. Returns the raw API dicts.

        Args:
            owner: If set, filter to repos whose ``owner.login`` matches.
                (The /user/repos endpoint returns collaborator repos too.)
            per_page: Page size (max 100).
        """
        try:
            import requests
        except ImportError:
            logger.warning("requests library not available for GitHub API")
            return []

        url: Optional[str] = (
            f"https://api.github.com/user/repos?per_page={per_page}&affiliation=owner"
        )
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'repoindex',
        }
        if self.token:
            headers['Authorization'] = f'token {self.token}'

        out: List[Dict[str, Any]] = []
        while url:
            try:
                resp = requests.get(url, headers=headers, timeout=30)
            except requests.RequestException as e:
                logger.warning("GitHub /user/repos failed: %s", e)
                break

            self._update_rate_limit_from_headers(resp.headers)
            if resp.status_code != 200:
                logger.warning(
                    "GitHub /user/repos returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
                break

            try:
                page = resp.json()
            except ValueError:
                break

            if isinstance(page, list):
                for repo in page:
                    if not isinstance(repo, dict):
                        continue
                    if owner:
                        login = (repo.get('owner') or {}).get('login')
                        if login != owner:
                            continue
                    out.append(repo)

            # Follow Link rel="next"
            url = _parse_next_link(resp.headers.get('Link'))

        return out


def _parse_next_link(link_header: Optional[str]) -> Optional[str]:
    """Extract the next-page URL from a GitHub Link header."""
    if not link_header:
        return None
    for chunk in link_header.split(','):
        parts = chunk.strip().split(';')
        if len(parts) < 2:
            continue
        url_part = parts[0].strip()
        rel_part = ';'.join(parts[1:]).strip()
        if 'rel="next"' in rel_part and url_part.startswith('<') and url_part.endswith('>'):
            return url_part[1:-1]
    return None
