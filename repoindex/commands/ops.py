"""
Operations command group for repoindex.

Provides collection-level write operations:
- git push/pull across multiple repos
- Boilerplate file generation (codemeta, license, gitignore, code of conduct, contributing)
"""

import json
import sys
from pathlib import Path
from typing import Optional

import click

from ..config import load_config
from ..database import Database, QueryCompileError, compile_query
from ..services.boilerplate_service import (
    GITIGNORE_TEMPLATES,
    LICENSES,
    AuthorInfo,
    BoilerplateService,
    GenerationOptions,
)
from ..services.git_ops_service import GitOpsOptions, GitOpsService
from ..services.github_ops_service import GitHubOpsOptions, GitHubOpsService
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


def _get_repos_from_query(config, query_string: str, debug: bool = False, **query_flags):
    """Get repos matching query and flags."""
    # Extract flags with defaults
    dirty = query_flags.get('dirty', False)
    clean = query_flags.get('clean', False)
    language = query_flags.get('language', None)
    recent = query_flags.get('recent', None)
    starred = query_flags.get('starred', False)
    tag = query_flags.get('tag', ())
    no_license = query_flags.get('no_license', False)
    no_readme = query_flags.get('no_readme', False)
    has_citation = query_flags.get('has_citation', False)
    has_doi = query_flags.get('has_doi', False)
    archived = query_flags.get('archived', False)
    public = query_flags.get('public', False)
    private = query_flags.get('private', False)
    fork = query_flags.get('fork', False)
    no_fork = query_flags.get('no_fork', False)

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


