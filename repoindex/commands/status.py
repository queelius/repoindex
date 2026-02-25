"""
Status dashboard command for repoindex.

Shows a quick overview of your repository collection from the database.
"""

import json
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import click

from ..config import load_config
from ..database import Database, get_database_info, get_scan_error_count
from ..database.refresh_log import ensure_refresh_log_table, get_latest_refresh, get_refresh_log


@click.command(name='status')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON for scripting')
@click.option('--repos', is_flag=True, help='List individual repositories')
@click.option('--refresh-log', 'show_refresh_log', is_flag=True, help='Show refresh history')
@click.option('--limit', default=10, type=int, help='Number of refresh log entries to show (default: 10)')
def status_handler(output_json: bool, repos: bool, show_refresh_log: bool, limit: int):
    """
    Show repository collection status dashboard.

    Displays a quick overview of your repository collection from the database.

    \b
    Examples:
        # Dashboard view
        repoindex status
        # JSON output for scripting
        repoindex status --json
        # List all repos
        repoindex status --repos
        # Show refresh history
        repoindex status --refresh-log
        # Show last 5 refreshes as JSON
        repoindex status --refresh-log --limit 5 --json
    """
    config = load_config()

    # Check if database exists
    try:
        db_info = get_database_info(config)
    except Exception:
        click.echo("Database not found. Run 'repoindex refresh' first.", err=True)
        sys.exit(1)

    if show_refresh_log:
        _show_refresh_log(config, output_json, limit)
        return

    if repos:
        _list_repos(config, output_json)
        return

    if output_json:
        _json_dashboard(config, db_info)
    else:
        _pretty_dashboard(config, db_info)


def _json_dashboard(config: dict, db_info: dict):
    """Output dashboard data as JSON."""
    data = _gather_dashboard_data(config, db_info)
    print(json.dumps(data, indent=2, default=str))


def _pretty_dashboard(config: dict, db_info: dict):
    """Display a pretty dashboard."""
    from rich.console import Console

    console = Console()
    data = _gather_dashboard_data(config, db_info)

    # Title
    console.print()
    console.print("[bold cyan]repoindex Status Dashboard[/bold cyan]")
    console.print("=" * 50)
    console.print()

    # Database section
    db = data['database']
    size_str = _format_size(db.get('size_bytes', 0))
    console.print(f"[bold]Database:[/bold]    {db['repos']} repos, {db['events']} events ({size_str})")

    if db.get('last_refresh'):
        refresh_ago = _format_time_ago(db['last_refresh'])
        console.print(f"[bold]Last refresh:[/bold] {refresh_ago}")
    else:
        console.print("[bold]Last refresh:[/bold] [yellow]never[/yellow]")

    console.print()

    # Health section
    health = data['health']
    total = health['clean'] + health['dirty']
    if total > 0:
        clean_pct = health['clean'] * 100 // total
        dirty_pct = 100 - clean_pct

        console.print("[bold]Health:[/bold]")
        console.print(f"  [green]Clean:[/green]     {health['clean']} repos ({clean_pct}%)")
        if health['dirty'] > 0:
            console.print(f"  [yellow]Dirty:[/yellow]     {health['dirty']} repos ({dirty_pct}%)")
        console.print()

    # Languages section
    if data['languages']:
        lang_parts = [f"{lang} ({count})" for lang, count in data['languages'][:5]]
        if len(data['languages']) > 5:
            lang_parts.append(f"+{len(data['languages']) - 5} more")
        console.print(f"[bold]Languages:[/bold]   {', '.join(lang_parts)}")
        console.print()

    # Recent activity section
    activity = data['recent_activity']
    if activity['commits'] > 0 or activity['tags'] > 0:
        console.print(f"[bold]Recent Activity ({activity['since']}):[/bold]")
        if activity['commits'] > 0:
            console.print(f"  Commits:    {activity['commits']} across {activity['active_repos']} repos")
        if activity['tags'] > 0:
            console.print(f"  Tags:       {activity['tags']} new releases")
        console.print()

    # Warnings section
    if data['warnings']:
        console.print("[bold red]Warnings:[/bold red]")
        for warning in data['warnings']:
            console.print(f"  [yellow]![/yellow] {warning}")
        console.print()

    # Suggestions section
    if data['suggestions']:
        console.print("[bold]Suggestions:[/bold]")
        for suggestion in data['suggestions']:
            console.print(f"  [dim]→[/dim] {suggestion}")
        console.print()

    # Footer (only if no suggestions were shown)
    if not data['suggestions']:
        if not db.get('last_refresh'):
            console.print("[dim]Run 'repoindex refresh' to populate the database.[/dim]")
        elif db['repos'] == 0:
            console.print("[dim]No repositories indexed. Check your configuration with 'repoindex config show'.[/dim]")
        else:
            console.print("[dim]Run 'repoindex query' to search your repositories.[/dim]")


