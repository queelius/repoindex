"""
Top-style repository activity monitor.

Shows recent activity across all repositories.
"""

import click
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

from ..config import load_config
from ..utils import find_git_repos_from_config, run_command
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
import time

console = Console()


def get_recent_activity(repo_path: str, since_hours: int = 24) -> List[Dict[str, Any]]:
    """Get recent commits from a repository.

    Args:
        repo_path: Path to repository
        since_hours: Hours to look back

    Returns:
        List of commit dictionaries
    """
    since_time = datetime.now() - timedelta(hours=since_hours)
    since_str = since_time.strftime("%Y-%m-%d %H:%M:%S")

    # Get commits since the specified time
    cmd = [
        'git', 'log',
        f'--since={since_str}',
        '--pretty=format:%H|%an|%ae|%at|%s',
        '--all'
    ]

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False)

    if returncode != 0 or not output:
        return []

    commits = []
    for line in output.strip().split('\n'):
        if not line:
            continue

        parts = line.split('|', 4)
        if len(parts) != 5:
            continue

        commit_hash, author_name, author_email, timestamp, message = parts

        commits.append({
            'repo': Path(repo_path).name,
            'repo_path': repo_path,
            'hash': commit_hash[:8],
            'author': author_name,
            'email': author_email,
            'timestamp': int(timestamp),
            'message': message[:80]  # Truncate long messages
        })

    return commits


def get_repo_file_changes(repo_path: str, since_hours: int = 24) -> Dict[str, int]:
    """Get file change statistics.

    Args:
        repo_path: Path to repository
        since_hours: Hours to look back

    Returns:
        Dictionary with change statistics
    """
    since_time = datetime.now() - timedelta(hours=since_hours)
    since_str = since_time.strftime("%Y-%m-%d %H:%M:%S")

    # Get file change stats
    cmd = [
        'git', 'log',
        f'--since={since_str}',
        '--numstat',
        '--pretty=format:',
        '--all'
    ]

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False)

    if returncode != 0 or not output:
        return {'additions': 0, 'deletions': 0, 'files_changed': 0}

    additions = 0
    deletions = 0
    files = set()

    for line in output.strip().split('\n'):
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) >= 3:
            try:
                add = int(parts[0]) if parts[0] != '-' else 0
                delete = int(parts[1]) if parts[1] != '-' else 0
                filename = parts[2]

                additions += add
                deletions += delete
                files.add(filename)
            except (ValueError, IndexError):
                continue

    return {
        'additions': additions,
        'deletions': deletions,
        'files_changed': len(files)
    }


@click.command('top')
@click.option('--hours', default=24, help='Hours to look back (default: 24)')
@click.option('--limit', default=20, help='Number of commits to show (default: 20)')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSONL')
@click.option('--watch', '-w', is_flag=True, help='Watch mode (refresh every 10 seconds)')
@click.option('--interval', default=10, help='Refresh interval in watch mode (seconds)')
def top_handler(hours, limit, json_output, watch, interval):
    """Show recent repository activity across all repos.

    Displays a top-style view of recent commits, authors, and activity.

    Examples:
        repoindex top                    # Last 24 hours
        repoindex top --hours 48         # Last 48 hours
        repoindex top --limit 10         # Show only 10 recent commits
        repoindex top --watch            # Watch mode (refresh every 10s)
        repoindex top --json             # JSONL output
    """
    config = load_config()

    if watch and not json_output:
        # Watch mode with live updates
        with Live(generate_top_display(config, hours, limit), refresh_per_second=1) as live:
            try:
                while True:
                    time.sleep(interval)
                    live.update(generate_top_display(config, hours, limit))
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopped watching[/yellow]")
    else:
        # Single display
        if json_output:
            output_json(config, hours, limit)
        else:
            display = generate_top_display(config, hours, limit)
            console.print(display)


