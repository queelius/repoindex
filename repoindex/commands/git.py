"""
Git command replication for repoindex.

Provides familiar git commands that work with the VFS and can operate
on multiple repositories simultaneously.
"""

import click
import json
from pathlib import Path
from typing import List, Dict, Any

from ..git_ops.utils import get_repos_from_vfs_path, run_git, parse_git_status_output
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

console = Console()


@click.group(name='git')
def git_cmd():
    """Git operations on repositories.

    Execute familiar git commands on repositories through the VFS.
    Commands can operate on single repositories or multiple repositories
    at once.

    In the shell, commands use the current VFS directory.
    In the CLI, specify the VFS path explicitly.

    Examples:

    \b
        # CLI mode
        repoindex git status /by-tag/work/active
        repoindex git log /repos/myproject --oneline -5
        repoindex git pull /by-tag/needs-update

    \b
        # Shell mode (from shell prompt)
        repoindex:/by-tag/work/active> git status
        repoindex:/repos/myproject> git log --oneline -5
    """
    pass


@git_cmd.command('status')
@click.argument('vfs_path', default='/repos', required=False)
@click.option('--short', '-s', is_flag=True, help='Show short format')
@click.option('--dirty-only', is_flag=True, help='Show only repos with changes')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSONL')
def git_status(vfs_path, short, dirty_only, json_output):
    """Show working tree status for repositories.

    VFS_PATH: Virtual filesystem path (default: /repos)

    Shows git status for all repositories at the given VFS path.
    For directories, shows status for all contained repositories.
    For single repositories, shows detailed status.

    Examples:

    \b
        repoindex git status /by-tag/work/active
        repoindex git status /repos/myproject
        repoindex git status --dirty-only /by-language/Python
    """
    # Get all repos from VFS path
    repos = get_repos_from_vfs_path(vfs_path)

    if not repos:
        click.echo(f"No repositories found at: {vfs_path}", err=True)
        raise click.Abort()

    # Run git status on each repo
    results = []
    for repo_path in repos:
        repo_name = Path(repo_path).name

        # Get git status
        output, returncode = run_git(repo_path, ['status', '--porcelain', '--branch'])

        if returncode != 0:
            results.append({
                'repo': repo_name,
                'path': repo_path,
                'error': 'Failed to get status',
                'clean': None
            })
            continue

        # Parse status
        status_info = parse_git_status_output(output)

        # Get branch info
        branch_output, _ = run_git(repo_path, ['rev-parse', '--abbrev-ref', 'HEAD'])
        branch = branch_output.strip() if branch_output else 'unknown'

        # Get ahead/behind info
        ahead_behind_output, _ = run_git(repo_path, ['rev-list', '--left-right', '--count', f'{branch}...@{{u}}'])
        ahead, behind = 0, 0
        if ahead_behind_output:
            parts = ahead_behind_output.strip().split('\t')
            if len(parts) == 2:
                ahead = int(parts[0])
                behind = int(parts[1])

        result = {
            'repo': repo_name,
            'path': repo_path,
            'branch': branch,
            'clean': status_info['clean'],
            'modified': len(status_info['modified']),
            'added': len(status_info['added']),
            'deleted': len(status_info['deleted']),
            'untracked': len(status_info['untracked']),
            'ahead': ahead,
            'behind': behind,
            'files': status_info if not short else None
        }

        results.append(result)

    # Filter if dirty-only
    if dirty_only:
        results = [r for r in results if not r.get('clean', True)]

    if not results:
        if dirty_only:
            console.print("[green]All repositories are clean![/green]")
        else:
            console.print("[yellow]No repositories found[/yellow]")
        return

    # Output results
    if json_output:
        for result in results:
            print(json.dumps(result))
    else:
        if len(results) == 1:
            # Single repo - detailed view
            show_detailed_status(results[0])
        else:
            # Multiple repos - table view
            show_status_table(results, short)


