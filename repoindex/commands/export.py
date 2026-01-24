"""
Export command for repoindex.

Exports repository index in ECHO-compliant format:
durable, self-describing, and works offline.
"""

import click
import sys
from pathlib import Path

from ..config import load_config
from ..services.export_service import ExportService, ExportOptions


@click.command('export')
@click.argument('output_dir', type=click.Path())
@click.option('--include-readmes', is_flag=True, help='Include README snapshots from each repo')
@click.option('--include-events', is_flag=True, help='Include git event history (commits, tags)')
@click.option('--include-git-summary', type=int, default=0, metavar='N',
              help='Include last N commits per repo as JSON summaries')
@click.option('--archive-repos', is_flag=True, help='Create tar.gz archives of repositories')
@click.option('--dry-run', is_flag=True, help='Preview export without writing files')
@click.option('--pretty', is_flag=True, help='Show progress with rich formatting')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def export_handler(
    output_dir: str,
    include_readmes: bool,
    include_events: bool,
    include_git_summary: int,
    archive_repos: bool,
    dry_run: bool,
    pretty: bool,
    debug: bool,
):
    """
    Export repository index in ECHO format.

    Creates a durable, self-describing export that works without repoindex.
    Output includes SQLite database, JSONL exports, README, and manifest.

    ECHO format exports are designed to remain useful for decades:
    - Durable formats (SQLite, JSONL, Markdown)
    - Self-describing (README explains everything)
    - No dependencies (works without original tool)

    Examples:

        # Basic export (database + JSONL + README + manifest)
        repoindex export ~/backups/repos-2026-01

        # Include README snapshots from each repository
        repoindex export ~/backups/repos --include-readmes

        # Include full event history
        repoindex export ~/backups/repos --include-events

        # Include last 10 commits per repo as JSON
        repoindex export ~/backups/repos --include-git-summary 10

        # Full export with archives (slow, large)
        repoindex export ~/backups/repos-full --include-readmes --include-events --archive-repos

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
    service = ExportService(config=config)

    options = ExportOptions(
        output_dir=Path(output_dir),
        include_readmes=include_readmes,
        include_events=include_events,
        include_git_summary=include_git_summary,
        archive_repos=archive_repos,
        dry_run=dry_run,
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
        if options.include_readmes:
            print(f"  READMEs: {result.readmes_exported}", file=sys.stderr)
        if options.include_git_summary > 0:
            print(f"  Git summaries: {result.git_summaries_exported}", file=sys.stderr)
        if options.archive_repos:
            print(f"  Archives: {result.archives_created}", file=sys.stderr)

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
    if options.include_readmes:
        table.add_row("READMEs", str(result.readmes_exported))
    if options.include_git_summary > 0:
        table.add_row("Git summaries", str(result.git_summaries_exported))
    if options.archive_repos:
        table.add_row("Archives", str(result.archives_created))

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
        console.print("  • [cyan]README.md[/cyan] - Documentation")
        console.print("  • [cyan]manifest.json[/cyan] - ECHO manifest")
        if options.include_readmes:
            console.print("  • [cyan]readmes/[/cyan] - README snapshots")
        if options.include_git_summary > 0:
            console.print("  • [cyan]git-summaries/[/cyan] - Commit history")
        if options.archive_repos:
            console.print("  • [cyan]archives/[/cyan] - Repo archives")
