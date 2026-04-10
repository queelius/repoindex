# ops wip-snapshot: Remote-Recoverable Working Tree Snapshots

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New command `repoindex ops wip-snapshot` that creates remote-recoverable snapshots of dirty repos' working trees by pushing to `wip/` branches, without modifying the user's working tree or main branches.

**Architecture:** Uses git plumbing commands (`git add -A`, `git write-tree`, `git commit-tree`, `git push`) to create a snapshot commit from the current working tree state and push it to a `wip/<hostname>/<date>` branch on origin. The working tree is restored to its original state after the snapshot. Parallelized across repos via the existing `ThreadPoolExecutor` infrastructure.

**Tech Stack:** git plumbing (subprocess), `concurrent.futures.ThreadPoolExecutor`, Click CLI

---

## Design

### Per-repo snapshot (the core operation)

```bash
# 1. Stage everything (respects .gitignore)
git add -A

# 2. Create a tree object from the index
TREE=$(git write-tree)

# 3. Create a snapshot commit (parent = current HEAD)
COMMIT=$(git commit-tree $TREE -p HEAD -m "WIP snapshot <hostname> <timestamp>")

# 4. Push to wip branch on origin (force = safe, it's a throwaway branch)
git push origin $COMMIT:refs/heads/wip/<hostname>/<date> --force

# 5. Reset the index back (working tree untouched)
git reset --quiet
```

**Properties:**
- Never modifies the working tree
- Never touches master/main or any user branch
- Uses force-push (safe: wip branches are throwaway, only one writer per hostname)
- Respects .gitignore (git add -A honors it)
- Creates a retrievable commit on the remote

**Recovery:**
```bash
git fetch origin wip/<hostname>/<date>
git checkout -b recovered FETCH_HEAD
```

### Command interface

```bash
repoindex ops wip-snapshot                          # all dirty repos
repoindex ops wip-snapshot --dry-run                # preview only
repoindex ops wip-snapshot "language == 'Python'"   # filtered
repoindex ops wip-snapshot --language python         # shorthand
```

### What to skip

- Clean repos (nothing to snapshot)
- Repos with no remote (nowhere to push)
- Repos with no HEAD (empty repos, no commits yet)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `repoindex/services/wip_service.py` | Create | `snapshot_repo()` function (git plumbing per repo) |
| `repoindex/commands/ops.py` | Modify | Add `wip-snapshot` subcommand |
| `tests/test_wip_snapshot.py` | Create | Tests for snapshot service |

---

### Task 1: Implement `snapshot_repo()` service function

**Files:**
- Create: `repoindex/services/wip_service.py`
- Test: `tests/test_wip_snapshot.py`

The function takes a repo path, creates a WIP snapshot commit, and pushes it to origin.

