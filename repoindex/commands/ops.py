"""
Operations command group for repoindex.

Provides collection-level write operations:
- git push/pull across multiple repos
- Boilerplate file generation (codemeta, license, gitignore, code of conduct, contributing)
"""

import click
import json
import sys
from pathlib import Path
from typing import Optional

from ..config import load_config
from ..database import Database, compile_query, QueryCompileError
from ..services.git_ops_service import GitOpsService, GitOpsOptions
from ..services.boilerplate_service import (
    BoilerplateService,
    GenerationOptions,
    AuthorInfo,
    LICENSES,
    GITIGNORE_TEMPLATES,
)
from .query import _build_query_from_flags


# ============================================================================
# Main ops command group
# ============================================================================

@click.group('ops')
def ops_cmd():
    """Collection-level operations on repositories.

    Operations are write actions that modify repositories or generate files.
    Use with caution - always preview with --dry-run first.

    \b
    Examples:
        # Push all repos with unpushed commits
        repoindex ops git push --dry-run
        # Pull updates for dirty repos
        repoindex ops git pull --dirty
        # Generate codemeta for Python repos
        repoindex ops generate codemeta --language python
        # Generate .gitignore files
        repoindex ops generate gitignore --lang python
        # Multi-repo git status
        repoindex ops git status --dirty
    """
    pass


# ============================================================================
# Git operations subgroup
# ============================================================================

@ops_cmd.group('git')
def git_cmd():
    """Git operations across multiple repositories.

    Push, pull, and check status across your repository collection.
    Supports the same query filters as the query command.

    \b
    Examples:
        # Push all repos with unpushed commits
        repoindex ops git push --dry-run
        # Pull updates for Python repos
        repoindex ops git pull --language python
        # Multi-repo status
        repoindex ops git status
        # Status of dirty repos only
        repoindex ops git status --dirty
    """
    pass


# Shared query flags decorator
def query_options(f):
    """Decorator to add query convenience flags."""
    f = click.option('--dirty', is_flag=True, help='Repos with uncommitted changes')(f)
    f = click.option('--clean', is_flag=True, help='Repos with no uncommitted changes')(f)
    f = click.option('--language', '-l', help='Filter by language (e.g., python, js, rust)')(f)
    f = click.option('--recent', '-r', help='Repos with recent commits (e.g., 7d, 30d)')(f)
    f = click.option('--starred', is_flag=True, help='Repos with stars')(f)
    f = click.option('--tag', '-t', multiple=True, help='Filter by tag (supports wildcards)')(f)
    f = click.option('--no-license', is_flag=True, help='Repos without a license')(f)
    f = click.option('--no-readme', is_flag=True, help='Repos without a README')(f)
    f = click.option('--has-citation', is_flag=True, help='Repos with citation files')(f)
    f = click.option('--has-doi', is_flag=True, help='Repos with DOI in citation metadata')(f)
    f = click.option('--archived', is_flag=True, help='Archived repos only')(f)
    f = click.option('--public', is_flag=True, help='Public repos only')(f)
    f = click.option('--private', is_flag=True, help='Private repos only')(f)
    f = click.option('--fork', is_flag=True, help='Forked repos only')(f)
    f = click.option('--no-fork', is_flag=True, help='Non-forked repos only')(f)
    return f


def _get_repos_from_query(
    config,
    query_string: str,
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
    debug: bool = False,
):
    """Get repos matching query and flags."""
    # Build query from flags
    has_flags = any([dirty, clean, language, recent, starred, tag, no_license, no_readme,
                     has_citation, has_doi, archived, public, private, fork, no_fork])
    if has_flags:
        query_string = _build_query_from_flags(
            query_string if query_string else None,
            dirty, clean, language, recent, starred, list(tag),
            no_license, no_readme, has_citation, has_doi, archived, public, private, fork, no_fork
        )

    # If no query and no flags, match all repos
    if not query_string:
        query_string = "1 == 1"

    # Query repos from database
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

    # Post-filter excluded directories from config
    exclude_dirs = config.get('exclude_directories', [])
    if exclude_dirs:
        expanded = [str(Path(d).expanduser()).rstrip('/') for d in exclude_dirs]
        repos = [r for r in repos if not any(r['path'].startswith(e) for e in expanded)]

    return repos


# ============================================================================
# Git push command
# ============================================================================

