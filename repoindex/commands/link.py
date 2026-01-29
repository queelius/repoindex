"""
Link command for repoindex.

Creates and manages symlink trees organized by metadata.
"""

import click
import json
import sys
from pathlib import Path
from typing import Optional

from ..config import load_config
from ..database import Database, compile_query, QueryCompileError
from ..services.link_service import (
    LinkService, LinkTreeOptions, OrganizeBy, MANIFEST_FILENAME
)
from .query import _build_query_from_flags
from .tag import get_implicit_tags_from_row


@click.group('link')
def link_cmd():
    """Manage symlink trees for repository organization.

    Create hierarchical symlink structures organized by tags, language,
    year, or owner. Repos can appear in multiple locations.

    \b
    Examples:
        # Create symlink tree by tags
        repoindex link tree ~/links/by-tag --by tag
        # Create symlink tree by language
        repoindex link tree ~/links/by-language --by language
        # Check tree status
        repoindex link status ~/links/by-tag
        # Refresh tree and remove broken links
        repoindex link refresh ~/links/by-tag --prune
    """
    pass


@link_cmd.command('tree')
@click.argument('destination', type=click.Path())
@click.option('--by', 'organize_by', type=click.Choice(['tag', 'language', 'created-year', 'modified-year', 'owner']),
              required=True, help='How to organize the symlink tree')
