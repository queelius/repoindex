"""
Digest command for repoindex.

Summarizes recent git activity into a structured overview grouped by project,
with commit type breakdowns, representative messages, and release highlights.
"""

import json
import re
import sys

import click

from datetime import datetime

from ..config import load_config
from ..database import Database
from ..events import parse_timespec

# Conventional commit prefix regex
_CONVENTIONAL_RE = re.compile(
    r'^(feat|fix|docs|refactor|test|chore|ci|style|perf|build|revert)'
    r'(?:\(([^)]+)\))?[!:]'
)


def parse_commit_prefix(msg: str) -> tuple:
    """Parse a commit message for conventional commit prefix.

    Returns:
        (type, scope|None) — e.g. ("feat", "papermill") or ("other", None)
    """
    if not msg:
        return ("other", None)
    first_line = msg.split('\n', 1)[0].strip()
    m = _CONVENTIONAL_RE.match(first_line)
    if m:
        return (m.group(1), m.group(2))
    return ("other", None)


def pick_representative(messages: list, limit: int = 5) -> list:
    """Pick up to *limit* representative commit messages.

    Strategy: deduplicate first lines, prefer conventional commits
    (more informative), then fill with freeform, up to limit.
    """
    if not messages:
        return []

    # Extract unique first lines, preserving order
    seen = set()
    conventional = []
    freeform = []
    for msg in messages:
        first_line = msg.split('\n', 1)[0].strip()
        if not first_line or first_line in seen:
            continue
        seen.add(first_line)
        if _CONVENTIONAL_RE.match(first_line):
            conventional.append(first_line)
        else:
            freeform.append(first_line)

    # Conventional first (more informative), then freeform
    result = conventional + freeform
    return result[:limit]


def _build_digest(db, since_dt: datetime, now: datetime, top: int | None) -> dict:
    """Build the digest data structure from the database.

    Args:
        db: Open Database connection
        since_dt: Start of the digest period
        now: End of the digest period (typically datetime.now())
        top: If set, limit to top N repos by commit count

    Returns:
        Digest dict with period, summary, projects, releases, languages
    """
    since_iso = since_dt.isoformat()
    days = max(1, (now - since_dt).days)

    # Q1 — Summary totals
    db.execute("""
        SELECT COUNT(*) as total_events,
            SUM(CASE WHEN type='commit' THEN 1 ELSE 0 END) as total_commits,
            SUM(CASE WHEN type='git_tag' THEN 1 ELSE 0 END) as total_tags,
            SUM(CASE WHEN type='merge' THEN 1 ELSE 0 END) as total_merges,
            COUNT(DISTINCT repo_id) as repos_active
        FROM events WHERE timestamp >= ?
    """, (since_iso,))
    summary_row = db.fetchone()

    summary = {
        "repos_active": summary_row["repos_active"] or 0,
        "total_commits": summary_row["total_commits"] or 0,
        "total_tags": summary_row["total_tags"] or 0,
        "total_merges": summary_row["total_merges"] or 0,
    }

    # Q2 — Per-repo commits with batched messages
    q2_sql = """
        SELECT r.name, r.language, r.is_clean,
            COUNT(*) as commits,
            GROUP_CONCAT(e.message, char(31)) as messages
        FROM events e JOIN repos r ON r.id = e.repo_id
        WHERE e.type='commit' AND e.timestamp >= ?
        GROUP BY e.repo_id ORDER BY commits DESC
    """
    if top:
        q2_sql += " LIMIT ?"
        db.execute(q2_sql, (since_iso, top))
    else:
        db.execute(q2_sql, (since_iso,))

    projects = []
    for row in db.fetchall():
        raw_msgs = (row["messages"] or "").split("\x1f")
        raw_msgs = [m for m in raw_msgs if m]

        by_type: dict[str, int] = {}
        scopes: set[str] = set()
        for msg in raw_msgs:
            prefix, scope = parse_commit_prefix(msg)
            by_type[prefix] = by_type.get(prefix, 0) + 1
            if scope:
                scopes.add(scope)

        projects.append({
            "name": row["name"],
            "language": row["language"],
            "commits": row["commits"],
            "by_type": by_type,
            "scopes": sorted(scopes),
            "recent_messages": pick_representative(raw_msgs),
            "tags": [],  # filled from Q3
            "is_dirty": not row["is_clean"],
        })

    # Build a lookup for adding tags to projects
    project_idx = {p["name"]: p for p in projects}

    # Q3 — Tags/releases
    db.execute("""
        SELECT r.name as repo, e.ref as tag, e.timestamp
        FROM events e JOIN repos r ON r.id = e.repo_id
        WHERE e.type='git_tag' AND e.timestamp >= ?
        ORDER BY e.timestamp DESC
    """, (since_iso,))

    releases = []
    for row in db.fetchall():
        releases.append({
            "repo": row["repo"],
            "tag": row["tag"],
            "timestamp": row["timestamp"],
        })
        # Also annotate the project entry if it exists
        if row["repo"] in project_idx:
            project_idx[row["repo"]]["tags"].append(row["tag"])

    # Q4 — Language distribution
    db.execute("""
        SELECT r.language, COUNT(DISTINCT e.repo_id) as active_repos
        FROM events e JOIN repos r ON r.id = e.repo_id
        WHERE e.type='commit' AND e.timestamp >= ? AND r.language IS NOT NULL
        GROUP BY r.language ORDER BY active_repos DESC
    """, (since_iso,))

    languages = [[row["language"], row["active_repos"]] for row in db.fetchall()]

    return {
        "period": {
            "since": since_dt.strftime("%Y-%m-%d"),
            "until": now.strftime("%Y-%m-%d"),
            "days": days,
        },
        "summary": summary,
        "projects": projects,
        "releases": releases,
        "languages": languages,
    }


