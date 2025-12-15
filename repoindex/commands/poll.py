"""
Event scanning command for repoindex.

Scans repositories for events and outputs them as a stream.
repoindex is read-only: it observes and reports, external tools consume the stream.

Local events (default, fast):
- git_tag, commit, branch, merge
- version_bump, deps_update, license_change, ci_config_change, docs_change, readme_change

Remote events (opt-in, uses APIs):
- --github: github_release, pr, issue, workflow_run, security_alert,
            repo_rename, repo_transfer, repo_visibility, repo_archive,
            deployment, fork, star
- --pypi: pypi_publish
- --cran: cran_publish
- --npm: npm_publish
- --cargo: cargo_publish
- --docker: docker_publish
- --gem: gem_publish
- --nuget: nuget_publish
- --maven: maven_publish

Config: Set events.default_types in config to customize default event types.
"""

import click
import json
import time
import sys
import logging
from pathlib import Path
from typing import Optional, Set, List

logger = logging.getLogger(__name__)


@click.command('events')
@click.option('--type', '-t', 'event_types',
              multiple=True,
              type=click.Choice([
                  # Local events (fast)
                  'git_tag', 'commit', 'branch', 'merge',
                  'version_bump', 'deps_update', 'license_change', 'ci_config_change', 'docs_change', 'readme_change',
                  # GitHub events (opt-in)
                  'github_release', 'pr', 'issue', 'workflow_run', 'security_alert',
                  'repo_rename', 'repo_transfer', 'repo_visibility', 'repo_archive',
                  'deployment', 'fork', 'star',
                  # Registry events (opt-in)
                  'pypi_publish', 'cran_publish', 'npm_publish', 'cargo_publish', 'docker_publish',
                  'gem_publish', 'nuget_publish', 'maven_publish'
              ]),
              help='Filter to specific event types')
@click.option('--github', '-g', is_flag=True,
              help='Include GitHub events (releases, PRs, issues, workflows, security alerts)')
@click.option('--pypi', is_flag=True,
              help='Include PyPI publish events')
@click.option('--cran', is_flag=True,
              help='Include CRAN publish events')
@click.option('--npm', is_flag=True,
              help='Include npm publish events')
@click.option('--cargo', is_flag=True,
              help='Include Cargo (crates.io) publish events')
@click.option('--docker', is_flag=True,
              help='Include Docker Hub publish events')
@click.option('--gem', is_flag=True,
              help='Include RubyGems publish events')
@click.option('--nuget', is_flag=True,
              help='Include NuGet (.NET) publish events')
@click.option('--maven', is_flag=True,
              help='Include Maven Central (Java) publish events')
@click.option('--all', '-a', 'include_all', is_flag=True,
              help='Include all event types (local + remote)')
@click.option('--repo', '-r',
              help='Filter by repository name')
@click.option('--since', '-s',
              help='Events after this time (e.g., 1h, 7d, 2024-01-01)')
@click.option('--until', '-u',
              help='Events before this time')
@click.option('--watch', '-w', is_flag=True,
              help='Continuous monitoring mode')
@click.option('--interval', '-i',
              type=int,
              default=300,
              help='Watch interval in seconds (default: 300)')
@click.option('--limit', '-n',
              type=int,
              default=100,
              help='Maximum events to output (default: 100, use 0 for unlimited)')
@click.option('--pretty', '-p', is_flag=True,
              help='Human-readable table output (default: JSONL)')
@click.option('--stats', is_flag=True,
              help='Show summary statistics for the event window')
@click.option('--relative-time', '-R', is_flag=True,
              help='Show relative timestamps (e.g., "2h ago") instead of absolute')
@click.option('--cache', is_flag=True,
              help='Enable caching for remote API calls (15 min TTL)')
@click.option('--cache-ttl',
              type=int,
              default=900,
              help='Cache TTL in seconds (default: 900 = 15 minutes)')
@click.option('--workers', '-W',
              type=int,
              default=8,
              help='Maximum parallel workers for scanning (default: 8)')
@click.option('--clear-cache', is_flag=True,
              help='Clear event cache and exit')
