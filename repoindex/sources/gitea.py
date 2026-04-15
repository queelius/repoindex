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
"""
import json
import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from . import MetadataSource

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


class GiteaSource(MetadataSource):
    """Metadata source for Gitea-based hosting platforms."""

    source_id = "gitea"
    name = "Gitea / Codeberg"
    target = "repos"

    def __init__(self):
        # Session cache keyed by (host, token_or_None) for connection pooling
        self._client_cache: Dict[Tuple[str, Optional[str]], requests.Session] = {}

    def _get_hosts(self, config):
        """Get configured Gitea hosts. Default: ['codeberg.org']."""
        return (config or {}).get('gitea', {}).get('hosts', _DEFAULT_HOSTS)

    def _get_token(self, config, host):
        """Get API token for a specific host."""
        tokens = (config or {}).get('gitea', {}).get('tokens', {})
        return tokens.get(host)

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

        result = {
            'gitea_owner': owner,
            'gitea_name': name,
            'gitea_host': host,
            'gitea_stars': data.get('stars_count', 0),
            'gitea_forks': data.get('forks_count', 0),
            'gitea_watchers': data.get('watchers_count', 0),
            'gitea_open_issues': data.get('open_issues_count', 0),
            'gitea_is_fork': int(bool(data.get('fork', False))),
            'gitea_is_private': int(bool(data.get('private', False))),
            'gitea_is_archived': int(bool(data.get('archived', False))),
            'gitea_description': data.get('description') or '',
            'gitea_created_at': data.get('created_at'),
            'gitea_updated_at': data.get('updated_at'),
        }

        if data.get('description'):
            result['description'] = data['description']

        topics = data.get('topics')
        if topics and isinstance(topics, list):
            result['gitea_topics'] = json.dumps(topics)

        for key in ('has_issues', 'has_wiki', 'has_pull_requests'):
            val = data.get(key)
            if val is not None:
                result[f'gitea_{key}'] = int(bool(val))

        return result


source = GiteaSource()
