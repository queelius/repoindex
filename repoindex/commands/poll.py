"""
Event scanning command for ghops.

Scans repositories for events (git tags, releases, commits) and outputs
them as a stream. ghops is read-only: it observes and reports, external
tools consume the stream and take actions.

Provides `ghops events` - unified event scanning command.
"""

import click
import json
import time
import sys
import logging
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)


@click.command('events')
@click.option('--type', '-t', 'event_types',
              multiple=True,
              type=click.Choice(['git_tag', 'commit']),
              help='Filter to specific event types (default: all)')
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
def events_handler(event_types, repo, since, until, watch, interval, limit, pretty):
    """
    Scan repositories for events.

    By default outputs JSONL (one JSON object per line) for easy piping
    to external tools. Use --pretty for human-readable output.

    \b
    Event Types (all shown by default, use --type to filter):
      git_tag    Git tags (versions, releases)
      commit     Git commits

    \b
    Time Specifications:
      Relative:  1h, 2d, 7d, 1w, 30m
      Absolute:  2024-01-15, 2024-01-15T10:30:00

    \b
    Examples:
      # All events in last 7 days (tags + commits)
      repoindex events --since 7d

      # Only git tags
      repoindex events --type git_tag --since 7d

      # Only commits for a specific repo
      repoindex events --type commit --repo myproject

      # Watch for new events, pipe to notification script
      repoindex events --watch | ./notify-releases.sh

      # Pretty print recent events
      repoindex events --since 1d --pretty

    \b
    Output Format (JSONL):
      {"id":"git_tag_repo_v1.0","type":"git_tag","timestamp":"2024-01-15T10:30:00",
       "repo":"myrepo","path":"/path/to/repo","data":{"tag":"v1.0","commit":"abc123"}}
    """
    from ..config import load_config
    from ..utils import find_git_repos_from_config
    from ..events import scan_events, parse_timespec
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

        # Default to all event types, --type filters down
        all_types = ['git_tag', 'commit']
        types = list(event_types) if event_types else all_types

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
            if e.type == 'git_tag':
                details = f"{e.data.get('tag', '')} - {e.data.get('message', '')[:40]}"
            elif e.type == 'commit':
                details = f"{e.data.get('hash', '')[:8]} - {e.data.get('message', '')[:40]}"
            else:
                details = str(e.data)[:50]

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
    from datetime import datetime

    timestamp = event.timestamp.strftime('%Y-%m-%d %H:%M:%S')

    if event.type == 'git_tag':
        tag = event.data.get('tag', 'unknown')
        message = event.data.get('message', '')[:50]
        click.echo(f"[{timestamp}] 🏷️  {event.repo_name}: {tag}")
        if message:
            click.echo(f"    {message}")
    elif event.type == 'commit':
        hash_short = event.data.get('hash', '')[:8]
        message = event.data.get('message', '')[:50]
        author = event.data.get('author', '')
        click.echo(f"[{timestamp}] 📝 {event.repo_name}: {hash_short} by {author}")
        if message:
            click.echo(f"    {message}")
    else:
        click.echo(f"[{timestamp}] {event.type} {event.repo_name}")