def _resolve_repos(output_json, pretty, debug, query_string, **query_flags):
    """Load config, resolve repos from query, handle errors.

    Returns (config, repos) on success, None on failure (after printing error).
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    try:
        repos = _get_repos_from_query(config, query_string, debug=debug, **query_flags)
    except QueryCompileError as e:
        _handle_query_error(e, query_string, output_json)
        return None

    if not repos:
        _no_repos_message(output_json, pretty)
        return None

    return config, repos


# ============================================================================
# Audit command
# ============================================================================

@ops_cmd.command('audit')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def ops_audit_handler(
    query_string: str,
    output_json: bool,
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
    Audit metadata completeness for repositories.

    Checks each repository for common metadata items: README, LICENSE,
    CI, citation, DOI, GitHub description, topics, pages, pyproject.toml,
    and mkdocs.yml. Reports what's missing per-repo and collection-wide.

    \b
    Examples:
        # Audit all repos
        repoindex ops audit --pretty
        # Audit Python repos only
        repoindex ops audit --language python --pretty
        # Machine-readable output
        repoindex ops audit --json
    """
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    # Run audit checks
    checks = [
        ('has_readme', 'README', lambda r: bool(r.get('has_readme'))),
        ('has_license', 'LICENSE', lambda r: bool(r.get('has_license'))),
        ('has_ci', 'CI', lambda r: bool(r.get('has_ci'))),
        ('has_citation', 'Citation file', lambda r: bool(r.get('has_citation'))),
        ('has_doi', 'DOI', lambda r: bool(r.get('citation_doi'))),
        ('has_description', 'GitHub description', lambda r: bool(r.get('github_description'))),
        ('has_topics', 'GitHub topics', lambda r: bool(r.get('github_topics') and r.get('github_topics') != '[]')),
        ('has_pages', 'GitHub Pages', lambda r: bool(r.get('github_has_pages'))),
        ('has_pyproject', 'pyproject.toml', lambda r: Path(r.get('path', '')).joinpath('pyproject.toml').exists() if r.get('path') else False),
        ('has_mkdocs', 'mkdocs.yml', lambda r: Path(r.get('path', '')).joinpath('mkdocs.yml').exists() if r.get('path') else False),
    ]

    audit_results = []
    summary_counts = {check_id: 0 for check_id, _, _ in checks}

    for repo in repos:
        repo_audit = {
            'name': repo.get('name', ''),
            'path': repo.get('path', ''),
            'missing': [],
            'present': [],
        }
        for check_id, _label, check_fn in checks:
            if check_fn(repo):
                repo_audit['present'].append(check_id)
                summary_counts[check_id] += 1
            else:
                repo_audit['missing'].append(check_id)
        repo_audit['score'] = len(repo_audit['present'])
        repo_audit['total'] = len(checks)
        audit_results.append(repo_audit)

    total_repos = len(repos)

    if output_json:
        for result in audit_results:
            print(json.dumps(result), flush=True)
        summary = {
            'type': 'summary',
            'total_repos': total_repos,
            'checks': {check_id: {'label': label, 'count': summary_counts[check_id], 'missing': total_repos - summary_counts[check_id]}
                       for check_id, label, _ in checks},
        }
        print(json.dumps(summary), flush=True)

    elif pretty:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        console.print("\n[bold]Metadata Audit[/bold]")
        console.print(f"[bold]Repositories:[/bold] {total_repos}\n")

        # Repos missing items (sorted by score ascending = worst first)
        incomplete = [r for r in audit_results if r['missing']]
        incomplete.sort(key=lambda r: r['score'])

        if incomplete:
            table = Table(title="Repos with Missing Metadata", show_header=True, show_lines=False)
            table.add_column("Repo", style="cyan")
            table.add_column("Score", justify="center")
            table.add_column("Missing", style="yellow")

            for r in incomplete:
                missing_labels = []
                for check_id, label, _ in checks:
                    if check_id in r['missing']:
                        missing_labels.append(label)
                score_str = f"{r['score']}/{r['total']}"
                table.add_row(r['name'], score_str, ', '.join(missing_labels))

            console.print(table)
        else:
            console.print("[green]All repositories have complete metadata![/green]")

        # Summary table
        console.print()
        summary_table = Table(title="Collection Summary", show_header=True)
        summary_table.add_column("Check", style="cyan")
        summary_table.add_column("Present", justify="right")
        summary_table.add_column("Missing", justify="right")
        summary_table.add_column("Coverage", justify="right")

        for check_id, label, _ in checks:
            count = summary_counts[check_id]
            missing = total_repos - count
            pct = (count / total_repos * 100) if total_repos > 0 else 0
            if pct == 100:
                pct_str = f"[green]{pct:.0f}%[/green]"
            elif pct >= 80:
                pct_str = f"[yellow]{pct:.0f}%[/yellow]"
            else:
                pct_str = f"[red]{pct:.0f}%[/red]"
            summary_table.add_row(
                label,
                f"[green]{count}[/green]",
                f"[red]{missing}[/red]" if missing > 0 else "[dim]0[/dim]",
                pct_str,
            )

        console.print(summary_table)

    else:
        # Simple text output
        for r in audit_results:
            if r['missing']:
                missing_labels = []
                for check_id, label, _ in checks:
                    if check_id in r['missing']:
                        missing_labels.append(label)
                print(f"{r['name']}: missing {', '.join(missing_labels)}", file=sys.stderr)

        print(f"\nSummary ({total_repos} repos):", file=sys.stderr)
        for check_id, label, _ in checks:
            count = summary_counts[check_id]
            missing = total_repos - count
            if missing > 0:
                print(f"  {label}: {count}/{total_repos} ({missing} missing)", file=sys.stderr)
            else:
                print(f"  {label}: {count}/{total_repos}", file=sys.stderr)


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
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

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
    progress_iter = service.push_repos(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options, "Git Push", len(repos),
                           extra_headers=[("Remote", options.remote)],
                           success_msg="Pushed {count} repositories")
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Push complete")



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
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    # Confirmation prompt
    if not dry_run and not yes:
        if not click.confirm(f"Pull {len(repos)} repositories from {remote}?"):
            print("Aborted.", file=sys.stderr)
            return

    options = GitOpsOptions(remote=remote, dry_run=dry_run)
    service = GitOpsService(config=config)

    progress_iter = service.pull_repos(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options, "Git Pull", len(repos),
                           extra_headers=[("Remote", options.remote)],
                           success_msg="Pulled {count} repositories")
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Pull complete")


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
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

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
        print("\nSummary:", file=sys.stderr)
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

    console.print("\n[bold]Git Status[/bold]")
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
# GitHub operations subgroup
# ============================================================================

