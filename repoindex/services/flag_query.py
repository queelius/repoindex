"""
Flag-based query builder for repoindex.

Builds SQL WHERE clauses and parameter lists from the standard filter flags
used by operation commands (ops, copy, link, export). This replaces the old
flags -> DSL -> SQL round-trip that went through the now-deleted query
compiler.

Only four filters are supported — these mirror the `query_options` decorator
in `commands/ops.py`:

- dirty: is_clean = 0 (repos with uncommitted changes)
- language: language = X (case-sensitive, with common aliases normalized)
- tag: EXISTS in tags table (one filter per flag; supports `*` wildcard)
- recent: has a commit event in the last N days/weeks/etc.

For anything more complex, use raw SQL via `repoindex sql` or the MCP
run_sql tool.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple


# Common language name aliases → canonical names stored in the DB.
# Matches the aliases the old DSL query builder used.
_LANGUAGE_ALIASES = {
    'py': 'Python',
    'python': 'Python',
    'js': 'JavaScript',
    'javascript': 'JavaScript',
    'ts': 'TypeScript',
    'typescript': 'TypeScript',
    'rb': 'Ruby',
    'ruby': 'Ruby',
    'rs': 'Rust',
    'rust': 'Rust',
    'go': 'Go',
    'golang': 'Go',
    'cpp': 'C++',
    'c++': 'C++',
}


def _normalize_language(language: str) -> str:
    """Map a short/lowercase language alias to its canonical form."""
    return _LANGUAGE_ALIASES.get(language.lower(), language)


def _parse_recent_duration(recent: str) -> datetime:
    """Parse a duration string ('30d', '2w', '3m' months, '1y', ISO date) into a cutoff datetime.

    Delegates to services.timespec.parse_since (the single duration parser).
    Raises ValueError on unparseable input: there is no silent default.
    """
    from .timespec import parse_since
    return parse_since(recent)


def build_where_and_params(
    *,
    dirty: bool = False,
    language: Optional[str] = None,
    tag: Sequence[str] = (),
    recent: Optional[str] = None,
) -> Tuple[str, List[Any]]:
    """Build a SQL WHERE clause and parameter list from standard filter flags.

    Returns ``('1=1', [])`` if no filters are active so callers can always
    splice the WHERE into their query without branching.

    Args:
        dirty: If True, only repos with uncommitted changes (is_clean = 0).
        language: Filter by language (case-insensitive alias lookup).
        tag: Zero or more tag filters. Each tag must match (AND semantics);
            ``*`` acts as a SQL LIKE wildcard (translated to ``%``).
        recent: Duration string (e.g. '7d', '30d'); repos must have a commit
            event newer than ``now - duration``.

    Returns:
        (where_clause, params) — where_clause is a SQL snippet suitable for
        substituting into ``SELECT ... FROM repos WHERE {where_clause}``.
    """
    clauses: List[str] = []
    params: List[Any] = []

    if dirty:
        clauses.append("is_clean = 0")

    if language:
        clauses.append("language = ?")
        params.append(_normalize_language(language))

    for t in tag:
        if not t:
            continue
        if '*' in t or '%' in t:
            pattern = t.replace('*', '%')
            clauses.append(
                "EXISTS (SELECT 1 FROM tags WHERE tags.repo_id = repos.id AND tags.tag LIKE ?)"
            )
            params.append(pattern)
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM tags WHERE tags.repo_id = repos.id AND tags.tag = ?)"
            )
            params.append(t)

    if recent:
        cutoff = _parse_recent_duration(recent)
        clauses.append(
            "EXISTS (SELECT 1 FROM events WHERE events.repo_id = repos.id "
            "AND events.type = 'commit' AND events.timestamp >= ?)"
        )
        params.append(cutoff.isoformat())

    if not clauses:
        return "1=1", []
    return " AND ".join(clauses), params


def fetch_repos_by_flags(
    config: dict,
    *,
    dirty: bool = False,
    language: Optional[str] = None,
    tag: Sequence[str] = (),
    recent: Optional[str] = None,
    debug: bool = False,
) -> List[dict]:
    """Fetch repositories matching the given filter flags.

    This is the drop-in replacement for the old
    ``commands/ops.py:_get_repos_from_query`` pipeline. It handles:

    - Building the SQL WHERE clause from flags.
    - Running the query against the repoindex database.
    - Filtering out repos under ``config['exclude_directories']``.

    Args:
        config: Loaded repoindex config dict.
        dirty: See :func:`build_where_and_params`.
        language: See :func:`build_where_and_params`.
        tag: See :func:`build_where_and_params`.
        recent: See :func:`build_where_and_params`.
        debug: If True, print the generated SQL and params to stderr.

    Returns:
        List of repo dicts (one per matching row in the ``repos`` table).
    """
    import sys

    from ..database import Database

    where, params = build_where_and_params(
        dirty=dirty, language=language, tag=tag, recent=recent
    )
    sql = f"SELECT * FROM repos WHERE {where}"

    if debug:
        print(f"DEBUG: SQL: {sql}", file=sys.stderr)
        print(f"DEBUG: Params: {params}", file=sys.stderr)

    repos: List[dict] = []
    with Database(config=config, read_only=True) as db:
        from ..commands import warn_if_stale

        warn_if_stale(db)
        db.execute(sql, tuple(params))
        for row in db.fetchall():
            repos.append(dict(row))

    exclude_dirs = config.get('exclude_directories', [])
    if exclude_dirs:
        expanded = [str(Path(d).expanduser()).rstrip('/') for d in exclude_dirs]
        repos = [r for r in repos if not any(r['path'].startswith(e) for e in expanded)]

    return repos
