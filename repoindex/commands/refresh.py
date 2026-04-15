"""
Refresh command for repoindex.

Populates the SQLite database with repository metadata.
This is the primary way to sync the database with filesystem state.
"""

import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional, Tuple

import click

logger = logging.getLogger(__name__)

_PROVIDER_WORKERS = 8

# SQL identifier validation (letters, digits, underscores; must start with letter/underscore)
_IDENT_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

# Cache of valid repos table columns (populated lazily from PRAGMA table_info)
_REPO_COLUMN_CACHE = None

# Local sources that run by default (fast, no HTTP)
_LOCAL_SOURCE_IDS = frozenset({'citation_cff', 'keywords', 'local_assets'})

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
    record_refresh,
)
from ..database.events import insert_events
from ..services.repository_service import RepositoryService
from ..services.tag_derivation import derive_persistable_tags
from ..events import scan_events
from ..sources import discover_sources


def _resolve_active_sources(
    source_names: Tuple[str, ...],
    provider_names: Tuple[str, ...],
    github: Optional[bool],
    external: bool,
    config: dict,
) -> list:
    """
    Resolve the list of active MetadataSource instances.

    Merges:
    - Explicit --source flags (primary)
    - Deprecated --provider flags (merged into source names)
    - --github / --no-github convenience alias
    - --external (all sources)
    - Config defaults from refresh.external_sources and refresh.providers

    Local sources (citation_cff, keywords, local_assets) always run unless
    explicitly excluded.

    Args:
        source_names: Explicit --source flag values
        provider_names: Deprecated --provider flag values
        github: --github/--no-github flag (True/False/None)
        external: Whether --external was passed
        config: Full config dict

    Returns:
        List of MetadataSource instances to run
    """
    ext_config = config.get('refresh', {}).get('external_sources', {})
    provider_config = config.get('refresh', {}).get('providers', {})

    # Merge --source and --provider (deprecated) into one set
    all_names = set(source_names) | set(provider_names)

    # Handle --github / --no-github
    excluded = set()
    if github is False:
        excluded.add('github')
        all_names.discard('github')
    elif github is True:
        all_names.add('github')
    elif ext_config.get('github', False):
        # Config default enables github
        all_names.add('github')

    # Config defaults for providers (e.g., pypi: true)
    for name, enabled in provider_config.items():
        if enabled and name not in excluded:
            all_names.add(name)

    # Determine active sources
    if external:
        # All sources, but respect explicit exclusions
        active_sources = [s for s in discover_sources() if s.source_id not in excluded]
    elif all_names:
        # Explicit names + always include local sources
        requested = all_names | _LOCAL_SOURCE_IDS
        active_sources = discover_sources(only=list(requested))
    else:
        # Default: only local sources (fast, no HTTP)
        active_sources = discover_sources(only=list(_LOCAL_SOURCE_IDS))

    return active_sources


@click.command('refresh')
@click.option('--full', is_flag=True, help='Force full refresh of all repos')
@click.option('--since', default='90d', help='How far back to scan for events (e.g., 7d, 30d, 90d)')
@click.option('--github/--no-github', default=None, help='Fetch GitHub metadata (alias for --source github)')
@click.option('--source', '-s', 'source_names', multiple=True,
              help='Enable specific sources (e.g., --source github --source pypi)')
@click.option('--provider', '-p', 'provider_names', multiple=True,
              help='(Deprecated: use --source) Enable specific providers', hidden=True)
@click.option('--external', is_flag=True, help='Enable all external sources (GitHub, registries, etc.)')
@click.option('-d', '--dir', 'directory', type=click.Path(exists=True),
              help='Refresh specific directory instead of configured paths')