@ops_cmd.group('github')
def github_cmd():
    """GitHub write operations across multiple repositories.

    Set topics, descriptions, and other GitHub settings.
    Requires the gh CLI to be installed and authenticated.

    \b
    Examples:
        # Sync pyproject.toml keywords as GitHub topics
        repoindex ops github set-topics --from-pyproject --language python --dry-run
        # Set specific topics
        repoindex ops github set-topics --topics python,cli,tools --dry-run
        # Set description from pyproject.toml
        repoindex ops github set-description --from-pyproject --dry-run
    """
    pass


@github_cmd.command('set-topics')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without setting topics')
@click.option('--topics', help='Comma-separated list of topics to set')
@click.option('--from-pyproject', is_flag=True, help='Read keywords from pyproject.toml')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def github_set_topics_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    topics: Optional[str],
    from_pyproject: bool,
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
    Set GitHub topics for repositories.

    Sets repository topics on GitHub. Topics can come from an explicit
    list or be synced from pyproject.toml keywords.

    \b
    Examples:
        # Sync from pyproject.toml keywords
        repoindex ops github set-topics --from-pyproject --language python --dry-run
        # Set specific topics for all repos
        repoindex ops github set-topics --topics python,cli,tools --dry-run
        # Combine: pyproject keywords + extra topics
        repoindex ops github set-topics --from-pyproject --topics extra-topic --dry-run
    """
    if not topics and not from_pyproject:
        click.echo("Error: specify --topics or --from-pyproject", err=True)
        return

    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    topic_list = [t.strip() for t in topics.split(',')] if topics else None
    options = GitHubOpsOptions(dry_run=dry_run)
    service = GitHubOpsService(config=config)

    progress_iter = service.set_topics(repos, options, topics=topic_list, from_pyproject=from_pyproject)
    if pretty:
        _ops_output_pretty(service, progress_iter, options, "Set GitHub Topics", len(repos))
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options)


@github_cmd.command('set-description')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without setting description')
@click.option('--text', help='Description text to set')
@click.option('--from-pyproject', is_flag=True, help='Read description from pyproject.toml')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def github_set_description_handler(
    query_string: str,
    output_json: bool,
    pretty: bool,
    dry_run: bool,
    text: Optional[str],
    from_pyproject: bool,
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
    Set GitHub description for repositories.

    Sets the repository description on GitHub. Description can be
    explicit text or synced from pyproject.toml.

    \b
    Examples:
        # Sync from pyproject.toml
        repoindex ops github set-description --from-pyproject --language python --dry-run
        # Set explicit description
        repoindex ops github set-description --text "My project" "name == 'my-repo'" --dry-run
    """
    if not text and not from_pyproject:
        click.echo("Error: specify --text or --from-pyproject", err=True)
        return

    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    options = GitHubOpsOptions(dry_run=dry_run)
    service = GitHubOpsService(config=config)

    progress_iter = service.set_description(repos, options, text=text, from_pyproject=from_pyproject)
    if pretty:
        _ops_output_pretty(service, progress_iter, options, "Set GitHub Description", len(repos))
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options)



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
        print(json.dumps({'warning': 'No repositories found matching query'}), file=sys.stderr)
    elif pretty:
        from rich.console import Console
        Console().print("[yellow]No repositories found matching query.[/yellow]")
    else:
        print("No repositories found matching query.", file=sys.stderr)


# ============================================================================
# Unified output helpers (for operations that produce OperationSummary)
# ============================================================================