def generate_top_display(config: Dict[str, Any], hours: int, limit: int):
    """Generate the top-style display.

    Args:
        config: Configuration dictionary
        hours: Hours to look back
        limit: Number of commits to show

    Returns:
        Rich renderable object
    """
    # Get all repositories
    repo_dirs = config.get('general', {}).get('repository_directories', [])
    repo_paths = find_git_repos_from_config(repo_dirs)

    # Collect all activity
    all_commits = []
    repo_stats = {}

    for repo_path in repo_paths:
        commits = get_recent_activity(repo_path, hours)
        all_commits.extend(commits)

        if commits:
            stats = get_repo_file_changes(repo_path, hours)
            stats['commit_count'] = len(commits)
            repo_stats[Path(repo_path).name] = stats

    # Sort commits by timestamp (most recent first)
    all_commits.sort(key=lambda x: x['timestamp'], reverse=True)

    # Limit commits
    recent_commits = all_commits[:limit]

    # Build summary
    total_commits = len(all_commits)
    total_repos = len(repo_stats)
    active_authors = len(set(c['author'] for c in all_commits))

    # Create header panel
    header = Text()
    header.append(f"Repository Activity Monitor", style="bold cyan")
    header.append(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="dim")
    header.append(f"\nLast {hours} hours • ", style="dim")
    header.append(f"{total_commits} commits • ", style="green")
    header.append(f"{total_repos} active repos • ", style="yellow")
    header.append(f"{active_authors} authors", style="blue")

    header_panel = Panel(header, border_style="cyan")

    # Create commits table
    table = Table(show_header=True, header_style="bold cyan", title="Recent Commits")
    table.add_column("Time", style="yellow", width=8)
    table.add_column("Repository", style="green", width=20)
    table.add_column("Author", style="blue", width=20)
    table.add_column("Hash", style="magenta", width=8)
    table.add_column("Message", style="white")

    for commit in recent_commits:
        # Format timestamp as relative time
        commit_time = datetime.fromtimestamp(commit['timestamp'])
        now = datetime.now()
        delta = now - commit_time

        if delta.total_seconds() < 3600:
            time_str = f"{int(delta.total_seconds() / 60)}m ago"
        elif delta.total_seconds() < 86400:
            time_str = f"{int(delta.total_seconds() / 3600)}h ago"
        else:
            time_str = f"{int(delta.total_seconds() / 86400)}d ago"

        table.add_row(
            time_str,
            commit['repo'],
            commit['author'],
            commit['hash'],
            commit['message']
        )

    # Create repository stats table
    stats_table = Table(show_header=True, header_style="bold cyan", title="Repository Stats")
    stats_table.add_column("Repository", style="green")
    stats_table.add_column("Commits", justify="right", style="yellow")
    stats_table.add_column("+Lines", justify="right", style="bright_green")
    stats_table.add_column("-Lines", justify="right", style="bright_red")
    stats_table.add_column("Files", justify="right", style="blue")

    for repo_name, stats in sorted(repo_stats.items(), key=lambda x: x[1]['commit_count'], reverse=True):
        stats_table.add_row(
            repo_name,
            str(stats['commit_count']),
            str(stats['additions']),
            str(stats['deletions']),
            str(stats['files_changed'])
        )

    # Combine into layout
    from rich.console import Group
    return Group(header_panel, "", table, "", stats_table)


def output_json(config: Dict[str, Any], hours: int, limit: int):
    """Output activity as JSONL.

    Args:
        config: Configuration dictionary
        hours: Hours to look back
        limit: Number of commits to show
    """
    # Get all repositories
    repo_dirs = config.get('general', {}).get('repository_directories', [])
    repo_paths = find_git_repos_from_config(repo_dirs)

    # Collect all activity
    all_commits = []

    for repo_path in repo_paths:
        commits = get_recent_activity(repo_path, hours)
        all_commits.extend(commits)

    # Sort commits by timestamp (most recent first)
    all_commits.sort(key=lambda x: x['timestamp'], reverse=True)

    # Limit and output
    for commit in all_commits[:limit]:
        print(json.dumps(commit))