@git_cmd.command('push')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without pushing')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--parallel', '-p', type=int, default=1, help='Number of parallel operations')
@click.option('--remote', default='origin', help='Remote to push to (default: origin)')
@click.option('--set-upstream', '-u', is_flag=True, help='Set upstream tracking')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def git_push_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    yes: bool,
    parallel: int,
    remote: str,
    set_upstream: bool,
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
    Push commits to remote for repositories with unpushed changes.

    Only pushes repos that have commits ahead of the remote.
    Use --dry-run to preview what would be pushed.

    \b
    Examples:
        # Preview what would be pushed
        repoindex ops git push --dry-run
        # Push all repos with unpushed commits
        repoindex ops git push --yes
        # Push only Python repos
        repoindex ops git push --language python --dry-run
        # Push repos with specific tag
        repoindex ops git push --tag "work/*" --yes
        # Push with DSL query
        repoindex ops git push "language == 'Python'" --dry-run
        # Parallel push (faster for many repos)
        repoindex ops git push --parallel 4 --yes
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(
            config, query_string,
            dirty, clean, language, recent, starred, tag,
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork, debug
        )
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return

    if not repos:
        _no_repos_message(output_json, pretty)
        return

    # Set up service
    options = GitOpsOptions(
        remote=remote,
        dry_run=dry_run,
        parallel=parallel,
        set_upstream=set_upstream,
    )
    service = GitOpsService(config=config)

    # Confirmation prompt (unless --yes or --dry-run)
    if not dry_run and not yes:
        # Count repos with commits to push
        pushable = service.get_repos_needing_push(repos, remote)
        if not pushable:
            if pretty:
                from rich.console import Console
                Console().print("[yellow]No repositories have unpushed commits.[/yellow]")
            else:
                print("No repositories have unpushed commits.", file=sys.stderr)
            return

        if not click.confirm(f"Push {len(pushable)} repositories to {remote}?"):
            print("Aborted.", file=sys.stderr)
            return

    # Execute
    if pretty:
        _git_push_pretty(service, repos, options)
    elif output_json:
        _git_push_json(service, repos, options)
    else:
        _git_push_simple(service, repos, options)


def _git_push_simple(service: GitOpsService, repos: list, options: GitOpsOptions):
    """Simple text output for git push."""
    mode = "[dry run] " if options.dry_run else ""

    for progress in service.push_repos(repos, options):
        print(f"{mode}{progress}", file=sys.stderr)

    result = service.last_result
    if result:
        print(f"\n{mode}Push complete:", file=sys.stderr)
        print(f"  Successful: {result.successful}", file=sys.stderr)
        if result.skipped > 0:
            print(f"  Skipped: {result.skipped}", file=sys.stderr)
        if result.failed > 0:
            print(f"  Failed: {result.failed}", file=sys.stderr)
            for error in result.errors:
                print(f"    - {error}", file=sys.stderr)
            sys.exit(1)


def _git_push_json(service: GitOpsService, repos: list, options: GitOpsOptions):
    """JSONL output for git push."""
    for progress in service.push_repos(repos, options):
        print(json.dumps({'progress': progress}), flush=True)

    result = service.last_result
    if result:
        for detail in result.details:
            print(json.dumps(detail.to_dict()), flush=True)
        print(json.dumps(result.to_dict()), flush=True)