def _ops_output_simple(service, progress_iter, options, op_label="Complete",
                       success_label="Successful"):
    """Simple text output for any operation that yields progress and produces OperationSummary."""
    mode = "[dry run] " if options.dry_run else ""

    for progress in progress_iter:
        print(f"{mode}{progress}", file=sys.stderr)

    result = service.last_result
    if result:
        print(f"\n{mode}{op_label}:", file=sys.stderr)
        print(f"  {success_label}: {result.successful}", file=sys.stderr)
        if result.skipped > 0:
            print(f"  Skipped: {result.skipped}", file=sys.stderr)
        if result.failed > 0:
            print(f"  Failed: {result.failed}", file=sys.stderr)
            for error in result.errors:
                print(f"    - {error}", file=sys.stderr)
            sys.exit(1)


def _ops_output_json(service, progress_iter, options):
    """JSONL output for any operation that yields progress and produces OperationSummary."""
    for progress in progress_iter:
        print(json.dumps({'progress': progress}), flush=True)

    result = service.last_result
    if result:
        for detail in result.details:
            print(json.dumps(detail.to_dict()), flush=True)
        print(json.dumps(result.to_dict()), flush=True)


def _ops_output_pretty(service, progress_iter, options, title, repo_count,
                       success_label="Successful",
                       success_msg=None,
                       extra_headers=None):
    """Rich formatted output for any operation that yields progress and produces OperationSummary.

    Args:
        service: Service with .last_result attribute
        progress_iter: Iterator yielding progress message strings
        options: Options object with .dry_run attribute
        title: Display title (e.g. "Git Push", "Generate codemeta.json")
        repo_count: Number of repos being processed
        success_label: Label for the success metric row (default "Successful")
        success_msg: Success message template with {count} placeholder, shown on completion
        extra_headers: List of (label, value) tuples for header section
    """
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
        task = progress.add_task("Processing...", total=None)

        for message in progress_iter:
            progress.update(task, description=message)

    result = service.last_result
    if not result:
        console.print(f"[red]{title} failed - no result[/red]")
        sys.exit(1)

    # Summary table
    table = Table(title=f"{mode}{title} Summary", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row(success_label, f"[green]{result.successful}[/green]")
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

    if not options.dry_run and result.successful > 0 and success_msg:
        console.print(f"\n[bold green]✓[/bold green] {success_msg.format(count=result.successful)}")


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
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

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

    progress_iter = service.generate_codemeta(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate codemeta.json", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers or None)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")


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
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

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

    progress_iter = service.generate_license(repos, options, license_type)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate LICENSE", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")


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
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
    )

    service = BoilerplateService(config=config)
    file_label = ".gitignore files"
    extra_headers = [("Language", language_template)]

    progress_iter = service.generate_gitignore(repos, options, language_template)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate .gitignore", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")


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
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

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

    progress_iter = service.generate_code_of_conduct(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate CODE_OF_CONDUCT.md", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers or None)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")


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
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
    )

    service = BoilerplateService(config=config)
    file_label = "CONTRIBUTING.md files"

    progress_iter = service.generate_contributing(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate CONTRIBUTING.md", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")


# ============================================================================
# Generate citation command
# ============================================================================

