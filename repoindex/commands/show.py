"""
Show command for repoindex.

Provides a detailed single-repo view with all metadata, tags,
publications, and recent events.
"""

import json
import sys
from pathlib import Path
from typing import Optional

import click

from ..config import load_config
from ..database import Database


def _shorten_path(path: str) -> str:
    """Shorten a filesystem path for display (replace $HOME with ~)."""
    home = str(Path.home())
    if path.startswith(home):
        return '~' + path[len(home):]
    return path


def _find_repo(db, identifier: str) -> Optional[dict]:
    """Find a repo by name or path. Returns dict or None."""
    # Try exact name match first
    db.execute("SELECT * FROM repos WHERE name = ?", (identifier,))
    row = db.fetchone()
    if row:
        return dict(row)

    # Try path match (expand ~ for user convenience)
    expanded = str(Path(identifier).expanduser()) if identifier.startswith('~') else identifier
    db.execute("SELECT * FROM repos WHERE path = ?", (expanded,))
    row = db.fetchone()
    if row:
        return dict(row)

    # Try substring name match (case-insensitive)
    db.execute("SELECT * FROM repos WHERE name LIKE ? COLLATE NOCASE", (f'%{identifier}%',))
    rows = db.fetchall()
    if len(rows) == 1:
        return dict(rows[0])
    elif len(rows) > 1:
        return rows  # Multiple matches — caller will handle

    return None


def _fetch_related(db, repo_id: int) -> tuple:
    """Fetch tags, publications, and recent events for a repo."""
    db.execute("SELECT tag, source FROM tags WHERE repo_id = ? ORDER BY tag", (repo_id,))
    tags = [dict(r) for r in db.fetchall()]

    db.execute(
        "SELECT registry, package_name, current_version, published, url, doi "
        "FROM publications WHERE repo_id = ?",
        (repo_id,)
    )
    publications = [dict(r) for r in db.fetchall()]

    db.execute(
        "SELECT type, timestamp, ref, message, author "
        "FROM events WHERE repo_id = ? ORDER BY timestamp DESC LIMIT 10",
        (repo_id,)
    )
    events = [dict(r) for r in db.fetchall()]

    return tags, publications, events


def _output_json(repo: dict, tags: list, publications: list, events: list):
    """Output repo details as a single JSON object."""
    repo['tags'] = [t['tag'] for t in tags]
    repo['publications'] = publications
    repo['recent_events'] = events
    print(json.dumps(repo, ensure_ascii=False, default=str), flush=True)


def _output_pretty(repo: dict, tags: list, publications: list, events: list):
    """Render repo details with Rich."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box

    console = Console()

    # Header
    console.print()
    console.print(f"  [bold cyan]{repo['name']}[/bold cyan]")
    console.print(f"  [dim]{_shorten_path(repo.get('path', ''))}[/dim]")
    if repo.get('description'):
        console.print(f"  [italic]{repo['description']}[/italic]")
    console.print()

    # Core metadata
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold", min_width=12)
    table.add_column("Value")

    if repo.get('language'):
        table.add_row("Language", repo['language'])
    table.add_row("Branch", repo.get('branch', ''))

    clean = repo.get('is_clean')
    if clean is not None:
        clean_str = "[green]Yes[/green]" if clean else "[yellow]No[/yellow]"
        table.add_row("Clean", clean_str)

    if repo.get('remote_url'):
        table.add_row("Remote", repo['remote_url'])
    if repo.get('license_name') or repo.get('license_key'):
        table.add_row("License", repo.get('license_name') or repo.get('license_key', ''))

    console.print(table)

    # GitHub metadata
    has_github = repo.get('github_owner') or repo.get('github_stars') is not None
    if has_github:
        console.print()
        console.print("  [bold]GitHub[/bold]")
        parts = []
        stars = repo.get('github_stars', 0) or 0
        forks = repo.get('github_forks', 0) or 0
        parts.append(f"Stars: {stars}")
        parts.append(f"Forks: {forks}")
        if repo.get('github_is_private'):
            parts.append("Private: [yellow]Yes[/yellow]")
        else:
            parts.append("Private: No")
        if repo.get('github_is_archived'):
            parts.append("[red]Archived[/red]")
        if repo.get('github_is_fork'):
            parts.append("Fork: Yes")
        console.print(f"    {  '  '.join(parts)}")

    # Publications
    console.print()
    console.print("  [bold]Publications[/bold]")
    if publications:
        for pub in publications:
            status = "[green]published[/green]" if pub.get('published') else "[dim]detected[/dim]"
            version = f" v{pub['current_version']}" if pub.get('current_version') else ""
            console.print(f"    {pub['registry']}: {pub['package_name']}{version} ({status})")
            if pub.get('doi'):
                console.print(f"      DOI: {pub['doi']}")
    else:
        console.print("    [dim](none)[/dim]")

    # Tags
    console.print()
    console.print("  [bold]Tags[/bold]")
    if tags:
        tag_strs = [t['tag'] for t in tags]
        console.print(f"    {', '.join(tag_strs)}")
    else:
        console.print("    [dim](none)[/dim]")

    # Recent events
    console.print()
    console.print("  [bold]Recent Events[/bold]")
    if events:
        evt_table = Table(box=None, show_header=False, padding=(0, 1))
        evt_table.add_column("Date", style="dim", min_width=10)
        evt_table.add_column("Type", min_width=8)
        evt_table.add_column("Detail")
        for evt in events:
            ts = str(evt.get('timestamp', ''))[:10]
            detail = evt.get('message') or evt.get('ref') or ''
            if len(detail) > 60:
                detail = detail[:57] + '...'
            evt_table.add_row(ts, evt['type'], detail)
        console.print(evt_table)
    else:
        console.print("    [dim](none)[/dim]")

    console.print()


@click.command('show')
@click.argument('identifier')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')
def show_handler(identifier: str, output_json: bool):
    """Show detailed information for a single repository.

    IDENTIFIER can be a repo name, path, or partial name match.

    \b
    Examples:
        repoindex show repoindex
        repoindex show ~/github/go-tools
        repoindex show repoindex --json
    """
    config = load_config()

    with Database(config=config, read_only=True) as db:
        from . import warn_if_stale
        warn_if_stale(db)

        result = _find_repo(db, identifier)

        if result is None:
            if output_json:
                print(json.dumps({'error': f'Repository not found: {identifier}'}), file=sys.stderr)
            else:
                click.echo(f"Error: Repository not found: {identifier}", err=True)
            sys.exit(1)

        if isinstance(result, list):
            # Multiple matches — show disambiguation
            names = [dict(r)['name'] for r in result]
            if output_json:
                print(json.dumps({'error': f'Multiple matches: {", ".join(names)}'}), file=sys.stderr)
            else:
                click.echo(f"Multiple repositories match '{identifier}':", err=True)
                for name in names:
                    click.echo(f"  {name}", err=True)
                click.echo("Please be more specific.", err=True)
            sys.exit(1)

        repo = result
        tags, publications, events = _fetch_related(db, repo['id'])

    if output_json:
        _output_json(repo, tags, publications, events)
    else:
        _output_pretty(repo, tags, publications, events)
