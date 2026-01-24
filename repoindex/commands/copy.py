"""
Copy command for repoindex.

Copies repositories to a destination directory with query filtering.
Useful for backups, redundancy, and organizing repos.
"""

import click
import json
import sys
from pathlib import Path
from typing import Optional

from ..config import load_config
from ..database import Database, compile_query, QueryCompileError
from ..services.copy_service import CopyService, CopyOptions, CollisionStrategy
from .query import _build_query_from_flags


def _format_bytes(bytes_val: int) -> str:
    """Format bytes as human-readable string."""
    size: float = float(bytes_val)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


@click.command('copy')
@click.argument('destination', type=click.Path())
@click.argument('query_string', required=False, default='')
# Output options
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display progress with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview copy without writing files')
# Copy options
@click.option('--exclude-git', is_flag=True, help='Skip .git directories')
@click.option('--preserve-structure', is_flag=True, help='Keep parent directory hierarchy')
@click.option('--collision', type=click.Choice(['rename', 'skip', 'overwrite']),
              default='rename', help='How to handle name collisions (default: rename)')
# Query convenience flags (same as query command)
@click.option('--dirty', is_flag=True, help='Repos with uncommitted changes')
@click.option('--clean', is_flag=True, help='Repos with no uncommitted changes')
@click.option('--language', '-l', help='Filter by language (e.g., python, js, rust)')
@click.option('--recent', '-r', help='Repos with recent commits (e.g., 7d, 30d)')
@click.option('--starred', is_flag=True, help='Repos with stars')
@click.option('--tag', '-t', multiple=True, help='Filter by tag (supports wildcards)')
@click.option('--no-license', is_flag=True, help='Repos without a license')
@click.option('--no-readme', is_flag=True, help='Repos without a README')
@click.option('--has-citation', is_flag=True, help='Repos with citation files')
@click.option('--has-doi', is_flag=True, help='Repos with DOI in citation metadata')
@click.option('--archived', is_flag=True, help='Archived repos only')
@click.option('--public', is_flag=True, help='Public repos only')
@click.option('--private', is_flag=True, help='Private repos only')
@click.option('--fork', is_flag=True, help='Forked repos only')
@click.option('--no-fork', is_flag=True, help='Non-forked repos only')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def copy_handler(
    destination: str,
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    exclude_git: bool,
    preserve_structure: bool,
    collision: str,
    # Query flags
    dirty: bool,
    clean: bool,
    language: Optional[str],
    recent: Optional[str],
    starred: bool,
    tag: tuple,
    no_license: bool,
    no_readme: bool,
    has_citation: bool,
    has_doi: bool,
    archived: bool,
    public: bool,
    private: bool,
    fork: bool,
    no_fork: bool,
    debug: bool,
):
    """
    Copy repositories to a destination directory.

    Supports the same query filters as the query command for selecting
    which repositories to copy.

    Examples:

        # Copy all repos to backup directory
        repoindex copy ~/backups/repos-2026-01

        # Copy only Python repos
        repoindex copy ~/backups/python --language python

        # Copy dirty repos (with uncommitted changes)
        repoindex copy ~/backups/uncommitted --dirty

        # Copy repos with specific tag
        repoindex copy ~/backups/work --tag "work/*"

        # Copy with DSL query
        repoindex copy ~/backups/popular "language == 'Python' and github_stars > 10"

        # Options
        repoindex copy ~/backups --exclude-git          # Skip .git directories
        repoindex copy ~/backups --preserve-structure   # Keep parent dir hierarchy
        repoindex copy ~/backups --collision skip       # Skip on name collision
        repoindex copy ~/backups --dry-run --pretty     # Preview
    """
    if debug:
        import logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    config = load_config()

    # Build query from flags
    has_flags = any([dirty, clean, language, recent, starred, tag, no_license, no_readme,
                     has_citation, has_doi, archived, public, private, fork, no_fork])
    if has_flags:
        query_string = _build_query_from_flags(
            query_string if query_string else None,
            dirty, clean, language, recent, starred, list(tag),
            no_license, no_readme, has_citation, has_doi, archived, public, private, fork, no_fork
        )

    # If no query and no flags, copy all repos
    if not query_string:
        query_string = "1 == 1"

    # Query repos from database
    try:
        views = config.get('views', {})
        compiled = compile_query(query_string, views=views)

        repos = []
        with Database(config=config, read_only=True) as db:
            if debug:
                print(f"DEBUG: SQL: {compiled.sql}", file=sys.stderr)
                print(f"DEBUG: Params: {compiled.params}", file=sys.stderr)

            db.execute(compiled.sql, tuple(compiled.params))
            for row in db.fetchall():
                repos.append(dict(row))

    except QueryCompileError as e:
        error = {
            'error': str(e),
            'type': 'query_compile_error',
            'query': query_string,
        }
        if output_json:
            print(json.dumps(error), file=sys.stderr)
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not repos:
        if output_json:
            print(json.dumps({'warning': 'No repositories found matching query'}))
        elif pretty:
            from rich.console import Console
            Console().print("[yellow]No repositories found matching query.[/yellow]")
        else:
            print("No repositories found matching query.", file=sys.stderr)
        return

    # Set up copy service
    collision_strategy = CollisionStrategy(collision)
    options = CopyOptions(
        destination=Path(destination),
        exclude_git=exclude_git,
        preserve_structure=preserve_structure,
        collision_strategy=collision_strategy,
        dry_run=dry_run,
    )

    service = CopyService(config=config)

    if pretty:
        _copy_pretty(service, repos, options)
    elif output_json:
        _copy_json(service, repos, options)
    else:
        _copy_simple(service, repos, options)


