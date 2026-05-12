"""Helpers for finding and dispatching to GitForge sources.

Wave V2.C introduced cross-platform write actions on the GitForge ABC.
The ``ops set-*`` commands look up a repo's ``forge_id`` and dispatch
to the matching source instance. These helpers centralise that lookup
so the command handlers stay short.
"""

from __future__ import annotations

from typing import Optional

from ..sources import GitForge, discover_sources


def find_forge(forge_id: str) -> Optional[GitForge]:
    """Return the GitForge whose ``source_id`` matches ``forge_id``.

    Returns ``None`` for an empty/unknown ``forge_id``.
    """
    if not forge_id:
        return None
    for source in discover_sources():
        if isinstance(source, GitForge) and source.source_id == forge_id:
            return source
    return None


def lookup_repo_forge(repo_record: Optional[dict]) -> Optional[GitForge]:
    """Return the GitForge that owns ``repo_record``.

    Reads ``repo_record['forge_id']`` (set by V2.B's refresh dispatcher)
    and looks up the matching source. Returns ``None`` if the repo has
    no resolved forge or if no source claims the id.
    """
    if not repo_record:
        return None
    return find_forge(repo_record.get('forge_id'))


__all__ = ['find_forge', 'lookup_repo_forge']