def _git_push_pretty(service: GitOpsService, repos: list, options: GitOpsOptions):
    """Rich formatted output for git push."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    console = Console()
    mode = "[bold yellow]DRY RUN[/bold yellow] " if options.dry_run else ""

    console.print(f"\n{mode}[bold]Git Push[/bold]")
    console.print(f"[bold]Remote:[/bold] {options.remote}")
    console.print(f"[bold]Repositories:[/bold] {len(repos)}")
    console.print()

    messages = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Pushing...", total=None)

        for message in service.push_repos(repos, options):
            progress.update(task, description=message)
            messages.append(message)

    result = service.last_result
    if not result:
        console.print("[red]Push failed - no result[/red]")
        sys.exit(1)

    # Summary table
    table = Table(title=f"{mode}Push Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Successful", f"[green]{result.successful}[/green]")
    if result.skipped > 0:
        table.add_row("Skipped", f"[yellow]{result.skipped}[/yellow]")
    if result.failed > 0:
        table.add_row("Failed", f"[red]{result.failed}[/red]")

    console.print(table)

    if result.errors:
        console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")
        sys.exit(1)

    if not options.dry_run and result.successful > 0:
        console.print(f"\n[bold green]✓[/bold green] Pushed {result.successful} repositories")


# ============================================================================
# Git pull command
# ============================================================================

@git_cmd.command('pull')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without pulling (fetches first)')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--remote', default='origin', help='Remote to pull from (default: origin)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def git_pull_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    yes: bool,
    remote: str,
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
    Pull updates from remote for repositories.

    Use --dry-run to preview what would be pulled (fetches to check).

    \b
    Examples:
        # Preview what would be pulled
        repoindex ops git pull --dry-run
        # Pull all repos
        repoindex ops git pull --yes
        # Pull only clean repos (no uncommitted changes)
        repoindex ops git pull --clean --yes
        # Pull Python repos
        repoindex ops git pull --language python --yes
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(
            config, query_string,
            dirty, clean, language, recent, starred, tag,
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork, debug
        )
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return

    if not repos:
        _no_repos_message(output_json, pretty)
        return

    # Confirmation prompt
    if not dry_run and not yes:
        if not click.confirm(f"Pull {len(repos)} repositories from {remote}?"):
            print("Aborted.", file=sys.stderr)
            return

    options = GitOpsOptions(remote=remote, dry_run=dry_run)
    service = GitOpsService(config=config)

    if pretty:
        _git_pull_pretty(service, repos, options)
    elif output_json:
        _git_pull_json(service, repos, options)
    else:
        _git_pull_simple(service, repos, options)


def _git_pull_simple(service: GitOpsService, repos: list, options: GitOpsOptions):
    """Simple text output for git pull."""
    mode = "[dry run] " if options.dry_run else ""

    for progress in service.pull_repos(repos, options):
        print(f"{mode}{progress}", file=sys.stderr)

    result = service.last_result
    if result:
        print(f"\n{mode}Pull complete:", file=sys.stderr)
        print(f"  Successful: {result.successful}", file=sys.stderr)
        if result.failed > 0:
            print(f"  Failed: {result.failed}", file=sys.stderr)
            sys.exit(1)


def _git_pull_json(service: GitOpsService, repos: list, options: GitOpsOptions):
    """JSONL output for git pull."""
    for progress in service.pull_repos(repos, options):
        print(json.dumps({'progress': progress}), flush=True)

    result = service.last_result
    if result:
        for detail in result.details:
            print(json.dumps(detail.to_dict()), flush=True)
        print(json.dumps(result.to_dict()), flush=True)


def _git_pull_pretty(service: GitOpsService, repos: list, options: GitOpsOptions):
    """Rich formatted output for git pull."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    console = Console()
    mode = "[bold yellow]DRY RUN[/bold yellow] " if options.dry_run else ""

    console.print(f"\n{mode}[bold]Git Pull[/bold]")
    console.print(f"[bold]Remote:[/bold] {options.remote}")
    console.print(f"[bold]Repositories:[/bold] {len(repos)}")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Pulling...", total=None)

        for message in service.pull_repos(repos, options):
            progress.update(task, description=message)

    result = service.last_result
    if not result:
        console.print("[red]Pull failed - no result[/red]")
        sys.exit(1)

    table = Table(title=f"{mode}Pull Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Successful", f"[green]{result.successful}[/green]")
    if result.failed > 0:
        table.add_row("Failed", f"[red]{result.failed}[/red]")

    console.print(table)

    if result.errors:
        console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")
        sys.exit(1)

    if not options.dry_run and result.successful > 0:
        console.print(f"\n[bold green]✓[/bold green] Pulled {result.successful} repositories")


# ============================================================================
# Git status command
# ============================================================================

@git_cmd.command('status')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--remote', default='origin', help='Remote to check against (default: origin)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def git_status_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    remote: str,
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
    Show git status for multiple repositories.

    Aggregates status across your repository collection.

    \b
    Examples:
        # Status of all repos
        repoindex ops git status
        # Status of dirty repos only
        repoindex ops git status --dirty
        # Status of Python repos
        repoindex ops git status --language python
        # JSONL output for scripting
        repoindex ops git status --json | jq 'select(.ahead > 0)'
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(
            config, query_string,
            dirty, clean, language, recent, starred, tag,
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork, debug
        )
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return

    if not repos:
        _no_repos_message(output_json, pretty)
        return

    options = GitOpsOptions(remote=remote)
    service = GitOpsService(config=config)

    if pretty:
        _git_status_pretty(service, repos, options)
    elif output_json:
        _git_status_json(service, repos, options)
    else:
        _git_status_simple(service, repos, options)