def _gather_dashboard_data(config: dict, db_info: dict) -> Dict[str, Any]:
    """Gather all dashboard data from the database."""
    warnings: List[str] = []
    suggestions: List[str] = []
    languages: List[Tuple[str, int]] = []
    data: Dict[str, Any] = {
        'database': {
            'repos': db_info.get('repos', 0),
            'events': db_info.get('events', 0),
            'tags': db_info.get('tags', 0),
            'size_bytes': db_info.get('size_bytes', 0),
            'last_refresh': None,
        },
        'health': {
            'clean': 0,
            'dirty': 0,
            'scan_errors': 0,
            'stale_repos': 0,  # Not scanned in 7+ days
        },
        'warnings': warnings,
        'suggestions': suggestions,
        'languages': languages,
        'recent_activity': {
            'since': '7 days',
            'commits': 0,
            'tags': 0,
            'active_repos': 0,
        },
    }

    try:
        with Database(config=config, read_only=True) as db:
            # Get last refresh time — prefer refresh_log, fall back to MAX(scanned_at)
            latest = get_latest_refresh(db)
            if latest:
                data['database']['last_refresh'] = latest['finished_at']
                data['database']['last_refresh_sources'] = latest.get('sources', [])
                data['database']['last_refresh_duration'] = latest.get('duration_seconds')
            else:
                db.execute("SELECT MAX(scanned_at) as scanned_at FROM repos")
                row = db.fetchone()
                if row and row['scanned_at']:
                    data['database']['last_refresh'] = row['scanned_at']

            # Get health stats
            db.execute("SELECT COUNT(*) as count FROM repos WHERE is_clean = 1")
            row = db.fetchone()
            data['health']['clean'] = row['count'] if row else 0

            db.execute("SELECT COUNT(*) as count FROM repos WHERE is_clean = 0")
            row = db.fetchone()
            data['health']['dirty'] = row['count'] if row else 0

            # Get language breakdown
            db.execute("""
                SELECT language, COUNT(*) as count
                FROM repos
                WHERE language IS NOT NULL AND language != ''
                GROUP BY language
                ORDER BY count DESC
                LIMIT 10
            """)
            data['languages'] = [(row['language'], row['count']) for row in db.fetchall()]

            # Get recent activity (last 7 days)
            since = datetime.now() - timedelta(days=7)
            since_str = since.strftime('%Y-%m-%d')

            db.execute("""
                SELECT COUNT(*) as count FROM events
                WHERE type = 'commit' AND timestamp >= ?
            """, (since_str,))
            row = db.fetchone()
            data['recent_activity']['commits'] = row['count'] if row else 0

            db.execute("""
                SELECT COUNT(*) as count FROM events
                WHERE type = 'git_tag' AND timestamp >= ?
            """, (since_str,))
            row = db.fetchone()
            data['recent_activity']['tags'] = row['count'] if row else 0

            db.execute("""
                SELECT COUNT(DISTINCT repo_id) as count FROM events
                WHERE type = 'commit' AND timestamp >= ?
            """, (since_str,))
            row = db.fetchone()
            data['recent_activity']['active_repos'] = row['count'] if row else 0

            # Get scan error count
            data['health']['scan_errors'] = get_scan_error_count(db)

            # Get stale repos (not scanned in 7+ days)
            stale_threshold = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            db.execute("""
                SELECT COUNT(*) as count FROM repos
                WHERE scanned_at < ? OR scanned_at IS NULL
            """, (stale_threshold,))
            row = db.fetchone()
            data['health']['stale_repos'] = row['count'] if row else 0

            # Generate warnings
            if data['health']['dirty'] > 0:
                data['warnings'].append(f"{data['health']['dirty']} repos have uncommitted changes")

            if data['health']['scan_errors'] > 0:
                data['warnings'].append(f"{data['health']['scan_errors']} repos failed to scan")

            if data['health']['stale_repos'] > 0:
                data['warnings'].append(f"{data['health']['stale_repos']} repos not scanned in 7+ days")

            # Generate suggestions
            if data['health']['stale_repos'] > 0 or data['health']['scan_errors'] > 0:
                data['suggestions'].append("Run 'repoindex refresh' to update the database")

            if data['health']['scan_errors'] > 0:
                data['suggestions'].append("Run 'repoindex sql \"SELECT * FROM scan_errors\"' to see failures")

            if data['database']['repos'] == 0:
                data['suggestions'].append("Check configuration with 'repoindex config show'")

    except Exception:
        pass  # Database might not exist yet

    return data


