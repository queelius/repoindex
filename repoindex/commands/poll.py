"""
Event scanning command for repoindex.

Scans repositories for events and outputs them as a stream.
repoindex is read-only: it observes and reports, external tools consume the stream.

Local events (default, fast):
- git_tag, commit, branch, merge

Remote events (opt-in, uses APIs):
- --github: github_release, pr, issue, workflow_run
- --pypi: pypi_publish
- --cran: cran_publish
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
                  'git_tag', 'commit', 'branch', 'merge',
                  'github_release', 'pr', 'issue', 'workflow_run',
                  'pypi_publish', 'cran_publish'
              ]),
              help='Filter to specific event types')
@click.option('--github', '-g', is_flag=True,
              help='Include GitHub events (releases, PRs, issues, workflows)')
@click.option('--pypi', is_flag=True,
              help='Include PyPI publish events')
@click.option('--cran', is_flag=True,
              help='Include CRAN publish events')
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
              default=50,
              help='Maximum events to output (default: 50)')
@click.option('--pretty', '-p', is_flag=True,
              help='Human-readable table output (default: JSONL)')
def events_handler(event_types, github, pypi, cran, include_all, repo, since, until, watch, interval, limit, pretty):
    """
    Scan repositories for events.

    By default scans local git events (fast). Use flags to include remote events.

    \b
    Local Events (default, fast):
      git_tag    Git tags (versions, releases)
      commit     Git commits
      branch     Branch creation (from reflog)
      merge      Merge commits

    \b
    Remote Events (opt-in, rate-limited):
      --github   GitHub releases, PRs, issues, workflow runs
      --pypi     PyPI package publishes
      --cran     CRAN package publishes
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

      # All events (local + remote)
      repoindex events --all --since 7d

      # Watch for new events
      repoindex events --watch --github

      # Pretty print
      repoindex events --since 1d --pretty
    """
    from ..config import load_config
    from ..utils import find_git_repos_from_config
    from ..events import (
        scan_events, parse_timespec,
        LOCAL_EVENT_TYPES, GITHUB_EVENT_TYPES, PYPI_EVENT_TYPES, CRAN_EVENT_TYPES, ALL_EVENT_TYPES
    )
    from ..render import render_table

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
        types = _build_event_types(event_types, github, pypi, cran, include_all)

        if watch:
            _run_watch_mode(repos, types, repo, interval, pretty)
        else:
            _run_single_scan(repos, types, repo, since_dt, until_dt, limit, pretty)

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


def _build_event_types(event_types, github: bool, pypi: bool, cran: bool, include_all: bool) -> List[str]:
    """Build the list of event types based on flags."""
    from ..events import LOCAL_EVENT_TYPES, GITHUB_EVENT_TYPES, PYPI_EVENT_TYPES, CRAN_EVENT_TYPES, ALL_EVENT_TYPES

    # If specific types were provided via --type, use those
    if event_types:
        return list(event_types)

    # If --all, return everything
    if include_all:
        return ALL_EVENT_TYPES.copy()

    # Start with local types (default)
    types = LOCAL_EVENT_TYPES.copy()

    # Add remote types based on flags
    if github:
        types.extend(GITHUB_EVENT_TYPES)
    if pypi:
        types.extend(PYPI_EVENT_TYPES)
    if cran:
        types.extend(CRAN_EVENT_TYPES)

    return types


def _run_single_scan(repos, types, repo_filter, since, until, limit, pretty):
    """Run a single event scan."""
    from ..events import scan_events
    from ..render import render_table

    events = list(scan_events(
        repos,
        types=types,
        since=since,
        until=until,
        limit=limit,
        repo_filter=repo_filter
    ))

    if pretty:
        if not events:
            click.echo("No events found")
            return

        click.echo(f"\nFound {len(events)} event(s):\n")

        headers = ['type', 'repo', 'timestamp', 'details']
        rows = []
        for e in events:
            details = _get_event_details(e)
            rows.append([
                e.type,
                e.repo_name,
                e.timestamp.strftime('%Y-%m-%d %H:%M'),
                details
            ])

        render_table(headers, rows)
    else:
        # JSONL output
        for event in events:
            print(event.to_jsonl(), flush=True)


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
    elif e.type == 'pypi_publish':
        return f"{d.get('package', '')} v{d.get('version', '')}"
    elif e.type == 'cran_publish':
        return f"{d.get('package', '')} v{d.get('version', '')}"
    else:
        return str(d)[:50]


def _run_watch_mode(repos, types, repo_filter, interval, pretty):
    """Run continuous watch mode."""
    from ..events import scan_events
    from datetime import datetime

    if pretty:
        click.echo(f"Watching {len(repos)} repositories for events...")
        click.echo(f"Types: {', '.join(types)}")
        click.echo(f"Interval: {interval}s")
        click.echo("Press Ctrl+C to stop\n")

    # Track seen events by ID to avoid duplicates
    seen_ids: Set[str] = set()

    # Start watching from now
    last_check = datetime.now()

    while True:
        try:
            # Scan for events since last check
            events = list(scan_events(
                repos,
                types=types,
                since=last_check,
                repo_filter=repo_filter
            ))

            # Filter out already-seen events
            new_events = [e for e in events if e.id not in seen_ids]

            # Output new events
            for event in new_events:
                seen_ids.add(event.id)

                if pretty:
                    _print_event_pretty(event)
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


def _print_event_pretty(event):
    """Print a single event in pretty format."""
    timestamp = event.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    d = event.data

    emoji_map = {
        'git_tag': '🏷️ ',
        'commit': '📝',
        'branch': '🌿',
        'merge': '🔀',
        'github_release': '🚀',
        'pr': '🔃',
        'issue': '🐛',
        'workflow_run': '⚙️ ',
        'pypi_publish': '📦',
        'cran_publish': '📊',
    }

    emoji = emoji_map.get(event.type, '📌')
    details = _get_event_details(event)

    click.echo(f"[{timestamp}] {emoji} {event.type:15} {event.repo_name}: {details}")