def show_detailed_status(result: Dict[str, Any]):
    """Show detailed status for a single repository."""
    repo_name = result['repo']
    branch = result['branch']

    # Create header
    header = Text()
    header.append(f"Repository: ", style="bold cyan")
    header.append(f"{repo_name}\n", style="bold white")
    header.append(f"Path: ", style="dim")
    header.append(f"{result['path']}\n", style="dim")
    header.append(f"Branch: ", style="bold blue")
    header.append(f"{branch}", style="bold white")

    # Ahead/behind
    if result.get('ahead', 0) > 0 or result.get('behind', 0) > 0:
        header.append(" [", style="dim")
        if result.get('ahead', 0) > 0:
            header.append(f"↑{result['ahead']}", style="green")
        if result.get('behind', 0) > 0:
            if result.get('ahead', 0) > 0:
                header.append(" ", style="dim")
            header.append(f"↓{result['behind']}", style="yellow")
        header.append("]", style="dim")

    console.print(Panel(header, border_style="cyan"))

    # Status summary
    if result.get('clean'):
        console.print("[green]Working tree is clean[/green]")
    else:
        console.print("[yellow]Changes present:[/yellow]")
        if result.get('modified', 0) > 0:
            console.print(f"  Modified: {result['modified']}")
        if result.get('added', 0) > 0:
            console.print(f"  Added: {result['added']}")
        if result.get('deleted', 0) > 0:
            console.print(f"  Deleted: {result['deleted']}")
        if result.get('untracked', 0) > 0:
            console.print(f"  Untracked: {result['untracked']}")

        # Show file details if available
        if result.get('files'):
            files = result['files']
            if files.get('modified'):
                console.print("\n[yellow]Modified files:[/yellow]")
                for f in files['modified'][:10]:
                    console.print(f"  • {f}")
                if len(files['modified']) > 10:
                    console.print(f"  ... and {len(files['modified']) - 10} more")


def show_status_table(results: List[Dict[str, Any]], short: bool = False):
    """Show status table for multiple repositories."""
    table = Table(show_header=True, header_style="bold cyan", title="Repository Status")

    table.add_column("Repository", style="green", width=30)
    table.add_column("Branch", style="blue", width=15)
    table.add_column("Status", style="white", width=10)

    if not short:
        table.add_column("Modified", justify="right", style="yellow")
        table.add_column("Untracked", justify="right", style="dim")
        table.add_column("Ahead/Behind", style="cyan")

    for result in results:
        repo = result['repo']
        branch = result['branch']
        status = "clean" if result.get('clean') else "dirty"

        status_style = "green" if result.get('clean') else "yellow"

        row = [
            repo,
            branch,
            f"[{status_style}]{status}[/{status_style}]"
        ]

        if not short:
            row.append(str(result.get('modified', 0)))
            row.append(str(result.get('untracked', 0)))

            # Ahead/behind
            ahead = result.get('ahead', 0)
            behind = result.get('behind', 0)
            ahead_behind = ""
            if ahead > 0:
                ahead_behind += f"↑{ahead}"
            if behind > 0:
                ahead_behind += f" ↓{behind}" if ahead > 0 else f"↓{behind}"
            row.append(ahead_behind if ahead_behind else "—")

        table.add_row(*row)

    console.print(table)

    # Summary
    total = len(results)
    clean = sum(1 for r in results if r.get('clean'))
    dirty = total - clean

    summary = f"\n[cyan]Total: {total} repositories"
    if dirty > 0:
        summary += f" • [yellow]{dirty} with changes"
    if clean > 0:
        summary += f" • [green]{clean} clean"
    summary += "[/cyan]"

    console.print(summary)


