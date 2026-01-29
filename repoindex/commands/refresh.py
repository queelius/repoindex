"""
Refresh command for repoindex.

Populates the SQLite database with repository metadata.
This is the primary way to sync the database with filesystem state.
"""

import json
import os
import sys
from datetime import datetime
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
    record_scan_error,
    clear_scan_error_for_path,
    get_scan_error_count,
)
from ..database.events import insert_events
from ..services.repository_service import RepositoryService
from ..events import scan_events


def _resolve_external_flag(explicit: Optional[bool], external: bool, config_default: bool) -> bool:
    """
    Resolve an external source flag.

    Priority: explicit flag > --external flag > config default

    Args:
        explicit: Explicit flag value (True/False/None)
        external: Whether --external was passed
        config_default: Default from config

    Returns:
        Whether to enable this source
    """
    if explicit is not None:
        return explicit
    if external:
        return True
    return config_default


@click.command('refresh')
@click.option('--full', is_flag=True, help='Force full refresh of all repos')
@click.option('--since', default='90d', help='How far back to scan for events (e.g., 7d, 30d, 90d)')
@click.option('--github/--no-github', default=None, help='Fetch GitHub metadata (stars, topics)')
@click.option('--pypi/--no-pypi', default=None, help='Fetch PyPI package status')
@click.option('--cran/--no-cran', default=None, help='Fetch CRAN package status')
@click.option('--zenodo/--no-zenodo', default=None, help='Fetch Zenodo DOI metadata (requires author.orcid in config)')
@click.option('--external', is_flag=True, help='Enable all external sources (github, pypi, cran, zenodo)')
@click.option('-d', '--dir', 'directory', type=click.Path(exists=True),
              help='Refresh specific directory instead of configured paths')
