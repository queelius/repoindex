"""
Operations command group for repoindex.

Provides collection-level write operations:
- git push/pull across multiple repos
- Boilerplate file generation (codemeta, license, gitignore, code of conduct, contributing)
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

import click

from . import TIMESPEC
from ..config import load_config
from ..database import Database
from ..services.boilerplate_service import (
    GITIGNORE_TEMPLATES,
    LICENSES,
    AuthorInfo,
    BoilerplateService,
    GenerationOptions,
)
from ..services.flag_query import fetch_repos_by_flags
from ..services.git_ops_service import GitOpsOptions, GitOpsService
from ..sources import GitForge, discover_sources

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
    Filter with --language/--tag/--dirty/--recent.

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
    f = click.option('--language', '-l', help='Filter by language (e.g., python, r, js)')(f)
    f = click.option('--dirty', is_flag=True, help='Repos with uncommitted changes')(f)
    f = click.option('--tag', '-t', multiple=True, help='Filter by tag (supports wildcards)')(f)
    f = click.option('--recent', '-r', type=TIMESPEC, help='Repos with recent commits (e.g., 7d, 30d)')(f)
    return f


def _get_repos_from_query(config, query_string: str = '', debug: bool = False, **query_flags):
    """Get repos matching the standard filter flags.

    The DSL was removed in v0.16. A non-empty ``query_string`` positional is
    almost always a stale DSL expression that, if silently ignored, would act
    on the WHOLE collection. Reject it loudly. For complex selection, use
    ``repoindex sql`` or the MCP ``run_sql`` tool.
    """
    if query_string:
        raise click.UsageError(
            "positional queries were removed in v0.16; use "
            "--language/--tag/--recent or `repoindex sql`"
        )
    return fetch_repos_by_flags(
        config,
        dirty=query_flags.get('dirty', False),
        language=query_flags.get('language', None),
        tag=query_flags.get('tag', ()),
        recent=query_flags.get('recent', None),
        debug=debug,
    )


def _resolve_repos(output_json, debug, query_string, **query_flags):
    """Load config, resolve repos from flag filters, handle empty result.

    Returns (config, repos) on success, None on failure (after printing error).
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    repos = _get_repos_from_query(config, query_string, debug=debug, **query_flags)

    if not repos:
        _no_repos_message(output_json)
        return None

    return config, repos


# ============================================================================
# Audit command
# ============================================================================

@ops_cmd.command('audit')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--category', 'audit_category',
              type=click.Choice(['essentials', 'development', 'discoverability', 'documentation']),
              help='Filter to one category')
