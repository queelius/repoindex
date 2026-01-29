"""
Events command for repoindex.

Queries events from the database (populated by 'repoindex refresh').
"""

import click
import json
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from ..config import load_config
from ..database import Database


def _parse_since(since_str: str) -> datetime:
    """Parse a --since value into a datetime."""
    if not since_str:
        return datetime.now() - timedelta(days=7)

    # Check for relative formats
    if since_str.endswith('d'):
        days = int(since_str[:-1])
        return datetime.now() - timedelta(days=days)
    elif since_str.endswith('h'):
        hours = int(since_str[:-1])
        return datetime.now() - timedelta(hours=hours)
    elif since_str.endswith('w'):
        weeks = int(since_str[:-1])
        return datetime.now() - timedelta(weeks=weeks)
    elif since_str.endswith('m'):
        minutes = int(since_str[:-1])
        return datetime.now() - timedelta(minutes=minutes)
    else:
        # Try parsing as ISO date
        try:
            return datetime.fromisoformat(since_str)
        except ValueError:
            return datetime.now() - timedelta(days=7)


@click.command('events')
@click.option('--type', '-t', 'event_types', multiple=True,
              help='Filter by event type (e.g., commit, git_tag, pr)')
@click.option('--repo', '-r', help='Filter by repository name')
@click.option('--since', '-s', default='7d',
              help='Events after this time (e.g., 1h, 7d, 2024-01-01)')
@click.option('--until', '-u', help='Events before this time')
@click.option('--limit', '-n', type=int, default=100,
              help='Maximum events to return (default: 100, 0 for unlimited)')
@click.option('--json', 'output_json', is_flag=True,
              help='Output as JSONL (default: pretty table)')
@click.option('--stats', is_flag=True,
              help='Show summary statistics only')
def events_handler(
    event_types: tuple,
    repo: Optional[str],
    since: str,
    until: Optional[str],
    limit: int,
    output_json: bool,
    stats: bool,
):
    """
    Query repository events from the database.

    Events are populated by 'repoindex refresh'. Run refresh first to ensure
    the database has current events.

    Output is a formatted table by default. Use --json for JSONL output.

    \b
    Examples:
        # Recent events (default: last 7 days, pretty table)
        repoindex events
        # Events from last 24 hours
        repoindex events --since 24h
        # Filter by type
        repoindex events --type commit --since 7d
        repoindex events --type git_tag
        # Filter by repository
        repoindex events --repo myproject
        # JSONL output for piping
        repoindex events --json | jq '.type'
        # Summary statistics
        repoindex events --stats
    """
    config = load_config()

    # Parse time filters
    since_dt = _parse_since(since)
    until_dt = _parse_since(until) if until else None

    if stats:
        _show_stats(config, event_types, repo, since_dt, until_dt)
    elif output_json:
        _show_events(config, event_types, repo, since_dt, until_dt, limit, as_array=False)
    else:
        # Default: pretty table
        _show_pretty(config, event_types, repo, since_dt, until_dt, limit)


