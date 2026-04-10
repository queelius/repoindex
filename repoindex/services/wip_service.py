"""WIP snapshot service for repoindex.

Creates remote-recoverable snapshots of dirty repos by pushing WIP
commits to origin, without modifying the working tree or user branches.
"""

import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SnapshotResult:
    """Result of a WIP snapshot operation."""
    repo_name: str
    repo_path: str
    success: bool
    branch: str = ""
    commit_sha: str = ""
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""


def snapshot_repo(
    repo_path: str,
    hostname: Optional[str] = None,
    dry_run: bool = False,
) -> SnapshotResult:
    """Create a WIP snapshot of a dirty repo and push to origin.

    Uses git plumbing to create a commit from the current working tree
    state without modifying the tree or any user branches. The commit
    is pushed to wip/<hostname>/<date> on origin.
    """
    name = Path(repo_path).name
    host = hostname or socket.gethostname()
    date = datetime.now().strftime('%Y-%m-%d')
    branch = f'wip/{host}/{date}'

    def _run(cmd):
        return subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, timeout=60
        )

    # Skip: no remote?
    r = _run(['git', 'remote', 'get-url', 'origin'])
    if r.returncode != 0:
        return SnapshotResult(name, repo_path, False, skipped=True, skip_reason='no remote')

    # Skip: no HEAD?
    r = _run(['git', 'rev-parse', 'HEAD'])
    if r.returncode != 0:
        return SnapshotResult(name, repo_path, False, skipped=True, skip_reason='no HEAD')

    # Skip: clean?
    r = _run(['git', 'status', '--porcelain'])
    if not r.stdout.strip():
        return SnapshotResult(name, repo_path, False, skipped=True, skip_reason='clean')

    if dry_run:
        return SnapshotResult(name, repo_path, True, branch=branch)

    try:
        # Stage all
        _run(['git', 'add', '-A'])

        # Write tree from index
        r = _run(['git', 'write-tree'])
        if r.returncode != 0:
            _run(['git', 'reset', '--quiet'])
            return SnapshotResult(name, repo_path, False, error=f'write-tree: {r.stderr.strip()}')
        tree = r.stdout.strip()

        # Get HEAD SHA
        head = _run(['git', 'rev-parse', 'HEAD']).stdout.strip()

        # Create snapshot commit
        msg = f'WIP snapshot {host} {datetime.now().isoformat()}'
        r = _run(['git', 'commit-tree', tree, '-p', head, '-m', msg])
        if r.returncode != 0:
            _run(['git', 'reset', '--quiet'])
            return SnapshotResult(name, repo_path, False, error=f'commit-tree: {r.stderr.strip()}')
        sha = r.stdout.strip()

        # Push to wip branch (force is safe: wip branches are throwaway)
        r = _run(['git', 'push', 'origin', f'{sha}:refs/heads/{branch}', '--force'])
        if r.returncode != 0:
            _run(['git', 'reset', '--quiet'])
            return SnapshotResult(name, repo_path, False, error=f'push: {r.stderr.strip()}')

        # Reset index back to original state
        _run(['git', 'reset', '--quiet'])

        return SnapshotResult(name, repo_path, True, branch=branch, commit_sha=sha)

    except subprocess.TimeoutExpired:
        _run(['git', 'reset', '--quiet'])
        return SnapshotResult(name, repo_path, False, error='timeout')
    except Exception as e:
        _run(['git', 'reset', '--quiet'])
        return SnapshotResult(name, repo_path, False, error=str(e))