def _copy_simple(service: CopyService, repos: list, options: CopyOptions):
    """Simple text output for copy."""
    mode = "[dry run] " if options.dry_run else ""

    for progress in service.copy(repos, options):
        print(f"{mode}{progress}", file=sys.stderr)

    result = service.last_result
    if result:
        print(f"\n{mode}Copy complete:", file=sys.stderr)
        print(f"  Repositories copied: {result.repos_copied}", file=sys.stderr)
        if result.repos_skipped > 0:
            print(f"  Repositories skipped: {result.repos_skipped}", file=sys.stderr)
        print(f"  Total size: {_format_bytes(result.bytes_copied)}", file=sys.stderr)

        if result.errors:
            print(f"\nErrors ({len(result.errors)}):", file=sys.stderr)
            for error in result.errors:
                print(f"  - {error}", file=sys.stderr)
            sys.exit(1)

        if not options.dry_run:
            print(f"\nOutput: {options.destination}", file=sys.stderr)


def _copy_json(service: CopyService, repos: list, options: CopyOptions):
    """JSONL output for copy."""
    for progress in service.copy(repos, options):
        print(json.dumps({'progress': progress}), flush=True)

    result = service.last_result
    if result:
        # Output each detail as a line
        for detail in result.details:
            print(json.dumps(detail), flush=True)

        # Output summary
        summary = {
            'type': 'summary',
            'repos_copied': result.repos_copied,
            'repos_skipped': result.repos_skipped,
            'bytes_copied': result.bytes_copied,
            'errors': result.errors,
            'dry_run': options.dry_run,
        }
        print(json.dumps(summary), flush=True)


def _copy_pretty(service: CopyService, repos: list, options: CopyOptions):
    """Rich formatted output for copy."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table

    console = Console()
    mode = "[bold yellow]DRY RUN[/bold yellow] " if options.dry_run else ""

    console.print(f"\n{mode}[bold]Copying to:[/bold] {options.destination}")
    console.print(f"[bold]Repositories:[/bold] {len(repos)}")
    if options.exclude_git:
        console.print("[dim]Excluding .git directories[/dim]")
    if options.preserve_structure:
        console.print("[dim]Preserving directory structure[/dim]")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Starting copy...", total=len(repos))
        copied = 0

        for message in service.copy(repos, options):
            copied += 1
            progress.update(task, advance=1, description=message)

    result = service.last_result
    if not result:
        console.print("[red]Copy failed - no result[/red]")
        sys.exit(1)

    # Summary table
    table = Table(title=f"{mode}Copy Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    table.add_row("Repositories copied", str(result.repos_copied))
    if result.repos_skipped > 0:
        table.add_row("Repositories skipped", str(result.repos_skipped))
    table.add_row("Total size", _format_bytes(result.bytes_copied))

    console.print(table)

    if result.errors:
        console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")
        sys.exit(1)

    if not options.dry_run:
        console.print(f"\n[bold green]✓[/bold green] Copy complete: {options.destination}")