def _print_pretty(data: dict) -> None:
    """Render the digest as a Rich console dashboard."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    console = Console()
    period = data["period"]
    summary = data["summary"]

    since_dt = datetime.fromisoformat(period["since"])
    until_dt = datetime.fromisoformat(period["until"])
    title = f"Activity Digest ({since_dt.strftime('%b %d')} \u2013 {until_dt.strftime('%b %d')}, {period['days']} days)"

    console.print()
    console.print(f"[bold cyan]{title}[/bold cyan]")
    console.print("\u2550" * len(title))

    total = summary["total_commits"] + summary["total_tags"] + summary["total_merges"]
    if total == 0:
        console.print(f"[yellow]No activity found in the last {period['days']} days.[/yellow]")
        return

    # Summary line
    parts = []
    if summary["total_commits"]:
        parts.append(f"{summary['total_commits']} commits")
    if summary["total_tags"]:
        parts.append(f"{summary['total_tags']} tags")
    if summary["total_merges"]:
        parts.append(f"{summary['total_merges']} merges")
    console.print(f"{', '.join(parts)} across {summary['repos_active']} repos")
    console.print()

    # Projects table
    if data["projects"]:
        table = Table(
            title="Top Projects",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Repository", style="cyan")
        table.add_column("Lang")
        table.add_column("Commits", justify="right")
        table.add_column("Breakdown")
        table.add_column("Status")

        for proj in data["projects"]:
            # Build breakdown string from by_type (skip "other" if only type)
            breakdown_parts = []
            for t in ("feat", "fix", "docs", "refactor", "test", "chore", "ci", "style", "perf", "build", "revert"):
                if t in proj["by_type"]:
                    breakdown_parts.append(f"{t}:{proj['by_type'][t]}")
            other_count = proj["by_type"].get("other", 0)
            if other_count and breakdown_parts:
                breakdown_parts.append(f"other:{other_count}")
            elif other_count and not breakdown_parts:
                breakdown_parts.append(f"{other_count} freeform")
            breakdown = ", ".join(breakdown_parts)

            status = "[yellow]dirty[/yellow]" if proj["is_dirty"] else "[green]clean[/green]"
            table.add_row(
                proj["name"],
                proj["language"] or "",
                str(proj["commits"]),
                breakdown,
                status,
            )

        console.print(table)
        console.print()

    # Releases
    if data["releases"]:
        rel_parts = [f"{r['repo']} {r['tag']}" for r in data["releases"][:10]]
        console.print(f"[bold]Releases:[/bold] {', '.join(rel_parts)}")

    # Languages
    if data["languages"]:
        lang_parts = [f"{lang} ({count})" for lang, count in data["languages"][:8]]
        console.print(f"[bold]Languages:[/bold] {', '.join(lang_parts)}")

    console.print()


@click.command("digest")
@click.option("--since", "-s", default="7d",
              help="Time range (e.g., 7d, 30d, 1w, 2024-01-01). Default: 7d")
@click.option("--top", "-n", type=int, default=None,
              help="Limit to top N repos by commit count")
@click.option("--json", "output_json", is_flag=True,
              help="Output as structured JSON")
def digest_handler(since: str, top: int | None, output_json: bool):
    """
    Summarize recent activity across all repositories.

    Produces a structured overview grouped by project, with commit type
    breakdowns, representative messages, and release highlights.

    \b
    Examples:
        # Last 7 days (default), pretty output
        repoindex digest
        # Last 30 days
        repoindex digest --since 30d
        # Structured JSON for scripting
        repoindex digest --json
        # Top 5 repos only
        repoindex digest --top 5
    """
    config = load_config()
    now = datetime.now()

    try:
        since_dt = parse_timespec(since)
    except ValueError:
        click.echo(f"Error: cannot parse time spec '{since}'", err=True)
        sys.exit(1)

    try:
        with Database(config=config, read_only=True) as db:
            from . import warn_if_stale
            warn_if_stale(db)

            data = _build_digest(db, since_dt, now, top)

    except Exception as e:
        click.echo(f"Error building digest: {e}", err=True)
        sys.exit(1)

    if output_json:
        print(json.dumps(data, indent=2, default=str))
    else:
        _print_pretty(data)