def events_handler(event_types, github, pypi, cran, npm, cargo, docker, gem, nuget, maven, include_all, repo, since, until, watch, interval, limit, pretty, stats, relative_time, cache, cache_ttl, workers, clear_cache):
    """
    Scan repositories for events.

    By default scans local git events (fast). Use flags to include remote events.

    \b
    Local Events (default, fast):
      git_tag          Git tags (versions, releases)
      commit           Git commits
      branch           Branch creation (from reflog)
      merge            Merge commits
      version_bump     Changes to version files
      deps_update      Dependency file changes
      license_change   LICENSE file modifications
      ci_config_change CI/CD config changes
      docs_change      Documentation changes
      readme_change    README file changes

    \b
    Remote Events (opt-in, rate-limited):
      --github   GitHub releases, PRs, issues, workflow runs, security alerts,
                 repo renames, transfers, visibility changes, archives,
                 deployments, forks, stars
      --pypi     PyPI package publishes
      --cran     CRAN package publishes
      --npm      npm package publishes
      --cargo    Cargo (crates.io) publishes
      --docker   Docker Hub image publishes
      --gem      RubyGems publishes
      --nuget    NuGet (.NET) publishes
      --maven    Maven Central (Java) publishes
      --all      All event types

    \b
    Time Specifications:
      Relative:  1h, 2d, 7d, 1w, 30m
      Absolute:  2024-01-15, 2024-01-15T10:30:00

    \b
    Examples:
      # Local events in last 7 days (default)
      repoindex events --since 7d

      # Only git tags
      repoindex events --type git_tag --since 7d

      # Include GitHub releases and PRs
      repoindex events --github --since 7d

      # Include PyPI publishes
      repoindex events --pypi --since 30d

      # Include npm publishes
      repoindex events --npm --since 30d

      # All events (local + remote)
      repoindex events --all --since 7d

      # Watch for new events
      repoindex events --watch --github

      # Pretty print with colors
      repoindex events --since 1d --pretty

      # Show statistics summary
      repoindex events --since 7d --stats --pretty

      # Relative timestamps ("2h ago" style)
      repoindex events --since 1d --pretty --relative-time

      # Security alerts only
      repoindex events --type security_alert --github

      # Use caching for faster repeated runs with remote APIs
      repoindex events --github --since 7d --cache

      # Custom cache TTL (30 minutes)
      repoindex events --github --cache --cache-ttl 1800

      # Increase parallelism for large collections
      repoindex events --github --workers 16
    """
    from ..config import load_config
    from ..utils import find_git_repos_from_config
    from ..events import (
        scan_events_parallel, parse_timespec, clear_event_cache,
        LOCAL_EVENT_TYPES, LOCAL_METADATA_EVENT_TYPES, GITHUB_EVENT_TYPES,
        PYPI_EVENT_TYPES, CRAN_EVENT_TYPES, NPM_EVENT_TYPES, CARGO_EVENT_TYPES,
        DOCKER_EVENT_TYPES, ALL_EVENT_TYPES
    )
    from ..render import render_table

    # Handle --clear-cache flag early
    if clear_cache:
        count = clear_event_cache()
        if pretty:
            click.echo(f"Cleared {count} cached event file(s)")
        else:
            print(json.dumps({'cache_cleared': count}), flush=True)
        return 0

    try:
        config = load_config()
        repo_dirs = config.get('general', {}).get('repository_directories', [])

        if not repo_dirs:
            if pretty:
                click.echo("No repository directories configured", err=True)
            else:
                print(json.dumps({'error': 'No repository directories configured'}), file=sys.stderr)
            return 1

        repos = find_git_repos_from_config(repo_dirs, recursive=True)

        if not repos:
            if pretty:
                click.echo("No repositories found", err=True)
            else:
                print(json.dumps({'error': 'No repositories found'}), file=sys.stderr)
            return 1

        # Parse time specifications
        since_dt = parse_timespec(since) if since else None
        until_dt = parse_timespec(until) if until else None

        # Build list of event types to scan
        types = _build_event_types(event_types, github, pypi, cran, npm, cargo, docker, gem, nuget, maven, include_all, config)

        if watch:
            _run_watch_mode(repos, types, repo, interval, pretty, relative_time, cache, cache_ttl, workers)
        else:
            _run_single_scan(repos, types, repo, since_dt, until_dt, limit, pretty, stats, relative_time, cache, cache_ttl, workers)

        return 0

    except ValueError as e:
        # Time parsing error
        if pretty:
            click.echo(f"Error: {e}", err=True)
        else:
            print(json.dumps({'error': str(e)}), file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        if pretty:
            click.echo("\nInterrupted", err=True)
        return 130

    except Exception as e:
        logger.error(f"Events scan failed: {e}", exc_info=True)
        if pretty:
            click.echo(f"Error: {e}", err=True)
        else:
            print(json.dumps({'error': str(e)}), file=sys.stderr)
        return 1


def _build_event_types(event_types, github: bool, pypi: bool, cran: bool, npm: bool, cargo: bool, docker: bool, gem: bool, nuget: bool, maven: bool, include_all: bool, config: dict) -> List[str]:
    """Build the list of event types based on flags and config."""
    from ..events import (
        LOCAL_EVENT_TYPES, LOCAL_METADATA_EVENT_TYPES, GITHUB_EVENT_TYPES,
        PYPI_EVENT_TYPES, CRAN_EVENT_TYPES, NPM_EVENT_TYPES, CARGO_EVENT_TYPES,
        DOCKER_EVENT_TYPES, GEM_EVENT_TYPES, NUGET_EVENT_TYPES, MAVEN_EVENT_TYPES,
        DEFAULT_EVENT_TYPES, ALL_EVENT_TYPES
    )

    # If specific types were provided via --type, use those
    if event_types:
        return list(event_types)

    # If --all, return everything
    if include_all:
        return list(ALL_EVENT_TYPES)

    # Check config for default event types
    config_defaults = config.get('events', {}).get('default_types', None)
    if config_defaults and isinstance(config_defaults, list):
        types = list(config_defaults)
    else:
        # Start with local types (default includes basic git + local metadata events)
        # These are fast (no API calls)
        types = list(DEFAULT_EVENT_TYPES)

    # Add remote types based on flags
    if github:
        types.extend(GITHUB_EVENT_TYPES)
    if pypi:
        types.extend(PYPI_EVENT_TYPES)
    if cran:
        types.extend(CRAN_EVENT_TYPES)
    if npm:
        types.extend(NPM_EVENT_TYPES)
    if cargo:
        types.extend(CARGO_EVENT_TYPES)
    if docker:
        types.extend(DOCKER_EVENT_TYPES)
    if gem:
        types.extend(GEM_EVENT_TYPES)
    if nuget:
        types.extend(NUGET_EVENT_TYPES)
    if maven:
        types.extend(MAVEN_EVENT_TYPES)

    return types


def _run_single_scan(repos, types, repo_filter, since, until, limit, pretty, stats, relative_time, use_cache=False, cache_ttl=900, max_workers=8):
    """Run a single event scan using parallel execution."""
    from ..events import scan_events_parallel
    from ..render import render_table
    from rich.console import Console
    from rich.table import Table

    # limit=0 means unlimited
    effective_limit = limit if limit > 0 else None

    events = list(scan_events_parallel(
        repos,
        types=types,
        since=since,
        until=until,
        limit=effective_limit,
        repo_filter=repo_filter,
        max_workers=max_workers,
        use_cache=use_cache,
        cache_ttl=cache_ttl
    ))

    if stats:
        _print_stats(events, since, until, pretty)
        if not pretty:
            return  # Stats only in JSONL mode

    if pretty:
        if not events:
            click.echo("No events found")
            return

        console = Console()
        click.echo(f"\nFound {len(events)} event(s):\n")

        # Use rich table for color coding
        table = Table(show_header=True, header_style="bold")
        table.add_column("Type", style="dim")
        table.add_column("Repository", style="cyan")
        table.add_column("Time", style="yellow")
        table.add_column("Details")

        for e in events:
            details = _get_event_details(e)
            time_str = _format_time(e.timestamp, relative_time)
            type_styled = _style_event_type(e.type)
            table.add_row(type_styled, e.repo_name, time_str, details)

        console.print(table)
    else:
        # JSONL output
        for event in events:
            print(event.to_jsonl(), flush=True)


def _format_time(timestamp, relative: bool = False) -> str:
    """Format a timestamp, optionally as relative time."""
    from datetime import datetime

    if not relative:
        return timestamp.strftime('%Y-%m-%d %H:%M')

    now = datetime.now()
    delta = now - timestamp

    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = seconds // 60
        return f"{mins}m ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    elif seconds < 604800:
        days = seconds // 86400
        return f"{days}d ago"
    elif seconds < 2592000:
        weeks = seconds // 604800
        return f"{weeks}w ago"
    else:
        months = seconds // 2592000
        return f"{months}mo ago"


def _style_event_type(event_type: str) -> str:
    """Return a colored/styled event type string for Rich."""
    # Color mapping for different event types
    colors = {
        # Local git events
        'git_tag': '[bold green]git_tag[/bold green]',
        'commit': '[blue]commit[/blue]',
        'branch': '[cyan]branch[/cyan]',
        'merge': '[magenta]merge[/magenta]',
        # Local metadata events
        'version_bump': '[bold yellow]version_bump[/bold yellow]',
        'deps_update': '[dim yellow]deps_update[/dim yellow]',
        'license_change': '[bold #9370db]license_change[/bold #9370db]',
        'ci_config_change': '[#ffa500]ci_config_change[/#ffa500]',
        'docs_change': '[#87ceeb]docs_change[/#87ceeb]',
        'readme_change': '[#98fb98]readme_change[/#98fb98]',
        # GitHub events
        'github_release': '[bold yellow]github_release[/bold yellow]',
        'pr': '[green]pr[/green]',
        'issue': '[red]issue[/red]',
        'workflow_run': '[dim]workflow_run[/dim]',
        'security_alert': '[bold red]security_alert[/bold red]',
        # GitHub repo events
        'repo_rename': '[bold #ff69b4]repo_rename[/bold #ff69b4]',
        'repo_transfer': '[bold #daa520]repo_transfer[/bold #daa520]',
        'repo_visibility': '[bold #8a2be2]repo_visibility[/bold #8a2be2]',
        'repo_archive': '[dim #808080]repo_archive[/dim #808080]',
        # GitHub additional events
        'deployment': '[bold #00d4aa]deployment[/bold #00d4aa]',
        'fork': '[bold #9370db]fork[/bold #9370db]',
        'star': '[bold #ffd700]star[/bold #ffd700]',
        # Registry events
        'pypi_publish': '[bold cyan]pypi_publish[/bold cyan]',
        'cran_publish': '[bold blue]cran_publish[/bold blue]',
        'npm_publish': '[bold magenta]npm_publish[/bold magenta]',
        'cargo_publish': '[bold #ff6600]cargo_publish[/bold #ff6600]',
        'docker_publish': '[bold #0db7ed]docker_publish[/bold #0db7ed]',
        'gem_publish': '[bold #cc342d]gem_publish[/bold #cc342d]',
        'nuget_publish': '[bold #004880]nuget_publish[/bold #004880]',
        'maven_publish': '[bold #c71a36]maven_publish[/bold #c71a36]',
    }
    return colors.get(event_type, event_type)


def _print_stats(events, since, until, pretty: bool):
    """Print summary statistics for the events."""
    from collections import Counter
    from datetime import datetime
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    if not events:
        if pretty:
            click.echo("No events found in time window")
        else:
            print(json.dumps({'stats': {'total': 0}}), flush=True)
        return

    # Calculate statistics
    type_counts = Counter(e.type for e in events)
    repo_counts = Counter(e.repo_name for e in events)

    # Time window
    earliest = min(e.timestamp for e in events)
    latest = max(e.timestamp for e in events)

    # Top repos
    top_repos = repo_counts.most_common(5)

    if pretty:
        console = Console()

        # Build stats display
        console.print("\n[bold]Event Statistics[/bold]")
        console.print(f"  Time window: {earliest.strftime('%Y-%m-%d %H:%M')} to {latest.strftime('%Y-%m-%d %H:%M')}")
        console.print(f"  Total events: [bold]{len(events)}[/bold]")
        console.print(f"  Unique repos: {len(repo_counts)}")
        console.print()

        # Events by type table
        type_table = Table(title="Events by Type", show_header=True)
        type_table.add_column("Type")
        type_table.add_column("Count", justify="right")
        type_table.add_column("Bar")

        max_count = max(type_counts.values()) if type_counts else 1
        for event_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            bar_len = int(20 * count / max_count)
            bar = "[green]" + "█" * bar_len + "[/green]"
            type_table.add_row(_style_event_type(event_type), str(count), bar)

        console.print(type_table)
        console.print()

        # Top repos table
        if top_repos:
            repo_table = Table(title="Most Active Repositories", show_header=True)
            repo_table.add_column("Repository", style="cyan")
            repo_table.add_column("Events", justify="right")
            repo_table.add_column("Bar")

            max_repo = top_repos[0][1] if top_repos else 1
            for repo, count in top_repos:
                bar_len = int(20 * count / max_repo)
                bar = "[blue]" + "█" * bar_len + "[/blue]"
                repo_table.add_row(repo, str(count), bar)

            console.print(repo_table)

        console.print()
    else:
        # JSONL stats output
        stats = {
            'stats': {
                'total': len(events),
                'unique_repos': len(repo_counts),
                'earliest': earliest.isoformat(),
                'latest': latest.isoformat(),
                'by_type': dict(type_counts),
                'top_repos': [{'repo': r, 'count': c} for r, c in top_repos]
            }
        }
        print(json.dumps(stats), flush=True)


def _get_event_details(event) -> str:
    """Get a summary string for an event."""
    e = event
    d = e.data

    if e.type == 'git_tag':
        return f"{d.get('tag', '')} - {d.get('message', '')[:40]}"
    elif e.type == 'commit':
        return f"{d.get('hash', '')[:8]} - {d.get('message', '')[:40]}"
    elif e.type == 'branch':
        return f"{d.get('branch', '')} ({d.get('action', '')})"
    elif e.type == 'merge':
        branch = d.get('merged_branch', '')
        return f"Merged {branch}" if branch else d.get('message', '')[:40]
    elif e.type == 'version_bump':
        version = d.get('version', '')
        version_str = f" → v{version}" if version else ""
        return f"{d.get('hash', '')[:8]}{version_str} - {d.get('message', '')[:30]}"
    elif e.type == 'deps_update':
        files = d.get('files', [])
        auto = " [auto]" if d.get('automated') else ""
        files_str = ', '.join(files[:2]) if files else ''
        return f"{d.get('hash', '')[:8]}{auto} {files_str}"
    elif e.type == 'github_release':
        return f"{d.get('tag', '')} - {d.get('name', '')[:30]}"
    elif e.type == 'pr':
        state = 'merged' if d.get('merged') else d.get('state', '')
        return f"#{d.get('number', '')} [{state}] {d.get('title', '')[:30]}"
    elif e.type == 'issue':
        return f"#{d.get('number', '')} [{d.get('state', '')}] {d.get('title', '')[:30]}"
    elif e.type == 'workflow_run':
        conclusion = d.get('conclusion', d.get('status', ''))
        return f"{d.get('name', '')[:20]} [{conclusion}]"
    elif e.type == 'security_alert':
        severity = d.get('severity', 'unknown')
        pkg = d.get('package', '')
        state = d.get('state', '')
        return f"[{severity}] {pkg} [{state}] - {d.get('summary', '')[:25]}"
    elif e.type == 'pypi_publish':
        return f"{d.get('package', '')} v{d.get('version', '')}"
    elif e.type == 'cran_publish':
        return f"{d.get('package', '')} v{d.get('version', '')}"
    elif e.type == 'npm_publish':
        return f"{d.get('package', '')} v{d.get('version', '')}"
    elif e.type == 'cargo_publish':
        yanked = " [yanked]" if d.get('yanked') else ""
        return f"{d.get('package', '')} v{d.get('version', '')}{yanked}"
    elif e.type == 'docker_publish':
        return f"{d.get('image', '')}:{d.get('tag', '')}"
    elif e.type == 'gem_publish':
        return f"{d.get('package', '')} v{d.get('version', '')}"
    elif e.type == 'nuget_publish':
        return f"{d.get('package', '')} v{d.get('version', '')}"
    elif e.type == 'maven_publish':
        return f"{d.get('group', '')}:{d.get('artifact', '')} v{d.get('version', '')}"
    elif e.type == 'license_change':
        old_lic = d.get('old_license', '')
        new_lic = d.get('new_license', '')
        if old_lic and new_lic:
            return f"{old_lic} → {new_lic}"
        return d.get('message', '')[:40] or "License modified"
    elif e.type == 'ci_config_change':
        files = d.get('files', [])
        files_str = ', '.join(files[:2]) if files else 'CI config'
        return f"{d.get('hash', '')[:8]} - {files_str}"
    elif e.type == 'docs_change':
        files = d.get('files', [])
        files_str = ', '.join(files[:2]) if files else 'docs'
        return f"{d.get('hash', '')[:8]} - {files_str}"
    elif e.type == 'readme_change':
        return f"{d.get('hash', '')[:8]} - {d.get('message', '')[:30]}"
    elif e.type == 'repo_rename':
        old_name = d.get('old_name', '')
        new_name = d.get('new_name', '')
        return f"{old_name} → {new_name}"
    elif e.type == 'repo_transfer':
        old_owner = d.get('old_owner', '')
        new_owner = d.get('new_owner', '')
        return f"{old_owner} → {new_owner}"
    elif e.type == 'repo_visibility':
        action = d.get('action', '')
        return f"{action} by {d.get('actor', '')}"
    elif e.type == 'repo_archive':
        archived = d.get('archived', False)
        return "Repository archived" if archived else "Repository unarchived"
    elif e.type == 'deployment':
        env = d.get('environment', 'production')
        ref = d.get('ref', '')[:20]
        creator = d.get('creator', '')
        return f"[{env}] {ref} by {creator}"
    elif e.type == 'fork':
        fork_name = d.get('fork_name', '')
        fork_owner = d.get('fork_owner', '')
        return f"Forked by {fork_owner} → {fork_name}"
    elif e.type == 'star':
        user = d.get('user', '')
        return f"⭐ Starred by {user}"
    else:
        return str(d)[:50]


def _run_watch_mode(repos, types, repo_filter, interval, pretty, relative_time, use_cache=False, cache_ttl=900, max_workers=8):
    """Run continuous watch mode."""
    from ..events import scan_events_parallel
    from datetime import datetime

    if pretty:
        click.echo(f"Watching {len(repos)} repositories for events...")
        click.echo(f"Types: {', '.join(types)}")
        click.echo(f"Interval: {interval}s")
        if use_cache:
            click.echo(f"Cache: enabled (TTL: {cache_ttl}s)")
        click.echo("Press Ctrl+C to stop\n")

    # Track seen events by ID to avoid duplicates
    seen_ids: Set[str] = set()

    # Start watching from now
    last_check = datetime.now()

    while True:
        try:
            # Scan for events since last check
            events = list(scan_events_parallel(
                repos,
                types=types,
                since=last_check,
                repo_filter=repo_filter,
                max_workers=max_workers,
                use_cache=use_cache,
                cache_ttl=cache_ttl
            ))

            # Filter out already-seen events
            new_events = [e for e in events if e.id not in seen_ids]

            # Output new events
            for event in new_events:
                seen_ids.add(event.id)

                if pretty:
                    _print_event_pretty(event, relative_time)
                else:
                    print(event.to_jsonl(), flush=True)

            # Update last check time
            last_check = datetime.now()

            # Sleep until next check
            time.sleep(interval)

        except KeyboardInterrupt:
            if pretty:
                click.echo("\nStopped watching")
            break


def _print_event_pretty(event, relative_time: bool = False):
    """Print a single event in pretty format with colors."""
    from rich.console import Console

    console = Console()
    time_str = _format_time(event.timestamp, relative_time)
    d = event.data

    emoji_map = {
        # Local git events
        'git_tag': '🏷️ ',
        'commit': '📝',
        'branch': '🌿',
        'merge': '🔀',
        # Local metadata events
        'version_bump': '⬆️ ',
        'deps_update': '📋',
        'license_change': '⚖️ ',
        'ci_config_change': '🔧',
        'docs_change': '📚',
        'readme_change': '📄',
        # GitHub events
        'github_release': '🚀',
        'pr': '🔃',
        'issue': '🐛',
        'workflow_run': '⚙️ ',
        'security_alert': '🔒',
        # GitHub repo events
        'repo_rename': '✏️ ',
        'repo_transfer': '🔄',
        'repo_visibility': '👁️ ',
        'repo_archive': '📥',
        # GitHub additional events
        'deployment': '🚢',
        'fork': '🍴',
        'star': '⭐',
        # Registry events
        'pypi_publish': '📦',
        'cran_publish': '📊',
        'npm_publish': '📦',
        'cargo_publish': '🦀',
        'docker_publish': '🐳',
        'gem_publish': '💎',
        'nuget_publish': '🟣',
        'maven_publish': '☕',
    }

    emoji = emoji_map.get(event.type, '📌')
    details = _get_event_details(event)
    type_styled = _style_event_type(event.type)

    console.print(f"[dim][{time_str}][/dim] {emoji} {type_styled:30} [cyan]{event.repo_name}[/cyan]: {details}")
