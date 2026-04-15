"""WIP snapshot service for repoindex.

Creates remote-recoverable snapshots of dirty repos by pushing WIP
commits to origin, without modifying the working tree or user branches.

Design notes
------------
The snapshot is built entirely against a temporary index file (via
``GIT_INDEX_FILE``), so the user's real ``.git/index`` is never touched.
This preserves any pre-staged blobs the user had lined up — including
partially-staged changes (e.g. ``MM file.txt``).

Each snapshot is pushed to a unique branch of the form
``wip/<hostname>/<YYYY-MM-DD-HHMMSS>-<uuid8>``. A ``wip/<host>/latest``
pointer is also force-updated on every run so recovery is trivial:

    git fetch origin wip/<host>/latest
    git checkout -b recovered FETCH_HEAD

Because every snapshot is a unique branch, wip branches accumulate on
the remote. Users should periodically prune old ones:

    git branch -r | grep 'origin/wip/<host>/' \\
        | grep -v latest | sed 's|origin/||' \\
        | xargs -r git push origin --delete
"""

import os
import socket
import subprocess
import tempfile
import uuid
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
    is pushed to a unique ``wip/<host>/<date-time>-<uuid>`` branch and
    ``wip/<host>/latest`` is updated to the same SHA for convenience.

    The user's real ``.git/index`` is never touched — we stage into a
    temporary index file (``GIT_INDEX_FILE``) that is deleted on exit.
    """
    name = Path(repo_path).name
    host = hostname or socket.gethostname()
    date_time = datetime.now().strftime('%Y-%m-%d-%H%M%S')
    short_id = uuid.uuid4().hex[:8]
    branch = f'wip/{host}/{date_time}-{short_id}'
    latest_branch = f'wip/{host}/latest'

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

    # Check dirtiness. A failure here is a real error (e.g. corrupt index),
    # not "clean" — misclassifying it as clean would silently hide damage.
    r = _run(['git', 'status', '--porcelain'])
    if r.returncode != 0:
        return SnapshotResult(
            name, repo_path, False,
            error=f'status: {r.stderr.strip() or "exit " + str(r.returncode)}',
        )
    if not r.stdout.strip():
        return SnapshotResult(name, repo_path, False, skipped=True, skip_reason='clean')

    if dry_run:
        return SnapshotResult(name, repo_path, True, branch=branch)

    # Create a temp index file so we never touch the user's real .git/index.
    # NamedTemporaryFile with delete=False gives us a path we can hand to git.
    tmp_fd, tmp_idx = tempfile.mkstemp(prefix='repoindex-wip-idx-')
    os.close(tmp_fd)
    # Start from a fresh state — read-tree will populate it from HEAD.
    try:
        os.unlink(tmp_idx)
    except OSError:
        pass

    env = {**os.environ, 'GIT_INDEX_FILE': tmp_idx}

    def _run_env(cmd):
        return subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True,
            timeout=60, env=env,
        )

    try:
        # Seed temp index with current HEAD's tree.
        r = _run_env(['git', 'read-tree', 'HEAD'])
        if r.returncode != 0:
            return SnapshotResult(
                name, repo_path, False,
                error=f'read-tree: {r.stderr.strip()}',
            )

        # Stage everything (into the temp index, NOT the user's index).
        r = _run_env(['git', 'add', '-A'])
        if r.returncode != 0:
            return SnapshotResult(
                name, repo_path, False,
                error=f'add: {r.stderr.strip()}',
            )

        # Write tree from temp index.
        r = _run_env(['git', 'write-tree'])
        if r.returncode != 0:
            return SnapshotResult(
                name, repo_path, False,
                error=f'write-tree: {r.stderr.strip()}',
            )
        tree = r.stdout.strip()

        # Get HEAD SHA (no env needed — rev-parse doesn't touch the index).
        r = _run(['git', 'rev-parse', 'HEAD'])
        if r.returncode != 0:
            return SnapshotResult(
                name, repo_path, False,
                error=f'rev-parse: {r.stderr.strip()}',
            )
        head = r.stdout.strip()

        # Create snapshot commit (commit-tree also doesn't use the index).
        msg = f'WIP snapshot {host} {datetime.now().isoformat()}'
        r = _run(['git', 'commit-tree', tree, '-p', head, '-m', msg])
        if r.returncode != 0:
            return SnapshotResult(
                name, repo_path, False,
                error=f'commit-tree: {r.stderr.strip()}',
            )
        sha = r.stdout.strip()

        # Push the unique snapshot branch AND update wip/<host>/latest in one
        # operation. The unique branch is for permanent recoverability; latest
        # is the convenience pointer. --force is only meaningful for 'latest'.
        r = _run([
            'git', 'push', 'origin',
            f'{sha}:refs/heads/{branch}',
            f'{sha}:refs/heads/{latest_branch}',
            '--force',
        ])
        if r.returncode != 0:
            return SnapshotResult(
                name, repo_path, False,
                error=f'push: {r.stderr.strip()}',
            )

        # NOTE: no cleanup of the user's index — it was never touched.
        return SnapshotResult(name, repo_path, True, branch=branch, commit_sha=sha)

    except subprocess.TimeoutExpired:
        return SnapshotResult(name, repo_path, False, error='timeout')
    except Exception as e:
        return SnapshotResult(name, repo_path, False, error=str(e))
    finally:
        # Always remove the temp index. If it doesn't exist (e.g. read-tree
        # never ran), that's fine — swallow the OSError.
        try:
            os.unlink(tmp_idx)
        except OSError:
            pass
