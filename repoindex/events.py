"""
Event scanning for repoindex.

Provides stateless event detection across repositories:

Local events (fast, default):
- git_tag: Git tags
- commit: Git commits
- branch: Branch creation/deletion (from reflog)
- merge: Merge commits
- version_bump: Changes to version files (pyproject.toml, package.json, etc.)
- deps_update: Dependency file changes (requirements.txt, lock files, etc.)
- license_change: LICENSE file modifications
- ci_config_change: CI/CD config changes (.github/workflows, .gitlab-ci.yml, etc.)
- docs_change: Documentation file changes (docs/, *.md excluding README)
- readme_change: README file changes

Remote events (opt-in, rate-limited):
- github_release: GitHub releases (--github)
- pr: Pull requests (--github)
- issue: Issues (--github)
- workflow_run: GitHub Actions (--github)
- security_alert: GitHub Dependabot security alerts (--github)
- repo_rename: Repository renamed (--github)
- repo_transfer: Repository transferred to new owner (--github)
- repo_visibility: Repository visibility changed (public/private) (--github)
- repo_archive: Repository archived/unarchived (--github)
- deployment: GitHub deployments, gh-pages (--github)
- fork: Repository forked by someone (--github)
- star: Repository starred by someone (--github)
- pypi_publish: PyPI releases (--pypi)
- cran_publish: CRAN releases (--cran)
- npm_publish: npm releases (--npm)
- cargo_publish: crates.io releases (--cargo)
- docker_publish: Docker Hub image pushes (--docker)
- gem_publish: RubyGems releases (--gem)
- nuget_publish: NuGet releases (--nuget)
- maven_publish: Maven Central releases (--maven)

Total: 30 event types across multiple categories.

repoindex is read-only: it observes and reports, external tools consume the stream.
"""

from typing import Dict, Any, List, Optional, Generator
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import json
import logging
import hashlib
import time

from .utils import run_command, get_remote_url, parse_repo_url
# Import Event from domain layer for backward compatibility
from .domain.event import Event

logger = logging.getLogger(__name__)

# Event type categories
# Local events are fast (no API calls)
LOCAL_EVENT_TYPES = ['git_tag', 'commit', 'branch', 'merge']
LOCAL_METADATA_EVENT_TYPES = ['version_bump', 'deps_update', 'license_change', 'ci_config_change', 'docs_change', 'readme_change']

# Remote events require API calls (opt-in)
GITHUB_EVENT_TYPES = ['github_release', 'pr', 'issue', 'workflow_run', 'security_alert',
                      'repo_rename', 'repo_transfer', 'repo_visibility', 'repo_archive',
                      'deployment', 'fork', 'star']
PYPI_EVENT_TYPES = ['pypi_publish']
CRAN_EVENT_TYPES = ['cran_publish']
NPM_EVENT_TYPES = ['npm_publish']
CARGO_EVENT_TYPES = ['cargo_publish']
DOCKER_EVENT_TYPES = ['docker_publish']
GEM_EVENT_TYPES = ['gem_publish']
NUGET_EVENT_TYPES = ['nuget_publish']
MAVEN_EVENT_TYPES = ['maven_publish']

# Default events (fast, no API calls)
DEFAULT_EVENT_TYPES = LOCAL_EVENT_TYPES + LOCAL_METADATA_EVENT_TYPES

# Remote event types (require API calls, benefit from caching and parallelization)
REMOTE_EVENT_TYPES = (
    GITHUB_EVENT_TYPES + PYPI_EVENT_TYPES + CRAN_EVENT_TYPES + NPM_EVENT_TYPES +
    CARGO_EVENT_TYPES + DOCKER_EVENT_TYPES + GEM_EVENT_TYPES + NUGET_EVENT_TYPES +
    MAVEN_EVENT_TYPES
)

# All available event types
ALL_EVENT_TYPES = (
    LOCAL_EVENT_TYPES + LOCAL_METADATA_EVENT_TYPES + GITHUB_EVENT_TYPES +
    PYPI_EVENT_TYPES + CRAN_EVENT_TYPES + NPM_EVENT_TYPES + CARGO_EVENT_TYPES +
    DOCKER_EVENT_TYPES + GEM_EVENT_TYPES + NUGET_EVENT_TYPES + MAVEN_EVENT_TYPES
)

# =============================================================================
# CACHING INFRASTRUCTURE
# =============================================================================

# Default cache directory
_CACHE_DIR: Optional[Path] = None
_CACHE_TTL_SECONDS: int = 900  # 15 minutes default