@click.option('--dry-run', is_flag=True, help='Show what would be refreshed')
@click.option('--quiet', '-q', is_flag=True, help='Minimal output')
def refresh_handler(
    full: bool,
    since: str,
    github: Optional[bool],
    source_names: Tuple[str, ...],
    provider_names: Tuple[str, ...],
    external: bool,
    directory: Optional[str],
    dry_run: bool,
    quiet: bool,
):
    """
    Refresh the repository index database.

    Scans configured directories for git repositories and populates
    the SQLite database with their metadata. Events (commits, tags)
    are always scanned.

    By default, performs a smart refresh that only updates repos
    that have changed since the last scan. Local sources (CITATION.cff,
    keywords, local assets) always run.

    External sources (GitHub, PyPI, CRAN, Zenodo, npm, cargo, etc.) are
    enabled via --source or --external. --github is a convenience alias
    for --source github. The deprecated --provider flag is equivalent
    to --source.

    \b
    Examples:
        # Smart refresh (only changed repos)
        repoindex refresh
        # Full refresh of all repos
        repoindex refresh --full
        # Include GitHub metadata
        repoindex refresh --github
        repoindex refresh --source github
        # Include specific sources
        repoindex refresh --source pypi --source cran
        repoindex refresh -s npm -s cargo
        # Include all external sources (slower)
        repoindex refresh --external
        # Refresh specific directory
        repoindex refresh -d ~/projects
        # Scan events from last 30 days only
        repoindex refresh --since 30d
        # Reset and rebuild: use sql --reset first
        repoindex sql --reset && repoindex refresh --full

    \b
    Config defaults (in config.yaml):
        refresh:
          external_sources:
            github: true    # GitHub metadata enabled by default
          providers:
            pypi: false     # Registry providers disabled by default
            cran: false
            zenodo: false
    """
    config = load_config()

    # Resolve active sources from all flags + config
    active_sources = _resolve_active_sources(
        source_names=source_names,
        provider_names=provider_names,
        github=github,
        external=external,
        config=config,
    )

    # Prefetch batch sources (e.g., Zenodo ORCID lookup)
    for s in active_sources:
        if s.batch:
            try:
                s.prefetch(config)
                if not quiet:
                    click.echo(f"Source {s.name}: prefetch complete", err=True)
            except Exception as e:
                if not quiet:
                    click.echo(f"Warning: {s.name} prefetch failed: {e}", err=True)

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
                    sources=active_sources,
                    config=config,
                    dry_run=dry_run,
                    quiet=quiet
                )
                progress.update(task, advance=1)

        # Cleanup repos that no longer exist
        if not dry_run:
            removed = cleanup_missing_repos(db)
            stats['removed'] = removed

        stats['end_time'] = datetime.now().isoformat()
        stats['total_repos'] = get_repo_count(db)
        stats['total_scan_errors'] = get_scan_error_count(db)

        # Write refresh log entry
        if not dry_run:
            try:
                # Build sources list
                source_list = ["git"]
                for s in active_sources:
                    if s.source_id not in source_list:
                        source_list.append(s.source_id)
                sources = source_list

                # Compute duration
                start_dt = datetime.fromisoformat(stats['start_time'])
                end_dt = datetime.fromisoformat(stats['end_time'])
                duration = (end_dt - start_dt).total_seconds()

                # Get CLI version
                try:
                    from .. import __version__
                    cli_version = __version__
                except Exception:
                    cli_version = None

                log_config = config.get('refresh', {}).get('log', {})
                max_rows = log_config.get('max_rows', 100)

                record_refresh(
                    db,
                    started_at=stats['start_time'],
                    finished_at=stats['end_time'],
                    sources=sources,
                    full_scan=full,
                    scan_roots=paths,
                    repos_total=stats.get('total_repos', 0),
                    repos_scanned=stats.get('scanned', 0),
                    repos_skipped=stats.get('skipped', 0),
                    repos_added=stats.get('updated', 0),
                    repos_removed=stats.get('removed', 0),
                    errors=stats.get('errors', 0),
                    duration_seconds=duration,
                    cli_version=cli_version,
                    max_rows=max_rows,
                )
            except Exception:
                pass  # Non-critical: don't fail refresh over logging

    # Output results
    if quiet:
        pass
    else:
        _print_summary_pretty(stats)


