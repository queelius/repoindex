"""Resolve a repo's forge from its origin remote URL.

Maps hostnames to forge_id values. Used during refresh to populate the
``repos.forge_id`` and ``repos.forge_host`` columns. The output of
``resolve_forge`` is the bridge between the GitForge ABC discovery layer
and the per-repo forge metadata fetch: refresh runs only the GitForge
whose ``source_id`` matches the resolved ``forge_id`` (instead of asking
every forge to ``detect()`` against every repo).

Built-in defaults cover the canonical platforms (github.com,
codeberg.org). User-configured forges in ``config['forges']`` add custom
hosts (e.g., self-hosted Gitea, Codeberg-as-mirror, etc.).
"""

from __future__ import annotations

import re
from typing import Optional, Tuple
from urllib.parse import urlparse


# Hostname -> forge_id. Authoritative for the canonical platforms.
DEFAULT_FORGE_HOSTS = {
    'github.com': 'github',
    'codeberg.org': 'gitea',  # codeberg runs gitea
}


# SSH-form prefix: git@host:owner/repo or user@host:owner/repo (no scheme).
_SSH_REMOTE_RE = re.compile(r'^(?:[^@/\s]+@)?([^:/\s]+):.+$')


def _extract_host(remote_url: str) -> Optional[str]:
    """Best-effort hostname extraction.

    Handles:
    - https://host/owner/repo[.git]
    - ssh://git@host[:port]/owner/repo[.git]
    - git@host:owner/repo[.git] (no scheme)

    Returns None for empty/malformed input.
    """
    if not remote_url:
        return None

    if remote_url.startswith(('http://', 'https://', 'ssh://', 'git://')):
        try:
            parsed = urlparse(remote_url)
            host = parsed.hostname  # urllib strips ports
            return host or None
        except Exception:
            return None

    # SSH form: git@host:owner/repo[.git]
    match = _SSH_REMOTE_RE.match(remote_url)
    if match:
        return match.group(1) or None

    return None


def resolve_forge(remote_url: Optional[str], config: Optional[dict]) -> Optional[Tuple[str, str]]:
    """Return ``(forge_id, host)`` for the given remote_url, or ``None``.

    Resolution order:

    1. Built-in defaults from ``DEFAULT_FORGE_HOSTS`` (github.com, codeberg.org).
    2. User-configured forges in ``config['forges']``: each entry may set a
       ``host`` field; matching it returns the entry's ``source_id`` (or
       the entry's name as a fallback).

    Args:
        remote_url: The repo's origin remote URL (may be HTTPS or SSH).
        config: Full config dict, or None.

    Returns:
        Tuple of ``(forge_id, host)`` if resolved, else ``None``.
    """
    host = _extract_host(remote_url) if remote_url else None
    if not host:
        return None

    # Built-in defaults first
    if host in DEFAULT_FORGE_HOSTS:
        return (DEFAULT_FORGE_HOSTS[host], host)

    # User-configured forges. Both primary and mirror roles contribute to
    # the hostname mapping: a repo cloned from a self-hosted Gitea is still
    # a Gitea repo regardless of whether you also push it as a mirror.
    from ..services.forge_config import load_forges, ForgeConfigError
    try:
        entries = load_forges(config)
    except ForgeConfigError:
        entries = []
    for entry in entries:
        if entry.host == host:
            return (entry.source_id, host)

    return None


__all__ = [
    'DEFAULT_FORGE_HOSTS',
    'resolve_forge',
]
