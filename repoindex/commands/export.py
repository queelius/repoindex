"""
Export command for repoindex.

Exports repository index in ECHO-compliant format:
durable, self-describing, and works offline.
"""

import click
import sys
from pathlib import Path
from typing import Optional

from ..config import load_config
from ..services.export_service import ExportService, ExportOptions
from ..database import compile_query, QueryCompileError
from .ops import query_options, _get_repos_from_query
from .query import _build_query_from_flags


@click.command('export')
@click.argument('output_dir', type=click.Path())
@click.argument('query_string', required=False, default='')
@click.option('--include-events', is_flag=True, help='Include git event history (commits, tags)')
@click.option('--dry-run', is_flag=True, help='Preview export without writing files')
@click.option('--pretty', is_flag=True, help='Show progress with rich formatting')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def export_handler(
    output_dir: str,
    query_string: str,
    include_events: bool,
    dry_run: bool,
    pretty: bool,
    debug: bool,
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
):
    """
    Export repository index in ECHO format.

    Creates a durable, self-describing export that works without repoindex.
    Output includes SQLite database, JSONL exports, READMEs, browsable site,
    and ECHO manifest.

    READMEs and a browsable site/ directory are always included --
    they are metadata, not content.

    Supports the same query flags as the query command to export a subset.

    \b
    Examples:
        # Basic export (database + JSONL + READMEs + site + manifest)
        repoindex export ~/backups/repos-2026-01
        # Include full event history
        repoindex export ~/backups/repos --include-events
        # Export subset using query flags
        repoindex export ~/backups/python-repos --language python
        repoindex export ~/backups/starred --starred
        repoindex export ~/backups/work --tag "work/*"
        # DSL query expression
        repoindex export ~/backups/popular "language == 'Python' and github_stars > 10"
        # Preview without writing
        repoindex export ~/backups/test --dry-run --pretty
    """
    if debug:
        import logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    config = load_config()

    # Build query filter from flags and/or DSL expression
    has_flags = any([dirty, clean, language, recent, starred, tag, no_license, no_readme,
                     has_citation, has_doi, archived, public, private, fork, no_fork])

    query_filter = None
    if has_flags or query_string:
        query_filter = _build_query_from_flags(
            query_string if query_string else None,
            dirty, clean, language, recent, starred, list(tag),
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork
        )

    service = ExportService(config=config)

    options = ExportOptions(
        output_dir=Path(output_dir),
        include_events=include_events,
        dry_run=dry_run,
        query_filter=query_filter,
    )

    if pretty:
        _export_pretty(service, options)
    else:
        _export_simple(service, options, dry_run)


def _export_simple(service: ExportService, options: ExportOptions, dry_run: bool):
    """Simple text output for export."""
    mode = "[dry run] " if dry_run else ""

    for progress in service.export(options):
        print(f"{mode}{progress}", file=sys.stderr)

    result = service.last_result
    if result:
        print(f"\n{mode}Export complete:", file=sys.stderr)
        print(f"  Repositories: {result.repos_exported}", file=sys.stderr)
        if options.include_events:
            print(f"  Events: {result.events_exported}", file=sys.stderr)
        print(f"  READMEs: {result.readmes_exported}", file=sys.stderr)

        if options.query_filter:
            print(f"  Filter: {options.query_filter}", file=sys.stderr)

        if result.errors:
            print(f"\nErrors ({len(result.errors)}):", file=sys.stderr)
            for error in result.errors:
                print(f"  - {error}", file=sys.stderr)
            sys.exit(1)

        if not dry_run:
            print(f"\nOutput: {options.output_dir}", file=sys.stderr)


def _export_pretty(service: ExportService, options: ExportOptions):
    """Rich formatted output for export."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    console = Console()
    mode = "[bold yellow]DRY RUN[/bold yellow] " if options.dry_run else ""

    console.print(f"\n{mode}[bold]Exporting to:[/bold] {options.output_dir}\n")

    if options.query_filter:
        console.print(f"[bold]Filter:[/bold] {options.query_filter}\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Starting export...", total=None)

        for message in service.export(options):
            progress.update(task, description=message)

    result = service.last_result
    if not result:
        console.print("[red]Export failed - no result[/red]")
        sys.exit(1)

    # Summary table
    table = Table(title=f"{mode}Export Summary", show_header=True)
    table.add_column("Component", style="cyan")
    table.add_column("Count", justify="right", style="green")

    table.add_row("Repositories", str(result.repos_exported))
    if options.include_events:
        table.add_row("Events", str(result.events_exported))
    table.add_row("READMEs", str(result.readmes_exported))

    console.print(table)

    if result.errors:
        console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")
        sys.exit(1)

    if not options.dry_run:
        console.print(f"\n[bold green]✓[/bold green] Export complete: {options.output_dir}")
        console.print("\nContents:")
        console.print("  • [cyan]index.db[/cyan] - SQLite database")
        console.print("  • [cyan]repos.jsonl[/cyan] - Repository records")
        if options.include_events:
            console.print("  • [cyan]events.jsonl[/cyan] - Event history")
        console.print("  • [cyan]readmes/[/cyan] - README snapshots")
        console.print("  • [cyan]site/[/cyan] - Browsable HTML dashboard")
        console.print("  • [cyan]README.md[/cyan] - Documentation")
        console.print("  • [cyan]manifest.json[/cyan] - ECHO manifest")
