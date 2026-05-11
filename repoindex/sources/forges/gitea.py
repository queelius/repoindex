"""Gitea / Codeberg / Forgejo metadata source for repoindex.

Enriches repos hosted on Gitea-based platforms (Codeberg, Forgejo, self-hosted).
Fetches stars, forks, watchers, issues, topics, and other metadata via Gitea REST API v1.

Configuration (in ~/.repoindex/config.yaml):

    gitea:
      hosts:
        - codeberg.org
        - git.mycompany.com
      tokens:
        codeberg.org: "your-token-here"
        git.mycompany.com: "another-token"

The Wave V2.C ``forges:`` section (one entry per host) is also honoured;
each entry may set ``token_env`` to name the environment variable that
carries the API token for that host. Per-host config wins over the
legacy ``gitea.tokens`` map.
"""
import json
import logging
import os
import re
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from .. import GitForge, RemoteRepo

logger = logging.getLogger(__name__)

_DEFAULT_HOSTS = ['codeberg.org']


def _parse_gitea_remote(
    url: Optional[str], hosts: List[str]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract (host, owner, name) from a Gitea remote URL.

    Handles HTTPS (with optional port), SSH, and URLs with/without .git suffix.
    Supports nested subgroup paths (e.g., parent/sub/repo -> owner='parent/sub').
    Returns (None, None, None) if URL doesn't match any configured host.
    """
    if not url:
        return None, None, None

    host: Optional[str] = None
    path: Optional[str] = None

    if url.startswith(('http://', 'https://', 'ssh://')):
        try:
            parsed = urlparse(url)
            host = parsed.hostname  # urllib strips port
            path = parsed.path.lstrip('/')
        except Exception:
            return None, None, None
    else:
        # SSH form: git@host:owner/repo[.git] (no scheme)
        ssh_match = re.match(r'^(?:[^@]+@)?([^:/\s]+):(.+?)$', url)
        if ssh_match:
            host = ssh_match.group(1)
            path = ssh_match.group(2)
        else:
            return None, None, None

    if not host or not path:
        return None, None, None

    if host not in hosts:
        return None, None, None

    # Strip .git suffix and trailing slash
    path = re.sub(r'\.git/?$', '', path).rstrip('/')
    if not path:
        return None, None, None

    parts = path.split('/')
    if len(parts) < 2:
        return None, None, None

    # Repo name is the last segment, owner is everything before
    # This supports nested Gitea subgroups (parent/sub/repo)
    name = parts[-1]
    owner = '/'.join(parts[:-1])

    if not owner or not name:
        return None, None, None

    return host, owner, name


class GiteaSource(GitForge):
    """Metadata source for Gitea-based hosting platforms."""

    source_id = "gitea"
    name = "Gitea / Codeberg"

    def __init__(self):
        # Session cache keyed by (host, token_or_None) for connection pooling
        self._client_cache: Dict[Tuple[str, Optional[str]], requests.Session] = {}

    def _get_hosts(self, config):
        """Get configured Gitea hosts. Default: ['codeberg.org']."""
        return (config or {}).get('gitea', {}).get('hosts', _DEFAULT_HOSTS)

    def _get_token(self, config, host):
        """Get API token for a specific host.

        Resolution order:

        1. ``forges:`` entry with ``host == host``: read ``token_env`` and
           look up the named env var (Wave V2.C style).
        2. Legacy ``gitea.tokens.<host>`` map.
        3. Generic ``GITEA_TOKEN`` env var as a final fallback.

        Returns ``None`` when no token is configured for the host.
        """
        forges_config = (config or {}).get('forges') or {}
        if isinstance(forges_config, dict):
            for entry in forges_config.values():
                if isinstance(entry, dict) and entry.get('host') == host:
                    env_name = entry.get('token_env')
                    if env_name:
                        env_token = os.environ.get(env_name)
                        if env_token:
                            return env_token
        elif isinstance(forges_config, list):
            for entry in forges_config:
                if isinstance(entry, dict) and entry.get('host') == host:
                    env_name = entry.get('token_env')
                    if env_name:
                        env_token = os.environ.get(env_name)
                        if env_token:
                            return env_token

        # Legacy nested map: gitea.tokens.<host>
        tokens = (config or {}).get('gitea', {}).get('tokens', {})
        if tokens.get(host):
            return tokens.get(host)

        # Generic fallback
        return os.environ.get('GITEA_TOKEN')

    def _get_session(self, host: str, token: Optional[str]) -> requests.Session:
        """Get a cached requests.Session for this host+token combo."""
        key = (host, token)
        session = self._client_cache.get(key)
        if session is None:
            session = requests.Session()
            session.headers['User-Agent'] = 'repoindex (+https://github.com/queelius/repoindex)'
            if token:
                session.headers['Authorization'] = f'token {token}'
            self._client_cache[key] = session
        return session

    def detect(self, repo_path, repo_record=None):
        """Always return True; actual host matching happens in fetch()
        where config (with custom Gitea hosts) is available.

        The cost is one regex/URL parse per repo in fetch(), which is trivial.
        This allows self-hosted Gitea users with custom hosts in their config
        to use this source.
        """
        return True

    def fetch(self, repo_path, repo_record=None, config=None):
        """Fetch Gitea metadata and return generic forge fields.

        The dispatcher in ``commands/refresh.py`` fills in ``forge_id`` and
        ``forge_host`` from the resolved remote URL; this method returns
        only the per-platform fields in their unified form.
        """
        url = (repo_record or {}).get('remote_url', '')
        hosts = self._get_hosts(config)
        host, owner, name = _parse_gitea_remote(url, hosts)
        if not host or not owner or not name:
            return None

        token = self._get_token(config, host)
        session = self._get_session(host, token)

        try:
            api_url = f'https://{host}/api/v1/repos/{owner}/{name}'
            resp = session.get(api_url, timeout=10)
            if resp.status_code != 200:
                logger.debug(
                    "Gitea API %s returned %d for %s/%s",
                    host, resp.status_code, owner, name,
                )
                return None
            data = resp.json()
        except Exception as e:
            logger.debug("Gitea API request failed for %s/%s: %s", owner, name, e)
            return None

        # Generic forge fields (Wave V2.B). Note: Gitea's
        # has_pull_requests collapses into the generic has_issues concept;
        # not every forge family exposes a separate flag.
        result = {
            'forge_owner': owner,
            'forge_name': name,
            'stars': data.get('stars_count', 0),
            'forks_count': data.get('forks_count', 0),
            'watchers': data.get('watchers_count', 0),
            'open_issues': data.get('open_issues_count', 0),
            'is_fork': int(bool(data.get('fork', False))),
            'is_private': int(bool(data.get('private', False))),
            'is_archived': int(bool(data.get('archived', False))),
            'forge_description': data.get('description') or '',
            'forge_created_at': data.get('created_at'),
            'forge_updated_at': data.get('updated_at'),
        }

        default_branch = data.get('default_branch')
        if default_branch:
            result['default_branch'] = default_branch

        if data.get('description'):
            result['description'] = data['description']

        topics = data.get('topics')
        if topics and isinstance(topics, list):
            result['topics'] = json.dumps(topics)

        for key in ('has_issues', 'has_wiki'):
            val = data.get(key)
            if val is not None:
                result[key] = int(bool(val))

        return result

    # ------------------------------------------------------------------
    # Write capabilities (Wave V2.C)
    # ------------------------------------------------------------------

    def _resolve_target(
        self, repo_record: dict, config: Optional[dict]
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Resolve (host, owner, name) for an action.

        Prefers DB columns populated by V2.B's refresh dispatcher; falls
        back to remote_url parsing if the record predates refresh.
        """
        host = (repo_record or {}).get('forge_host')
        owner = (repo_record or {}).get('forge_owner')
        name = (repo_record or {}).get('forge_name')
        if host and owner and name:
            return host, owner, name
        hosts = self._get_hosts(config)
        remote_url = (repo_record or {}).get('remote_url', '')
        return _parse_gitea_remote(remote_url, hosts)

    def _request(
        self,
        method: str,
        host: str,
        path: str,
        config: Optional[dict],
        payload: Optional[dict] = None,
    ) -> Tuple[int, Optional[dict]]:
        """Issue an authenticated request to ``https://{host}/api/v1{path}``."""
        token = self._get_token(config, host)
        session = self._get_session(host, token)
        url = f'https://{host}/api/v1{path}'
        try:
            resp = session.request(method, url, json=payload, timeout=30)
        except requests.RequestException as e:
            logger.warning("Gitea %s %s failed: %s", method, url, e)
            return 0, None
        body: Optional[dict]
        try:
            body = resp.json() if resp.text else None
        except ValueError:
            body = None
        return resp.status_code, body

    def _ok(self, status: int, body: Optional[dict]) -> Tuple[bool, Optional[str]]:
        """Translate (status, body) into a (success, error_message) tuple."""
        if 200 <= status < 300:
            return True, None
        msg = (body or {}).get('message') if isinstance(body, dict) else None
        return False, msg or f"HTTP {status}"

    def enumerate_user_repos(self, config: dict) -> Iterator[RemoteRepo]:
        """Yield RemoteRepo records for every repo the authenticated user owns.

        Uses ``GET /repos/search?owner={user}`` paginated. The owner login
        is taken from ``config['author']['github']`` when set (we reuse
        the github login slot rather than introducing a per-forge login
        column; users with different logins per host can override via the
        per-forge config entry's ``user`` field).
        """
        for host in self._get_hosts(config):
            login = self._user_login(config, host)
            if not login:
                logger.warning(
                    "Gitea: no user login configured for host %s; skipping enumerate.",
                    host,
                )
                continue
            page = 1
            while True:
                qs = f"?owner={login}&limit=50&page={page}"
                status, body = self._request('GET', host, f"/repos/search{qs}", config)
                if status != 200 or not isinstance(body, dict):
                    if status != 200:
                        logger.warning(
                            "Gitea /repos/search on %s returned %d", host, status,
                        )
                    break
                data = body.get('data') or []
                if not isinstance(data, list) or not data:
                    break
                for repo in data:
                    if not isinstance(repo, dict):
                        continue
                    yield RemoteRepo(
                        name=repo.get('name') or '',
                        clone_url=repo.get('clone_url') or '',
                        default_branch=repo.get('default_branch'),
                        is_archived=bool(repo.get('archived', False)),
                        description=repo.get('description'),
                    )
                if len(data) < 50:
                    break
                page += 1

    def _user_login(self, config: Optional[dict], host: str) -> Optional[str]:
        """Return the authenticated-user login to filter by on this host.

        Reads ``forges:`` entries for an explicit per-host ``user``,
        falling back to ``config['author']['github']``.
        """
        forges_config = (config or {}).get('forges') or {}
        entries: List[dict] = []
        if isinstance(forges_config, dict):
            entries = [e for e in forges_config.values() if isinstance(e, dict)]
        elif isinstance(forges_config, list):
            entries = [e for e in forges_config if isinstance(e, dict)]
        for entry in entries:
            if entry.get('host') == host and entry.get('user'):
                return entry.get('user')
        return (config or {}).get('author', {}).get('github') or None

    def set_topics(
        self, repo_record: dict, topics: List[str], config: dict
    ) -> None:
        """PUT /repos/{owner}/{name}/topics with ``{'topics': [...]}``."""
        host, owner, name = self._resolve_target(repo_record, config)
        if not host or not owner or not name:
            raise ValueError("Cannot resolve host/owner/name for Gitea repo")
        status, body = self._request(
            'PUT', host, f"/repos/{owner}/{name}/topics",
            config, {'topics': list(topics)},
        )
        ok, err = self._ok(status, body)
        if not ok:
            raise RuntimeError(err)

    def set_description(
        self, repo_record: dict, description: str, config: dict
    ) -> None:
        """PATCH /repos/{owner}/{name} with ``description``."""
        host, owner, name = self._resolve_target(repo_record, config)
        if not host or not owner or not name:
            raise ValueError("Cannot resolve host/owner/name for Gitea repo")
        status, body = self._request(
            'PATCH', host, f"/repos/{owner}/{name}",
            config, {'description': description},
        )
        ok, err = self._ok(status, body)
        if not ok:
            raise RuntimeError(err)

    def set_archived(
        self, repo_record: dict, archived: bool, config: dict
    ) -> None:
        """PATCH /repos/{owner}/{name} with ``archived``."""
        host, owner, name = self._resolve_target(repo_record, config)
        if not host or not owner or not name:
            raise ValueError("Cannot resolve host/owner/name for Gitea repo")
        status, body = self._request(
            'PATCH', host, f"/repos/{owner}/{name}",
            config, {'archived': bool(archived)},
        )
        ok, err = self._ok(status, body)
        if not ok:
            raise RuntimeError(err)

    def set_visibility(
        self, repo_record: dict, public: bool, config: dict
    ) -> None:
        """PATCH /repos/{owner}/{name} with ``private`` (the inverse)."""
        host, owner, name = self._resolve_target(repo_record, config)
        if not host or not owner or not name:
            raise ValueError("Cannot resolve host/owner/name for Gitea repo")
        status, body = self._request(
            'PATCH', host, f"/repos/{owner}/{name}",
            config, {'private': not bool(public)},
        )
        ok, err = self._ok(status, body)
        if not ok:
            raise RuntimeError(err)

    def set_default_branch(
        self, repo_record: dict, branch: str, config: dict
    ) -> None:
        """PATCH /repos/{owner}/{name} with ``default_branch``."""
        host, owner, name = self._resolve_target(repo_record, config)
        if not host or not owner or not name:
            raise ValueError("Cannot resolve host/owner/name for Gitea repo")
        status, body = self._request(
            'PATCH', host, f"/repos/{owner}/{name}",
            config, {'default_branch': branch},
        )
        ok, err = self._ok(status, body)
        if not ok:
            raise RuntimeError(err)

    def enable_pages(
        self, repo_record: dict, branch: str, path: str, config: dict
    ) -> None:
        """Pages support varies across Gitea instances; not implemented.

        Codeberg ships Codeberg Pages with separate mechanics; vanilla
        Gitea has no equivalent. Users hitting this hook get a clean
        ``NotImplementedError`` surfaced as a per-repo error.
        """
        raise NotImplementedError(
            "gitea does not support enable_pages "
            "(Pages mechanics vary per instance; configure manually)"
        )


source = GiteaSource()
