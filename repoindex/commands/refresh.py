"""
Refresh command for repoindex.

Populates the SQLite database with repository metadata.
This is the primary way to sync the database with filesystem state.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from ..config import load_config, get_repository_directories
from ..database import (
    Database,
    get_database_info,
    reset_database,
    upsert_repo,
    cleanup_missing_repos,
    needs_refresh,
    get_repo_count,
    get_repo_by_path,
)
from ..database.events import insert_events
from ..services.repository_service import RepositoryService
from ..events import scan_events


@click.command('refresh')
@click.option('--full', is_flag=True, help='Force full refresh of all repos')
@click.option('--since', default='90d', help='How far back to scan for events (e.g., 7d, 30d, 90d)')
@click.option('--github', is_flag=True, help='Fetch GitHub metadata (stars, topics, etc.)')
@click.option('-d', '--dir', 'directory', type=click.Path(exists=True),
              help='Refresh specific directory instead of configured paths')
@click.option('--dry-run', is_flag=True, help='Show what would be refreshed')
@click.option('--quiet', '-q', is_flag=True, help='Minimal output')
@click.option('--pretty', is_flag=True, help='Pretty output with progress')
def refresh_handler(
    full: bool,
    since: str,
    github: bool,
    directory: Optional[str],
    dry_run: bool,
    quiet: bool,
    pretty: bool,
):
    """
    Refresh the repository index database.

    Scans configured directories for git repositories and populates
    the SQLite database with their metadata. Events (commits, tags)
    are always scanned.

    By default, performs a smart refresh that only updates repos
    that have changed since the last scan.

    Examples:

        # Smart refresh (only changed repos)
        repoindex refresh

        # Full refresh of all repos
        repoindex refresh --full

        # Include GitHub metadata
        repoindex refresh --github

        # Refresh specific directory
        repoindex refresh -d ~/projects

        # Scan events from last 30 days only
        repoindex refresh --since 30d

        # Reset and rebuild: use sql --reset first
        repoindex sql --reset && repoindex refresh --full
    """
    config = load_config()

    # Get paths to scan
    if directory:
        paths = [directory]
    else:
        paths = get_repository_directories(config)
        if not paths:
            click.echo(json.dumps({
                "error": "No repository directories configured",
                "hint": "Use 'repoindex init' or provide --dir"
            }))
            sys.exit(1)

    # Initialize service
    service = RepositoryService(config=config)

    # Stats tracking
    stats = {
        'scanned': 0,
        'updated': 0,
        'skipped': 0,
        'events_added': 0,
        'errors': 0,
        'start_time': datetime.now().isoformat(),
    }

    # Parse since parameter for event scanning
    since_datetime = _parse_since(since)

    if dry_run:
        click.echo("Dry run - showing what would be refreshed:", err=True)

    with Database(config=config) as db:
        # Discover repositories
        repos = list(service.discover(paths=paths, recursive=True))

        if pretty:
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            ) as progress:
                task = progress.add_task("Refreshing repos...", total=len(repos))

                for repo in repos:
                    _process_repo(
                        db, service, repo, stats,
                        full=full,
                        since=since_datetime,
                        github=github,
                        dry_run=dry_run,
                        quiet=quiet
                    )
                    progress.update(task, advance=1)
        else:
            for repo in repos:
                _process_repo(
                    db, service, repo, stats,
                    full=full,
                    since=since_datetime,
                    github=github,
                    dry_run=dry_run,
                    quiet=quiet
                )

        # Cleanup repos that no longer exist
        if not dry_run:
            removed = cleanup_missing_repos(db)
            stats['removed'] = removed

        stats['end_time'] = datetime.now().isoformat()
        stats['total_repos'] = get_repo_count(db)

    # Output results
    if quiet:
        pass
    elif pretty:
        _print_summary_pretty(stats)
    else:
        print(json.dumps(stats))


def _process_repo(
    db: Database,
    service: RepositoryService,
    repo,
    stats: dict,
    full: bool,
    since: datetime,
    github: bool,
    dry_run: bool,
    quiet: bool,
):
    """Process a single repository."""
    stats['scanned'] += 1

    try:
        # Check if needs refresh
        if not full and not needs_refresh(db, repo.path):
            stats['skipped'] += 1
            return

        if dry_run:
            if not quiet:
                click.echo(f"  Would refresh: {repo.name} ({repo.path})", err=True)
            return

        # Enrich with status
        enriched = service.get_status(repo, fetch_github=github)

        # Load tags from config
        tags_from_config = service.config.get('repository_tags', {}).get(repo.path, [])
        if tags_from_config:
            enriched = enriched.with_tags(frozenset(tags_from_config))

        # Upsert to database
        repo_id = upsert_repo(db, enriched)
        stats['updated'] += 1

        # Always scan events
        if repo_id:
            try:
                repo_events = list(scan_events(
                    repos=[repo.path],
                    since=since,
                    types=['commit', 'git_tag', 'branch', 'merge']
                ))
                if repo_events:
                    inserted = insert_events(db, repo_events, repo_id)
                    stats['events_added'] += inserted
            except Exception as e:
                if not quiet:
                    click.echo(f"Warning: Failed to scan events for {repo.name}: {e}", err=True)

        if not quiet:
            click.echo(f"  Refreshed: {repo.name}", err=True)

    except Exception as e:
        stats['errors'] += 1
        if not quiet:
            click.echo(f"  Error: {repo.name}: {e}", err=True)


def _parse_since(since_str: str) -> datetime:
    """Parse a since string like '7d', '30d', '90d' into a datetime."""
    from datetime import timedelta

    now = datetime.now()

    if since_str.endswith('d'):
        days = int(since_str[:-1])
        return now - timedelta(days=days)
    elif since_str.endswith('w'):
        weeks = int(since_str[:-1])
        return now - timedelta(weeks=weeks)
    elif since_str.endswith('m'):
        # Approximate months as 30 days
        months = int(since_str[:-1])
        return now - timedelta(days=months * 30)
    elif since_str.endswith('y'):
        years = int(since_str[:-1])
        return now - timedelta(days=years * 365)
    else:
        # Try parsing as ISO date
        try:
            return datetime.fromisoformat(since_str)
        except ValueError:
            # Default to 90 days
            return now - timedelta(days=90)


def _print_summary_pretty(stats: dict):
    """Print a pretty summary of refresh results."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    table = Table(title="Refresh Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Repos scanned", str(stats.get('scanned', 0)))
    table.add_row("Repos updated", str(stats.get('updated', 0)))
    table.add_row("Repos skipped", str(stats.get('skipped', 0)))
    table.add_row("Repos removed", str(stats.get('removed', 0)))
    table.add_row("Events added", str(stats.get('events_added', 0)))
    table.add_row("Errors", str(stats.get('errors', 0)))
    table.add_row("Total in DB", str(stats.get('total_repos', 0)))

    console.print(table)