def _build_query(event_types: tuple, repo: Optional[str], since_dt: datetime,
                 until_dt: Optional[datetime], limit: int) -> tuple:
    """Build SQL query and parameters."""
    conditions = ["timestamp >= ?"]
    params: List = [since_dt.isoformat()]

    if until_dt:
        conditions.append("timestamp <= ?")
        params.append(until_dt.isoformat())

    if event_types:
        placeholders = ','.join(['?' for _ in event_types])
        conditions.append(f"type IN ({placeholders})")
        params.extend(event_types)

    if repo:
        conditions.append("(repo_name LIKE ? OR repo_path LIKE ?)")
        params.append(f"%{repo}%")
        params.append(f"%{repo}%")

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT e.*, r.path as repo_path, r.name as repo_name
        FROM events e
        LEFT JOIN repos r ON e.repo_id = r.id
        WHERE {where_clause}
        ORDER BY timestamp DESC
    """

    if limit > 0:
        sql += f" LIMIT {limit}"

    return sql, params


def _show_events(config: dict, event_types: tuple, repo: Optional[str],
                 since_dt: datetime, until_dt: Optional[datetime],
                 limit: int, as_array: bool = False):
    """Output events as JSONL (default) or JSON array."""
    sql, params = _build_query(event_types, repo, since_dt, until_dt, limit)

    try:
        with Database(config=config, read_only=True) as db:
            db.execute(sql, params)
            rows = db.fetchall()

            if as_array:
                events = [dict(row) for row in rows]
                print(json.dumps(events, indent=2, default=str))
            else:
                # JSONL format (one JSON object per line)
                for row in rows:
                    event = dict(row)
                    print(json.dumps(event, default=str), flush=True)

    except Exception as e:
        click.echo(f"Error querying events: {e}", err=True)
        sys.exit(1)


def _show_pretty(config: dict, event_types: tuple, repo: Optional[str],
                 since_dt: datetime, until_dt: Optional[datetime], limit: int):
    """Display events as a formatted table."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    sql, params = _build_query(event_types, repo, since_dt, until_dt, limit)

    try:
        with Database(config=config, read_only=True) as db:
            db.execute(sql, params)
            rows = db.fetchall()

            console = Console()

            if not rows:
                console.print("[yellow]No events found in the specified time range.[/yellow]")
                return

            table = Table(
                title=f"Events ({len(rows)} results)",
                box=box.ROUNDED,
                show_header=True,
                header_style="bold magenta"
            )

            table.add_column("Time", style="dim")
            table.add_column("Type")
            table.add_column("Repository", style="cyan")
            table.add_column("Details")

            for row in rows:
                timestamp = row['timestamp']
                if isinstance(timestamp, str):
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        timestamp = dt.strftime("%Y-%m-%d %H:%M")
                    except ValueError:
                        timestamp = timestamp[:16]

                event_type = row['type'] or ""
                repo_name = row['repo_name'] or ""

                # Format details based on event type
                data: Dict[str, Any] = {}
                # Use 'metadata' column (schema) or 'message' (events table)
                raw_metadata = row['metadata'] if 'metadata' in row.keys() else None
                if not raw_metadata:
                    raw_metadata = row['message'] if 'message' in row.keys() else None
                if raw_metadata:
                    try:
                        data = json.loads(raw_metadata) if isinstance(raw_metadata, str) else {}
                    except (json.JSONDecodeError, TypeError):
                        data = {'message': raw_metadata} if isinstance(raw_metadata, str) else {}

                details = ""
                if event_type == 'commit':
                    details = data.get('message', '')[:50] if data.get('message') else ""
                elif event_type == 'git_tag':
                    details = data.get('tag', '') or data.get('name', '')
                elif event_type in ('pr', 'issue'):
                    details = data.get('title', '')[:40] if data.get('title') else ""
                elif event_type == 'github_release':
                    details = data.get('tag_name', '') or data.get('name', '')
                else:
                    # Generic: show first meaningful field
                    for key in ['message', 'title', 'name', 'version', 'tag']:
                        if data.get(key):
                            details = str(data[key])[:50]
                            break

                table.add_row(timestamp, event_type, repo_name, details)

            console.print(table)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _show_stats(config: dict, event_types: tuple, repo: Optional[str],
                since_dt: datetime, until_dt: Optional[datetime]):
    """Show summary statistics for events."""
    from rich.console import Console

    console = Console()

    conditions = ["timestamp >= ?"]
    params: List = [since_dt.isoformat()]

    if until_dt:
        conditions.append("timestamp <= ?")
        params.append(until_dt.isoformat())

    if event_types:
        placeholders = ','.join(['?' for _ in event_types])
        conditions.append(f"type IN ({placeholders})")
        params.extend(event_types)

    if repo:
        conditions.append("(repo_name LIKE ? OR repo_path LIKE ?)")
        params.append(f"%{repo}%")
        params.append(f"%{repo}%")

    where_clause = " AND ".join(conditions)

    try:
        with Database(config=config, read_only=True) as db:
            # Total events
            db.execute(f"SELECT COUNT(*) as count FROM events e LEFT JOIN repos r ON e.repo_id = r.id WHERE {where_clause}", tuple(params))
            row = db.fetchone()
            total = row['count'] if row else 0

            # By type
            db.execute(f"""
                SELECT type, COUNT(*) as count
                FROM events e
                LEFT JOIN repos r ON e.repo_id = r.id
                WHERE {where_clause}
                GROUP BY type
                ORDER BY count DESC
            """, tuple(params))
            by_type = db.fetchall()

            # Active repos
            db.execute(f"""
                SELECT COUNT(DISTINCT repo_id) as count
                FROM events e
                LEFT JOIN repos r ON e.repo_id = r.id
                WHERE {where_clause}
            """, tuple(params))
            row = db.fetchone()
            active_repos = row['count'] if row else 0

            # Display
            console.print()
            console.print("[bold cyan]Event Statistics[/bold cyan]")
            console.print("=" * 40)
            console.print()

            since_str = since_dt.strftime("%Y-%m-%d %H:%M")
            console.print(f"[bold]Time range:[/bold] Since {since_str}")
            console.print(f"[bold]Total events:[/bold] {total}")
            console.print(f"[bold]Active repos:[/bold] {active_repos}")
            console.print()

            if by_type:
                console.print("[bold]By type:[/bold]")
                for row in by_type:
                    console.print(f"  {row['type']}: {row['count']}")
                console.print()

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