def _git_status_simple(service: GitOpsService, repos: list, options: GitOpsOptions):
    """Simple text output for git status."""
    for progress in service.status_repos(repos, options):
        print(progress, file=sys.stderr)

    status = service.last_status
    if status:
        print(f"\nSummary:", file=sys.stderr)
        print(f"  Total: {status.total}", file=sys.stderr)
        print(f"  Clean: {status.clean}", file=sys.stderr)
        print(f"  Dirty: {status.dirty}", file=sys.stderr)
        print(f"  Ahead (unpushed): {status.ahead}", file=sys.stderr)
        print(f"  Behind (need pull): {status.behind}", file=sys.stderr)
        if status.no_remote > 0:
            print(f"  No remote: {status.no_remote}", file=sys.stderr)


def _git_status_json(service: GitOpsService, repos: list, options: GitOpsOptions):
    """JSONL output for git status."""
    list(service.status_repos(repos, options))

    status = service.last_status
    if status:
        for detail in status.details:
            print(json.dumps(detail), flush=True)
        print(json.dumps(status.to_dict()), flush=True)


def _git_status_pretty(service: GitOpsService, repos: list, options: GitOpsOptions):
    """Rich formatted output for git status."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    console = Console()

    console.print(f"\n[bold]Git Status[/bold]")
    console.print(f"[bold]Repositories:[/bold] {len(repos)}")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Checking status...", total=None)

        for message in service.status_repos(repos, options):
            progress.update(task, description=message)

    status = service.last_status
    if not status:
        console.print("[red]Failed to get status[/red]")
        sys.exit(1)

    # Summary table
    table = Table(title="Status Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total", str(status.total))
    table.add_row("Clean", f"[green]{status.clean}[/green]")
    if status.dirty > 0:
        table.add_row("Dirty", f"[yellow]{status.dirty}[/yellow]")
    if status.ahead > 0:
        table.add_row("Ahead (unpushed)", f"[blue]{status.ahead}[/blue]")
    if status.behind > 0:
        table.add_row("Behind (need pull)", f"[magenta]{status.behind}[/magenta]")
    if status.no_remote > 0:
        table.add_row("No remote", f"[dim]{status.no_remote}[/dim]")

    console.print(table)

    # Show details for non-clean repos
    dirty_repos = [d for d in status.details if not d['clean'] or d['ahead'] > 0 or d['behind'] > 0]
    if dirty_repos:
        console.print(f"\n[bold]Repos needing attention ({len(dirty_repos)}):[/bold]")
        detail_table = Table(show_header=True, box=None)
        detail_table.add_column("Repo")
        detail_table.add_column("Branch")
        detail_table.add_column("Path", style="dim")
        detail_table.add_column("Status")

        home = str(Path.home())
        for d in dirty_repos:
            status_parts = []
            if not d['clean']:
                status_parts.append("[yellow]dirty[/yellow]")
            if d['ahead'] > 0:
                status_parts.append(f"[blue]↑{d['ahead']}[/blue]")
            if d['behind'] > 0:
                status_parts.append(f"[magenta]↓{d['behind']}[/magenta]")
            path = d.get('path', '')
            if path.startswith(home):
                path = '~' + path[len(home):]
            detail_table.add_row(d['name'], d['branch'], path, ' '.join(status_parts))

        console.print(detail_table)


# ============================================================================
# Helper functions
# ============================================================================

def _handle_query_error(e, query_string, output_json):
    """Handle query compilation error."""
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


def _no_repos_message(output_json, pretty):
    """Show message when no repos match."""
    if output_json:
        print(json.dumps({'warning': 'No repositories found matching query'}))
    elif pretty:
        from rich.console import Console
        Console().print("[yellow]No repositories found matching query.[/yellow]")
    else:
        print("No repositories found matching query.", file=sys.stderr)


# ============================================================================
# Generate operations subgroup
# ============================================================================

@ops_cmd.group('generate')
def generate_cmd():
    """Generate boilerplate files for repositories.

    Creates codemeta.json, LICENSE, .gitignore, CODE_OF_CONDUCT.md,
    and CONTRIBUTING.md files. Uses author information from config.

    \b
    Examples:
        # Generate codemeta.json for Python repos
        repoindex ops generate codemeta --language python --dry-run
        # Generate MIT license for repos without license
        repoindex ops generate license --no-license --license mit --dry-run
        # Generate .gitignore for Python repos
        repoindex ops generate gitignore --lang python --dry-run
        # Generate CODE_OF_CONDUCT.md
        repoindex ops generate code-of-conduct --dry-run
        # Generate CONTRIBUTING.md
        repoindex ops generate contributing --dry-run
    """
    pass


# ============================================================================
# Generate codemeta command
# ============================================================================

@generate_cmd.command('codemeta')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing codemeta.json files')
@click.option('--author', help='Author name (overrides config)')
@click.option('--orcid', help='ORCID identifier (overrides config)')
@click.option('--email', help='Author email (overrides config)')
@click.option('--affiliation', help='Author affiliation (overrides config)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_codemeta_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    force: bool,
    author: Optional[str],
    orcid: Optional[str],
    email: Optional[str],
    affiliation: Optional[str],
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
    Generate codemeta.json files for repositories.

    Creates CodeMeta metadata files following the schema.org vocabulary.
    Useful for software discoverability and citation.

    \b
    Examples:
        # Generate for Python repos
        repoindex ops generate codemeta --language python --dry-run
        # Generate with author info
        repoindex ops generate codemeta --author "Jane Doe" --dry-run
        # Force overwrite existing files
        repoindex ops generate codemeta --force --dry-run
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(
            config, query_string,
            dirty, clean, language, recent, starred, tag,
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork, debug
        )
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return

    if not repos:
        _no_repos_message(output_json, pretty)
        return

    author_info = _build_author_info(config, author, orcid, email, affiliation)

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
        author=author_info,
    )

    service = BoilerplateService(config=config)
    file_label = "codemeta.json files"
    extra_headers = []
    if options.author:
        extra_headers.append(("Author", options.author.name))

    if pretty:
        _generate_pretty(
            service, service.generate_codemeta(repos, options), options,
            file_label, "Generate codemeta.json", len(repos),
            extra_headers=extra_headers or None,
        )
    elif output_json:
        _generate_json(service, service.generate_codemeta(repos, options), options, file_label)
    else:
        _generate_simple(service, service.generate_codemeta(repos, options), options, file_label)


# ============================================================================
# Generate license command
# ============================================================================

@generate_cmd.command('license')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing LICENSE files')
@click.option('--license', 'license_type', default='mit',
              type=click.Choice(['mit', 'apache-2.0', 'gpl-3.0', 'bsd-3-clause', 'mpl-2.0']),
              help='License type (default: mit)')
@click.option('--author', help='Author/copyright holder name (overrides config)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_license_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    force: bool,
    license_type: str,
    author: Optional[str],
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
    Generate LICENSE files for repositories.

    Creates LICENSE files with the specified license type.
    Supports: MIT, Apache-2.0, GPL-3.0, BSD-3-Clause, MPL-2.0.

    \b
    Examples:
        # Generate MIT license for repos without license
        repoindex ops generate license --no-license --dry-run
        # Generate Apache 2.0 license
        repoindex ops generate license --license apache-2.0 --no-license --dry-run
        # With custom author name
        repoindex ops generate license --author "My Company Inc." --dry-run
        # Force overwrite existing licenses
        repoindex ops generate license --force --license gpl-3.0 --dry-run
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(
            config, query_string,
            dirty, clean, language, recent, starred, tag,
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork, debug
        )
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return

    if not repos:
        _no_repos_message(output_json, pretty)
        return

    author_info = _build_author_info(config, author, None, None, None)

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
        author=author_info,
        license=license_type,
    )

    service = BoilerplateService(config=config)
    file_label = "LICENSE files"
    license_info = LICENSES.get(license_type, {'name': license_type})
    license_name = license_info.get('name', license_type)
    extra_headers = [("License", license_name)]
    if options.author:
        extra_headers.append(("Copyright holder", options.author.name))

    if pretty:
        _generate_pretty(
            service, service.generate_license(repos, options, license_type), options,
            file_label, "Generate LICENSE", len(repos),
            extra_headers=extra_headers,
        )
    elif output_json:
        _generate_json(service, service.generate_license(repos, options, license_type), options, file_label)
    else:
        _generate_simple(service, service.generate_license(repos, options, license_type), options, file_label)


# ============================================================================
# Generate helper functions
# ============================================================================

def _build_author_info(
    config: dict,
    author: Optional[str],
    orcid: Optional[str],
    email: Optional[str],
    affiliation: Optional[str]
) -> Optional[AuthorInfo]:
    """Build AuthorInfo from CLI options or config."""
    # Start with config defaults
    base_author = AuthorInfo.from_config(config)

    # Override with CLI options
    if author or orcid or email or affiliation:
        name = author or (base_author.name if base_author else '')
        if not name:
            return None

        # Parse name into parts
        given_names = None
        family_names = None
        if ' ' in name:
            parts = name.rsplit(' ', 1)
            given_names = parts[0]
            family_names = parts[1]

        return AuthorInfo(
            name=name,
            given_names=given_names,
            family_names=family_names,
            email=email or (base_author.email if base_author else None),
            orcid=orcid or (base_author.orcid if base_author else None),
            affiliation=affiliation or (base_author.affiliation if base_author else None),
        )

    return base_author


def _generate_simple(service: BoilerplateService, progress_iter, options: GenerationOptions, file_label: str):
    """Simple text output for any boilerplate generation."""
    mode = "[dry run] " if options.dry_run else ""

    for progress in progress_iter:
        print(f"{mode}{progress}", file=sys.stderr)

    result = service.last_result
    if result:
        print(f"\n{mode}Generation complete:", file=sys.stderr)
        print(f"  Generated: {result.successful}", file=sys.stderr)
        if result.skipped > 0:
            print(f"  Skipped: {result.skipped}", file=sys.stderr)
        if result.failed > 0:
            print(f"  Failed: {result.failed}", file=sys.stderr)
            sys.exit(1)


def _generate_json(service: BoilerplateService, progress_iter, options: GenerationOptions, file_label: str):
    """JSONL output for any boilerplate generation."""
    for progress in progress_iter:
        print(json.dumps({'progress': progress}), flush=True)

    result = service.last_result
    if result:
        for detail in result.details:
            print(json.dumps(detail.to_dict()), flush=True)
        print(json.dumps(result.to_dict()), flush=True)


def _generate_pretty(
    service: BoilerplateService,
    progress_iter,
    options: GenerationOptions,
    file_label: str,
    title: str,
    repo_count: int,
    extra_headers: Optional[list] = None,
):
    """Rich formatted output for any boilerplate generation."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    console = Console()
    mode = "[bold yellow]DRY RUN[/bold yellow] " if options.dry_run else ""

    console.print(f"\n{mode}[bold]{title}[/bold]")
    if extra_headers:
        for label, value in extra_headers:
            console.print(f"[bold]{label}:[/bold] {value}")
    console.print(f"[bold]Repositories:[/bold] {repo_count}")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating...", total=None)

        for message in progress_iter:
            progress.update(task, description=message)

    result = service.last_result
    if not result:
        console.print("[red]Generation failed - no result[/red]")
        sys.exit(1)

    table = Table(title=f"{mode}Generation Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Generated", f"[green]{result.successful}[/green]")
    if result.skipped > 0:
        table.add_row("Skipped", f"[yellow]{result.skipped}[/yellow]")
    if result.failed > 0:
        table.add_row("Failed", f"[red]{result.failed}[/red]")

    console.print(table)

    if result.errors:
        console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")
        sys.exit(1)

    if not options.dry_run and result.successful > 0:
        console.print(f"\n[bold green]✓[/bold green] Generated {result.successful} {file_label}")