```python
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class SnapshotResult:
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
    is pushed to a wip/<hostname>/<date> branch on origin.

    Args:
        repo_path: Path to the git repository
        hostname: Override hostname for branch name (default: socket.gethostname())
        dry_run: If True, don't actually push

    Returns:
        SnapshotResult with success/failure details
    """
    name = Path(repo_path).name
    host = hostname or socket.gethostname()
    date = datetime.now().strftime('%Y-%m-%d')
    branch = f'wip/{host}/{date}'

    def _run(cmd, **kwargs):
        return subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True,
            timeout=60, **kwargs
        )

    # Check: has remote?
    result = _run(['git', 'remote', 'get-url', 'origin'])
    if result.returncode != 0:
        return SnapshotResult(name, repo_path, False, skipped=True, skip_reason='no remote')

    # Check: has HEAD?
    result = _run(['git', 'rev-parse', 'HEAD'])
    if result.returncode != 0:
        return SnapshotResult(name, repo_path, False, skipped=True, skip_reason='no HEAD (empty repo)')

    # Check: is dirty?
    result = _run(['git', 'status', '--porcelain'])
    if not result.stdout.strip():
        return SnapshotResult(name, repo_path, False, skipped=True, skip_reason='clean')

    if dry_run:
        return SnapshotResult(name, repo_path, True, branch=branch, skipped=False)

    try:
        # Stage all changes (respects .gitignore)
        _run(['git', 'add', '-A'])

        # Create tree from index
        result = _run(['git', 'write-tree'])
        if result.returncode != 0:
            return SnapshotResult(name, repo_path, False, error=f'write-tree failed: {result.stderr}')
        tree_sha = result.stdout.strip()

        # Get current HEAD
        result = _run(['git', 'rev-parse', 'HEAD'])
        head_sha = result.stdout.strip()

        # Create snapshot commit
        timestamp = datetime.now().isoformat()
        message = f'WIP snapshot {host} {timestamp}'
        result = _run(['git', 'commit-tree', tree_sha, '-p', head_sha, '-m', message])
        if result.returncode != 0:
            _run(['git', 'reset', '--quiet'])
            return SnapshotResult(name, repo_path, False, error=f'commit-tree failed: {result.stderr}')
        commit_sha = result.stdout.strip()

        # Push to wip branch
        refspec = f'{commit_sha}:refs/heads/{branch}'
        result = _run(['git', 'push', 'origin', refspec, '--force'])
        if result.returncode != 0:
            _run(['git', 'reset', '--quiet'])
            return SnapshotResult(name, repo_path, False, error=f'push failed: {result.stderr}')

        # Reset index (restore original state)
        _run(['git', 'reset', '--quiet'])

        return SnapshotResult(name, repo_path, True, branch=branch, commit_sha=commit_sha)

    except subprocess.TimeoutExpired:
        _run(['git', 'reset', '--quiet'])
        return SnapshotResult(name, repo_path, False, error='timeout')
    except Exception as e:
        _run(['git', 'reset', '--quiet'])
        return SnapshotResult(name, repo_path, False, error=str(e))
```

### Task 2: Add `wip-snapshot` CLI subcommand

**Files:**
- Modify: `repoindex/commands/ops.py`

Add under the `ops` command group:

```python
@ops_cmd.command('wip-snapshot')
@click.argument('query_string', required=False, default='')
@click.option('--dry-run', is_flag=True, help='Preview what would be snapshotted')
@click.option('--hostname', help='Override hostname for branch name')
@query_options
def wip_snapshot_handler(query_string, dry_run, hostname, language, dirty, tag, recent):
    """Snapshot dirty working trees to wip/ branches on origin.

    Creates remote-recoverable snapshots using git plumbing without
    modifying your working tree or main branches. Safe to run anytime.

    Each dirty repo gets a commit pushed to origin/wip/<hostname>/<date>.
    Force-push is used (safe: wip branches are throwaway).

    Recovery: git fetch origin wip/<hostname>/<date> && git checkout -b recovered FETCH_HEAD
    """
```

The handler:
1. Queries repos from DB (using query flags)
2. Filters to dirty repos (override: always add `not is_clean` to the query)
3. For each repo, calls `snapshot_repo()` (parallel via ThreadPoolExecutor)
4. Reports results: N snapshotted, N skipped, N failed

### Task 3: Tests

**Files:**
- Create: `tests/test_wip_snapshot.py`

Tests for `snapshot_repo()`:
- Clean repo is skipped
- Repo with no remote is skipped
- Repo with no HEAD is skipped
- Dirty repo creates snapshot commit (use a real tmp git repo)
- Dry run returns branch name without pushing
- The working tree is unchanged after snapshot
- The wip branch name includes hostname and date

Tests for the CLI:
- `--dry-run` produces output without side effects
- Query flags filter repos correctly

### Task 4: Integration test

- Create a real temp git repo with uncommitted changes
- Run `snapshot_repo` on it
- Verify the wip branch exists on the remote
- Verify the working tree is unchanged
- Verify the commit contains the dirty changes

---

## Sequencing

Task 1 first (core function), Task 2 (CLI wiring), Task 3 (tests), Task 4 (integration).