@click.option('--severity', 'audit_severity',
              type=click.Choice(['critical', 'recommended', 'suggested']),
              help='Minimum severity threshold (critical=only critical, recommended=critical+recommended, suggested=all)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def ops_audit_handler(
    query_string: str,
    output_json: bool,
    audit_category: Optional[str],
    audit_severity: Optional[str],
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """
    Audit metadata completeness for repositories.

    Checks repositories across 4 categories (essentials, development,
    discoverability, documentation) with severity levels (critical,
    recommended, suggested). Reports scores, missing items, and
    actionable fix commands.

    \b
    Examples:
        # Audit all repos
        repoindex ops audit
        # Audit Python repos only
        repoindex ops audit --language python
        # Only essential checks
        repoindex ops audit --category essentials
        # Only critical issues
        repoindex ops audit --severity critical
        # Machine-readable output for Claude Code
        repoindex ops audit --json
    """
    from ..domain.audit import Category as AuditCategory, Severity as AuditSeverity
    from ..services.audit_service import AuditService, CHECKS, _CHECKS_BY_ID

    result = _resolve_repos(
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
    )
    if result is None:
        return
    config, repos = result

    # Convert string options to enums
    cat_enum = AuditCategory(audit_category) if audit_category else None
    sev_enum = AuditSeverity(audit_severity) if audit_severity else None

    service = AuditService(config=config)

    # Open DB for publications check
    with Database(config=config, read_only=True) as db:
        progress_iter = service.audit_repos(
            repos, db=db, category=cat_enum, severity=sev_enum
        )
        # Consume progress
        if output_json:
            _audit_output_json(service, progress_iter)
        else:
            _audit_output_pretty(service, progress_iter, _CHECKS_BY_ID)


def _audit_output_json(service, progress_iter):
    """JSONL output for audit: one line per repo, then summary."""
    # Consume progress (discard messages)
    for _ in progress_iter:
        pass

    results = service.last_results or []
    summary = service.last_summary

    for repo_result in results:
        print(json.dumps(repo_result.to_dict()), flush=True)

    if summary:
        print(json.dumps(summary.to_dict()), flush=True)


def _audit_output_simple(service, progress_iter, checks_by_id):
    """Simple text output for audit."""
    for progress in progress_iter:
        print(progress, file=sys.stderr)

    results = service.last_results or []
    summary = service.last_summary

    # Per-repo failures
    for r in results:
        failed = r.failed_checks
        if failed:
            labels = [checks_by_id[f.check_id].label for f in failed if f.check_id in checks_by_id]
            print(f"{r.name}: missing {', '.join(labels)}", file=sys.stderr)

    if summary:
        print(f"\nSummary ({summary.total_repos} repos, score {summary.overall_score:.0%}):", file=sys.stderr)
        for cat in ['essentials', 'development', 'discoverability', 'documentation']:
            cat_data = summary.categories.get(cat)
            if cat_data:
                pct = cat_data['score']
                print(f"  {cat}: {cat_data['passed']}/{cat_data['total']} ({pct:.0%})", file=sys.stderr)


def _audit_output_pretty(service, progress_iter, checks_by_id):
    """Rich formatted output for audit."""
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    console = Console()

    # Progress spinner
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Auditing...", total=None)
        for message in progress_iter:
            progress.update(task, description=message)

    results = service.last_results or []
    summary = service.last_summary
    if not summary:
        console.print("[red]Audit failed - no summary[/red]")
        return

    total_repos = summary.total_repos
    console.print(f"\n[bold]Metadata Audit[/bold]")
    console.print(f"[bold]Repositories:[/bold] {total_repos}")
    console.print(f"[bold]Overall Score:[/bold] {summary.overall_score:.0%}\n")

    # --- Repos needing attention (sorted worst-first) ---
    incomplete = [r for r in results if r.failed_checks]
    incomplete.sort(key=lambda r: r.score)

    if incomplete:
        table = Table(title="Repos Needing Attention", show_header=True, show_lines=False)
        table.add_column("Repo", style="cyan")
        table.add_column("Score", justify="center")
        table.add_column("Critical/Recommended Missing", style="yellow")

        from ..domain.audit import Severity as _Sev
        for r in incomplete:
            # Show critical and recommended failures
            important_fails = [
                f for f in r.failed_checks
                if f.check_id in checks_by_id
                and checks_by_id[f.check_id].severity in (_Sev.CRITICAL, _Sev.RECOMMENDED)
            ]
            if not important_fails:
                # Only suggested failures — still show but dim
                labels = [checks_by_id[f.check_id].label for f in r.failed_checks
                          if f.check_id in checks_by_id]
                label_str = f"[dim]{', '.join(labels)}[/dim]"
            else:
                labels = [checks_by_id[f.check_id].label for f in important_fails]
                label_str = ', '.join(labels)

            score_pct = f"{r.score:.0%}"
            if r.score < 0.5:
                score_str = f"[red]{score_pct}[/red]"
            elif r.score < 0.8:
                score_str = f"[yellow]{score_pct}[/yellow]"
            else:
                score_str = f"[green]{score_pct}[/green]"

            table.add_row(r.name, score_str, label_str)

        console.print(table)
    else:
        console.print("[green]All repositories have complete metadata![/green]")

    # --- Coverage by Category ---
    from ..domain.audit import Severity as AuditSeverity
    severity_icon = {
        AuditSeverity.CRITICAL: "[red]*[/red]",
        AuditSeverity.RECOMMENDED: "[yellow]+[/yellow]",
        AuditSeverity.SUGGESTED: "[dim]·[/dim]",
    }

    # Group checks by category
    from ..domain.audit import Category as AuditCategory
    for cat in AuditCategory:
        cat_checks = [c for c in checks_by_id.values() if c.category == cat]
        if not cat_checks:
            continue

        cat_data = summary.categories.get(cat.value)
        if not cat_data:
            continue

        cat_pct = cat_data['score']
        console.print()
        cat_table = Table(
            title=f"{cat.value.title()} ({cat_pct:.0%})",
            show_header=True,
        )
        cat_table.add_column("", width=1)  # severity icon
        cat_table.add_column("Check", style="cyan")
        cat_table.add_column("Present", justify="right")
        cat_table.add_column("Missing", justify="right")
        cat_table.add_column("Coverage", justify="right")

        for check in cat_checks:
            stats = summary.checks.get(check.id, {})
            passed = stats.get('passed', 0)
            missing = total_repos - passed
            pct = (passed / total_repos * 100) if total_repos > 0 else 0

            if pct == 100:
                pct_str = f"[green]{pct:.0f}%[/green]"
            elif pct >= 80:
                pct_str = f"[yellow]{pct:.0f}%[/yellow]"
            else:
                pct_str = f"[red]{pct:.0f}%[/red]"

            icon = severity_icon.get(check.severity, "")
            cat_table.add_row(
                icon,
                check.label,
                f"[green]{passed}[/green]",
                f"[red]{missing}[/red]" if missing > 0 else "[dim]0[/dim]",
                pct_str,
            )

        console.print(cat_table)

    # Overall score line
    console.print()
    if summary.overall_score >= 0.9:
        console.print(f"[bold green]Overall: {summary.overall_score:.0%}[/bold green]")
    elif summary.overall_score >= 0.7:
        console.print(f"[bold yellow]Overall: {summary.overall_score:.0%}[/bold yellow]")
    else:
        console.print(f"[bold red]Overall: {summary.overall_score:.0%}[/bold red]")


# ============================================================================
# Git push command
# ============================================================================

@git_cmd.command('push')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
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
    dry_run: bool,
    yes: bool,
    parallel: int,
    remote: str,
    set_upstream: bool,
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        # Parallel push (faster for many repos)
        repoindex ops git push --parallel 4 --yes
    """
    result = _resolve_repos(
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
            if not output_json:
                from rich.console import Console
                Console().print("[yellow]No repositories have unpushed commits.[/yellow]")
            return

        if not click.confirm(f"Push {len(pushable)} repositories to {remote}?"):
            print("Aborted.", file=sys.stderr)
            return

    # Execute
    progress_iter = service.push_repos(repos, options)
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options, "Git Push", len(repos),
                           extra_headers=[("Remote", options.remote)],
                           success_msg="Pushed {count} repositories")



# ============================================================================
# Git pull command
# ============================================================================

@git_cmd.command('pull')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--dry-run', is_flag=True, help='Preview without pulling (fetches first)')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--remote', default='origin', help='Remote to pull from (default: origin)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def git_pull_handler(
    query_string: str,
    output_json: bool,
    dry_run: bool,
    yes: bool,
    remote: str,
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        # Pull repos with a tag
        repoindex ops git pull --tag "work/*" --yes
        # Pull Python repos
        repoindex ops git pull --language python --yes
    """
    result = _resolve_repos(
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options, "Git Pull", len(repos),
                           extra_headers=[("Remote", options.remote)],
                           success_msg="Pulled {count} repositories")


# ============================================================================
# Git status command
# ============================================================================

@git_cmd.command('status')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--remote', default='origin', help='Remote to check against (default: origin)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def git_status_handler(
    query_string: str,
    output_json: bool,
    remote: str,
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
    )
    if result is None:
        return
    config, repos = result

    options = GitOpsOptions(remote=remote)
    service = GitOpsService(config=config)

    if output_json:
        _git_status_json(service, repos, options)
    else:
        _git_status_pretty(service, repos, options)


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

# ============================================================================
# Helper functions
# ============================================================================

def _no_repos_message(output_json):
    """Show message when no repos match."""
    if output_json:
        print(json.dumps({'warning': 'No repositories found matching query'}), file=sys.stderr)
    else:
        from rich.console import Console
        Console().print("[yellow]No repositories found matching query.[/yellow]")


def _emit_error(msg: str, output_json: bool, exit_code: int = 2) -> None:
    """Print an error message in the right format and exit.

    JSONL output goes to stderr (consistent with the project's error
    contract); pretty output uses ``click.echo``. Never returns.
    """
    if output_json:
        print(json.dumps({"error": msg}), file=sys.stderr, flush=True)
    else:
        click.echo(f"Error: {msg}", err=True)
    sys.exit(exit_code)


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
        # Generate MIT license for Python repos
        repoindex ops generate license --language python --license mit --dry-run
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
    dry_run: bool,
    force: bool,
    author: Optional[str],
    orcid: Optional[str],
    email: Optional[str],
    affiliation: Optional[str],
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate codemeta.json", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers or None)


# ============================================================================
# Generate license command
# ============================================================================

@generate_cmd.command('license')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
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
    dry_run: bool,
    force: bool,
    license_type: str,
    author: Optional[str],
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """
    Generate LICENSE files for repositories.

    Creates LICENSE files with the specified license type.
    Supports: MIT, Apache-2.0, GPL-3.0, BSD-3-Clause, MPL-2.0.

    \b
    Examples:
        # Generate MIT license for all repos
        repoindex ops generate license --dry-run
        # Generate Apache 2.0 license for Python repos
        repoindex ops generate license --license apache-2.0 --language python --dry-run
        # With custom author name
        repoindex ops generate license --author "My Company Inc." --dry-run
        # Force overwrite existing licenses
        repoindex ops generate license --force --license gpl-3.0 --dry-run
    """
    result = _resolve_repos(
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate LICENSE", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers)


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
    dry_run: bool,
    force: bool,
    language_template: str,
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate .gitignore", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers)


# ============================================================================
# Generate code-of-conduct command
# ============================================================================

@generate_cmd.command('code-of-conduct')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing CODE_OF_CONDUCT.md files')
@click.option('--email', help='Contact email (overrides config)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_code_of_conduct_handler(
    query_string: str,
    output_json: bool,
    dry_run: bool,
    force: bool,
    email: Optional[str],
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate CODE_OF_CONDUCT.md", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers or None)


# ============================================================================
# Generate contributing command
# ============================================================================

@generate_cmd.command('contributing')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing CONTRIBUTING.md files')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_contributing_handler(
    query_string: str,
    output_json: bool,
    dry_run: bool,
    force: bool,
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate CONTRIBUTING.md", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label)


# ============================================================================
# Generate citation command
# ============================================================================

@generate_cmd.command('citation')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
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
    dry_run: bool,
    force: bool,
    author: Optional[str],
    orcid: Optional[str],
    email: Optional[str],
    affiliation: Optional[str],
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate CITATION.cff", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers or None)


# ============================================================================
# Generate zenodo command
# ============================================================================

@generate_cmd.command('zenodo')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
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
    dry_run: bool,
    force: bool,
    author: Optional[str],
    orcid: Optional[str],
    email: Optional[str],
    affiliation: Optional[str],
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate .zenodo.json", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label,
                           extra_headers=extra_headers or None)


# ============================================================================
# Generate mkdocs command
# ============================================================================

@generate_cmd.command('mkdocs')
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--dry-run', is_flag=True, help='Preview without writing files')
@click.option('--force', is_flag=True, help='Overwrite existing mkdocs.yml files')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def generate_mkdocs_handler(
    query_string: str,
    output_json: bool,
    dry_run: bool,
    force: bool,
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
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
        output_json, debug, query_string,
        language=language, dirty=dirty, tag=tag, recent=recent,
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
    if output_json:
        _ops_output_json(service, progress_iter, options)
    else:
        _ops_output_pretty(service, progress_iter, options,
                           "Generate mkdocs.yml", len(repos),
                           success_label="Generated",
                           success_msg="Generated {count} " + file_label)


# ============================================================================
# Generate gh-pages command
# ============================================================================

# ============================================================================
# WIP Snapshot command
# ============================================================================

@ops_cmd.command('wip-snapshot')
@click.argument('query_string', required=False, default='')
@click.option('--dry-run', is_flag=True, help='Preview what would be snapshotted')
@click.option('--hostname', help='Override hostname for wip branch name')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def wip_snapshot_handler(
    query_string: str,
    dry_run: bool,
    hostname: Optional[str],
    output_json: bool,
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """Snapshot dirty working trees to wip/ branches on origin.

    Creates remote-recoverable snapshots using git plumbing without
    modifying your working tree or main branches. Safe to run anytime.

    Each dirty repo gets a commit pushed to origin/wip/<hostname>/<date>.
    Force-push is used (safe: wip branches are throwaway).

    \b
    Examples:
        # Snapshot all dirty repos
        repoindex ops wip-snapshot
        # Preview first
        repoindex ops wip-snapshot --dry-run
        # Only Python repos
        repoindex ops wip-snapshot --language python
        # Only repos with a tag
        repoindex ops wip-snapshot --tag "work/*"

    Recovery:
        git fetch origin wip/<hostname>/<date>
        git checkout -b recovered FETCH_HEAD
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ..services.wip_service import snapshot_repo, SnapshotResult

    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    # Always filter to dirty repos (the whole point is snapshotting uncommitted work)
    repos = _get_repos_from_query(
        config, query_string, debug=debug,
        language=language, dirty=True, tag=tag, recent=recent,
    )

    if not repos:
        if output_json:
            print(json.dumps({"error": "No dirty repos found."}), flush=True)
        else:
            click.echo("No dirty repos found.", err=True)
        return

    if not output_json:
        click.echo(
            f"{'[DRY RUN] ' if dry_run else ''}Snapshotting {len(repos)} dirty repo(s)...",
            err=True,
        )

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(snapshot_repo, r['path'], hostname=hostname, dry_run=dry_run): r
            for r in repos
        }
        for future in as_completed(futures):
            repo = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                # An uncaught exception in snapshot_repo must not kill the
                # whole batch — it would throw away the already-completed
                # (possibly already-pushed) snapshots sitting in ``results``.
                results.append(SnapshotResult(
                    repo_name=Path(repo['path']).name,
                    repo_path=repo['path'],
                    success=False,
                    error=f'unexpected: {type(e).__name__}: {e}',
                ))

    # Categorize results
    snapshotted = [r for r in results if r.success and not r.skipped]
    skipped = [r for r in results if r.skipped]
    failed = [r for r in results if not r.success and not r.skipped]

    if output_json:
        _wip_snapshot_output_json(snapshotted, skipped, failed, dry_run)
    else:
        _wip_snapshot_output_pretty(snapshotted, skipped, failed, dry_run)


def _wip_snapshot_output_json(snapshotted, skipped, failed, dry_run):
    """JSONL output for wip-snapshot."""
    for r in snapshotted:
        record = {
            "status": "snapshotted",
            "repo": r.repo_name,
            "path": r.repo_path,
            "branch": r.branch,
        }
        if not dry_run:
            record["commit"] = r.commit_sha
        print(json.dumps(record), flush=True)

    for r in skipped:
        print(json.dumps({
            "status": "skipped",
            "repo": r.repo_name,
            "path": r.repo_path,
            "reason": r.skip_reason,
        }), flush=True)

    for r in failed:
        print(json.dumps({
            "status": "failed",
            "repo": r.repo_name,
            "path": r.repo_path,
            "error": r.error,
        }), flush=True)

    print(json.dumps({
        "summary": {
            "snapshotted": len(snapshotted),
            "skipped": len(skipped),
            "failed": len(failed),
            "dry_run": dry_run,
        }
    }), flush=True)


# ============================================================================
# Mirror command
# ============================================================================

@ops_cmd.command('mirror')
@click.option('--to', 'to_mirrors', multiple=True,
              help='Name of a configured mirror to push to (repeatable)')
@click.option('--all', 'all_mirrors', is_flag=True,
              help='Push to every configured mirror')
@click.option('--init', is_flag=True,
              help='For file:// targets, init a bare repo if missing')
@click.option('--force', is_flag=True,
              help='Bypass fast-forward check (use with care)')
@click.option('--dry-run', is_flag=True, help='Preview actions without pushing')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def mirror_handler(
    to_mirrors: tuple,
    all_mirrors: bool,
    init: bool,
    force: bool,
    dry_run: bool,
    output_json: bool,
    debug: bool,
    # Query flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """Mirror repositories to configured redundancy targets.

    Pushes every branch and tag (``git push --mirror``) to one or more
    forges defined in ``~/.repoindex/config.yaml`` with ``role: mirror``:

        forges:
          codeberg:
            source_id: gitea
            host: codeberg.org
            role: mirror
            url_template: "https://codeberg.org/queelius/{repo}.git"
          gitea-gdrive:
            source_id: gitea
            role: mirror
            url_template: "file:///mnt/gdrive/git-mirrors/{repo}.git"

    For each repo x mirror, the URL is resolved from an existing git
    remote of the same name if present (user override wins), else added
    from ``url_template``. Fast-forward is enforced by default; use
    ``--force`` to overwrite. ``--init`` creates missing bare repos for
    ``file://`` targets.

    \b
    Examples:
        # Preview pushing every repo to Codeberg
        repoindex ops mirror --to codeberg --dry-run
        # Push all Python repos to every configured mirror
        repoindex ops mirror --all --language python
        # Mirror dirty repos to local Gitea, initializing bare repos
        repoindex ops mirror --to gitea-gdrive --dirty --init
        # Force push (overwrites diverged mirror branches)
        repoindex ops mirror --to nas-backup --force
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ..services.forge_config import ForgeConfigError, get_mirrors
    from ..services.mirror_service import mirror_repo, MirrorResult

    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    # --- Scoping: --to and --all are mutually exclusive -------------------
    if all_mirrors and to_mirrors:
        _emit_error("--to and --all are mutually exclusive", output_json)

    if not all_mirrors and not to_mirrors:
        _emit_error("Specify --to <name> or --all", output_json)

    config = load_config()

    # Migration warning: the old top-level mirrors: section is gone.
    legacy = config.get('mirrors')
    if legacy:
        click.echo(
            "Warning: top-level 'mirrors:' is no longer supported. "
            "Migrate to forges: with role: mirror. See docs/ops.md.",
            err=True,
        )

    try:
        all_targets = get_mirrors(config)
    except ForgeConfigError as e:
        _emit_error(f"invalid forges config: {e}", output_json)

    if not all_targets:
        _emit_error(
            "no mirrors configured (add forges: entries with role: mirror "
            "to ~/.repoindex/config.yaml)",
            output_json,
        )

    if all_mirrors:
        selected = list(all_targets)
    else:
        by_name = {m.name: m for m in all_targets}
        selected = []
        unknown = []
        for name in to_mirrors:
            if name in by_name:
                selected.append(by_name[name])
            else:
                unknown.append(name)
        if unknown:
            known = ', '.join(sorted(by_name))
            _emit_error(
                f"unknown mirror(s): {', '.join(unknown)} "
                f"(configured: {known or 'none'})",
                output_json,
            )

    # --- Resolve repos via standard flag-based query ----------------------
    repos = _get_repos_from_query(
        config, '', debug=debug,
        language=language, dirty=dirty, tag=tag, recent=recent,
    )
    if not repos:
        _no_repos_message(output_json)
        return

    if not output_json:
        mode = "[DRY RUN] " if dry_run else ""
        click.echo(
            f"{mode}Mirroring {len(repos)} repo(s) to "
            f"{len(selected)} target(s)...",
            err=True,
        )

    def _mirror_one_repo(repo) -> list[MirrorResult]:
        """Run all selected mirrors for ONE repo, sequentially.

        Mirrors are kept sequential per repo to avoid server-side lock
        contention when a host happens to back multiple mirror URLs.
        Exceptions in mirror_repo are caught so one bad mirror doesn't
        stop the others for the same repo.
        """
        results: list[MirrorResult] = []
        for target in selected:
            try:
                results.append(mirror_repo(
                    repo['path'], target,
                    force=force, init=init, dry_run=dry_run,
                ))
            except Exception as e:
                results.append(MirrorResult(
                    repo_name=Path(repo['path']).name,
                    repo_path=repo['path'],
                    mirror_name=target.name,
                    mirror_url=target.url_for(Path(repo['path']).name),
                    status='failed',
                    detail=f"unexpected: {type(e).__name__}: {e}",
                ))
        return results

    all_results: list[MirrorResult] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_mirror_one_repo, r): r for r in repos}
        for future in as_completed(futures):
            repo = futures[future]
            try:
                all_results.extend(future.result())
            except Exception as e:
                # Per-repo isolation: a failure in the worker must not
                # discard results already collected for other repos.
                for target in selected:
                    all_results.append(MirrorResult(
                        repo_name=Path(repo['path']).name,
                        repo_path=repo['path'],
                        mirror_name=target.name,
                        mirror_url=target.url_for(Path(repo['path']).name),
                        status='failed',
                        detail=f"unexpected: {type(e).__name__}: {e}",
                    ))

    if output_json:
        _mirror_output_json(all_results, dry_run)
    else:
        _mirror_output_pretty(all_results, dry_run)


def _mirror_summary(results: list) -> tuple[int, int, int]:
    """Return (mirrored, skipped, failed) counts for mirror results."""
    mirrored = sum(1 for r in results if r.status in ('ok', 'init+pushed', 'dry-run'))
    skipped = sum(1 for r in results if r.status == 'skipped')
    failed = sum(1 for r in results if r.status == 'failed')
    return mirrored, skipped, failed


def _mirror_output_json(results, dry_run):
    """JSONL output for ops mirror."""
    for r in results:
        print(json.dumps({
            "status": r.status,
            "repo": r.repo_name,
            "path": r.repo_path,
            "mirror": r.mirror_name,
            "url": r.mirror_url,
            "detail": r.detail,
            "added_remote": r.added_remote,
        }), flush=True)

    mirrored, skipped, failed = _mirror_summary(results)
    print(json.dumps({
        "summary": {
            "mirrored": mirrored,
            "skipped": skipped,
            "failed": failed,
            "dry_run": dry_run,
        }
    }), flush=True)


def _mirror_output_pretty(results, dry_run):
    """Pretty terminal output for ops mirror."""
    from rich.console import Console
    from rich.table import Table

    console = Console(stderr=True)
    mode = "[bold yellow]DRY RUN[/bold yellow] " if dry_run else ""
    console.print(f"\n{mode}[bold]Mirror[/bold]")

    if results:
        table = Table(show_header=True, show_lines=False)
        table.add_column("Repo", style="cyan")
        table.add_column("Mirror")
        table.add_column("Status")
        table.add_column("Detail", style="dim", overflow="fold")

        status_style = {
            'ok': 'green',
            'init+pushed': 'green',
            'dry-run': 'yellow',
            'skipped': 'yellow',
            'failed': 'red',
        }
        for r in sorted(results, key=lambda x: (x.repo_name, x.mirror_name)):
            color = status_style.get(r.status, 'white')
            table.add_row(
                r.repo_name,
                r.mirror_name,
                f"[{color}]{r.status}[/{color}]",
                r.detail,
            )
        console.print(table)

    mirrored, skipped, failed = _mirror_summary(results)
    console.print(
        f"\nSummary: {mirrored} mirrored, {skipped} skipped, {failed} failed"
    )


def _wip_snapshot_output_pretty(snapshotted, skipped, failed, dry_run):
    """Pretty terminal output for wip-snapshot."""
    if snapshotted:
        click.echo(f"\nSnapshotted ({len(snapshotted)}):", err=True)
        for r in sorted(snapshotted, key=lambda x: x.repo_name):
            if dry_run:
                click.echo(f"  {r.repo_name} -> origin/{r.branch}", err=True)
            else:
                click.echo(f"  {r.repo_name} -> origin/{r.branch} [{r.commit_sha[:8]}]", err=True)

    if skipped:
        skip_counts = {}
        for r in skipped:
            skip_counts[r.skip_reason] = skip_counts.get(r.skip_reason, 0) + 1
        skip_summary = ', '.join(f'{v} {k}' for k, v in sorted(skip_counts.items()))
        click.echo(f"\nSkipped ({len(skipped)}): {skip_summary}", err=True)

    if failed:
        click.echo(f"\nFailed ({len(failed)}):", err=True)
        for r in sorted(failed, key=lambda x: x.repo_name):
            click.echo(f"  {r.repo_name}: {r.error}", err=True)

    click.echo(
        f"\nSummary: {len(snapshotted)} snapshotted, {len(skipped)} skipped, {len(failed)} failed",
        err=True,
    )


# ============================================================================
# Cross-forge actions (Wave V2.C): ops set-topics / set-description /
# set-archived / set-visibility / set-default-branch / set-pages
#
# Each command resolves the target repo's GitForge via forge_id and
# dispatches to the matching source instance's write method. The shared
# helpers below keep handler bodies short while preserving per-repo
# exception isolation (the same pattern as wip-snapshot and mirror).
# ============================================================================

def _resolve_set_repos(
    repo_name: Optional[str],
    apply_all: bool,
    output_json: bool,
    debug: bool,
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """Resolve repos for a set-* action.

    Single-repo mode: positional ``repo_name`` selects exactly one repo
    by ``repos.name`` (path uniqueness is irrelevant; we want the local
    name the user typed). Bulk mode (``--all``) uses the filter flags.
    Without either, the command errors out to prevent mass-mutation by
    accident.

    Returns ``(config, repos)`` or ``None`` after printing an error.
    """
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = load_config()

    if repo_name and apply_all:
        _emit_error("REPO and --all are mutually exclusive", output_json)

    if not repo_name and not apply_all:
        _emit_error(
            "specify a single REPO (with no --all) or --all "
            "plus filter flags for bulk operation",
            output_json,
        )

    if repo_name:
        # Look up by name. Single match preferred; ambiguity is a hard error.
        from ..database.repository import get_repo_by_name
        with Database(config=config, read_only=True) as db:
            row = get_repo_by_name(db, repo_name)
        if not row:
            _emit_error(f"repo not found: {repo_name}", output_json, exit_code=1)
        return config, [row]

    # Bulk mode
    repos = _get_repos_from_query(
        config, '', debug=debug,
        language=language, dirty=dirty, tag=tag, recent=recent,
    )
    if not repos:
        _no_repos_message(output_json)
        return None
    return config, repos


def _dispatch_set_action(
    repos: list,
    config: dict,
    action_name: str,
    invoke,
    dry_run: bool,
    output_json: bool,
):
    """Run a write action across ``repos`` with per-repo isolation.

    Args:
        repos: List of repo dicts (DB rows).
        config: Loaded configuration.
        action_name: Short label (``"set_topics"``, ``"set_pages"``, ...).
        invoke: Callable ``(forge, repo) -> str`` that performs the API call
            and returns a human-readable detail message. Should raise on
            failure; ``NotImplementedError`` is treated as "skipped: forge
            does not support this action".
        dry_run: If True, no invocation is made; emits "would" rows.
        output_json: Output format.
    """
    from ..services.forge_actions import lookup_repo_forge

    results: list[dict] = []

    def record(repo, forge_id, status, detail):
        results.append({
            'status': status,
            'repo': repo.get('name', ''),
            'path': repo.get('path', ''),
            'forge': forge_id,
            'detail': detail,
        })

    for repo in repos:
        forge_id = repo.get('forge_id')

        if not forge_id:
            record(repo, None, 'skipped',
                   'no forge_id (run repoindex refresh --external)')
            continue

        forge = lookup_repo_forge(repo)
        if forge is None:
            record(repo, forge_id, 'skipped',
                   f'no GitForge source for forge_id={forge_id}')
            continue

        if dry_run:
            record(repo, forge_id, 'dry-run', f'would invoke {action_name}')
            continue

        try:
            detail = invoke(forge, repo)
            record(repo, forge_id, 'ok', detail or action_name)
        except NotImplementedError as e:
            record(repo, forge_id, 'skipped',
                   f'forge does not support {action_name}: {e}')
        except Exception as e:
            record(repo, forge_id, 'failed', f'{type(e).__name__}: {e}')

    _set_action_output(results, action_name, dry_run, output_json)


def _set_action_output(results, action_name, dry_run, output_json):
    """Emit per-repo rows and a summary for a set-* dispatch."""
    ok = sum(1 for r in results if r['status'] in ('ok', 'dry-run'))
    skipped = sum(1 for r in results if r['status'] == 'skipped')
    failed = sum(1 for r in results if r['status'] == 'failed')

    if output_json:
        for r in results:
            print(json.dumps(r), flush=True)
        print(json.dumps({
            'summary': {
                'action': action_name,
                'ok': ok,
                'skipped': skipped,
                'failed': failed,
                'dry_run': dry_run,
            }
        }), flush=True)
        if failed:
            sys.exit(1)
        return

    from rich.console import Console
    from rich.table import Table

    console = Console(stderr=True)
    mode = "[bold yellow]DRY RUN[/bold yellow] " if dry_run else ""
    console.print(f"\n{mode}[bold]{action_name}[/bold]")

    if results:
        table = Table(show_header=True, show_lines=False)
        table.add_column("Repo", style="cyan")
        table.add_column("Forge")
        table.add_column("Status")
        table.add_column("Detail", style="dim", overflow="fold")
        style = {'ok': 'green', 'dry-run': 'yellow',
                 'skipped': 'yellow', 'failed': 'red'}
        for r in sorted(results, key=lambda x: x['repo']):
            color = style.get(r['status'], 'white')
            table.add_row(
                r['repo'],
                r.get('forge') or '-',
                f"[{color}]{r['status']}[/{color}]",
                r['detail'],
            )
        console.print(table)

    console.print(f"\nSummary: {ok} ok, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)


def _stdout_isatty() -> bool:
    """Return whether stdout is a TTY.

    Wrapped in a module-level helper so tests can patch it: ``CliRunner``
    replaces ``sys.stdout`` at invoke time, which makes the swapped stream's
    ``isatty()`` unpatchable from the outside.
    """
    return sys.stdout.isatty()


def _confirm_bulk_set(
    n: int,
    dry_run: bool,
    output_json: bool,
    yes: bool,
    action_name: str,
) -> bool:
    """Decide whether a bulk set-* action may proceed.

    Returns True to proceed, False to abort. A confirmation prompt is shown
    only for a genuine interactive bulk mutation: more than one repo, not a
    dry run, not JSON output, an interactive TTY, and ``--yes`` not given. All
    other cases proceed without prompting so scripted, piped, single-repo, and
    preview invocations never hang.
    """
    if yes or dry_run or output_json or n <= 1 or not _stdout_isatty():
        return True
    if not click.confirm(f"Apply {action_name} to {n} repositories?"):
        print("Aborted.", file=sys.stderr)
        return False
    return True


@ops_cmd.command('set-topics')
@click.argument('repo_name', required=False, metavar='REPO')
@click.argument('topics', nargs=-1)
@click.option('--all', 'apply_all', is_flag=True,
              help='Apply to all repos matching filters (bulk mode)')
@click.option('--dry-run', is_flag=True,
              help='Preview without making API calls')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def set_topics_handler(
    repo_name: Optional[str],
    topics: tuple,
    apply_all: bool,
    dry_run: bool,
    yes: bool,
    output_json: bool,
    debug: bool,
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """Set topics on a forge-hosted repo (cross-platform).

    Dispatches to the GitForge claiming the repo's ``forge_id``. Topics
    are passed as positional args after REPO; pass them once and the
    forge replaces its full topic list.

    \b
    Examples:
        # Single repo
        repoindex ops set-topics myrepo python cli unix
        # All Python repos (no REPO, all positionals are topics)
        repoindex ops set-topics --all --language python python cli --dry-run
    """
    # In --all mode there's no REPO; what Click parsed as REPO is
    # actually the first topic. Re-bind so the bulk path sees all topics.
    if apply_all and repo_name:
        topics = (repo_name, *topics)
        repo_name = None

    if not topics:
        click.echo("Error: provide one or more topics after REPO", err=True)
        sys.exit(2)

    resolved = _resolve_set_repos(
        repo_name, apply_all, output_json, debug,
        language, dirty, tag, recent,
    )
    if resolved is None:
        return
    config, repos = resolved

    if not _confirm_bulk_set(
        len(repos), dry_run, output_json, yes, 'set_topics',
    ):
        return

    topic_list = list(topics)

    def invoke(forge, repo):
        forge.set_topics(repo, topic_list, config)
        return f"topics={','.join(topic_list)}"

    _dispatch_set_action(
        repos, config, 'set_topics', invoke, dry_run, output_json,
    )


@ops_cmd.command('set-description')
@click.argument('repo_name', required=False, metavar='REPO')
@click.argument('description', required=False)
@click.option('--all', 'apply_all', is_flag=True,
              help='Apply to all repos matching filters (bulk mode)')
@click.option('--dry-run', is_flag=True,
              help='Preview without making API calls')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def set_description_handler(
    repo_name: Optional[str],
    description: Optional[str],
    apply_all: bool,
    dry_run: bool,
    yes: bool,
    output_json: bool,
    debug: bool,
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """Set the forge-side description on a repo.

    \b
    Examples:
        # Single repo
        repoindex ops set-description myrepo "A short description"
        # Bulk (sets all matching repos to the same text)
        repoindex ops set-description --all --language python "Python tools" --dry-run
    """
    # In --all mode the user omits REPO; the first positional is the
    # description. Re-bind so the bulk path sees the right value.
    if apply_all and repo_name and not description:
        description = repo_name
        repo_name = None

    if not description:
        click.echo("Error: provide DESCRIPTION text", err=True)
        sys.exit(2)

    resolved = _resolve_set_repos(
        repo_name, apply_all, output_json, debug,
        language, dirty, tag, recent,
    )
    if resolved is None:
        return
    config, repos = resolved

    if not _confirm_bulk_set(
        len(repos), dry_run, output_json, yes, 'set_description',
    ):
        return

    def invoke(forge, repo):
        forge.set_description(repo, description, config)
        return f"description set ({len(description)} chars)"

    _dispatch_set_action(
        repos, config, 'set_description', invoke, dry_run, output_json,
    )


@ops_cmd.command('set-archived')
@click.argument('repo_name', required=False, metavar='REPO')
@click.argument('value', required=False,
                type=click.Choice(['true', 'false'], case_sensitive=False))
@click.option('--all', 'apply_all', is_flag=True,
              help='Apply to all repos matching filters (bulk mode)')
@click.option('--dry-run', is_flag=True,
              help='Preview without making API calls')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def set_archived_handler(
    repo_name: Optional[str],
    value: Optional[str],
    apply_all: bool,
    dry_run: bool,
    yes: bool,
    output_json: bool,
    debug: bool,
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """Archive or unarchive a repo on its forge.

    \b
    Examples:
        repoindex ops set-archived old-repo true
        repoindex ops set-archived --all --tag work/legacy true --dry-run
    """
    # In --all mode REPO is omitted; what Click parsed as REPO is the
    # boolean value. Re-bind.
    if apply_all and repo_name and value is None:
        if repo_name.lower() in ('true', 'false'):
            value = repo_name
            repo_name = None

    if value is None:
        click.echo("Error: provide a value of true or false", err=True)
        sys.exit(2)

    resolved = _resolve_set_repos(
        repo_name, apply_all, output_json, debug,
        language, dirty, tag, recent,
    )
    if resolved is None:
        return
    config, repos = resolved

    if not _confirm_bulk_set(
        len(repos), dry_run, output_json, yes, 'set_archived',
    ):
        return

    archived = value.lower() == 'true'

    def invoke(forge, repo):
        forge.set_archived(repo, archived, config)
        return f"archived={archived}"

    _dispatch_set_action(
        repos, config, 'set_archived', invoke, dry_run, output_json,
    )


@ops_cmd.command('set-visibility')
@click.argument('repo_name', required=False, metavar='REPO')
@click.argument('value', required=False,
                type=click.Choice(['public', 'private'], case_sensitive=False))
@click.option('--all', 'apply_all', is_flag=True,
              help='Apply to all repos matching filters (bulk mode)')
@click.option('--dry-run', is_flag=True,
              help='Preview without making API calls')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def set_visibility_handler(
    repo_name: Optional[str],
    value: Optional[str],
    apply_all: bool,
    dry_run: bool,
    yes: bool,
    output_json: bool,
    debug: bool,
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """Toggle public/private visibility on a forge.

    \b
    Examples:
        repoindex ops set-visibility myrepo public
        repoindex ops set-visibility --all --tag work/internal private --dry-run
    """
    if apply_all and repo_name and value is None:
        if repo_name.lower() in ('public', 'private'):
            value = repo_name
            repo_name = None

    if value is None:
        click.echo("Error: provide a value of public or private", err=True)
        sys.exit(2)

    resolved = _resolve_set_repos(
        repo_name, apply_all, output_json, debug,
        language, dirty, tag, recent,
    )
    if resolved is None:
        return
    config, repos = resolved

    if not _confirm_bulk_set(
        len(repos), dry_run, output_json, yes, 'set_visibility',
    ):
        return

    public = value.lower() == 'public'

    def invoke(forge, repo):
        forge.set_visibility(repo, public, config)
        return f"public={public}"

    _dispatch_set_action(
        repos, config, 'set_visibility', invoke, dry_run, output_json,
    )


@ops_cmd.command('set-default-branch')
@click.argument('repo_name', required=False, metavar='REPO')
@click.argument('branch', required=False)
@click.option('--all', 'apply_all', is_flag=True,
              help='Apply to all repos matching filters (bulk mode)')
@click.option('--dry-run', is_flag=True,
              help='Preview without making API calls')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@query_options
def set_default_branch_handler(
    repo_name: Optional[str],
    branch: Optional[str],
    apply_all: bool,
    dry_run: bool,
    yes: bool,
    output_json: bool,
    debug: bool,
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """Change the default branch on a forge.

    \b
    Examples:
        repoindex ops set-default-branch myrepo main
        repoindex ops set-default-branch --all main --dry-run
    """
    if apply_all and repo_name and not branch:
        branch = repo_name
        repo_name = None

    if not branch:
        click.echo("Error: provide the new branch name", err=True)
        sys.exit(2)

    resolved = _resolve_set_repos(
        repo_name, apply_all, output_json, debug,
        language, dirty, tag, recent,
    )
    if resolved is None:
        return
    config, repos = resolved

    if not _confirm_bulk_set(
        len(repos), dry_run, output_json, yes, 'set_default_branch',
    ):
        return

    def invoke(forge, repo):
        forge.set_default_branch(repo, branch, config)
        return f"default_branch={branch}"

    _dispatch_set_action(
        repos, config, 'set_default_branch', invoke, dry_run, output_json,
    )


@ops_cmd.command('set-pages')
@click.argument('repo_name', metavar='REPO')
@click.option('--branch', required=True, help='Source branch for Pages')
@click.option('--path', default='/', show_default=True,
              help='Subdirectory inside the branch')
@click.option('--dry-run', is_flag=True,
              help='Preview without making API calls')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def set_pages_handler(
    repo_name: str,
    branch: str,
    path: str,
    dry_run: bool,
    yes: bool,
    output_json: bool,
    debug: bool,
):
    """Enable Pages on a forge-hosted repo (per-repo, no --all).

    Pages source is forge-specific: GitHub supports POST/PUT
    ``/repos/{owner}/{repo}/pages``. Gitea instances vary; the gitea
    source surfaces a clean "not supported" error.

    \b
    Examples:
        repoindex ops set-pages my-site --branch gh-pages --path /
        repoindex ops set-pages docs-repo --branch main --path /docs
    """
    resolved = _resolve_set_repos(
        repo_name, apply_all=False, output_json=output_json, debug=debug,
        language=None, dirty=False, tag=(), recent=None,
    )
    if resolved is None:
        return
    config, repos = resolved

    def invoke(forge, repo):
        forge.enable_pages(repo, branch, path, config)
        return f"pages enabled on {branch}:{path}"

    _dispatch_set_action(
        repos, config, 'set_pages', invoke, dry_run, output_json,
    )


# ============================================================================
# ops sync (Wave V2.C): clone repos owned on enumerable forges that
# aren't present locally.
# ============================================================================

@ops_cmd.command('sync')
@click.option('--from', 'from_forges', multiple=True,
              help='Sync from specific forge (repeatable, e.g. --from github)')
@click.option('--all', 'all_forges', is_flag=True,
              help='Sync from every enumerable forge')
@click.option('--into', 'into_path', type=click.Path(),
              help='Override clone destination root')
@click.option('--dry-run', is_flag=True, help='Preview without cloning')
@click.option('--include-archived', is_flag=True,
              help='Include archived repos (skipped by default)')
@click.option('--filter', 'name_filter', metavar='PATTERN',
              help='Glob pattern on repo name (fnmatch)')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def sync_handler(
    from_forges: tuple,
    all_forges: bool,
    into_path: Optional[str],
    dry_run: bool,
    include_archived: bool,
    name_filter: Optional[str],
    output_json: bool,
    debug: bool,
):
    """Clone repos you own on configured forges that aren't present locally.

    For each selected GitForge, enumerates the authenticated user's owned
    repos. Skips repos already in the local DB (matched by normalized
    ``remote_url``). Skips archived repos unless ``--include-archived``.
    Optionally filters by repo name via ``--filter`` (fnmatch).

    Destination resolution:
        --into PATH                   {PATH}/{forge_id}/{repo_name}
        forges.<id>.sync_into in config
        default                       ~/github/imported/{forge_id}/{repo_name}

    Use ``repoindex refresh`` afterwards to index the new clones.

    \b
    Examples:
        # Preview what'd be cloned from every enumerable forge
        repoindex ops sync --all --dry-run
        # Sync only from GitHub, filtered by name
        repoindex ops sync --from github --filter 'lib-*'
        # Custom destination root
        repoindex ops sync --all --into /mnt/extra/imports
    """
    import fnmatch
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    if from_forges and all_forges:
        _emit_error("--from and --all are mutually exclusive", output_json)

    if not from_forges and not all_forges:
        _emit_error("specify --from <name> (repeatable) or --all", output_json)

    config = load_config()

    # Select forges
    forges = [s for s in discover_sources() if isinstance(s, GitForge)]
    if from_forges:
        wanted = set(from_forges)
        forges = [f for f in forges if f.source_id in wanted]
        if not forges:
            available = [
                f.source_id for f in discover_sources()
                if isinstance(f, GitForge)
            ]
            _emit_error(
                f"no GitForge matches --from {list(from_forges)}; "
                f"available: {available}",
                output_json,
            )

    # Load existing remote_urls for dedup
    existing_urls = _load_existing_remote_urls(config)

    # Enumerate
    to_clone: list[dict] = []
    enumerate_errors: list[dict] = []

    for forge in forges:
        try:
            for remote in forge.enumerate_user_repos(config):
                norm = _normalize_remote(remote.clone_url)
                if norm in existing_urls:
                    to_clone.append({
                        'forge': forge.source_id,
                        'name': remote.name,
                        'clone_url': remote.clone_url,
                        'status': 'already-have',
                    })
                    continue
                if remote.is_archived and not include_archived:
                    to_clone.append({
                        'forge': forge.source_id,
                        'name': remote.name,
                        'clone_url': remote.clone_url,
                        'status': 'skipped-archived',
                    })
                    continue
                if name_filter and not fnmatch.fnmatch(remote.name, name_filter):
                    to_clone.append({
                        'forge': forge.source_id,
                        'name': remote.name,
                        'clone_url': remote.clone_url,
                        'status': 'skipped-filter',
                    })
                    continue

                dest = _resolve_sync_destination(
                    forge.source_id, remote.name, into_path, config,
                )
                to_clone.append({
                    'forge': forge.source_id,
                    'name': remote.name,
                    'clone_url': remote.clone_url,
                    'status': 'pending',
                    'destination': dest,
                })
        except NotImplementedError as e:
            enumerate_errors.append({
                'forge': forge.source_id,
                'error': f'enumerate not supported: {e}',
            })
        except Exception as e:
            enumerate_errors.append({
                'forge': forge.source_id,
                'error': f'{type(e).__name__}: {e}',
            })

    # Dry-run reporting before any clones
    pending = [r for r in to_clone if r['status'] == 'pending']

    if dry_run:
        _sync_output(to_clone, enumerate_errors, dry_run=True,
                     output_json=output_json)
        return

    # Clone the pending ones
    if pending:
        if not output_json:
            click.echo(
                f"Cloning {len(pending)} repo(s) from "
                f"{len(forges)} forge(s)...", err=True,
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(_clone_one, r['clone_url'], r['destination']): r
                for r in pending
            }
            for future in as_completed(futures):
                r = futures[future]
                try:
                    success, detail = future.result()
                except Exception as e:
                    success, detail = False, f'{type(e).__name__}: {e}'
                r['status'] = 'cloned' if success else 'failed'
                r['detail'] = detail

    _sync_output(to_clone, enumerate_errors, dry_run=False,
                 output_json=output_json)


def _load_existing_remote_urls(config) -> set:
    """Load and normalize ``remote_url`` columns from the repos table.

    Returns a set of normalized URLs for dedup matching during sync. The
    normalization collapses SSH and HTTPS variants of the same canonical
    remote so we don't re-clone a repo that's already local under either
    form.
    """
    urls: set = set()
    with Database(config=config, read_only=True) as db:
        db.execute("SELECT remote_url FROM repos WHERE remote_url IS NOT NULL")
        for row in db.fetchall():
            url = row['remote_url'] if isinstance(row, dict) else row[0]
            if url:
                urls.add(_normalize_remote(url))
    return urls


def _normalize_remote(url: str) -> str:
    """Normalize a git remote URL for dedup matching.

    Collapses SSH (``git@host:owner/repo.git``) and HTTPS
    (``https://host/owner/repo.git``) to a single canonical form
    ``host/owner/repo``. Strips trailing ``.git`` and trailing slashes.
    """
    if not url:
        return ''
    s = url.strip()

    # https:// or ssh:// scheme
    if s.startswith(('http://', 'https://', 'ssh://', 'git://')):
        from urllib.parse import urlparse
        try:
            parsed = urlparse(s)
            host = parsed.hostname or ''
            path = parsed.path.lstrip('/')
        except Exception:
            return s.lower()
    else:
        # SSH form git@host:owner/repo[.git]
        m = re.match(r'^(?:[^@]+@)?([^:/\s]+):(.+?)$', s)
        if not m:
            return s.lower()
        host = m.group(1)
        path = m.group(2)

    # Strip .git and trailing slash
    path = re.sub(r'\.git/?$', '', path).rstrip('/')
    return f"{host.lower()}/{path}".lower()


def _resolve_sync_destination(
    forge_id: str,
    repo_name: str,
    into_path: Optional[str],
    config: dict,
) -> str:
    """Compute the local clone destination for a sync target.

    Precedence:
        1. ``--into PATH`` (CLI override): ``PATH/forge_id/repo_name``.
        2. ``forges.<forge_id>.sync_into`` in config: appended with repo_name.
        3. Default: ``~/github/imported/<forge_id>/<repo_name>``.
    """
    if into_path:
        return str(Path(into_path).expanduser() / forge_id / repo_name)

    # Look up the forge entry whose source_id matches; prefer a 'primary'
    # entry if multiple exist for the same source_id.
    from ..services.forge_config import load_forges, ForgeConfigError
    try:
        entries = load_forges(config)
    except ForgeConfigError:
        entries = []
    matched = [e for e in entries if e.source_id == forge_id]
    matched.sort(key=lambda e: 0 if e.role == 'primary' else 1)
    for entry in matched:
        if entry.sync_into:
            return str(Path(entry.sync_into).expanduser() / repo_name)

    return str(Path('~/github/imported').expanduser() / forge_id / repo_name)


def _clone_one(clone_url: str, destination: str) -> tuple[bool, str]:
    """Clone ``clone_url`` into ``destination`` with a 5-minute timeout."""
    import subprocess
    dest_path = Path(destination).expanduser()
    if dest_path.exists():
        return False, f'destination already exists: {dest_path}'
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ['git', 'clone', clone_url, str(dest_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, 'git clone timed out (>5min)'
    except FileNotFoundError:
        return False, 'git executable not found'
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or '').strip().splitlines()
        return False, err[-1] if err else f'git clone exited {proc.returncode}'
    return True, str(dest_path)


def _sync_summary(results: list) -> dict:
    """Return per-status counts used by both JSON and pretty output."""
    skipped_statuses = {'skipped-archived', 'skipped-filter'}
    return {
        'pending': sum(1 for r in results if r['status'] == 'pending'),
        'cloned': sum(1 for r in results if r['status'] == 'cloned'),
        'failed': sum(1 for r in results if r['status'] == 'failed'),
        'already': sum(1 for r in results if r['status'] == 'already-have'),
        'skipped': sum(1 for r in results if r['status'] in skipped_statuses),
    }


def _sync_output(results, enumerate_errors, dry_run, output_json):
    """Emit per-repo rows, enumeration errors, and a summary for ops sync."""
    counts = _sync_summary(results)
    if output_json:
        for r in results:
            print(json.dumps(r), flush=True)
        for e in enumerate_errors:
            print(json.dumps({'status': 'forge-error', **e}), flush=True)
        print(json.dumps({
            'summary': {
                'pending': counts['pending'],
                'cloned': counts['cloned'],
                'failed': counts['failed'],
                'already_have': counts['already'],
                'skipped': counts['skipped'],
                'forge_errors': len(enumerate_errors),
                'dry_run': dry_run,
            },
        }), flush=True)
        if not dry_run and counts['cloned'] > 0:
            print(json.dumps({
                'hint': 'run "repoindex refresh" to index newly cloned repos',
            }), flush=True)
        if counts['failed']:
            sys.exit(1)
        return

    from rich.console import Console
    from rich.table import Table

    console = Console(stderr=True)
    mode = "[bold yellow]DRY RUN[/bold yellow] " if dry_run else ""
    console.print(f"\n{mode}[bold]Sync[/bold]")

    if enumerate_errors:
        console.print("\n[red]Forge enumeration errors:[/red]")
        for e in enumerate_errors:
            console.print(f"  [red]{e['forge']}[/red]: {e['error']}")

    if results:
        table = Table(show_header=True, show_lines=False)
        table.add_column("Forge", style="cyan")
        table.add_column("Repo")
        table.add_column("Status")
        table.add_column("Detail", style="dim", overflow="fold")
        style = {
            'pending': 'yellow',
            'cloned': 'green',
            'failed': 'red',
            'already-have': 'dim',
            'skipped-archived': 'yellow',
            'skipped-filter': 'yellow',
        }
        for r in sorted(results, key=lambda x: (x['forge'], x['name'])):
            color = style.get(r['status'], 'white')
            detail = r.get('detail') or r.get('destination') or r['clone_url']
            table.add_row(
                r['forge'], r['name'],
                f"[{color}]{r['status']}[/{color}]",
                detail,
            )
        console.print(table)

    if dry_run:
        console.print(
            f"\nSummary: {counts['pending']} would-clone, "
            f"{counts['already']} already-have, "
            f"{counts['skipped']} skipped, "
            f"{len(enumerate_errors)} forge errors"
        )
    else:
        console.print(
            f"\nSummary: {counts['cloned']} cloned, {counts['failed']} failed, "
            f"{counts['already']} already-have, {counts['skipped']} skipped, "
            f"{len(enumerate_errors)} forge errors"
        )
        if counts['cloned'] > 0:
            console.print(
                "\n[dim]Hint: run [cyan]repoindex refresh[/cyan] to index "
                "the new clones.[/dim]"
            )

    if counts['failed']:
        sys.exit(1)