# ============================================================================
# Generate gitignore command
# ============================================================================

@generate_cmd.command('gitignore')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing .gitignore files')
@click.option('--lang', 'language_template', default='python',
              type=click.Choice(list(GITIGNORE_TEMPLATES.keys())),
              help='Language template (default: python)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_gitignore_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    force: bool,
    language_template: str,
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
    Generate .gitignore files for repositories.

    Creates .gitignore files with standard patterns for the specified language.
    Supports: python, node, rust, go, cpp, java.

    \b
    Examples:
        # Generate Python .gitignore for all repos
        repoindex ops generate gitignore --dry-run
        # Generate Node.js .gitignore
        repoindex ops generate gitignore --lang node --dry-run
        # Generate for Python repos only
        repoindex ops generate gitignore --language python --dry-run
        # Force overwrite existing files
        repoindex ops generate gitignore --force --dry-run
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(
            config, query_string,
            dirty, clean, language, recent, starred, tag,
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork, debug
        )
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return

    if not repos:
        _no_repos_message(output_json, pretty)
        return

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
    )

    service = BoilerplateService(config=config)
    file_label = ".gitignore files"
    extra_headers = [("Language", language_template)]

    if pretty:
        _generate_pretty(
            service, service.generate_gitignore(repos, options, language_template), options,
            file_label, "Generate .gitignore", len(repos),
            extra_headers=extra_headers,
        )
    elif output_json:
        _generate_json(service, service.generate_gitignore(repos, options, language_template), options, file_label)
    else:
        _generate_simple(service, service.generate_gitignore(repos, options, language_template), options, file_label)