@git_cmd.command('log')
@click.argument('vfs_path', default='/repos', required=False)
@click.option('--oneline', is_flag=True, help='Show one line per commit')
@click.option('-n', '--max-count', type=int, default=10, help='Limit number of commits')
@click.option('--since', help='Show commits since date (e.g., "1 week ago")')
@click.option('--author', help='Filter by author')
@click.option('--graph', is_flag=True, help='Show commit graph')
@click.option('--all', 'all_branches', is_flag=True, help='Show all branches')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSONL')
def git_log(vfs_path, oneline, max_count, since, author, graph, all_branches, json_output):
    """Show commit history for repositories.

    VFS_PATH: Virtual filesystem path (default: /repos)

    Shows git log for all repositories at the given VFS path.

    Examples:

    \b
        repoindex git log /repos/myproject --oneline -n 5
        repoindex git log /by-tag/work/active --since="1 week ago"
        repoindex git log /by-language/Python --author="john"
    """
    # Get all repos from VFS path
    repos = get_repos_from_vfs_path(vfs_path)

    if not repos:
        click.echo(f"No repositories found at: {vfs_path}", err=True)
        raise click.Abort()

    # Build git log command
    git_args = ['log']

    if oneline:
        git_args.append('--oneline')
    if graph:
        git_args.append('--graph')
    if all_branches:
        git_args.append('--all')
    if max_count:
        git_args.extend(['-n', str(max_count)])
    if since:
        git_args.append(f'--since={since}')
    if author:
        git_args.append(f'--author={author}')

    # Format for parsing
    if not oneline and not json_output:
        git_args.extend(['--pretty=format:%H|%an|%ae|%at|%s'])

    # Run git log on each repo
    results = []
    for repo_path in repos:
        repo_name = Path(repo_path).name

        output, returncode = run_git(repo_path, git_args)

        if returncode != 0:
            if json_output:
                print(json.dumps({'repo': repo_name, 'path': repo_path, 'error': 'Failed to get log'}))
            continue

        if not output or not output.strip():
            if json_output:
                print(json.dumps({'repo': repo_name, 'path': repo_path, 'commits': []}))
            continue

        # Parse commits
        commits = []
        for line in output.strip().split('\n'):
            if not line:
                continue

            if oneline:
                commits.append({'message': line})
            else:
                parts = line.split('|', 4)
                if len(parts) == 5:
                    commit_hash, author_name, author_email, timestamp, message = parts
                    commits.append({
                        'hash': commit_hash[:8],
                        'author': author_name,
                        'email': author_email,
                        'timestamp': int(timestamp),
                        'message': message
                    })

        results.append({
            'repo': repo_name,
            'path': repo_path,
            'commits': commits
        })

    # Output results
    if json_output:
        for result in results:
            print(json.dumps(result))
    else:
        if len(results) == 1:
            # Single repo - detailed view
            show_detailed_log(results[0], oneline, graph)
        else:
            # Multiple repos - compact view
            show_log_summary(results, oneline)


def show_detailed_log(result: Dict[str, Any], oneline: bool = False, graph: bool = False):
    """Show detailed log for a single repository."""
    repo_name = result['repo']

    console.print(f"\n[bold cyan]Repository:[/bold cyan] {repo_name}")
    console.print(f"[dim]Path: {result['path']}[/dim]\n")

    commits = result.get('commits', [])
    if not commits:
        console.print("[yellow]No commits found[/yellow]")
        return

    for commit in commits:
        if oneline:
            console.print(f"  {commit['message']}")
        else:
            from datetime import datetime
            commit_time = datetime.fromtimestamp(commit['timestamp'])
            console.print(f"[yellow]{commit['hash']}[/yellow] {commit['message']}")
            console.print(f"  [dim]{commit['author']} • {commit_time.strftime('%Y-%m-%d %H:%M')}[/dim]\n")


def show_log_summary(results: List[Dict[str, Any]], oneline: bool = False):
    """Show log summary for multiple repositories."""
    for result in results:
        repo_name = result['repo']
        commits = result.get('commits', [])

        if not commits:
            continue

        console.print(f"\n[bold cyan]━━ {repo_name} ━━[/bold cyan]")

        for i, commit in enumerate(commits[:5]):  # Show max 5 per repo in summary
            if oneline:
                console.print(f"  {commit['message']}")
            else:
                from datetime import datetime
                commit_time = datetime.fromtimestamp(commit['timestamp'])
                console.print(f"  [yellow]{commit['hash']}[/yellow] {commit['message'][:60]}")
                console.print(f"    [dim]{commit['author']} • {commit_time.strftime('%Y-%m-%d %H:%M')}[/dim]")

        if len(commits) > 5:
            console.print(f"  [dim]... and {len(commits) - 5} more commits[/dim]")

    # Summary
    total_repos = len([r for r in results if r.get('commits')])
    total_commits = sum(len(r.get('commits', [])) for r in results)
    console.print(f"\n[cyan]Total: {total_commits} commits across {total_repos} repositories[/cyan]")