@click.argument('query_string', required=False, default='')
# Output options
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display progress with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without creating links')
# Tree options
@click.option('--max-depth', type=int, default=10, help='Maximum directory depth (default: 10)')
@click.option('--collision', type=click.Choice(['rename', 'skip']),
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
def tree_handler(
    destination: str,
    organize_by: str,
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    max_depth: int,
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
    Create a symlink tree organized by metadata.

    Supports the same query filters as the query command for selecting
    which repositories to include.

    \b
    Examples:
        # Create symlink tree organized by tags
        repoindex link tree ~/links/by-tag --by tag
        # Organize by language
        repoindex link tree ~/links/by-language --by language
        # Organize by year of last modification
        repoindex link tree ~/links/by-year --by modified-year
        # Organize by repository owner
        repoindex link tree ~/links/by-owner --by owner
        # Filter to only Python repos
        repoindex link tree ~/links/python-by-tag --by tag --language python
        # Preview without creating
        repoindex link tree ~/links/test --by tag --dry-run --pretty
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

    # If no query and no flags, include all repos
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
                record = dict(row)
                # Get explicit tags from database
                db.execute("SELECT tag FROM tags WHERE repo_id = ?", (record['id'],))
                explicit_tags = [r['tag'] for r in db.fetchall()]

                # Get implicit tags (including topic:{github_topic})
                implicit_tags = get_implicit_tags_from_row(record)

                # Merge all tags (deduplication via set)
                record['tags'] = list(set(explicit_tags + implicit_tags))
                repos.append(record)

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

    # Set up link service
    organize_enum = OrganizeBy(organize_by)
    options = LinkTreeOptions(
        destination=Path(destination),
        organize_by=organize_enum,
        max_depth=max_depth,
        collision_strategy=collision,
        dry_run=dry_run,
    )

    service = LinkService(config=config)

    if pretty:
        _tree_pretty(service, repos, options)
    elif output_json:
        _tree_json(service, repos, options)
    else:
        _tree_simple(service, repos, options)


def _tree_simple(service: LinkService, repos: list, options: LinkTreeOptions):
    """Simple text output for tree creation."""
    mode = "[dry run] " if options.dry_run else ""

    for progress in service.create_tree(repos, options):
        print(f"{mode}{progress}", file=sys.stderr)

    result = service.last_result
    if result:
        print(f"\n{mode}Link tree complete:", file=sys.stderr)
        print(f"  Links created: {result.links_created}", file=sys.stderr)
        if result.links_updated > 0:
            print(f"  Links updated: {result.links_updated}", file=sys.stderr)
        if result.links_skipped > 0:
            print(f"  Links skipped: {result.links_skipped}", file=sys.stderr)

        if result.errors:
            print(f"\nErrors ({len(result.errors)}):", file=sys.stderr)
            for error in result.errors:
                print(f"  - {error}", file=sys.stderr)
            sys.exit(1)

        if not options.dry_run:
            print(f"\nOutput: {options.destination}", file=sys.stderr)


def _tree_json(service: LinkService, repos: list, options: LinkTreeOptions):
    """JSONL output for tree creation."""
    for progress in service.create_tree(repos, options):
        print(json.dumps({'progress': progress}), flush=True)

    result = service.last_result
    if result:
        for detail in result.details:
            print(json.dumps(detail), flush=True)

        summary = {
            'type': 'summary',
            'links_created': result.links_created,
            'links_updated': result.links_updated,
            'links_skipped': result.links_skipped,
            'errors': result.errors,
            'dry_run': options.dry_run,
        }
        print(json.dumps(summary), flush=True)


def _tree_pretty(service: LinkService, repos: list, options: LinkTreeOptions):
    """Rich formatted output for tree creation."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table

    console = Console()
    mode = "[bold yellow]DRY RUN[/bold yellow] " if options.dry_run else ""

    console.print(f"\n{mode}[bold]Creating symlink tree:[/bold] {options.destination}")
    console.print(f"[bold]Organize by:[/bold] {options.organize_by.value}")
    console.print(f"[bold]Repositories:[/bold] {len(repos)}")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Creating links...", total=len(repos))

        for message in service.create_tree(repos, options):
            progress.update(task, advance=1, description=message)

    result = service.last_result
    if not result:
        console.print("[red]Failed - no result[/red]")
        sys.exit(1)

    # Summary table
    table = Table(title=f"{mode}Link Tree Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    table.add_row("Links created", str(result.links_created))
    if result.links_updated > 0:
        table.add_row("Links updated", str(result.links_updated))
    if result.links_skipped > 0:
        table.add_row("Links skipped", str(result.links_skipped))
    if result.dirs_created > 0:
        table.add_row("Directories created", str(result.dirs_created))

    console.print(table)

    if result.errors:
        console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")
        sys.exit(1)

    if not options.dry_run:
        console.print(f"\n[bold green]✓[/bold green] Link tree created: {options.destination}")


@link_cmd.command('refresh')
@click.argument('tree_path', type=click.Path(exists=True))
@click.option('--prune', is_flag=True, help='Remove broken symlinks')
@click.option('--dry-run', is_flag=True, help='Preview without making changes')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
def refresh_handler(
    tree_path: str,
    prune: bool,
    dry_run: bool,
    output_json: bool,
    pretty: bool,
):
    """
    Refresh an existing symlink tree.

    Checks for broken symlinks and optionally removes them.

    \b
    Examples:
        # Check and remove broken links
        repoindex link refresh ~/links/by-tag --prune
        # Preview what would be pruned
        repoindex link refresh ~/links/by-tag --prune --dry-run
        # Just scan without pruning
        repoindex link refresh ~/links/by-tag
    """
    config = load_config()
    service = LinkService(config=config)

    tree_dir = Path(tree_path)

    if pretty:
        _refresh_pretty(service, tree_dir, prune, dry_run)
    elif output_json:
        _refresh_json(service, tree_dir, prune, dry_run)
    else:
        _refresh_simple(service, tree_dir, prune, dry_run)


def _refresh_simple(service: LinkService, tree_path: Path, prune: bool, dry_run: bool):
    """Simple text output for refresh."""
    mode = "[dry run] " if dry_run else ""

    for progress in service.refresh_tree(tree_path, prune=prune, dry_run=dry_run):
        print(f"{mode}{progress}", file=sys.stderr)

    result = service.last_refresh_result
    if result:
        print(f"\n{mode}Refresh complete:", file=sys.stderr)
        print(f"  Total links: {result.total_links}", file=sys.stderr)
        print(f"  Valid links: {result.valid_links}", file=sys.stderr)
        print(f"  Broken links: {result.broken_links}", file=sys.stderr)
        if prune:
            print(f"  Removed: {result.removed_links}", file=sys.stderr)

        if result.broken_paths and not prune:
            print("\nBroken links:", file=sys.stderr)
            for path in result.broken_paths[:10]:
                print(f"  - {path}", file=sys.stderr)
            if len(result.broken_paths) > 10:
                print(f"  ... and {len(result.broken_paths) - 10} more", file=sys.stderr)


def _refresh_json(service: LinkService, tree_path: Path, prune: bool, dry_run: bool):
    """JSONL output for refresh."""
    for progress in service.refresh_tree(tree_path, prune=prune, dry_run=dry_run):
        print(json.dumps({'progress': progress}), flush=True)

    result = service.last_refresh_result
    if result:
        summary = {
            'type': 'summary',
            'total_links': result.total_links,
            'valid_links': result.valid_links,
            'broken_links': result.broken_links,
            'removed_links': result.removed_links,
            'broken_paths': result.broken_paths,
            'dry_run': dry_run,
        }
        print(json.dumps(summary), flush=True)


def _refresh_pretty(service: LinkService, tree_path: Path, prune: bool, dry_run: bool):
    """Rich formatted output for refresh."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    console = Console()
    mode = "[bold yellow]DRY RUN[/bold yellow] " if dry_run else ""

    console.print(f"\n{mode}[bold]Refreshing:[/bold] {tree_path}")
    if prune:
        console.print("[dim]Will remove broken symlinks[/dim]")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning...", total=None)

        for message in service.refresh_tree(tree_path, prune=prune, dry_run=dry_run):
            progress.update(task, description=message)

    result = service.last_refresh_result
    if not result:
        console.print("[red]Failed - no result[/red]")
        sys.exit(1)

    # Summary table
    table = Table(title=f"{mode}Refresh Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total links", str(result.total_links))
    table.add_row("Valid links", f"[green]{result.valid_links}[/green]")
    table.add_row("Broken links", f"[red]{result.broken_links}[/red]" if result.broken_links else "0")
    if prune:
        table.add_row("Removed", str(result.removed_links))

    console.print(table)

    if result.broken_paths and not prune:
        console.print(f"\n[yellow]Broken links ({len(result.broken_paths)}):[/yellow]")
        for path in result.broken_paths[:10]:
            console.print(f"  [red]✗[/red] {path}")
        if len(result.broken_paths) > 10:
            console.print(f"  [dim]... and {len(result.broken_paths) - 10} more[/dim]")
        console.print("\n[dim]Run with --prune to remove broken links[/dim]")

    if result.broken_links == 0:
        console.print("\n[bold green]✓[/bold green] All links are valid")


@link_cmd.command('status')
@click.argument('tree_path', type=click.Path(exists=True))
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
def status_handler(
    tree_path: str,
    output_json: bool,
    pretty: bool,
):
    """
    Show status of an existing symlink tree.

    Non-modifying operation that reports on link health.

    \b
    Examples:
        repoindex link status ~/links/by-tag
        repoindex link status ~/links/by-tag --pretty
    """
    config = load_config()
    service = LinkService(config=config)

    tree_dir = Path(tree_path)

    # Read manifest if it exists
    manifest = None
    manifest_path = tree_dir / MANIFEST_FILENAME
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            pass

    if pretty:
        _status_pretty(service, tree_dir, manifest)
    elif output_json:
        _status_json(service, tree_dir, manifest)
    else:
        _status_simple(service, tree_dir, manifest)


def _status_simple(service: LinkService, tree_path: Path, manifest: Optional[dict]):
    """Simple text output for status."""
    for progress in service.get_tree_status(tree_path):
        print(progress, file=sys.stderr)

    result = service.last_refresh_result
    if result:
        print(f"\nStatus: {tree_path}", file=sys.stderr)
        if manifest:
            print(f"  Created: {manifest.get('created_at', 'unknown')}", file=sys.stderr)
            print(f"  Organize by: {manifest.get('organize_by', 'unknown')}", file=sys.stderr)

        print(f"  Total links: {result.total_links}", file=sys.stderr)
        print(f"  Valid: {result.valid_links}", file=sys.stderr)
        print(f"  Broken: {result.broken_links}", file=sys.stderr)

        if result.broken_paths:
            print("\nBroken links:", file=sys.stderr)
            for path in result.broken_paths[:5]:
                print(f"  - {path}", file=sys.stderr)
            if len(result.broken_paths) > 5:
                print(f"  ... and {len(result.broken_paths) - 5} more", file=sys.stderr)


def _status_json(service: LinkService, tree_path: Path, manifest: Optional[dict]):
    """JSONL output for status."""
    list(service.get_tree_status(tree_path))

    result = service.last_refresh_result
    if result:
        output = {
            'path': str(tree_path),
            'total_links': result.total_links,
            'valid_links': result.valid_links,
            'broken_links': result.broken_links,
            'broken_paths': result.broken_paths,
        }
        if manifest:
            output['manifest'] = manifest
        print(json.dumps(output), flush=True)


def _status_pretty(service: LinkService, tree_path: Path, manifest: Optional[dict]):
    """Rich formatted output for status."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.panel import Panel

    console = Console()

    console.print(f"\n[bold]Link Tree Status:[/bold] {tree_path}\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning...", total=None)

        for message in service.get_tree_status(tree_path):
            progress.update(task, description=message)

    result = service.last_refresh_result
    if not result:
        console.print("[red]Failed to get status[/red]")
        sys.exit(1)

    # Info panel
    if manifest:
        info_lines = [
            f"[bold]Created:[/bold] {manifest.get('created_at', 'unknown')}",
            f"[bold]Organize by:[/bold] {manifest.get('organize_by', 'unknown')}",
            f"[bold]Original repos:[/bold] {manifest.get('repos_count', 'unknown')}",
            f"[bold]Version:[/bold] {manifest.get('repoindex_version', 'unknown')}",
        ]
        console.print(Panel('\n'.join(info_lines), title="Tree Info"))

    # Status table
    table = Table(title="Link Status", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total links", str(result.total_links))
    table.add_row("Valid links", f"[green]{result.valid_links}[/green]")

    if result.broken_links > 0:
        table.add_row("Broken links", f"[red]{result.broken_links}[/red]")
    else:
        table.add_row("Broken links", "[green]0[/green]")

    console.print(table)

    if result.broken_links > 0:
        console.print("\n[yellow]Broken links:[/yellow]")
        for path in result.broken_paths[:5]:
            console.print(f"  [red]✗[/red] {path}")
        if len(result.broken_paths) > 5:
            console.print(f"  [dim]... and {len(result.broken_paths) - 5} more[/dim]")
        console.print(f"\n[dim]Run 'repoindex link refresh {tree_path} --prune' to remove[/dim]")
    else:
        console.print(f"\n[bold green]✓[/bold green] All {result.total_links} links are valid")