@click.option('--dry-run', is_flag=True, help='Show what would be refreshed')
@click.option('--quiet', '-q', is_flag=True, help='Minimal output')
@click.option('--pretty', is_flag=True, help='Pretty output with progress')
def refresh_handler(
    full: bool,
    since: str,
    github: Optional[bool],
    pypi: Optional[bool],
    cran: Optional[bool],
    zenodo: Optional[bool],
    external: bool,
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

    External sources (GitHub, PyPI, CRAN, Zenodo) are disabled by default
    but can be enabled via flags or config. These make API calls
    and can be slow for large collections.

    \b
    Examples:
        # Smart refresh (only changed repos)
        repoindex refresh
        # Full refresh of all repos
        repoindex refresh --full
        # Include GitHub metadata
        repoindex refresh --github
        # Include all external sources (slower)
        repoindex refresh --external
        # Include PyPI and CRAN package status
        repoindex refresh --pypi --cran
        # Include Zenodo DOI metadata (requires author.orcid)
        repoindex refresh --zenodo
        # Refresh specific directory
        repoindex refresh -d ~/projects
        # Scan events from last 30 days only
        repoindex refresh --since 30d
        # Reset and rebuild: use sql --reset first
        repoindex sql --reset && repoindex refresh --full

    \b
    External source config defaults (in config.yaml):
        refresh:
          external_sources:
            github: true   # Enable by default
            pypi: false    # Disabled by default
            cran: false    # Disabled by default
            zenodo: false  # Disabled by default (requires author.orcid)
    """
    config = load_config()

    # Resolve external source flags using config defaults
    # Priority: explicit flag > --external flag > config default > false
    ext_config = config.get('refresh', {}).get('external_sources', {})

    fetch_github = _resolve_external_flag(github, external, ext_config.get('github', False))
    fetch_pypi = _resolve_external_flag(pypi, external, ext_config.get('pypi', False))
    fetch_cran = _resolve_external_flag(cran, external, ext_config.get('cran', False))
    fetch_zenodo = _resolve_external_flag(zenodo, external, ext_config.get('zenodo', False))

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

    # Check if configured paths exist and warn if not
    missing_paths = []
    for p in paths:
        expanded = os.path.expanduser(p.rstrip('*').rstrip('/'))
        if not os.path.exists(expanded):
            missing_paths.append(p)

    if missing_paths and not quiet:
        click.echo(f"Warning: {len(missing_paths)} configured path(s) do not exist:", err=True)
        for p in missing_paths[:3]:  # Show first 3
            click.echo(f"  - {p}", err=True)
        if len(missing_paths) > 3:
            click.echo(f"  ... and {len(missing_paths) - 3} more", err=True)
        click.echo("Use 'repoindex config repos list' to see configured paths.", err=True)
        click.echo("", err=True)

    # Initialize service
    service = RepositoryService(config=config)

    # Batch-fetch Zenodo records (single API call for all repos)
    zenodo_records = []
    if fetch_zenodo:
        orcid = config.get('author', {}).get('orcid', '')
        if orcid:
            from ..infra.zenodo_client import ZenodoClient
            try:
                zenodo_client = ZenodoClient()
                zenodo_records = zenodo_client.search_by_orcid(orcid)
                if not quiet:
                    click.echo(f"Zenodo: fetched {len(zenodo_records)} records for ORCID {orcid}", err=True)
            except Exception as e:
                if not quiet:
                    click.echo(f"Warning: Zenodo fetch failed: {e}", err=True)
        else:
            if not quiet:
                click.echo("Warning: --zenodo requires author.orcid in config (skipping)", err=True)

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

        # Warn if no repos found
        if not repos and not quiet:
            click.echo("Warning: No repositories found in configured paths.", err=True)
            click.echo("The database may contain stale data from previous scans.", err=True)
            click.echo("Use 'repoindex config repos add <path>' to configure paths.", err=True)
            click.echo("", err=True)

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
                        fetch_github=fetch_github,
                        fetch_pypi=fetch_pypi,
                        fetch_cran=fetch_cran,
                        zenodo_records=zenodo_records,
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
                    fetch_github=fetch_github,
                    fetch_pypi=fetch_pypi,
                    fetch_cran=fetch_cran,
                    zenodo_records=zenodo_records,
                    dry_run=dry_run,
                    quiet=quiet
                )

        # Cleanup repos that no longer exist
        if not dry_run:
            removed = cleanup_missing_repos(db)
            stats['removed'] = removed

        stats['end_time'] = datetime.now().isoformat()
        stats['total_repos'] = get_repo_count(db)
        stats['total_scan_errors'] = get_scan_error_count(db)

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
    fetch_github: bool,
    fetch_pypi: bool,
    fetch_cran: bool,
    zenodo_records: list,
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
        enriched = service.get_status(
            repo,
            fetch_github=fetch_github,
            fetch_pypi=fetch_pypi,
            fetch_cran=fetch_cran
        )

        # Load tags from config
        tags_from_config = service.config.get('repository_tags', {}).get(repo.path, [])
        if tags_from_config:
            enriched = enriched.with_tags(frozenset(tags_from_config))

        # Upsert to database
        repo_id = upsert_repo(db, enriched)

        # Handle Zenodo publication (separate from main package field)
        # Zenodo uses batch-fetch, so we match pre-fetched records here
        if zenodo_records and repo_id:
            zenodo_package = service.match_zenodo_record(enriched, zenodo_records)
            if zenodo_package:
                from ..database.repository import _upsert_publication
                _upsert_publication(db, repo_id, zenodo_package)
        stats['updated'] += 1

        # Clear any previous scan errors for this path
        clear_scan_error_for_path(db, repo.path)

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

    except PermissionError as e:
        stats['errors'] += 1
        record_scan_error(db, repo.path, 'permission', str(e))
        if not quiet:
            click.echo(f"  Error (permission): {repo.name}: {e}", err=True)

    except Exception as e:
        stats['errors'] += 1
        # Determine error type
        error_type = 'git_error'
        error_msg = str(e)
        if 'not a git repository' in error_msg.lower():
            error_type = 'not_git'
        elif 'corrupt' in error_msg.lower():
            error_type = 'corrupt'
        record_scan_error(db, repo.path, error_type, error_msg)
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


def _format_bytes(size: int) -> str:
    """Format byte size as human readable string."""
    sz: float = float(size)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if sz < 1024:
            return f"{sz:.1f} {unit}"
        sz /= 1024
    return f"{sz:.1f} TB"


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
    table.add_row("Errors (this run)", str(stats.get('errors', 0)))
    table.add_row("Total scan errors", str(stats.get('total_scan_errors', 0)))
    table.add_row("Total in DB", str(stats.get('total_repos', 0)))

    console.print(table)


@click.command('db')
@click.option('--info', 'show_info', is_flag=True, help='Show database info')
@click.option('--path', 'show_path', is_flag=True, help='Show database path')
@click.option('--reset', is_flag=True, help='Delete and recreate database')
def db_handler(show_info: bool, show_path: bool, reset: bool):
    """
    Database management commands.

    \b
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
@click.option('--stats', 'show_stats', is_flag=True, help='Show table statistics (row counts)')
@click.option('--integrity', 'check_integrity', is_flag=True, help='Check database integrity')
@click.option('--vacuum', 'do_vacuum', is_flag=True, help='Compact and optimize database')
@click.option('--reset', 'do_reset', is_flag=True, help='Delete and recreate database')
def sql_handler(
    query: Optional[str],
    sql_file: Optional[str],
    output_format: str,
    interactive: bool,
    show_info: bool,
    show_path: bool,
    show_schema: bool,
    show_stats: bool,
    check_integrity: bool,
    do_vacuum: bool,
    do_reset: bool,
):
    """
    Execute raw SQL queries on the database.

    Also provides database management operations via flags.

    \b
    Examples:
        # Query data
        repoindex sql "SELECT name, stars FROM repos ORDER BY stars DESC LIMIT 10"
        # Database info
        repoindex sql --info
        repoindex sql --path
        repoindex sql --schema
        repoindex sql --stats
        # Query from file
        repoindex sql -f query.sql
        # CSV output
        repoindex sql "SELECT * FROM repos" --format csv
        # Interactive shell
        repoindex sql -i
        # Database maintenance
        repoindex sql --integrity
        repoindex sql --vacuum
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

    if show_stats:
        with Database(config=config, read_only=True) as db:
            # Get all tables
            db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' ORDER BY name")
            tables = [row['name'] for row in db.fetchall()]

            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table(title="Table Statistics")
            table.add_column("Table", style="cyan")
            table.add_column("Rows", style="green", justify="right")

            for tbl in tables:
                db.execute(f"SELECT COUNT(*) as count FROM {tbl}")
                count = db.fetchone()['count']
                table.add_row(tbl, str(count))

            console.print(table)
        return

    if check_integrity:
        with Database(config=config, read_only=True) as db:
            db.execute("PRAGMA integrity_check")
            result = db.fetchone()
            if result and result[0] == 'ok':
                click.echo("Database integrity check: OK", err=False)
            else:
                click.echo(f"Database integrity check failed: {result[0] if result else 'unknown error'}", err=True)
                sys.exit(1)
        return

    if do_vacuum:
        from ..database import get_db_path
        import os

        db_path = get_db_path(config)
        size_before = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        with Database(config=config) as db:
            db.execute("VACUUM")

        size_after = os.path.getsize(db_path)
        saved = size_before - size_after

        click.echo("Database optimized.", err=False)
        click.echo(f"  Size before: {_format_bytes(size_before)}", err=False)
        click.echo(f"  Size after:  {_format_bytes(size_after)}", err=False)
        if saved > 0:
            click.echo(f"  Saved:       {_format_bytes(saved)}", err=False)
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