@click.command('db')
@click.option('--info', 'show_info', is_flag=True, help='Show database info')
@click.option('--path', 'show_path', is_flag=True, help='Show database path')
@click.option('--reset', is_flag=True, help='Delete and recreate database')
def db_handler(show_info: bool, show_path: bool, reset: bool):
    """
    Database management commands.

    Examples:

        # Show database info
        repoindex db --info

        # Show database path
        repoindex db --path

        # Reset database
        repoindex db --reset
    """
    config = load_config()

    if show_path:
        from ..database import get_db_path
        print(get_db_path(config))
        return

    if reset:
        reset_database(config)
        click.echo("Database reset.", err=True)
        return

    if show_info or True:  # Default to showing info
        info = get_database_info(config)
        print(json.dumps(info, indent=2))


@click.command('sql')
@click.argument('query', required=False)
@click.option('--file', '-f', 'sql_file', type=click.Path(exists=True),
              help='Read SQL from file')
@click.option('--format', 'output_format', type=click.Choice(['json', 'csv', 'table']),
              default='json', help='Output format')
@click.option('--interactive', '-i', is_flag=True, help='Interactive SQL shell')
@click.option('--info', 'show_info', is_flag=True, help='Show database info')
@click.option('--path', 'show_path', is_flag=True, help='Show database path')
@click.option('--schema', 'show_schema', is_flag=True, help='Show database schema')
@click.option('--reset', 'do_reset', is_flag=True, help='Delete and recreate database')
def sql_handler(
    query: Optional[str],
    sql_file: Optional[str],
    output_format: str,
    interactive: bool,
    show_info: bool,
    show_path: bool,
    show_schema: bool,
    do_reset: bool,
):
    """
    Execute raw SQL queries on the database.

    Also provides database management operations via flags.

    Examples:

        # Query data
        repoindex sql "SELECT name, stars FROM repos ORDER BY stars DESC LIMIT 10"

        # Database info
        repoindex sql --info
        repoindex sql --path
        repoindex sql --schema

        # Query from file
        repoindex sql -f query.sql

        # CSV output
        repoindex sql "SELECT * FROM repos" --format csv

        # Interactive shell
        repoindex sql -i

        # Reset database
        repoindex sql --reset
    """
    config = load_config()

    # Database management operations
    if show_path:
        from ..database import get_db_path
        print(get_db_path(config))
        return

    if do_reset:
        reset_database(config)
        click.echo("Database reset.", err=True)
        return

    if show_info:
        info = get_database_info(config)
        print(json.dumps(info, indent=2))
        return

    if show_schema:
        with Database(config=config, read_only=True) as db:
            db.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name")
            for row in db.fetchall():
                if row['sql']:
                    print(row['sql'])
                    print()
        return

    if interactive:
        _interactive_shell(config)
        return

    if sql_file:
        with open(sql_file) as f:
            query = f.read()

    if not query:
        click.echo("Error: Query required. Use -i for interactive mode.", err=True)
        sys.exit(1)

    with Database(config=config, read_only=True) as db:
        try:
            db.execute(query)
            rows = db.fetchall()

            if output_format == 'json':
                result = [dict(row) for row in rows]
                print(json.dumps(result, indent=2, default=str))
            elif output_format == 'csv':
                import csv
                if rows:
                    writer = csv.DictWriter(sys.stdout, fieldnames=rows[0].keys())
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(dict(row))
            elif output_format == 'table':
                _print_table(rows)

        except Exception as e:
            click.echo(f"SQL Error: {e}", err=True)
            sys.exit(1)