# ============================================================================
# Generate code-of-conduct command
# ============================================================================

@generate_cmd.command('code-of-conduct')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing CODE_OF_CONDUCT.md files')
@click.option('--email', help='Contact email (overrides config)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_code_of_conduct_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    force: bool,
    email: Optional[str],
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
    Generate CODE_OF_CONDUCT.md files for repositories.

    Creates CODE_OF_CONDUCT.md using Contributor Covenant v2.1.
    Uses contact email from config or command-line option.

    \b
    Examples:
        # Generate for all repos
        repoindex ops generate code-of-conduct --dry-run
        # With custom contact email
        repoindex ops generate code-of-conduct --email "contact@example.com" --dry-run
        # For Python repos only
        repoindex ops generate code-of-conduct --language python --dry-run
        # Force overwrite existing files
        repoindex ops generate code-of-conduct --force --dry-run
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(
            config, query_string,
            dirty, clean, language, recent, starred, tag,
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork, debug
        )
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return

    if not repos:
        _no_repos_message(output_json, pretty)
        return

    # Build author info with optional email override
    author_info = _build_author_info(config, None, None, email, None)

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
        author=author_info,
    )

    service = BoilerplateService(config=config)
    file_label = "CODE_OF_CONDUCT.md files"
    extra_headers = []
    if options.author and options.author.email:
        extra_headers.append(("Contact", options.author.email))

    if pretty:
        _generate_pretty(
            service, service.generate_code_of_conduct(repos, options), options,
            file_label, "Generate CODE_OF_CONDUCT.md", len(repos),
            extra_headers=extra_headers or None,
        )
    elif output_json:
        _generate_json(service, service.generate_code_of_conduct(repos, options), options, file_label)
    else:
        _generate_simple(service, service.generate_code_of_conduct(repos, options), options, file_label)


