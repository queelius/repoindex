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
from typing import List, Optional, Tuple

import requests

from . import MetadataSource

logger = logging.getLogger(__name__)

_DEFAULT_HOSTS = ['codeberg.org']


def _parse_gitea_remote(
    url: Optional[str], hosts: List[str]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract (host, owner, name) from a Gitea remote URL.

    Returns (None, None, None) if URL doesn't match any configured host.
    Handles HTTPS and SSH URLs, with/without .git suffix.
    """
    if not url:
        return None, None, None
    for host in hosts:
        # Matches both HTTPS (https://host/user/repo) and SSH (git@host:user/repo)
        pattern = re.compile(
            rf'{re.escape(host)}[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$'
        )
        m = pattern.search(url)
        if m:
            return host, m.group(1), m.group(2)
    return None, None, None


class GiteaSource(MetadataSource):
    """Metadata source for Gitea-based hosting platforms."""

    source_id = "gitea"
    name = "Gitea / Codeberg"
    target = "repos"

    def __init__(self):
        self._client_cache = {}  # (host, token) -> requests.Session

    def _get_hosts(self, config):
        """Get configured Gitea hosts. Default: ['codeberg.org']."""
        return (config or {}).get('gitea', {}).get('hosts', _DEFAULT_HOSTS)

    def _get_token(self, config, host):
        """Get API token for a specific host."""
        tokens = (config or {}).get('gitea', {}).get('tokens', {})
        return tokens.get(host)

    def detect(self, repo_path, repo_record=None):
        url = (repo_record or {}).get('remote_url', '')
        # Use default hosts for detection (config not available in detect)
        host, owner, name = _parse_gitea_remote(url, _DEFAULT_HOSTS)
        return host is not None

    def fetch(self, repo_path, repo_record=None, config=None):
        url = (repo_record or {}).get('remote_url', '')
        hosts = self._get_hosts(config)
        host, owner, name = _parse_gitea_remote(url, hosts)
        if not host or not owner or not name:
            return None

        token = self._get_token(config, host)
        headers = {'User-Agent': 'repoindex (+https://github.com/queelius/repoindex)'}
        if token:
            headers['Authorization'] = f'token {token}'

        try:
            api_url = f'https://{host}/api/v1/repos/{owner}/{name}'
            resp = requests.get(api_url, headers=headers, timeout=10)
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