def _interactive_shell(config: dict):
    """Run an interactive SQL shell."""
    from ..database import get_db_path

    db_path = get_db_path(config)
    click.echo(f"Connected to: {db_path}", err=True)
    click.echo("Type SQL queries, or '.help' for commands, '.quit' to exit.", err=True)
    click.echo("", err=True)

    with Database(config=config) as db:
        while True:
            try:
                query = input("sql> ").strip()
            except (EOFError, KeyboardInterrupt):
                click.echo("\nGoodbye!", err=True)
                break

            if not query:
                continue

            if query.lower() in ['.quit', '.exit', 'exit', 'quit']:
                break

            if query.lower() == '.help':
                click.echo("Commands:")
                click.echo("  .tables    List all tables")
                click.echo("  .schema    Show full schema")
                click.echo("  .info      Show database info")
                click.echo("  .quit      Exit")
                continue

            if query.lower() == '.tables':
                db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                for row in db.fetchall():
                    print(row['name'])
                continue

            if query.lower() == '.schema':
                db.execute("SELECT sql FROM sqlite_master WHERE type='table'")
                for row in db.fetchall():
                    if row['sql']:
                        print(row['sql'])
                        print()
                continue

            if query.lower() == '.info':
                info = get_database_info(config)
                print(json.dumps(info, indent=2))
                continue

            try:
                db.execute(query)
                rows = db.fetchall()
                if rows:
                    _print_table(rows)
                else:
                    click.echo(f"OK ({db.rowcount} rows affected)", err=True)
            except Exception as e:
                click.echo(f"Error: {e}", err=True)


def _print_table(rows):
    """Print rows as a formatted table."""
    if not rows:
        return

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table()

        # Add columns
        for key in rows[0].keys():
            table.add_column(key)

        # Add rows
        for row in rows:
            table.add_row(*[str(v) if v is not None else '' for v in row])

        console.print(table)
    except ImportError:
        # Fallback to simple output
        if rows:
            print('\t'.join(rows[0].keys()))
            for row in rows:
                print('\t'.join(str(v) if v is not None else '' for v in row))
