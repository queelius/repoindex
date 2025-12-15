"""
Event scanning for ghops.

Provides stateless event detection across repositories:
- Scan for git tags, releases, commits
- Filter by time, type, repo
- Output as stream (JSONL) for external consumption

ghops is read-only: it detects and reports events, but does not
dispatch or take actions. External tools consume the event stream.
"""

from typing import Dict, Any, List, Optional, Generator
from datetime import datetime, timedelta
from pathlib import Path
import re
import logging

from .utils import run_command
# Import Event from domain layer for backward compatibility
from .domain.event import Event

logger = logging.getLogger(__name__)

# Re-export Event for backward compatibility
__all__ = ['Event', 'parse_timespec', 'scan_git_tags', 'scan_commits', 'scan_events', 'get_recent_events', 'events_to_jsonl']


# =============================================================================
# TIME PARSING
# =============================================================================

def parse_timespec(spec: str) -> datetime:
    """
    Parse a time specification into a datetime.

    Supports:
        - Relative: "1h", "2d", "7d", "1w", "30m"
        - ISO format: "2024-01-15", "2024-01-15T10:30:00"
        - Date: "2024-01-15"

    Args:
        spec: Time specification string

    Returns:
        datetime object

    Raises:
        ValueError: If spec cannot be parsed
    """
    spec = spec.strip()

    # Try relative time (e.g., "1h", "2d", "7d", "30m", "1w")
    relative_match = re.match(r'^(\d+)([mhdwM])$', spec)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)

        units = {
            'm': timedelta(minutes=amount),
            'h': timedelta(hours=amount),
            'd': timedelta(days=amount),
            'w': timedelta(weeks=amount),
            'M': timedelta(days=amount * 30),  # Approximate month
        }

        return datetime.now() - units[unit]

    # Try ISO format with time
    try:
        return datetime.fromisoformat(spec)
    except ValueError:
        pass

    # Try date only (YYYY-MM-DD)
    try:
        return datetime.strptime(spec, '%Y-%m-%d')
    except ValueError:
        pass

    raise ValueError(f"Cannot parse time specification: {spec}")


# =============================================================================
# EVENT SCANNING
# =============================================================================

def scan_git_tags(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan a repository for git tags.

    Args:
        repo_path: Path to git repository
        since: Only tags after this time
        until: Only tags before this time
        limit: Maximum tags to return per repo

    Yields:
        Event objects for each tag found
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Get tags with metadata
    # Format: tag_name|date|commit|tagger|message
    cmd = '''git for-each-ref --sort=-creatordate \
             --format='%(refname:short)|%(creatordate:iso8601)|%(objectname:short)|%(taggeremail)|%(subject)' \
             refs/tags'''

    if limit:
        cmd += f' --count={limit * 2}'  # Get extra in case we filter some out

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    count = 0
    for line in output.strip().split('\n'):
        if not line or '|' not in line:
            continue

        parts = line.split('|', 4)
        if len(parts) < 3:
            continue

        tag = parts[0].strip()
        date_str = parts[1].strip()
        commit = parts[2].strip()
        tagger = parts[3].strip() if len(parts) > 3 else ''
        message = parts[4].strip() if len(parts) > 4 else ''

        # Parse date
        try:
            # Handle git's ISO format with timezone
            tag_date = datetime.fromisoformat(date_str.replace(' ', 'T').replace(' +', '+').replace(' -', '-'))
            # Convert to naive datetime for comparison
            if tag_date.tzinfo:
                tag_date = tag_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            tag_date = datetime.now()

        # Apply time filters
        if since and tag_date < since:
            continue
        if until and tag_date > until:
            continue

        yield Event(
            type='git_tag',
            timestamp=tag_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'tag': tag,
                'commit': commit,
                'tagger': tagger,
                'message': message
            }
        )

        count += 1
        if limit and count >= limit:
            break


def scan_commits(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan a repository for recent commits.

    Args:
        repo_path: Path to git repository
        since: Only commits after this time
        until: Only commits before this time
        limit: Maximum commits to return

    Yields:
        Event objects for each commit found
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Build git log command
    cmd = 'git log --format="%H|%aI|%an|%ae|%s"'

    if since:
        cmd += f' --since="{since.isoformat()}"'
    if until:
        cmd += f' --until="{until.isoformat()}"'
    if limit:
        cmd += f' -n {limit}'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    for line in output.strip().split('\n'):
        if not line or '|' not in line:
            continue

        parts = line.split('|', 4)
        if len(parts) < 5:
            continue

        commit_hash = parts[0].strip()
        date_str = parts[1].strip()
        author_name = parts[2].strip()
        author_email = parts[3].strip()
        message = parts[4].strip()

        try:
            commit_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if commit_date.tzinfo:
                commit_date = commit_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            commit_date = datetime.now()

        yield Event(
            type='commit',
            timestamp=commit_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'hash': commit_hash,
                'author': author_name,
                'email': author_email,
                'message': message
            }
        )


def scan_events(
    repos: List[str],
    types: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
    repo_filter: Optional[str] = None
) -> Generator[Event, None, None]:
    """
    Scan multiple repositories for events.

    Args:
        repos: List of repository paths
        types: Event types to scan for (default: ['git_tag'])
        since: Only events after this time
        until: Only events before this time
        limit: Maximum total events to return
        repo_filter: Only scan repos matching this name

    Yields:
        Event objects sorted by timestamp (newest first)
    """
    if types is None:
        types = ['git_tag']

    # Collect all events first for sorting
    all_events = []

    for repo_path in repos:
        repo_name = Path(repo_path).name

        # Apply repo filter
        if repo_filter and repo_name != repo_filter:
            continue

        # Scan for each type
        if 'git_tag' in types:
            for event in scan_git_tags(repo_path, since, until):
                all_events.append(event)

        if 'commit' in types:
            # Limit commits per repo to avoid explosion
            for event in scan_commits(repo_path, since, until, limit=50):
                all_events.append(event)

    # Sort by timestamp (newest first)
    all_events.sort(key=lambda e: e.timestamp, reverse=True)

    # Apply global limit
    count = 0
    for event in all_events:
        yield event
        count += 1
        if limit and count >= limit:
            break


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_recent_events(
    repos: List[str],
    days: int = 7,
    types: Optional[List[str]] = None,
    limit: int = 50
) -> List[Event]:
    """
    Get recent events as a list.

    Convenience function for common use case.

    Args:
        repos: List of repository paths
        days: Look back this many days
        types: Event types (default: ['git_tag'])
        limit: Maximum events

    Returns:
        List of Event objects
    """
    since = datetime.now() - timedelta(days=days)
    return list(scan_events(repos, types, since=since, limit=limit))


def events_to_jsonl(events: List[Event]) -> str:
    """Convert list of events to JSONL string."""
    return '\n'.join(e.to_jsonl() for e in events)