@generate_cmd.command('citation')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing CITATION.cff files')
@click.option('--author', help='Author name (overrides config)')
@click.option('--orcid', help='ORCID identifier (overrides config)')
@click.option('--email', help='Author email (overrides config)')
@click.option('--affiliation', help='Author affiliation (overrides config)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_citation_handler(
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
    Generate CITATION.cff files for repositories.

    Creates CITATION.cff metadata files following the CFF 1.2.0 standard.
    Reads pyproject.toml for project metadata (name, version, description,
    license, keywords). Uses author information from config or CLI options.

    When regenerating with --force, preserves any existing DOI.

    \b
    Examples:
        # Generate for Python repos
        repoindex ops generate citation --language python --dry-run
        # Generate with author info
        repoindex ops generate citation --author "Jane Doe" --orcid "0000-0001-2345-6789" --dry-run
        # Force overwrite existing files (preserves DOI)
        repoindex ops generate citation --force --dry-run
    """
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    author_info = _build_author_info(config, author, orcid, email, affiliation)

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
        author=author_info,
    )

    service = BoilerplateService(config=config)
    file_label = "CITATION.cff files"
    extra_headers = []
    if options.author:
        extra_headers.append(("Author", options.author.name))
    if options.author and options.author.orcid:
        extra_headers.append(("ORCID", options.author.orcid))

    progress_iter = service.generate_citation_cff(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate CITATION.cff", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers or None)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")


# ============================================================================
# Generate zenodo command
# ============================================================================

@generate_cmd.command('zenodo')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing .zenodo.json files')
@click.option('--author', help='Author name (overrides config)')
@click.option('--orcid', help='ORCID identifier (overrides config)')
@click.option('--email', help='Author email (overrides config)')
@click.option('--affiliation', help='Author affiliation (overrides config)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_zenodo_handler(
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
    Generate .zenodo.json files for repositories.

    Creates .zenodo.json metadata files for Zenodo DOI minting.
    Reads pyproject.toml for project metadata (name, version, description,
    license, keywords). Uses author information from config or CLI options.

    When regenerating with --force, preserves any existing DOI.

    \b
    Examples:
        # Generate for Python repos
        repoindex ops generate zenodo --language python --dry-run
        # Generate with author info
        repoindex ops generate zenodo --author "Jane Doe" --orcid "0000-0001-2345-6789" --dry-run
        # Force overwrite existing files (preserves DOI)
        repoindex ops generate zenodo --force --dry-run
    """
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    author_info = _build_author_info(config, author, orcid, email, affiliation)

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
        author=author_info,
    )

    service = BoilerplateService(config=config)
    file_label = ".zenodo.json files"
    extra_headers = []
    if options.author:
        extra_headers.append(("Author", options.author.name))
    if options.author and options.author.orcid:
        extra_headers.append(("ORCID", options.author.orcid))

    progress_iter = service.generate_zenodo_json(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate .zenodo.json", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers or None)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")


# ============================================================================
# Generate mkdocs command
# ============================================================================

@generate_cmd.command('mkdocs')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing mkdocs.yml files')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_mkdocs_handler(
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
    Generate mkdocs.yml files for repositories.

    Scaffolds mkdocs.yml with Material theme, dark/light toggle,
    standard markdown extensions, and auto-detected nav from docs/.

    \b
    Examples:
        # Generate for Python repos
        repoindex ops generate mkdocs --language python --dry-run
        # Force overwrite existing files
        repoindex ops generate mkdocs --force --dry-run
    """
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
    )

    service = BoilerplateService(config=config)
    file_label = "mkdocs.yml files"

    progress_iter = service.generate_mkdocs(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate mkdocs.yml", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")


# ============================================================================
# Generate gh-pages command
# ============================================================================

@generate_cmd.command('gh-pages')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--pretty', is_flag=True, help='Display with rich formatting')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing workflow files')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_gh_pages_handler(
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
    Generate GitHub Pages deployment workflow for repositories.

    Creates .github/workflows/deploy-docs.yml for deploying
    MkDocs sites to GitHub Pages via GitHub Actions.

    \b
    Examples:
        # Generate for Python repos
        repoindex ops generate gh-pages --language python --dry-run
        # Force overwrite existing workflow
        repoindex ops generate gh-pages --force --dry-run
    """
    result = _resolve_repos(
        output_json, pretty, debug, query_string,
        dirty=dirty, clean=clean, language=language, recent=recent,
        starred=starred, tag=tag, no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi, archived=archived,
        public=public, private=private, fork=fork, no_fork=no_fork,
    )
    if result is None:
        return
    config, repos = result

    options = GenerationOptions(
        dry_run=dry_run,
        force=force,
    )

    service = BoilerplateService(config=config)
    file_label = "deploy-docs.yml files"

    progress_iter = service.generate_gh_pages_workflow(repos, options)
    if pretty:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate deploy-docs.yml", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label)
    elif output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_simple(service, progress_iter, options, "Generation complete",
                           success_label="Generated")