@git_cmd.command('diff')
@click.argument('vfs_path', default='/repos', required=False)
@click.option('--name-only', is_flag=True, help='Show only names of changed files')
@click.option('--name-status', is_flag=True, help='Show names and status of changed files')
@click.option('--stat', is_flag=True, help='Show diffstat')
@click.option('--cached', '--staged', is_flag=True, help='Show staged changes')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSONL')
def git_diff(vfs_path, name_only, name_status, stat, cached, json_output):
    """Show changes in repositories.

    VFS_PATH: Virtual filesystem path (default: /repos)

    Shows git diff for all repositories at the given VFS path.

    Examples:

    \b
        repoindex git diff /repos/myproject
        repoindex git diff /by-tag/work/active --stat
        repoindex git diff /by-language/Python --name-only
        repoindex git diff --cached /repos/myproject
    """
    # Get all repos from VFS path
    repos = get_repos_from_vfs_path(vfs_path)

    if not repos:
        click.echo(f"No repositories found at: {vfs_path}", err=True)
        raise click.Abort()

    # Build git diff command
    git_args = ['diff']

    if cached:
        git_args.append('--cached')
    if name_only:
        git_args.append('--name-only')
    elif name_status:
        git_args.append('--name-status')
    elif stat:
        git_args.append('--stat')

    # Run git diff on each repo
    results = []
    for repo_path in repos:
        repo_name = Path(repo_path).name

        output, returncode = run_git(repo_path, git_args)

        if returncode != 0:
            if json_output:
                print(json.dumps({'repo': repo_name, 'path': repo_path, 'error': 'Failed to get diff'}))
            continue

        # Count changes
        has_changes = output and output.strip()

        if name_only or name_status:
            # Parse file list
            files = [line for line in output.strip().split('\n') if line] if output else []
            results.append({
                'repo': repo_name,
                'path': repo_path,
                'has_changes': has_changes,
                'files': files,
                'file_count': len(files)
            })
        elif stat:
            # Parse stat output
            results.append({
                'repo': repo_name,
                'path': repo_path,
                'has_changes': has_changes,
                'stat': output.strip() if output else ''
            })
        else:
            # Full diff
            results.append({
                'repo': repo_name,
                'path': repo_path,
                'has_changes': has_changes,
                'diff': output if output else ''
            })

    # Filter out repos with no changes
    results = [r for r in results if r.get('has_changes')]

    if not results:
        console.print("[green]No changes in any repository[/green]")
        return

    # Output results
    if json_output:
        for result in results:
            print(json.dumps(result))
    else:
        if len(results) == 1:
            # Single repo - show full output
            show_detailed_diff(results[0], name_only, name_status, stat)
        else:
            # Multiple repos - show summary
            show_diff_summary(results, name_only, name_status, stat)


def show_detailed_diff(result: Dict[str, Any], name_only: bool = False,
                      name_status: bool = False, stat: bool = False):
    """Show detailed diff for a single repository."""
    repo_name = result['repo']

    console.print(f"\n[bold cyan]Repository:[/bold cyan] {repo_name}")
    console.print(f"[dim]Path: {result['path']}[/dim]\n")

    if name_only or name_status:
        # Show file list
        files = result.get('files', [])
        if files:
            console.print(f"[yellow]Changed files ({len(files)}):[/yellow]")
            for f in files:
                console.print(f"  {f}")
        else:
            console.print("[green]No changes[/green]")
    elif stat:
        # Show stat
        stat_output = result.get('stat', '')
        if stat_output:
            console.print(stat_output)
        else:
            console.print("[green]No changes[/green]")
    else:
        # Show full diff
        diff = result.get('diff', '')
        if diff:
            from rich.syntax import Syntax
            # Use syntax highlighting for diff
            syntax = Syntax(diff, "diff", theme="monokai", line_numbers=False)
            console.print(syntax)
        else:
            console.print("[green]No changes[/green]")


def show_diff_summary(results: List[Dict[str, Any]], name_only: bool = False,
                     name_status: bool = False, stat: bool = False):
    """Show diff summary for multiple repositories."""
    from rich.panel import Panel

    for result in results:
        repo_name = result['repo']

        console.print(f"\n[bold cyan]━━ {repo_name} ━━[/bold cyan]")

        if name_only or name_status:
            files = result.get('files', [])
            file_count = result.get('file_count', 0)

            if files:
                # Show first 5 files
                for f in files[:5]:
                    console.print(f"  {f}")

                if len(files) > 5:
                    console.print(f"  [dim]... and {len(files) - 5} more files[/dim]")
        elif stat:
            stat_output = result.get('stat', '')
            if stat_output:
                # Show stat summary
                lines = stat_output.split('\n')
                for line in lines[-3:]:  # Show last 3 lines (summary)
                    console.print(f"  {line}")
        else:
            # For full diff, just show that changes exist
            console.print(f"  [yellow]Repository has uncommitted changes[/yellow]")
            console.print(f"  [dim]Run 'repoindex git diff /repos/{repo_name}' for full diff[/dim]")

    # Summary
    total_repos = len(results)
    if name_only or name_status:
        total_files = sum(r.get('file_count', 0) for r in results)
        console.print(f"\n[cyan]Total: {total_files} changed files across {total_repos} repositories[/cyan]")
    else:
        console.print(f"\n[cyan]Total: {total_repos} repositories with changes[/cyan]")