# ============================================================================
# Generate contributing command
# ============================================================================

@generate_cmd.command('contributing')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing CONTRIBUTING.md files')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_contributing_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    force: bool,
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
    Generate CONTRIBUTING.md files for repositories.

    Creates CONTRIBUTING.md with standard contribution guidelines.
    Uses repository name for project-specific content.

    \b
    Examples:
        # Generate for all repos
        repoindex ops generate contributing --dry-run
        # For Python repos only
        repoindex ops generate contributing --language python --dry-run
        # Force overwrite existing files
        repoindex ops generate contributing --force --dry-run
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(
            config, query_string,
            dirty, clean, language, recent, starred, tag,
            no_license, no_readme, has_citation, has_doi,
            archived, public, private, fork, no_fork, debug
        )
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return

    if not repos:
        _no_repos_message(output_json, pretty)
        return

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
    )

    service = BoilerplateService(config=config)
    file_label = "CONTRIBUTING.md files"

    if pretty:
        _generate_pretty(
            service, service.generate_contributing(repos, options), options,
            file_label, "Generate CONTRIBUTING.md", len(repos),
        )
    elif output_json:
        _generate_json(service, service.generate_contributing(repos, options), options, file_label)
    else:
        _generate_simple(service, service.generate_contributing(repos, options), options, file_label)