def _get_valid_repo_columns(db):
    """Return the set of valid column names from the repos table (cached)."""
    global _REPO_COLUMN_CACHE
    if _REPO_COLUMN_CACHE is None:
        db.execute("PRAGMA table_info(repos)")
        _REPO_COLUMN_CACHE = {row['name'] for row in db.fetchall()}
    return _REPO_COLUMN_CACHE


def _update_repo_platform_fields(db, repo_id, fields):
    """Update repo with platform-specific fields.

    Column names are validated against the actual schema to prevent SQL
    injection from user-provided platform providers. Unknown or malformed
    column names are dropped with a warning.
    """
    if not fields:
        return
    valid = _get_valid_repo_columns(db)
    safe_fields = {
        k: v for k, v in fields.items()
        if _IDENT_RE.match(k) and k in valid
    }
    dropped = set(fields.keys()) - set(safe_fields.keys())
    if dropped:
        logger.warning(f"Dropping unknown platform fields: {sorted(dropped)}")
    if not safe_fields:
        return
    set_clauses = ', '.join(f'{k} = ?' for k in safe_fields.keys())
    params = list(safe_fields.values()) + [repo_id]
    db.execute(f"UPDATE repos SET {set_clauses} WHERE id = ?", tuple(params))


def _run_sources_parallel(sources, repo_path, repo_dict, config, quiet=False):
    """Run MetadataSource.fetch() calls in parallel.

    Returns list of (source, data) tuples for successful fetches.
    Each source's detect() is checked first; if it returns False, the
    source is skipped. Errors are isolated per-source.
    """
    if not sources:
        return []

    def _check(src):
        if src.detect(repo_path, repo_dict):
            data = src.fetch(repo_path, repo_dict, config)
            if data:
                return src, data
        return None

    results = []
    with ThreadPoolExecutor(max_workers=min(len(sources), _PROVIDER_WORKERS)) as pool:
        futures = {pool.submit(_check, s): s for s in sources}
        for future in as_completed(futures):
            src = futures[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"Source {src.source_id} failed: {e}")
                if not quiet:
                    click.echo(f"  Warning: source {src.source_id} failed: {e}", err=True)
    return results


def _derive_tags(db, repo_id, repo_record):
    """Derive tags from metadata fields and sync to tags table.

    Runs after all MetadataSources have enriched a repo. Reads metadata
    columns and populates the tags table with source-attributed entries.

    User-assigned tags (source='user') are never touched.
    Derived tags (all other sources) are synced: stale ones removed, new ones added.

    The actual derivation logic lives in
    `repoindex.services.tag_derivation.derive_persistable_tags`; this
    function is the thin DB-aware wrapper that supplies the published
    registries from the publications table.
    """
    # Look up which registries have a published row for this repo.
    # Kept at the call site (rather than pushed into tag_derivation) so
    # the shared helper stays pure / DB-free and can be used by read-view
    # code paths that already hold the data in memory.
    db.execute(
        "SELECT DISTINCT registry FROM publications WHERE repo_id = ? AND published = 1",
        (repo_id,)
    )
    published_registries = [row['registry'] for row in db.fetchall()]

    derived = derive_persistable_tags(repo_record, published_registries)

    # Sync derived tags (remove stale, add new, never touch user tags)
    _sync_derived_tags(db, repo_id, derived)