def _get_cache_dir() -> Path:
    """Get the cache directory path, creating it if needed."""
    global _CACHE_DIR
    if _CACHE_DIR is None:
        _CACHE_DIR = Path.home() / '.repoindex' / 'cache'
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _cache_key(repo_path: str, event_type: str, since: Optional[datetime], until: Optional[datetime]) -> str:
    """Generate a cache key for the given parameters."""
    # Round timestamps to 5-minute intervals for better cache hits
    since_str = ""
    until_str = ""
    if since:
        # Round down to nearest 5 minutes
        rounded_since = since.replace(second=0, microsecond=0)
        rounded_since = rounded_since.replace(minute=(since.minute // 5) * 5)
        since_str = rounded_since.isoformat()
    if until:
        rounded_until = until.replace(second=0, microsecond=0)
        rounded_until = rounded_until.replace(minute=(until.minute // 5) * 5)
        until_str = rounded_until.isoformat()

    key_str = f"{repo_path}|{event_type}|{since_str}|{until_str}"
    return hashlib.md5(key_str.encode()).hexdigest()


def _cache_get(key: str, ttl_seconds: int = _CACHE_TTL_SECONDS) -> Optional[List[Dict[str, Any]]]:
    """Get cached data if it exists and is not expired."""
    try:
        cache_file = _get_cache_dir() / f"{key}.json"
        if not cache_file.exists():
            return None

        # Check if cache is expired
        mtime = cache_file.stat().st_mtime
        if time.time() - mtime > ttl_seconds:
            # Cache expired, remove it
            cache_file.unlink(missing_ok=True)
            return None

        with open(cache_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.debug(f"Cache read error: {e}")
        return None


def _cache_set(key: str, events: List[Dict[str, Any]]) -> None:
    """Store events in cache."""
    try:
        cache_file = _get_cache_dir() / f"{key}.json"
        with open(cache_file, 'w') as f:
            json.dump(events, f)
    except Exception as e:
        logger.debug(f"Cache write error: {e}")


def clear_event_cache() -> int:
    """Clear all cached event data. Returns number of files removed."""
    cache_dir = _get_cache_dir()
    count = 0
    for cache_file in cache_dir.glob("*.json"):
        try:
            cache_file.unlink()
            count += 1
        except Exception:
            pass
    return count

# Re-export Event for backward compatibility
__all__ = [
    'Event', 'parse_timespec', 'scan_git_tags', 'scan_commits', 'scan_branches',
    'scan_merges', 'scan_github_releases', 'scan_github_prs', 'scan_github_issues',
    'scan_github_workflows', 'scan_github_security_alerts', 'scan_github_repo_events',
    'scan_github_deployments', 'scan_github_forks', 'scan_github_stars',
    'scan_pypi_publishes', 'scan_cran_publishes',
    'scan_npm_publishes', 'scan_cargo_publishes', 'scan_docker_publishes',
    'scan_gem_publishes', 'scan_nuget_publishes', 'scan_maven_publishes',
    'scan_version_bumps', 'scan_deps_updates',
    'scan_license_changes', 'scan_ci_config_changes', 'scan_docs_changes', 'scan_readme_changes',
    'scan_events', 'scan_events_parallel', 'get_recent_events', 'events_to_jsonl',
    'clear_event_cache',
    'LOCAL_EVENT_TYPES', 'LOCAL_METADATA_EVENT_TYPES', 'GITHUB_EVENT_TYPES',
    'PYPI_EVENT_TYPES', 'CRAN_EVENT_TYPES', 'NPM_EVENT_TYPES', 'CARGO_EVENT_TYPES',
    'DOCKER_EVENT_TYPES', 'GEM_EVENT_TYPES', 'NUGET_EVENT_TYPES', 'MAVEN_EVENT_TYPES',
    'REMOTE_EVENT_TYPES', 'DEFAULT_EVENT_TYPES', 'ALL_EVENT_TYPES'
]


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


def scan_branches(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan a repository for branch creation/deletion events from reflog.

    Args:
        repo_path: Path to git repository
        since: Only events after this time
        until: Only events before this time
        limit: Maximum events to return

    Yields:
        Event objects for branch events
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Get reflog entries for branch operations
    # Format: hash|date|action|message
    cmd = 'git reflog --format="%H|%gd|%gs" --date=iso'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    count = 0
    seen_branches = set()

    for line in output.strip().split('\n'):
        if not line:
            continue

        # Look for branch creation patterns
        if 'branch:' in line.lower() or 'checkout:' in line.lower():
            parts = line.split('|', 2)
            if len(parts) < 3:
                continue

            commit_hash = parts[0].strip()
            _ref_info = parts[1].strip()  # noqa: F841 - parsed but unused
            action_msg = parts[2].strip()

            # Extract branch name from action message
            branch_name = None
            action = None

            if 'created' in action_msg.lower():
                action = 'created'
                # Try to extract branch name
                match = re.search(r'branch: (.+)', action_msg, re.IGNORECASE)
                if match:
                    branch_name = match.group(1).strip()
            elif 'moving from' in action_msg.lower():
                # checkout: moving from X to Y
                match = re.search(r'moving from .+ to (.+)', action_msg)
                if match:
                    branch_name = match.group(1).strip()
                    action = 'checkout'

            if not branch_name or branch_name in seen_branches:
                continue

            seen_branches.add(branch_name)

            # Get the date from the commit
            date_cmd = f'git log -1 --format="%aI" {commit_hash}'
            date_output, _ = run_command(date_cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

            try:
                event_date = datetime.fromisoformat(date_output.strip().replace('Z', '+00:00'))
                if event_date.tzinfo:
                    event_date = event_date.replace(tzinfo=None)
            except (ValueError, AttributeError):
                event_date = datetime.now()

            # Apply time filters
            if since and event_date < since:
                continue
            if until and event_date > until:
                continue

            yield Event(
                type='branch',
                timestamp=event_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'branch': branch_name,
                    'action': action,
                    'commit': commit_hash[:8]
                }
            )

            count += 1
            if limit and count >= limit:
                break


def scan_merges(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan a repository for merge commits.

    Args:
        repo_path: Path to git repository
        since: Only merges after this time
        until: Only merges before this time
        limit: Maximum merges to return

    Yields:
        Event objects for merge commits
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Get merge commits (commits with more than one parent)
    cmd = 'git log --merges --format="%H|%aI|%an|%ae|%s"'

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
            merge_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if merge_date.tzinfo:
                merge_date = merge_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            merge_date = datetime.now()

        # Extract merged branch from message (e.g., "Merge branch 'feature' into main")
        merged_branch = None
        match = re.search(r"Merge (?:branch |pull request .+ from )?['\"]?([^'\"]+)['\"]?", message)
        if match:
            merged_branch = match.group(1).strip()

        yield Event(
            type='merge',
            timestamp=merge_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'hash': commit_hash,
                'author': author_name,
                'email': author_email,
                'message': message,
                'merged_branch': merged_branch
            }
        )


# =============================================================================
# GITHUB EVENT SCANNING (opt-in, uses gh CLI)
# =============================================================================

def _get_github_repo_info(repo_path: str) -> Optional[tuple]:
    """Get GitHub owner/repo from a local repository."""
    remote_url = get_remote_url(repo_path)
    if not remote_url:
        return None

    owner, name = parse_repo_url(remote_url)
    if not owner or not name:
        return None

    return (owner, name)


def scan_github_releases(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan GitHub releases for a repository.

    Requires: gh CLI installed and authenticated.

    Args:
        repo_path: Path to git repository
        since: Only releases after this time
        until: Only releases before this time
        limit: Maximum releases to return

    Yields:
        Event objects for GitHub releases
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI to get releases
    cmd = f'gh api repos/{owner}/{name}/releases --paginate'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        releases = json.loads(output)
    except json.JSONDecodeError:
        return

    count = 0
    for release in releases:
        try:
            published_at = release.get('published_at') or release.get('created_at')
            if not published_at:
                continue

            release_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            if release_date.tzinfo:
                release_date = release_date.replace(tzinfo=None)

            # Apply time filters
            if since and release_date < since:
                continue
            if until and release_date > until:
                continue

            yield Event(
                type='github_release',
                timestamp=release_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'tag': release.get('tag_name', ''),
                    'name': release.get('name', ''),
                    'body': (release.get('body') or '')[:500],  # Truncate long release notes
                    'draft': release.get('draft', False),
                    'prerelease': release.get('prerelease', False),
                    'author': release.get('author', {}).get('login', ''),
                    'assets': len(release.get('assets', [])),
                    'url': release.get('html_url', '')
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Error parsing release: {e}")
            continue


def scan_github_prs(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
    state: str = 'all'
) -> Generator[Event, None, None]:
    """
    Scan GitHub pull requests for a repository.

    Requires: gh CLI installed and authenticated.

    Args:
        repo_path: Path to git repository
        since: Only PRs updated after this time
        until: Only PRs updated before this time
        limit: Maximum PRs to return
        state: PR state filter ('open', 'closed', 'merged', 'all')

    Yields:
        Event objects for pull requests
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI to get PRs
    # Note: state_filter is computed but we use state=all in the hardcoded URL
    cmd = f'gh api "repos/{owner}/{name}/pulls?state=all&sort=updated&direction=desc&per_page=100"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        prs = json.loads(output)
    except json.JSONDecodeError:
        return

    count = 0
    for pr in prs:
        try:
            # Use updated_at as the event timestamp
            updated_at = pr.get('updated_at')
            if not updated_at:
                continue

            pr_date = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            if pr_date.tzinfo:
                pr_date = pr_date.replace(tzinfo=None)

            # Apply time filters
            if since and pr_date < since:
                continue
            if until and pr_date > until:
                continue

            yield Event(
                type='pr',
                timestamp=pr_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'number': pr.get('number'),
                    'title': pr.get('title', ''),
                    'state': pr.get('state', ''),
                    'merged': pr.get('merged_at') is not None,
                    'author': pr.get('user', {}).get('login', ''),
                    'base': pr.get('base', {}).get('ref', ''),
                    'head': pr.get('head', {}).get('ref', ''),
                    'url': pr.get('html_url', '')
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Error parsing PR: {e}")
            continue


def scan_github_issues(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
    state: str = 'all'
) -> Generator[Event, None, None]:
    """
    Scan GitHub issues for a repository.

    Requires: gh CLI installed and authenticated.

    Args:
        repo_path: Path to git repository
        since: Only issues updated after this time
        until: Only issues updated before this time
        limit: Maximum issues to return
        state: Issue state filter ('open', 'closed', 'all')

    Yields:
        Event objects for issues
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI to get issues (excluding PRs)
    cmd = f'gh api "repos/{owner}/{name}/issues?state=all&sort=updated&direction=desc&per_page=100"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        issues = json.loads(output)
    except json.JSONDecodeError:
        return

    count = 0
    for issue in issues:
        try:
            # Skip pull requests (they show up in issues API too)
            if 'pull_request' in issue:
                continue

            updated_at = issue.get('updated_at')
            if not updated_at:
                continue

            issue_date = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            if issue_date.tzinfo:
                issue_date = issue_date.replace(tzinfo=None)

            # Apply time filters
            if since and issue_date < since:
                continue
            if until and issue_date > until:
                continue

            labels = [label.get('name', '') for label in issue.get('labels', [])]

            yield Event(
                type='issue',
                timestamp=issue_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'number': issue.get('number'),
                    'title': issue.get('title', ''),
                    'state': issue.get('state', ''),
                    'author': issue.get('user', {}).get('login', ''),
                    'labels': labels,
                    'comments': issue.get('comments', 0),
                    'url': issue.get('html_url', '')
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Error parsing issue: {e}")
            continue


def scan_github_workflows(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan GitHub Actions workflow runs for a repository.

    Requires: gh CLI installed and authenticated.

    Args:
        repo_path: Path to git repository
        since: Only runs after this time
        until: Only runs before this time
        limit: Maximum runs to return

    Yields:
        Event objects for workflow runs
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI to get workflow runs
    cmd = f'gh api "repos/{owner}/{name}/actions/runs?per_page=100"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        data = json.loads(output)
        runs = data.get('workflow_runs', [])
    except json.JSONDecodeError:
        return

    count = 0
    for run in runs:
        try:
            created_at = run.get('created_at')
            if not created_at:
                continue

            run_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if run_date.tzinfo:
                run_date = run_date.replace(tzinfo=None)

            # Apply time filters
            if since and run_date < since:
                continue
            if until and run_date > until:
                continue

            yield Event(
                type='workflow_run',
                timestamp=run_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'id': run.get('id'),
                    'name': run.get('name', ''),
                    'workflow': run.get('workflow_id'),
                    'status': run.get('status', ''),
                    'conclusion': run.get('conclusion', ''),
                    'branch': run.get('head_branch', ''),
                    'event': run.get('event', ''),
                    'actor': run.get('actor', {}).get('login', ''),
                    'url': run.get('html_url', '')
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Error parsing workflow run: {e}")
            continue


# =============================================================================
# PYPI EVENT SCANNING (opt-in)
# =============================================================================

def scan_pypi_publishes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan PyPI for package releases related to a repository.

    Looks for pyproject.toml or setup.py to determine package name.

    Args:
        repo_path: Path to git repository
        since: Only releases after this time
        until: Only releases before this time
        limit: Maximum releases to return

    Yields:
        Event objects for PyPI releases
    """
    import requests

    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Try to determine package name from pyproject.toml or setup.py
    package_name = None

    pyproject_path = Path(repo_path) / 'pyproject.toml'
    if pyproject_path.exists():
        try:
            import tomllib
            with open(pyproject_path, 'rb') as f:
                pyproject = tomllib.load(f)
            package_name = pyproject.get('project', {}).get('name')
        except Exception:
            pass

    if not package_name:
        setup_py = Path(repo_path) / 'setup.py'
        if setup_py.exists():
            # Simple extraction - look for name= in setup()
            try:
                content = setup_py.read_text()
                match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    package_name = match.group(1)
            except Exception:
                pass

    if not package_name:
        return

    # Query PyPI API
    try:
        response = requests.get(f'https://pypi.org/pypi/{package_name}/json', timeout=10)
        if response.status_code != 200:
            return

        data = response.json()
    except Exception:
        return

    count = 0
    releases = data.get('releases', {})

    # Sort by upload time (newest first)
    release_items = []
    for version, files in releases.items():
        if not files:
            continue
        # Get the earliest upload time for this version
        upload_time = min(f.get('upload_time', '') for f in files if f.get('upload_time'))
        if upload_time:
            release_items.append((version, upload_time, files))

    release_items.sort(key=lambda x: x[1], reverse=True)

    for version, upload_time, files in release_items:
        try:
            release_date = datetime.fromisoformat(upload_time)

            # Apply time filters
            if since and release_date < since:
                continue
            if until and release_date > until:
                continue

            yield Event(
                type='pypi_publish',
                timestamp=release_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'package': package_name,
                    'version': version,
                    'files': len(files),
                    'url': f'https://pypi.org/project/{package_name}/{version}/'
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (ValueError, TypeError) as e:
            logger.debug(f"Error parsing PyPI release: {e}")
            continue


# =============================================================================
# CRAN EVENT SCANNING (opt-in)
# =============================================================================

def scan_cran_publishes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan CRAN for R package releases related to a repository.

    Looks for DESCRIPTION file to determine package name.

    Args:
        repo_path: Path to git repository
        since: Only releases after this time
        until: Only releases before this time
        limit: Maximum releases to return

    Yields:
        Event objects for CRAN releases
    """
    import requests

    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Check for DESCRIPTION file (R package indicator)
    desc_path = Path(repo_path) / 'DESCRIPTION'
    if not desc_path.exists():
        return

    # Parse DESCRIPTION for package name
    package_name = None
    try:
        content = desc_path.read_text()
        match = re.search(r'^Package:\s*(.+)$', content, re.MULTILINE)
        if match:
            package_name = match.group(1).strip()
    except Exception:
        return

    if not package_name:
        return

    # Query CRAN API
    try:
        response = requests.get(
            f'https://crandb.r-pkg.org/{package_name}/all',
            timeout=10
        )
        if response.status_code != 200:
            return

        data = response.json()
    except Exception:
        return

    count = 0
    versions = data.get('versions', {})

    # Sort by date (newest first)
    version_items = []
    for version, info in versions.items():
        date_str = info.get('Date/Publication') or info.get('Packaged', '').split(';')[0]
        if date_str:
            version_items.append((version, date_str, info))

    version_items.sort(key=lambda x: x[1], reverse=True)

    for version, date_str, info in version_items:
        try:
            # CRAN dates can be in various formats
            release_date = None
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d']:
                try:
                    release_date = datetime.strptime(date_str.split(' UTC')[0].strip(), fmt)
                    break
                except ValueError:
                    continue

            if not release_date:
                continue

            # Apply time filters
            if since and release_date < since:
                continue
            if until and release_date > until:
                continue

            yield Event(
                type='cran_publish',
                timestamp=release_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'package': package_name,
                    'version': version,
                    'title': info.get('Title', ''),
                    'maintainer': info.get('Maintainer', ''),
                    'url': f'https://cran.r-project.org/package={package_name}'
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (ValueError, TypeError) as e:
            logger.debug(f"Error parsing CRAN release: {e}")
            continue


# =============================================================================
# NPM EVENT SCANNING (opt-in)
# =============================================================================

def scan_npm_publishes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan npm registry for package releases related to a repository.

    Looks for package.json to determine package name.

    Args:
        repo_path: Path to git repository
        since: Only releases after this time
        until: Only releases before this time
        limit: Maximum releases to return

    Yields:
        Event objects for npm releases
    """
    import requests

    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Check for package.json
    package_json_path = Path(repo_path) / 'package.json'
    if not package_json_path.exists():
        return

    # Parse package.json for package name
    package_name = None
    try:
        import json
        with open(package_json_path) as f:
            pkg = json.load(f)
        package_name = pkg.get('name')
        # Skip private packages
        if pkg.get('private'):
            return
    except Exception:
        return

    if not package_name:
        return

    # Query npm registry
    try:
        response = requests.get(f'https://registry.npmjs.org/{package_name}', timeout=10)
        if response.status_code != 200:
            return

        data = response.json()
    except Exception:
        return

    count = 0
    time_info = data.get('time', {})

    # Sort by publish time (newest first)
    version_times = []
    for version, time_str in time_info.items():
        if version in ('created', 'modified'):
            continue
        try:
            release_date = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            if release_date.tzinfo:
                release_date = release_date.replace(tzinfo=None)
            version_times.append((version, release_date))
        except (ValueError, TypeError):
            continue

    version_times.sort(key=lambda x: x[1], reverse=True)

    for version, release_date in version_times:
        # Apply time filters
        if since and release_date < since:
            continue
        if until and release_date > until:
            continue

        yield Event(
            type='npm_publish',
            timestamp=release_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'package': package_name,
                'version': version,
                'url': f'https://www.npmjs.com/package/{package_name}/v/{version}'
            }
        )

        count += 1
        if limit and count >= limit:
            break


# =============================================================================
# CARGO (RUST) EVENT SCANNING (opt-in)
# =============================================================================

def scan_cargo_publishes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan crates.io for Rust package releases related to a repository.

    Looks for Cargo.toml to determine package name.

    Args:
        repo_path: Path to git repository
        since: Only releases after this time
        until: Only releases before this time
        limit: Maximum releases to return

    Yields:
        Event objects for crates.io releases
    """
    import requests

    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Check for Cargo.toml
    cargo_path = Path(repo_path) / 'Cargo.toml'
    if not cargo_path.exists():
        return

    # Parse Cargo.toml for package name
    package_name = None
    try:
        import tomllib
        with open(cargo_path, 'rb') as f:
            cargo = tomllib.load(f)
        package_name = cargo.get('package', {}).get('name')
    except Exception:
        # Try basic regex parsing
        try:
            content = cargo_path.read_text()
            match = re.search(r'^name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if match:
                package_name = match.group(1)
        except Exception:
            return

    if not package_name:
        return

    # Query crates.io API
    try:
        headers = {'User-Agent': 'repoindex (https://github.com/queelius/repoindex)'}
        response = requests.get(
            f'https://crates.io/api/v1/crates/{package_name}/versions',
            headers=headers,
            timeout=10
        )
        if response.status_code != 200:
            return

        data = response.json()
    except Exception:
        return

    count = 0
    versions = data.get('versions', [])

    for v in versions:
        try:
            created_at = v.get('created_at')
            if not created_at:
                continue

            release_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if release_date.tzinfo:
                release_date = release_date.replace(tzinfo=None)

            # Apply time filters
            if since and release_date < since:
                continue
            if until and release_date > until:
                continue

            version = v.get('num', '')

            yield Event(
                type='cargo_publish',
                timestamp=release_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'package': package_name,
                    'version': version,
                    'downloads': v.get('downloads', 0),
                    'yanked': v.get('yanked', False),
                    'url': f'https://crates.io/crates/{package_name}/{version}'
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (ValueError, TypeError) as e:
            logger.debug(f"Error parsing crates.io release: {e}")
            continue


# =============================================================================
# DOCKER EVENT SCANNING (opt-in)
# =============================================================================

def scan_docker_publishes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan Docker Hub for image tags related to a repository.

    Attempts to derive Docker Hub namespace from GitHub remote URL.

    Args:
        repo_path: Path to git repository
        since: Only tags after this time
        until: Only tags before this time
        limit: Maximum tags to return

    Yields:
        Event objects for Docker Hub tags
    """
    import requests

    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Check for Dockerfile
    dockerfile_path = Path(repo_path) / 'Dockerfile'
    if not dockerfile_path.exists():
        return

    # Try to derive Docker Hub namespace from GitHub remote
    remote_url = get_remote_url(repo_path)
    if not remote_url:
        return

    owner, name = parse_repo_url(remote_url)
    if not owner or not name:
        return

    # Try common Docker Hub naming patterns
    # 1. owner/repo (most common)
    # 2. repo (official images, unlikely for user repos)
    docker_image = f"{owner}/{name}".lower()

    # Query Docker Hub API
    try:
        response = requests.get(
            f'https://hub.docker.com/v2/repositories/{docker_image}/tags?page_size=100',
            timeout=10
        )
        if response.status_code != 200:
            return

        data = response.json()
    except Exception:
        return

    count = 0
    tags = data.get('results', [])

    for tag in tags:
        try:
            last_updated = tag.get('last_updated')
            if not last_updated:
                continue

            tag_date = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
            if tag_date.tzinfo:
                tag_date = tag_date.replace(tzinfo=None)

            # Apply time filters
            if since and tag_date < since:
                continue
            if until and tag_date > until:
                continue

            tag_name = tag.get('name', '')

            yield Event(
                type='docker_publish',
                timestamp=tag_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'image': docker_image,
                    'tag': tag_name,
                    'size': tag.get('full_size', 0),
                    'digest': tag.get('digest', ''),
                    'url': f'https://hub.docker.com/r/{docker_image}/tags?name={tag_name}'
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (ValueError, TypeError) as e:
            logger.debug(f"Error parsing Docker Hub tag: {e}")
            continue


# =============================================================================
# LOCAL METADATA EVENT SCANNING (fast, no API)
# =============================================================================

def scan_version_bumps(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan git history for version bump events.

    Detects changes to version files: pyproject.toml, package.json, Cargo.toml, etc.

    Args:
        repo_path: Path to git repository
        since: Only events after this time
        until: Only events before this time
        limit: Maximum events to return

    Yields:
        Event objects for version bumps
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Version files to track
    version_files = [
        'pyproject.toml', 'setup.py', 'setup.cfg',
        'package.json',
        'Cargo.toml',
        'version.txt', 'VERSION',
        'pom.xml',
        '*.gemspec'
    ]

    # Build git log command to find commits touching version files
    file_patterns = ' '.join([f'"{f}"' for f in version_files])
    cmd = f'git log --format="%H|%aI|%an|%s" --all -- {file_patterns}'

    if since:
        cmd += f' --since="{since.isoformat()}"'
    if until:
        cmd += f' --until="{until.isoformat()}"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    count = 0
    for line in output.strip().split('\n'):
        if not line or '|' not in line:
            continue

        parts = line.split('|', 3)
        if len(parts) < 4:
            continue

        commit_hash = parts[0].strip()
        date_str = parts[1].strip()
        author = parts[2].strip()
        message = parts[3].strip()

        # Check if message suggests version bump
        version_keywords = ['version', 'bump', 'release', 'v0.', 'v1.', 'v2.', 'v3.']
        is_version_commit = any(kw.lower() in message.lower() for kw in version_keywords)

        if not is_version_commit:
            # Also check if the commit actually changed a version number
            diff_cmd = f'git show {commit_hash} --format="" -- {file_patterns}'
            diff_output, _ = run_command(diff_cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)
            if diff_output and re.search(r'[+-].*version.*["\']?\d+\.\d+', diff_output, re.IGNORECASE):
                is_version_commit = True

        if not is_version_commit:
            continue

        try:
            commit_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if commit_date.tzinfo:
                commit_date = commit_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            commit_date = datetime.now()

        # Try to extract version from commit message
        version_match = re.search(r'v?(\d+\.\d+(?:\.\d+)?)', message)
        version = version_match.group(1) if version_match else None

        yield Event(
            type='version_bump',
            timestamp=commit_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'hash': commit_hash[:8],
                'author': author,
                'message': message[:100],
                'version': version
            }
        )

        count += 1
        if limit and count >= limit:
            break


def scan_deps_updates(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan git history for dependency update events.

    Detects changes to dependency files: requirements.txt, package-lock.json, etc.

    Args:
        repo_path: Path to git repository
        since: Only events after this time
        until: Only events before this time
        limit: Maximum events to return

    Yields:
        Event objects for dependency updates
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Dependency files to track
    deps_files = [
        'requirements.txt', 'requirements-*.txt', 'requirements/*.txt',
        'Pipfile.lock', 'poetry.lock',
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
        'Cargo.lock',
        'Gemfile.lock',
        'go.sum',
        'composer.lock'
    ]

    # Build git log command
    file_patterns = ' '.join([f'"{f}"' for f in deps_files])
    cmd = f'git log --format="%H|%aI|%an|%s" --all -- {file_patterns}'

    if since:
        cmd += f' --since="{since.isoformat()}"'
    if until:
        cmd += f' --until="{until.isoformat()}"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    count = 0
    for line in output.strip().split('\n'):
        if not line or '|' not in line:
            continue

        parts = line.split('|', 3)
        if len(parts) < 4:
            continue

        commit_hash = parts[0].strip()
        date_str = parts[1].strip()
        author = parts[2].strip()
        message = parts[3].strip()

        try:
            commit_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if commit_date.tzinfo:
                commit_date = commit_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            commit_date = datetime.now()

        # Detect if this is likely a dependabot/renovate commit
        is_automated = any(bot in author.lower() for bot in ['dependabot', 'renovate', 'greenkeeper', 'snyk'])

        # Get files changed
        files_cmd = f'git show {commit_hash} --name-only --format=""'
        files_output, _ = run_command(files_cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)
        files_changed = [f.strip() for f in files_output.strip().split('\n') if f.strip()] if files_output else []

        yield Event(
            type='deps_update',
            timestamp=commit_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'hash': commit_hash[:8],
                'author': author,
                'message': message[:100],
                'automated': is_automated,
                'files': files_changed[:5]  # Limit to first 5 files
            }
        )

        count += 1
        if limit and count >= limit:
            break


# =============================================================================
# GITHUB SECURITY ALERTS (opt-in, uses gh CLI)
# =============================================================================

def scan_github_security_alerts(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan GitHub Dependabot security alerts for a repository.

    Requires: gh CLI installed and authenticated with appropriate permissions.

    Args:
        repo_path: Path to git repository
        since: Only alerts after this time
        until: Only alerts before this time
        limit: Maximum alerts to return

    Yields:
        Event objects for security alerts
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI to get Dependabot alerts
    cmd = f'gh api repos/{owner}/{name}/dependabot/alerts --paginate'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        alerts = json.loads(output)
    except json.JSONDecodeError:
        return

    count = 0
    for alert in alerts:
        try:
            created_at = alert.get('created_at')
            if not created_at:
                continue

            alert_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if alert_date.tzinfo:
                alert_date = alert_date.replace(tzinfo=None)

            # Apply time filters
            if since and alert_date < since:
                continue
            if until and alert_date > until:
                continue

            security_advisory = alert.get('security_advisory', {})
            dependency = alert.get('dependency', {})
            package_info = dependency.get('package', {})

            severity = security_advisory.get('severity', 'unknown')

            yield Event(
                type='security_alert',
                timestamp=alert_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'number': alert.get('number'),
                    'state': alert.get('state', ''),
                    'severity': severity,
                    'package': package_info.get('name', ''),
                    'ecosystem': package_info.get('ecosystem', ''),
                    'vulnerable_version': dependency.get('manifest_path', ''),
                    'cve': security_advisory.get('cve_id', ''),
                    'summary': security_advisory.get('summary', '')[:100],
                    'url': alert.get('html_url', '')
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Error parsing security alert: {e}")
            continue


# =============================================================================
# GITHUB REPOSITORY EVENTS (opt-in, uses gh CLI)
# =============================================================================

def scan_github_repo_events(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan GitHub repository events (rename, transfer, visibility, archive).

    Uses the GitHub Events API to detect repository-level administrative changes.

    Requires: gh CLI installed and authenticated.

    Args:
        repo_path: Path to git repository
        since: Only events after this time
        until: Only events before this time
        limit: Maximum events to return

    Yields:
        Event objects for repository events (repo_rename, repo_transfer,
        repo_visibility, repo_archive)
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI to get repository events
    # The events API returns various event types including repo-level changes
    cmd = f'gh api "repos/{owner}/{name}/events?per_page=100"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        events = json.loads(output)
    except json.JSONDecodeError:
        return

    # Event type mapping from GitHub API to our event types
    # See: https://docs.github.com/en/rest/using-the-rest-api/github-event-types
    # Note: This mapping documents the event types but isn't currently used in code
    # 'RepositoryRenamedEvent': 'repo_rename'  # Not in standard events API
    # 'MemberEvent': None                      # Collaborator changes (skip for now)
    # 'PublicEvent': 'repo_visibility'         # Repo made public
    # 'PrivateEvent': 'repo_visibility'        # Repo made private (rare in API)

    count = 0
    for event in events:
        try:
            event_type = event.get('type', '')
            created_at = event.get('created_at')

            if not created_at:
                continue

            event_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if event_date.tzinfo:
                event_date = event_date.replace(tzinfo=None)

            # Apply time filters
            if since and event_date < since:
                continue
            if until and event_date > until:
                continue

            _payload = event.get('payload', {})  # noqa: F841 - available for future use
            actor = event.get('actor', {}).get('login', '')

            # Handle different event types
            if event_type == 'PublicEvent':
                # Repository was made public
                yield Event(
                    type='repo_visibility',
                    timestamp=event_date,
                    repo_name=repo_name,
                    repo_path=repo_path,
                    data={
                        'action': 'made_public',
                        'actor': actor,
                        'url': f'https://github.com/{owner}/{name}'
                    }
                )
                count += 1

            # Note: GitHub's standard Events API doesn't include rename events directly.
            # We can check the repo API for name mismatches to detect renames.

            if limit and count >= limit:
                break

        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Error parsing GitHub event: {e}")
            continue

    # Additionally, check if current repo name differs from local directory name
    # This can detect a recent rename
    try:
        repo_info_cmd = f'gh api "repos/{owner}/{name}"'
        repo_output, repo_rc = run_command(repo_info_cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

        if repo_rc == 0 and repo_output:
            repo_data = json.loads(repo_output)
            github_name = repo_data.get('name', '')
            local_name = Path(repo_path).name

            # If names don't match, the repo was likely renamed
            if github_name and local_name and github_name.lower() != local_name.lower():
                # Get the updated_at time as approximate rename time
                updated_at = repo_data.get('updated_at')
                if updated_at:
                    rename_date = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                    if rename_date.tzinfo:
                        rename_date = rename_date.replace(tzinfo=None)

                    # Apply time filters
                    if (not since or rename_date >= since) and (not until or rename_date <= until):
                        yield Event(
                            type='repo_rename',
                            timestamp=rename_date,
                            repo_name=github_name,  # Use new name
                            repo_path=repo_path,
                            data={
                                'old_name': local_name,
                                'new_name': github_name,
                                'owner': owner,
                                'url': f'https://github.com/{owner}/{github_name}'
                            }
                        )

            # Check if repo is archived
            if repo_data.get('archived'):
                updated_at = repo_data.get('updated_at')
                if updated_at:
                    archive_date = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                    if archive_date.tzinfo:
                        archive_date = archive_date.replace(tzinfo=None)

                    if (not since or archive_date >= since) and (not until or archive_date <= until):
                        yield Event(
                            type='repo_archive',
                            timestamp=archive_date,
                            repo_name=repo_name,
                            repo_path=repo_path,
                            data={
                                'archived': True,
                                'owner': owner,
                                'url': f'https://github.com/{owner}/{name}'
                            }
                        )

            # Check visibility
            # Note: is_private is available but we can't detect *changes* without historical data
            _is_private = repo_data.get('private', False)  # noqa: F841

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.debug(f"Error checking repo info: {e}")


# =============================================================================
# GITHUB DEPLOYMENTS (opt-in, uses gh CLI)
# =============================================================================

def scan_github_deployments(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan GitHub deployments for a repository.

    Detects gh-pages deployments and other deployment environments.

    Requires: gh CLI installed and authenticated.

    Args:
        repo_path: Path to git repository
        since: Only deployments after this time
        until: Only deployments before this time
        limit: Maximum deployments to return

    Yields:
        Event objects for deployments
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI to get deployments
    cmd = f'gh api "repos/{owner}/{name}/deployments?per_page=100"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        deployments = json.loads(output)
    except json.JSONDecodeError:
        return

    count = 0
    for deployment in deployments:
        try:
            created_at = deployment.get('created_at')
            if not created_at:
                continue

            deploy_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if deploy_date.tzinfo:
                deploy_date = deploy_date.replace(tzinfo=None)

            # Apply time filters
            if since and deploy_date < since:
                continue
            if until and deploy_date > until:
                continue

            environment = deployment.get('environment', 'production')
            creator = deployment.get('creator', {}).get('login', '')

            yield Event(
                type='deployment',
                timestamp=deploy_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'id': deployment.get('id'),
                    'environment': environment,
                    'ref': deployment.get('ref', ''),
                    'sha': deployment.get('sha', '')[:8],
                    'creator': creator,
                    'description': deployment.get('description', ''),
                    'url': f'https://github.com/{owner}/{name}/deployments/{environment}'
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Error parsing deployment: {e}")
            continue


# =============================================================================
# GITHUB FORKS (opt-in, uses gh CLI)
# =============================================================================

def scan_github_forks(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan GitHub forks of a repository.

    Detects when someone forks your repository.

    Requires: gh CLI installed and authenticated.

    Args:
        repo_path: Path to git repository
        since: Only forks after this time
        until: Only forks before this time
        limit: Maximum forks to return

    Yields:
        Event objects for forks
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI to get forks (sorted by newest)
    cmd = f'gh api "repos/{owner}/{name}/forks?sort=newest&per_page=100"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        forks = json.loads(output)
    except json.JSONDecodeError:
        return

    count = 0
    for fork in forks:
        try:
            created_at = fork.get('created_at')
            if not created_at:
                continue

            fork_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if fork_date.tzinfo:
                fork_date = fork_date.replace(tzinfo=None)

            # Apply time filters
            if since and fork_date < since:
                continue
            if until and fork_date > until:
                continue

            fork_owner = fork.get('owner', {}).get('login', '')
            fork_name = fork.get('full_name', '')

            yield Event(
                type='fork',
                timestamp=fork_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'fork_owner': fork_owner,
                    'fork_name': fork_name,
                    'fork_url': fork.get('html_url', ''),
                    'description': fork.get('description', ''),
                    'stars': fork.get('stargazers_count', 0)
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Error parsing fork: {e}")
            continue


# =============================================================================
# GITHUB STARS (opt-in, uses gh CLI)
# =============================================================================

def scan_github_stars(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan GitHub stargazers of a repository.

    Note: The basic stargazers API doesn't include timestamps. We use the
    starring API with Accept header to get timestamps, but this may not work
    for all repos.

    Requires: gh CLI installed and authenticated.

    Args:
        repo_path: Path to git repository
        since: Only stars after this time
        until: Only stars before this time
        limit: Maximum stars to return

    Yields:
        Event objects for stars
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    info = _get_github_repo_info(repo_path)
    if not info:
        return

    owner, name = info

    # Use gh CLI with star timestamps (requires special Accept header)
    cmd = f'gh api "repos/{owner}/{name}/stargazers" -H "Accept: application/vnd.github.star+json" --paginate'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    try:
        stargazers = json.loads(output)
    except json.JSONDecodeError:
        return

    # Sort by starred_at (newest first)
    stargazers_with_time = []
    for sg in stargazers:
        starred_at = sg.get('starred_at')
        if starred_at:
            try:
                star_date = datetime.fromisoformat(starred_at.replace('Z', '+00:00'))
                if star_date.tzinfo:
                    star_date = star_date.replace(tzinfo=None)
                stargazers_with_time.append((star_date, sg))
            except (ValueError, TypeError):
                continue

    stargazers_with_time.sort(key=lambda x: x[0], reverse=True)

    count = 0
    for star_date, sg in stargazers_with_time:
        # Apply time filters
        if since and star_date < since:
            continue
        if until and star_date > until:
            continue

        user = sg.get('user', {})
        username = user.get('login', '')

        yield Event(
            type='star',
            timestamp=star_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'user': username,
                'user_url': user.get('html_url', ''),
                'avatar_url': user.get('avatar_url', '')
            }
        )

        count += 1
        if limit and count >= limit:
            break


# =============================================================================
# RUBYGEMS EVENT SCANNING (opt-in)
# =============================================================================

def scan_gem_publishes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan RubyGems for gem releases related to a repository.

    Looks for .gemspec file to determine gem name.

    Args:
        repo_path: Path to git repository
        since: Only releases after this time
        until: Only releases before this time
        limit: Maximum releases to return

    Yields:
        Event objects for RubyGems releases
    """
    import requests

    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Find gemspec file
    gemspec_files = list(Path(repo_path).glob('*.gemspec'))
    if not gemspec_files:
        return

    # Parse gemspec for gem name
    gem_name = None
    try:
        content = gemspec_files[0].read_text()
        # Look for: spec.name = "gem_name" or s.name = 'gem_name'
        match = re.search(r'\.name\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            gem_name = match.group(1)
    except Exception:
        return

    if not gem_name:
        # Fallback to gemspec filename
        gem_name = gemspec_files[0].stem

    # Query RubyGems API
    try:
        response = requests.get(
            f'https://rubygems.org/api/v1/versions/{gem_name}.json',
            timeout=10
        )
        if response.status_code != 200:
            return

        versions = response.json()
    except Exception:
        return

    count = 0
    for v in versions:
        try:
            created_at = v.get('created_at')
            if not created_at:
                continue

            release_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            if release_date.tzinfo:
                release_date = release_date.replace(tzinfo=None)

            # Apply time filters
            if since and release_date < since:
                continue
            if until and release_date > until:
                continue

            version = v.get('number', '')

            yield Event(
                type='gem_publish',
                timestamp=release_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'package': gem_name,
                    'version': version,
                    'downloads': v.get('downloads_count', 0),
                    'platform': v.get('platform', 'ruby'),
                    'url': f'https://rubygems.org/gems/{gem_name}/versions/{version}'
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (ValueError, TypeError) as e:
            logger.debug(f"Error parsing RubyGems release: {e}")
            continue


# =============================================================================
# NUGET EVENT SCANNING (opt-in)
# =============================================================================

def scan_nuget_publishes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan NuGet for .NET package releases related to a repository.

    Looks for .csproj or .nuspec files to determine package name.

    Args:
        repo_path: Path to git repository
        since: Only releases after this time
        until: Only releases before this time
        limit: Maximum releases to return

    Yields:
        Event objects for NuGet releases
    """
    import requests

    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Find package name from .csproj or .nuspec
    package_name = None

    # Try .csproj first
    csproj_files = list(Path(repo_path).glob('**/*.csproj'))
    for csproj in csproj_files[:3]:  # Limit search
        try:
            content = csproj.read_text()
            match = re.search(r'<PackageId>([^<]+)</PackageId>', content)
            if match:
                package_name = match.group(1)
                break
        except Exception:
            continue

    # Try .nuspec if no PackageId found
    if not package_name:
        nuspec_files = list(Path(repo_path).glob('**/*.nuspec'))
        for nuspec in nuspec_files[:3]:
            try:
                content = nuspec.read_text()
                match = re.search(r'<id>([^<]+)</id>', content, re.IGNORECASE)
                if match:
                    package_name = match.group(1)
                    break
            except Exception:
                continue

    if not package_name:
        return

    # Query NuGet API
    try:
        response = requests.get(
            f'https://api.nuget.org/v3/registration5-semver1/{package_name.lower()}/index.json',
            timeout=10
        )
        if response.status_code != 200:
            return

        data = response.json()
    except Exception:
        return

    count = 0
    # NuGet returns pages of versions
    for page in data.get('items', []):
        for item in page.get('items', []):
            try:
                catalog_entry = item.get('catalogEntry', {})
                published = catalog_entry.get('published')
                if not published:
                    continue

                release_date = datetime.fromisoformat(published.replace('Z', '+00:00'))
                if release_date.tzinfo:
                    release_date = release_date.replace(tzinfo=None)

                # Apply time filters
                if since and release_date < since:
                    continue
                if until and release_date > until:
                    continue

                version = catalog_entry.get('version', '')

                yield Event(
                    type='nuget_publish',
                    timestamp=release_date,
                    repo_name=repo_name,
                    repo_path=repo_path,
                    data={
                        'package': package_name,
                        'version': version,
                        'description': catalog_entry.get('description', '')[:100],
                        'url': f'https://www.nuget.org/packages/{package_name}/{version}'
                    }
                )

                count += 1
                if limit and count >= limit:
                    return

            except (ValueError, TypeError) as e:
                logger.debug(f"Error parsing NuGet release: {e}")
                continue


# =============================================================================
# MAVEN EVENT SCANNING (opt-in)
# =============================================================================

def scan_maven_publishes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan Maven Central for Java package releases related to a repository.

    Looks for pom.xml to determine groupId and artifactId.

    Args:
        repo_path: Path to git repository
        since: Only releases after this time
        until: Only releases before this time
        limit: Maximum releases to return

    Yields:
        Event objects for Maven Central releases
    """
    import requests

    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Find pom.xml
    pom_path = Path(repo_path) / 'pom.xml'
    if not pom_path.exists():
        return

    # Parse pom.xml for groupId and artifactId
    group_id = None
    artifact_id = None
    try:
        content = pom_path.read_text()
        # Simple regex parsing (not full XML parsing)
        group_match = re.search(r'<groupId>([^<]+)</groupId>', content)
        artifact_match = re.search(r'<artifactId>([^<]+)</artifactId>', content)
        if group_match and artifact_match:
            group_id = group_match.group(1)
            artifact_id = artifact_match.group(1)
    except Exception:
        return

    if not group_id or not artifact_id:
        return

    # Query Maven Central Search API
    try:
        response = requests.get(
            f'https://search.maven.org/solrsearch/select?q=g:{group_id}+AND+a:{artifact_id}&core=gav&rows=20&wt=json',
            timeout=10
        )
        if response.status_code != 200:
            return

        data = response.json()
    except Exception:
        return

    count = 0
    docs = data.get('response', {}).get('docs', [])

    for doc in docs:
        try:
            # Maven returns timestamp in milliseconds
            timestamp_ms = doc.get('timestamp')
            if not timestamp_ms:
                continue

            release_date = datetime.fromtimestamp(timestamp_ms / 1000)

            # Apply time filters
            if since and release_date < since:
                continue
            if until and release_date > until:
                continue

            version = doc.get('v', '')

            yield Event(
                type='maven_publish',
                timestamp=release_date,
                repo_name=repo_name,
                repo_path=repo_path,
                data={
                    'group_id': group_id,
                    'artifact_id': artifact_id,
                    'version': version,
                    'package': f'{group_id}:{artifact_id}',
                    'url': f'https://search.maven.org/artifact/{group_id}/{artifact_id}/{version}/jar'
                }
            )

            count += 1
            if limit and count >= limit:
                break

        except (ValueError, TypeError) as e:
            logger.debug(f"Error parsing Maven release: {e}")
            continue


# =============================================================================
# LOCAL CODE CHANGE EVENTS (fast, no API)
# =============================================================================

def scan_license_changes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan git history for LICENSE file changes.

    Args:
        repo_path: Path to git repository
        since: Only events after this time
        until: Only events before this time
        limit: Maximum events to return

    Yields:
        Event objects for license changes
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # License file patterns
    license_files = 'LICENSE LICENSE.txt LICENSE.md COPYING COPYING.txt'

    cmd = f'git log --format="%H|%aI|%an|%s" --all -- {license_files}'

    if since:
        cmd += f' --since="{since.isoformat()}"'
    if until:
        cmd += f' --until="{until.isoformat()}"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    count = 0
    for line in output.strip().split('\n'):
        if not line or '|' not in line:
            continue

        parts = line.split('|', 3)
        if len(parts) < 4:
            continue

        commit_hash = parts[0].strip()
        date_str = parts[1].strip()
        author = parts[2].strip()
        message = parts[3].strip()

        try:
            commit_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if commit_date.tzinfo:
                commit_date = commit_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            commit_date = datetime.now()

        yield Event(
            type='license_change',
            timestamp=commit_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'hash': commit_hash[:8],
                'author': author,
                'message': message[:100]
            }
        )

        count += 1
        if limit and count >= limit:
            break


def scan_ci_config_changes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan git history for CI/CD configuration changes.

    Detects changes to:
    - .github/workflows/
    - .gitlab-ci.yml
    - Jenkinsfile
    - .circleci/
    - .travis.yml
    - azure-pipelines.yml

    Args:
        repo_path: Path to git repository
        since: Only events after this time
        until: Only events before this time
        limit: Maximum events to return

    Yields:
        Event objects for CI config changes
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # CI config file patterns
    ci_patterns = [
        '.github/workflows/',
        '.gitlab-ci.yml',
        'Jenkinsfile',
        '.circleci/',
        '.travis.yml',
        'azure-pipelines.yml',
        'bitbucket-pipelines.yml',
        '.buildkite/',
        'appveyor.yml'
    ]

    # Build git log command
    file_patterns = ' '.join([f'"{p}"' for p in ci_patterns])
    cmd = f'git log --format="%H|%aI|%an|%s" --all -- {file_patterns}'

    if since:
        cmd += f' --since="{since.isoformat()}"'
    if until:
        cmd += f' --until="{until.isoformat()}"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    count = 0
    for line in output.strip().split('\n'):
        if not line or '|' not in line:
            continue

        parts = line.split('|', 3)
        if len(parts) < 4:
            continue

        commit_hash = parts[0].strip()
        date_str = parts[1].strip()
        author = parts[2].strip()
        message = parts[3].strip()

        try:
            commit_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if commit_date.tzinfo:
                commit_date = commit_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            commit_date = datetime.now()

        # Get files changed to determine CI system
        files_cmd = f'git show {commit_hash} --name-only --format=""'
        files_output, _ = run_command(files_cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)
        files_changed = [f.strip() for f in files_output.strip().split('\n') if f.strip()] if files_output else []

        # Determine CI system
        ci_system = 'unknown'
        for f in files_changed:
            if '.github/workflows' in f:
                ci_system = 'github_actions'
                break
            elif 'gitlab-ci' in f:
                ci_system = 'gitlab_ci'
                break
            elif 'Jenkinsfile' in f:
                ci_system = 'jenkins'
                break
            elif '.circleci' in f:
                ci_system = 'circleci'
                break
            elif '.travis' in f:
                ci_system = 'travis'
                break
            elif 'azure-pipelines' in f:
                ci_system = 'azure'
                break

        yield Event(
            type='ci_config_change',
            timestamp=commit_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'hash': commit_hash[:8],
                'author': author,
                'message': message[:100],
                'ci_system': ci_system,
                'files': files_changed[:3]
            }
        )

        count += 1
        if limit and count >= limit:
            break


def scan_docs_changes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan git history for documentation changes.

    Detects changes to docs/ directory and *.md files (excluding README).

    Args:
        repo_path: Path to git repository
        since: Only events after this time
        until: Only events before this time
        limit: Maximum events to return

    Yields:
        Event objects for documentation changes
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # Doc patterns (excluding README which has its own event type)
    doc_patterns = 'docs/ doc/ documentation/ "*.md" "!README.md" "!readme.md"'

    cmd = f'git log --format="%H|%aI|%an|%s" --all -- {doc_patterns}'

    if since:
        cmd += f' --since="{since.isoformat()}"'
    if until:
        cmd += f' --until="{until.isoformat()}"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    count = 0
    seen_hashes = set()

    for line in output.strip().split('\n'):
        if not line or '|' not in line:
            continue

        parts = line.split('|', 3)
        if len(parts) < 4:
            continue

        commit_hash = parts[0].strip()

        # Skip duplicates
        if commit_hash in seen_hashes:
            continue
        seen_hashes.add(commit_hash)

        date_str = parts[1].strip()
        author = parts[2].strip()
        message = parts[3].strip()

        # Skip if this is just a README change (handled by readme_change)
        files_cmd = f'git show {commit_hash} --name-only --format=""'
        files_output, _ = run_command(files_cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)
        files_changed = [f.strip() for f in files_output.strip().split('\n') if f.strip()] if files_output else []

        # Filter out README files
        non_readme_files = [f for f in files_changed if not f.lower().startswith('readme')]
        doc_files = [f for f in non_readme_files if f.startswith('doc') or f.endswith('.md')]

        if not doc_files:
            continue

        try:
            commit_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if commit_date.tzinfo:
                commit_date = commit_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            commit_date = datetime.now()

        yield Event(
            type='docs_change',
            timestamp=commit_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'hash': commit_hash[:8],
                'author': author,
                'message': message[:100],
                'files': doc_files[:5]
            }
        )

        count += 1
        if limit and count >= limit:
            break


def scan_readme_changes(
    repo_path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None
) -> Generator[Event, None, None]:
    """
    Scan git history for README file changes.

    Args:
        repo_path: Path to git repository
        since: Only events after this time
        until: Only events before this time
        limit: Maximum events to return

    Yields:
        Event objects for README changes
    """
    repo_path = str(Path(repo_path).resolve())
    repo_name = Path(repo_path).name

    # README file patterns
    readme_files = 'README README.md README.txt README.rst readme.md'

    cmd = f'git log --format="%H|%aI|%an|%s" --all -- {readme_files}'

    if since:
        cmd += f' --since="{since.isoformat()}"'
    if until:
        cmd += f' --until="{until.isoformat()}"'

    output, returncode = run_command(cmd, cwd=repo_path, capture_output=True, check=False, log_stderr=False)

    if returncode != 0 or not output:
        return

    count = 0
    for line in output.strip().split('\n'):
        if not line or '|' not in line:
            continue

        parts = line.split('|', 3)
        if len(parts) < 4:
            continue

        commit_hash = parts[0].strip()
        date_str = parts[1].strip()
        author = parts[2].strip()
        message = parts[3].strip()

        try:
            commit_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if commit_date.tzinfo:
                commit_date = commit_date.replace(tzinfo=None)
        except (ValueError, AttributeError):
            commit_date = datetime.now()

        yield Event(
            type='readme_change',
            timestamp=commit_date,
            repo_name=repo_name,
            repo_path=repo_path,
            data={
                'hash': commit_hash[:8],
                'author': author,
                'message': message[:100]
            }
        )

        count += 1
        if limit and count >= limit:
            break


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
        types: Event types to scan for (default: LOCAL_EVENT_TYPES)
        since: Only events after this time
        until: Only events before this time
        limit: Maximum total events to return
        repo_filter: Only scan repos matching this name

    Yields:
        Event objects sorted by timestamp (newest first)
    """
    if types is None:
        types = LOCAL_EVENT_TYPES

    # Collect all events first for sorting
    all_events = []

    for repo_path in repos:
        repo_name = Path(repo_path).name

        # Apply repo filter
        if repo_filter and repo_name != repo_filter:
            continue

        # Local git events (fast)
        if 'git_tag' in types:
            for event in scan_git_tags(repo_path, since, until):
                all_events.append(event)

        if 'commit' in types:
            # Limit commits per repo to avoid explosion
            for event in scan_commits(repo_path, since, until, limit=50):
                all_events.append(event)

        if 'branch' in types:
            for event in scan_branches(repo_path, since, until, limit=20):
                all_events.append(event)

        if 'merge' in types:
            for event in scan_merges(repo_path, since, until, limit=50):
                all_events.append(event)

        # GitHub events (opt-in, uses gh CLI)
        if 'github_release' in types:
            for event in scan_github_releases(repo_path, since, until):
                all_events.append(event)

        if 'pr' in types:
            for event in scan_github_prs(repo_path, since, until, limit=50):
                all_events.append(event)

        if 'issue' in types:
            for event in scan_github_issues(repo_path, since, until, limit=50):
                all_events.append(event)

        if 'workflow_run' in types:
            for event in scan_github_workflows(repo_path, since, until, limit=50):
                all_events.append(event)

        # PyPI events (opt-in)
        if 'pypi_publish' in types:
            for event in scan_pypi_publishes(repo_path, since, until):
                all_events.append(event)

        # CRAN events (opt-in)
        if 'cran_publish' in types:
            for event in scan_cran_publishes(repo_path, since, until):
                all_events.append(event)

        # npm events (opt-in)
        if 'npm_publish' in types:
            for event in scan_npm_publishes(repo_path, since, until):
                all_events.append(event)

        # Cargo/Rust events (opt-in)
        if 'cargo_publish' in types:
            for event in scan_cargo_publishes(repo_path, since, until):
                all_events.append(event)

        # Docker events (opt-in)
        if 'docker_publish' in types:
            for event in scan_docker_publishes(repo_path, since, until):
                all_events.append(event)

        # Local metadata events (fast, no API)
        if 'version_bump' in types:
            for event in scan_version_bumps(repo_path, since, until, limit=20):
                all_events.append(event)

        if 'deps_update' in types:
            for event in scan_deps_updates(repo_path, since, until, limit=30):
                all_events.append(event)

        # GitHub security alerts (opt-in, requires permissions)
        if 'security_alert' in types:
            for event in scan_github_security_alerts(repo_path, since, until, limit=50):
                all_events.append(event)

        # GitHub repo events (opt-in) - rename, transfer, visibility, archive
        repo_event_types = ['repo_rename', 'repo_transfer', 'repo_visibility', 'repo_archive']
        if any(t in types for t in repo_event_types):
            for event in scan_github_repo_events(repo_path, since, until, limit=20):
                if event.type in types:
                    all_events.append(event)

        # GitHub deployments (opt-in)
        if 'deployment' in types:
            for event in scan_github_deployments(repo_path, since, until, limit=50):
                all_events.append(event)

        # GitHub forks (opt-in)
        if 'fork' in types:
            for event in scan_github_forks(repo_path, since, until, limit=50):
                all_events.append(event)

        # GitHub stars (opt-in)
        if 'star' in types:
            for event in scan_github_stars(repo_path, since, until, limit=50):
                all_events.append(event)

        # RubyGems events (opt-in)
        if 'gem_publish' in types:
            for event in scan_gem_publishes(repo_path, since, until):
                all_events.append(event)

        # NuGet events (opt-in)
        if 'nuget_publish' in types:
            for event in scan_nuget_publishes(repo_path, since, until):
                all_events.append(event)

        # Maven events (opt-in)
        if 'maven_publish' in types:
            for event in scan_maven_publishes(repo_path, since, until):
                all_events.append(event)

        # Local code change events (fast, no API)
        if 'license_change' in types:
            for event in scan_license_changes(repo_path, since, until, limit=10):
                all_events.append(event)

        if 'ci_config_change' in types:
            for event in scan_ci_config_changes(repo_path, since, until, limit=20):
                all_events.append(event)

        if 'docs_change' in types:
            for event in scan_docs_changes(repo_path, since, until, limit=20):
                all_events.append(event)

        if 'readme_change' in types:
            for event in scan_readme_changes(repo_path, since, until, limit=10):
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
# PARALLEL SCANNING
# =============================================================================

def _scan_repo_events(
    repo_path: str,
    types: List[str],
    since: Optional[datetime],
    until: Optional[datetime],
    use_cache: bool = False,
    cache_ttl: int = 900
) -> List[Event]:
    """
    Scan a single repository for events.

    Internal function used by scan_events_parallel for concurrent scanning.
    Returns a list (not generator) for thread-safety.
    """
    events: List[Event] = []
    _repo_name = Path(repo_path).name  # noqa: F841 - computed for debugging

    # Local git events (fast, no caching needed)
    if 'git_tag' in types:
        events.extend(scan_git_tags(repo_path, since, until))

    if 'commit' in types:
        events.extend(scan_commits(repo_path, since, until, limit=50))

    if 'branch' in types:
        events.extend(scan_branches(repo_path, since, until, limit=20))

    if 'merge' in types:
        events.extend(scan_merges(repo_path, since, until, limit=50))

    # Local metadata events (fast, no caching needed)
    if 'version_bump' in types:
        events.extend(scan_version_bumps(repo_path, since, until, limit=20))

    if 'deps_update' in types:
        events.extend(scan_deps_updates(repo_path, since, until, limit=30))

    if 'license_change' in types:
        events.extend(scan_license_changes(repo_path, since, until, limit=10))

    if 'ci_config_change' in types:
        events.extend(scan_ci_config_changes(repo_path, since, until, limit=20))

    if 'docs_change' in types:
        events.extend(scan_docs_changes(repo_path, since, until, limit=20))

    if 'readme_change' in types:
        events.extend(scan_readme_changes(repo_path, since, until, limit=10))

    # Remote events - check cache first if enabled
    remote_types_to_scan = [t for t in types if t in REMOTE_EVENT_TYPES]

    for event_type in remote_types_to_scan:
        cache_key = _cache_key(repo_path, event_type, since, until) if use_cache else None

        if use_cache and cache_key:
            cached_data = _cache_get(cache_key, cache_ttl)
            if cached_data is not None:
                # Reconstruct Event objects from cached dicts
                for ed in cached_data:
                    try:
                        ts = datetime.fromisoformat(ed['timestamp']) if isinstance(ed['timestamp'], str) else ed['timestamp']
                        events.append(Event(
                            type=ed['type'],
                            timestamp=ts,
                            repo_name=ed['repo_name'],
                            repo_path=ed.get('repo_path', repo_path),
                            data=ed['data']
                        ))
                    except Exception as e:
                        logger.debug(f"Error reconstructing cached event: {e}")
                continue  # Skip to next event type, we used cache

        # Not cached, fetch from API
        fetched_events = []

        if event_type == 'github_release':
            fetched_events = list(scan_github_releases(repo_path, since, until))
        elif event_type == 'pr':
            fetched_events = list(scan_github_prs(repo_path, since, until, limit=50))
        elif event_type == 'issue':
            fetched_events = list(scan_github_issues(repo_path, since, until, limit=50))
        elif event_type == 'workflow_run':
            fetched_events = list(scan_github_workflows(repo_path, since, until, limit=50))
        elif event_type == 'security_alert':
            fetched_events = list(scan_github_security_alerts(repo_path, since, until, limit=50))
        elif event_type in ['repo_rename', 'repo_transfer', 'repo_visibility', 'repo_archive']:
            # These come from same API call, handle together
            all_repo_events = list(scan_github_repo_events(repo_path, since, until, limit=20))
            fetched_events = [e for e in all_repo_events if e.type == event_type]
        elif event_type == 'deployment':
            fetched_events = list(scan_github_deployments(repo_path, since, until, limit=50))
        elif event_type == 'fork':
            fetched_events = list(scan_github_forks(repo_path, since, until, limit=50))
        elif event_type == 'star':
            fetched_events = list(scan_github_stars(repo_path, since, until, limit=50))
        elif event_type == 'pypi_publish':
            fetched_events = list(scan_pypi_publishes(repo_path, since, until))
        elif event_type == 'cran_publish':
            fetched_events = list(scan_cran_publishes(repo_path, since, until))
        elif event_type == 'npm_publish':
            fetched_events = list(scan_npm_publishes(repo_path, since, until))
        elif event_type == 'cargo_publish':
            fetched_events = list(scan_cargo_publishes(repo_path, since, until))
        elif event_type == 'docker_publish':
            fetched_events = list(scan_docker_publishes(repo_path, since, until))
        elif event_type == 'gem_publish':
            fetched_events = list(scan_gem_publishes(repo_path, since, until))
        elif event_type == 'nuget_publish':
            fetched_events = list(scan_nuget_publishes(repo_path, since, until))
        elif event_type == 'maven_publish':
            fetched_events = list(scan_maven_publishes(repo_path, since, until))

        events.extend(fetched_events)

        # Cache the results if caching enabled
        if use_cache and cache_key and fetched_events:
            cache_data = [{
                'type': e.type,
                'timestamp': e.timestamp.isoformat(),
                'repo_name': e.repo_name,
                'repo_path': e.repo_path,
                'data': e.data
            } for e in fetched_events]
            _cache_set(cache_key, cache_data)

    return events


def scan_events_parallel(
    repos: List[str],
    types: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
    repo_filter: Optional[str] = None,
    max_workers: int = 8,
    use_cache: bool = False,
    cache_ttl: int = 900
) -> Generator[Event, None, None]:
    """
    Scan multiple repositories for events using parallel execution.

    This function scans repos concurrently using a thread pool, providing
    significant speedup for remote API events across many repositories.

    Args:
        repos: List of repository paths
        types: Event types to scan for (default: LOCAL_EVENT_TYPES)
        since: Only events after this time
        until: Only events before this time
        limit: Maximum total events to return
        repo_filter: Only scan repos matching this name
        max_workers: Maximum concurrent threads (default: 8)
        use_cache: Enable caching for remote API calls (default: False)
        cache_ttl: Cache TTL in seconds (default: 900 = 15 minutes)

    Yields:
        Event objects sorted by timestamp (newest first)
    """
    if types is None:
        types = LOCAL_EVENT_TYPES

    # Filter repos if specified
    if repo_filter:
        repos = [r for r in repos if Path(r).name == repo_filter]

    if not repos:
        return

    all_events = []

    # Use thread pool for concurrent repo scanning
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all repo scans
        future_to_repo = {
            executor.submit(
                _scan_repo_events, repo_path, types, since, until, use_cache, cache_ttl
            ): repo_path
            for repo_path in repos
        }

        # Collect results as they complete
        for future in as_completed(future_to_repo):
            repo_path = future_to_repo[future]
            try:
                repo_events = future.result()
                all_events.extend(repo_events)
            except Exception as e:
                logger.warning(f"Error scanning {repo_path}: {e}")

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
