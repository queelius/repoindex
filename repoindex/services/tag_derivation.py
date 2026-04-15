"""
Tag derivation from repository metadata.

Single source of truth for converting a repos-table row (plus related
publications rows) into the set of derived / implicit tags that the rest
of the system persists and queries. Previously this logic lived in three
places — `commands/refresh.py:_derive_tags`, `commands/tag.py:get_implicit_tags_from_row`,
and `services/tag_service.py:TagService.get_implicit_tags` — and they
drifted (e.g., one lowercased topics while another did not). Centralizing
it here keeps all call sites consistent.

The derivation is purely functional over dict inputs and returns
`(tag_string, source_label)` tuples so callers can persist them with
attribution or flatten to just the tag strings.

Source labels mirror what the `tags` table stores in its `source` column:
- 'implicit' — derived from intrinsic repo state (language, has_* flags,
  is_clean, etc.)
- 'github', 'gitea' — platform-provided topics
- 'pyproject' — keywords from a local file (pyproject.toml / package.json)
- '<registry>' — the registry name itself, for `published:<registry>` tags
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# (tag_string, source_label)
DerivedTag = Tuple[str, str]


# Boolean flags on the repos table that map 1:1 to has:<name> tags.
# Order is preserved so derived-tag output is deterministic.
_HAS_FLAGS: Tuple[str, ...] = (
    'has_readme',
    'has_license',
    'has_ci',
    'has_citation',
    'has_codemeta',
    'has_funding',
    'has_contributors',
    'has_changelog',
)


def _load_json_list(raw: Any) -> Optional[list]:
    """Decode a JSON array stored as a TEXT column, or pass through a list.

    Returns None on malformed input, empty list for empty input. Keeps
    callers from having to repeat the try/except dance.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, list) else None


def _normalize_topic(value: Any) -> Optional[str]:
    """Lowercase + strip topics/keywords; None for non-strings or empties.

    Matches the normalization applied everywhere topics and keywords are
    written. Anything else (numbers, None, whitespace-only) is dropped.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped.lower()


def derive_persistable_tags(
    repo_row: Mapping[str, Any],
    published_registries: Iterable[str] = (),
) -> List[DerivedTag]:
    """Derived tags that get written to the `tags` table during refresh.

    This is the set that `_sync_derived_tags` reconciles: topics, keywords,
    language, has_* flags, and publication-status tags. The `repo:`, `dir:`,
    `owner:`, `license:`, `status:`, and GitHub visibility/stars tags come
    from `derive_implicit_tags` below and are not persisted through this
    path (they are rendered on demand for queries that join against the
    repos table directly).

    Args:
        repo_row: A dict-like row from the repos table.
        published_registries: Iterable of registry names where the repo
            has published=1 rows in the publications table. The caller
            runs the SQL; this function just maps to tag strings.

    Returns:
        List of (tag_string, source_label) tuples.
    """
    derived: List[DerivedTag] = []

    # Platform topics (github / gitea)
    for field, source_name in (
        ('github_topics', 'github'),
        ('gitea_topics', 'gitea'),
    ):
        topics = _load_json_list(repo_row.get(field))
        if topics:
            for topic in topics:
                norm = _normalize_topic(topic)
                if norm:
                    derived.append((f'topic:{norm}', source_name))

    # Project keywords (pyproject.toml / package.json)
    keywords = _load_json_list(repo_row.get('keywords'))
    if keywords:
        for kw in keywords:
            norm = _normalize_topic(kw)
            if norm:
                derived.append((f'keyword:{norm}', 'pyproject'))

    # Language
    lang = repo_row.get('language')
    if lang and isinstance(lang, str):
        derived.append((f'lang:{lang.lower()}', 'implicit'))

    # Boolean flags
    for flag in _HAS_FLAGS:
        if repo_row.get(flag):
            tag_name = flag.replace('has_', 'has:')
            derived.append((tag_name, 'implicit'))

    # Publication status (attribution = registry itself)
    for registry in published_registries:
        if registry:
            derived.append((f'published:{registry}', registry))

    return derived


def derive_implicit_tags(repo_row: Mapping[str, Any]) -> List[str]:
    """Implicit tags for a repo, returned as plain strings.

    Superset of `derive_persistable_tags` that also includes the
    identity-level tags (`repo:`, `dir:`, `owner:`, `license:`,
    `status:`) and GitHub-specific read-view tags (`visibility:`,
    `source:fork`, `archived:true`, `stars:N+`). This is the view
    the `tag list` / `tag tree` commands render.

    The union covers both what the refresh writes to the DB and what
    read-only callers want to display. Callers that only need one side
    should use `derive_persistable_tags` or filter the output.

    Args:
        repo_row: A dict-like row from the repos table.

    Returns:
        List of tag strings (deduplicated would require set(); this
        function preserves order for stable output).
    """
    tags: List[str] = []

    # repo:name
    name = repo_row.get('name')
    if name:
        tags.append(f"repo:{name}")

    # dir:parent (from path)
    path = repo_row.get('path')
    if path:
        parent = Path(path).parent.name
        if parent:
            tags.append(f"dir:{parent}")

    # Persistable tags (lang, topics, keywords, has:*, published:*)
    # Note: published:* requires an extra query and is typically empty
    # from this call site; callers needing it pass published_registries
    # through a lower-level helper.
    for tag_string, _source in derive_persistable_tags(repo_row):
        tags.append(tag_string)

    # owner:owner
    owner = repo_row.get('owner')
    if owner:
        tags.append(f"owner:{owner}")

    # license:key
    license_key = repo_row.get('license_key')
    if license_key:
        tags.append(f"license:{license_key}")

    # status:clean or status:dirty
    is_clean = repo_row.get('is_clean')
    if is_clean is not None:
        tags.append(f"status:{'clean' if is_clean else 'dirty'}")

    # GitHub-specific implicit tags (guarded on github_owner presence
    # because the github_* columns are all nullable and a non-GitHub repo
    # would otherwise get a phantom visibility:public)
    if repo_row.get('github_owner'):
        if repo_row.get('github_is_private'):
            tags.append("visibility:private")
        else:
            tags.append("visibility:public")

        if repo_row.get('github_is_fork'):
            tags.append("source:fork")

        if repo_row.get('github_is_archived'):
            tags.append("archived:true")

        stars = repo_row.get('github_stars') or 0
        if stars >= 1000:
            tags.append("stars:1000+")
        elif stars >= 100:
            tags.append("stars:100+")
        elif stars >= 10:
            tags.append("stars:10+")

    return tags


__all__ = [
    'DerivedTag',
    'derive_persistable_tags',
    'derive_implicit_tags',
]