def _sync_derived_tags(db, repo_id, derived_tags):
    """Sync derived tags for a repo. Preserves user-assigned tags.

    Uses the tag string as the identity key (matches PRIMARY KEY (repo_id, tag)).
    Tags with source='user' are never modified. For derived tags, stale ones
    are removed and new ones are added.

    Args:
        db: Database connection
        repo_id: Repository ID
        derived_tags: list of (tag_string, source_name) tuples
    """
    # Build desired map: tag_string -> source_name
    # If the same tag appears from multiple sources, first one wins
    desired = {}
    for tag, source in derived_tags:
        if tag not in desired:
            desired[tag] = source

    # Get current non-user tags
    db.execute(
        "SELECT tag, source FROM tags WHERE repo_id = ? AND source != 'user'",
        (repo_id,)
    )
    current = {row['tag']: row['source'] for row in db.fetchall()}

    # Remove stale tags (in current but not desired)
    for tag in current:
        if tag not in desired:
            db.execute(
                "DELETE FROM tags WHERE repo_id = ? AND tag = ?",
                (repo_id, tag)
            )

    # Add new tags (in desired but not current)
    for tag, source in desired.items():
        if tag not in current:
            db.execute(
                "INSERT OR IGNORE INTO tags (repo_id, tag, source) VALUES (?, ?, ?)",
                (repo_id, tag, source)
            )

    # Update source if it changed for an existing derived tag
    for tag, source in desired.items():
        if tag in current and current[tag] != source:
            db.execute(
                "UPDATE tags SET source = ? WHERE repo_id = ? AND tag = ?",
                (source, repo_id, tag)
            )


def _process_repo(
    db: Database,
    service: RepositoryService,
    repo,
    stats: dict,
    full: bool,
    since: datetime,
    sources: list,
    config: dict,
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
        enriched = service.get_status(repo)

        # Load tags from config
        tags_from_config = service.config.get('repository_tags', {}).get(repo.path, [])
        if tags_from_config:
            enriched = enriched.with_tags(frozenset(tags_from_config))

        # Upsert to database
        repo_id = upsert_repo(db, enriched)

        # Run all active sources (parallel) — isolated so source failures
        # don't poison the rest of repo processing (event scanning, etc.).
        if sources and repo_id:
            try:
                repo_dict = {
                    'remote_url': enriched.remote_url,
                    'name': enriched.name,
                    'owner': getattr(enriched, 'owner', None),
                }
                results = _run_sources_parallel(
                    sources, repo.path, repo_dict, config, quiet=quiet
                )
                for source, data in results:
                    if source.target == 'repos':
                        _update_repo_platform_fields(db, repo_id, data)
                    elif source.target == 'publications':
                        from ..database.repository import _upsert_publication
                        from ..domain.repository import PackageMetadata
                        pkg = PackageMetadata(
                            registry=data.get('registry', ''),
                            name=data.get('name', ''),
                            version=data.get('version'),
                            published=data.get('published', False),
                            url=data.get('url'),
                            doi=data.get('doi'),
                            downloads=data.get('downloads'),
                            downloads_30d=data.get('downloads_30d'),
                            last_updated=data.get('last_updated'),
                        )
                        _upsert_publication(db, repo_id, pkg)
                    else:
                        # Belt-and-suspenders: discover_sources() already
                        # filters unknown targets, but if something slips
                        # through (e.g., a source mutates self.target after
                        # discovery), surface it instead of silently dropping
                        # the fetched data.
                        logger.warning(
                            "Source %s has unknown target %r; skipping",
                            source.source_id, source.target,
                        )
            except Exception as e:
                if not quiet:
                    click.echo(f"  Warning: source enrichment failed for {repo.name}: {e}", err=True)
        stats['updated'] += 1

        # Derive tags from all metadata (runs after sources have enriched the repo)
        if repo_id:
            try:
                db.execute("SELECT * FROM repos WHERE id = ?", (repo_id,))
                updated_record = db.fetchone()
                if updated_record:
                    _derive_tags(db, repo_id, dict(updated_record))
            except Exception as e:
                if not quiet:
                    click.echo(f"  Warning: tag derivation failed for {repo.name}: {e}", err=True)

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
@click.option('--json', 'force_json', is_flag=True, help='Output as JSON (alias for --format json)')
@click.option('--csv', 'force_csv', is_flag=True, help='Output as CSV (alias for --format csv)')
@click.option('--table', 'force_table', is_flag=True, help='Output as table (alias for --format table)')
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
    force_json: bool,
    force_csv: bool,
    force_table: bool,
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

    # Resolve format aliases
    if force_table:
        output_format = 'table'
    elif force_csv:
        output_format = 'csv'
    elif force_json:
        output_format = 'json'

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