def _show_refresh_log(config: dict, output_json: bool, limit: int):
    """Display the refresh log."""
    try:
        with Database(config=config, read_only=True) as db:
            entries = get_refresh_log(db, limit=limit)

            if not entries:
                click.echo("No refresh log entries found. Run 'repoindex refresh' first.", err=True)
                return

            if output_json:
                print(json.dumps(entries, indent=2, default=str))
            else:
                _print_refresh_log_table(entries)

    except Exception as e:
        click.echo(f"Error reading refresh log: {e}", err=True)
        sys.exit(1)


def _print_refresh_log_table(entries):
    """Print refresh log entries as a Rich table."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    console = Console()
    table = Table(title=f"Refresh Log ({len(entries)} entries)", box=box.ROUNDED)

    table.add_column("Date", style="cyan")
    table.add_column("Type")
    table.add_column("Sources")
    table.add_column("Repos", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Errors", justify="right")

    for entry in entries:
        # Format date
        date_str = entry.get('started_at', '')
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str)
                date_str = dt.strftime('%Y-%m-%d %H:%M')
            except (ValueError, TypeError):
                pass

        # Format type
        scan_type = "full" if entry.get('full_scan') else "smart"

        # Format sources
        sources = entry.get('sources', [])
        if isinstance(sources, list):
            sources_str = ', '.join(sources)
        else:
            sources_str = str(sources)

        # Format repos
        scanned = entry.get('repos_scanned', 0)
        skipped = entry.get('repos_skipped', 0)
        repos_str = f"{scanned} scanned"
        if skipped:
            repos_str += f", {skipped} skipped"

        # Format duration
        duration = entry.get('duration_seconds')
        if duration is not None:
            if duration < 60:
                duration_str = f"{duration:.1f}s"
            else:
                mins = int(duration // 60)
                secs = duration % 60
                duration_str = f"{mins}m {secs:.0f}s"
        else:
            duration_str = "-"

        # Format errors
        errors = entry.get('errors', 0)
        error_str = str(errors)
        if errors > 0:
            error_str = f"[red]{errors}[/red]"

        table.add_row(date_str, scan_type, sources_str, repos_str, duration_str, error_str)

    console.print(table)


def _list_repos(config: dict, output_json: bool):
    """List individual repositories."""
    try:
        with Database(config=config, read_only=True) as db:
            db.execute("""
                SELECT name, path, language, branch, is_clean, github_stars
                FROM repos
                ORDER BY name
            """)
            rows = db.fetchall()

            if output_json:
                repos = [dict(row) for row in rows]
                print(json.dumps(repos, indent=2))
            else:
                _print_repos_table(rows)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _print_repos_table(rows):
    """Print repositories as a table."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    console = Console()
    table = Table(title=f"Repositories ({len(rows)})", box=box.ROUNDED)

    table.add_column("Name", style="cyan")
    table.add_column("Language")
    table.add_column("Branch")
    table.add_column("Status")
    table.add_column("GitHub Stars", justify="right")

    for row in rows:
        status = "[green]clean[/green]" if row['is_clean'] else "[yellow]dirty[/yellow]"
        github_stars = str(row['github_stars']) if row['github_stars'] else ""
        table.add_row(
            row['name'] or "",
            row['language'] or "",
            row['branch'] or "",
            status,
            github_stars,
        )

    console.print(table)


def _format_size(bytes_size: int) -> str:
    """Format bytes as human readable."""
    size: float = float(bytes_size)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.0f} TB"


def _format_time_ago(timestamp: str) -> str:
    """Format timestamp as time ago."""
    try:
        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = timestamp

        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = now - dt

        if delta.days > 30:
            return dt.strftime('%Y-%m-%d')
        elif delta.days > 0:
            return f"{delta.days} days ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hours ago"
        elif delta.seconds > 60:
            mins = delta.seconds // 60
            return f"{mins} minutes ago"
        else:
            return "just now"
    except Exception:
        return str(timestamp)
