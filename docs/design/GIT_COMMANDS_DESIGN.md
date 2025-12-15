# Git Commands Design

## Vision

Replicate familiar git commands in repoindex, allowing users to run git operations on repositories through the VFS. This is especially powerful in the shell where users can execute git commands on multiple repositories at once.

## Key Design Principles

1. **Familiar Interface**: Commands should feel like native git
2. **VFS-Aware**: Work with VFS paths, not just filesystem paths
3. **Multi-Repo**: Can operate on multiple repositories simultaneously
4. **Shell-First**: Optimized for interactive shell use, but CLI works too
5. **Non-Destructive Defaults**: Require confirmation for destructive operations

## Use Cases

### In Shell
```bash
# Navigate to VFS location
repoindex:/> cd /by-tag/work/active

# Run git status on ALL repos with that tag
repoindex:/by-tag/work/active> git status

# See recent commits across all active work repos
repoindex:/by-tag/work/active> git log --oneline -5

# Pull updates for all active work repos
repoindex:/by-tag/work/active> git pull

# Navigate to specific repo
repoindex:/> cd /repos/myproject

# Git commands work on single repo
repoindex:/repos/myproject> git log --graph --all
repoindex:/repos/myproject> git diff
repoindex:/repos/myproject> git commit -m "Update"
```

### In CLI
```bash
# Status for specific VFS path
repoindex git status /by-tag/work/active

# Log for specific repo
repoindex git log /repos/myproject --oneline -5

# Pull all repos in directory
repoindex git pull /by-tag/needs-update

# Diff across multiple repos
repoindex git diff --name-status /by-language/Python
```

## Command Categories

### Read-Only Commands (Safe, No Confirmation)
- `git status` - Show working tree status
- `git log` - Show commit history
- `git diff` - Show changes
- `git show` - Show commit details
- `git branch` - List branches
- `git remote` - Show remotes
- `git ls-files` - List tracked files
- `git blame` - Show line-by-line authorship

### State-Changing Commands (Require Confirmation)
- `git pull` - Pull from remote
- `git fetch` - Fetch from remote
- `git push` - Push to remote (with --dry-run default?)
- `git checkout` / `git switch` - Switch branches
- `git stash` - Stash changes
- `git clean` - Remove untracked files

### Write Commands (Require Explicit Confirmation)
- `git add` - Stage changes
- `git commit` - Commit changes
- `git reset` - Reset changes
- `git revert` - Revert commits
- `git merge` - Merge branches
- `git rebase` - Rebase branches

## Implementation Structure

```
repoindex git <command> [VFS_PATH] [options]
```

### Examples:
```bash
# CLI mode - path is explicit
repoindex git status /by-tag/work/active
repoindex git log /repos/myproject --oneline -10
repoindex git pull /by-tag/needs-update --confirm

# Shell mode - path is from cwd
repoindex:/by-tag/work/active> git status
repoindex:/repos/myproject> git log --oneline -10
repoindex:/by-tag/needs-update> git pull
```

## Output Formats

### Single Repository
```bash
repoindex git status /repos/myproject

Repository: myproject (/home/user/repos/myproject)
On branch: main
Your branch is up to date with 'origin/main'.

Changes not staged for commit:
  modified:   README.md
  modified:   src/main.py
```

### Multiple Repositories
```bash
repoindex git status /by-tag/work/active

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Repository: myproject
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
On branch: main
Modified: 2 files
Untracked: 0 files

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Repository: another-project
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
On branch: develop
Clean working tree

Summary: 2 repositories, 1 with changes
```

### JSONL Mode
```bash
repoindex git status /by-tag/work/active --json

{"repo": "myproject", "path": "/home/user/repos/myproject", "branch": "main", "clean": false, "modified": 2}
{"repo": "another-project", "path": "/home/user/repos/another", "branch": "develop", "clean": true, "modified": 0}
```

## Command-Specific Designs

### `git status`
```bash
Usage: repoindex git status [VFS_PATH] [OPTIONS]

Show working tree status for repositories.

Options:
  --short, -s          Show short format
  --branch, -b         Show branch info
  --json               Output as JSONL
  --dirty-only         Show only repos with changes
```

### `git log`
```bash
Usage: repoindex git log [VFS_PATH] [OPTIONS]

Show commit history.

Options:
  --oneline            Show one line per commit
  --graph              Show commit graph
  --all                Show all branches
  -n, --max-count N    Limit to N commits
  --since DATE         Show commits since date
  --author AUTHOR      Filter by author
  --json               Output as JSONL
```

### `git pull`
```bash
Usage: repoindex git pull [VFS_PATH] [OPTIONS]

Pull changes from remote.

Options:
  --dry-run            Show what would be pulled
  --confirm            Require confirmation for each repo
  --no-confirm         Don't require confirmation (use with caution!)
  --parallel           Pull repos in parallel
  --json               Output as JSONL
```

### `git diff`
```bash
Usage: repoindex git diff [VFS_PATH] [OPTIONS]

Show changes.

Options:
  --name-only          Show only names
  --name-status        Show names with status
  --stat               Show stats
  --cached, --staged   Show staged changes
  --json               Output as JSONL
```

## Shell Integration

In the shell, git commands should:

1. **Use current VFS directory as default path**
   ```bash
   repoindex:/by-tag/work/active> git status
   # Equivalent to: repoindex git status /by-tag/work/active
   ```

2. **Support relative VFS paths**
   ```bash
   repoindex:/by-tag> git status work/active
   # Equivalent to: repoindex git status /by-tag/work/active
   ```

3. **Work on single repos**
   ```bash
   repoindex:/repos/myproject> git log --oneline -10
   # Shows log for just myproject
   ```

## Safety Features

### Confirmation Prompts
```bash
repoindex git pull /by-tag/work/active

Found 5 repositories. Pull changes? [y/N]: y

Pulling: myproject... ✓ (already up to date)
Pulling: another-project... ✓ (fast-forward, 3 commits)
Pulling: third-project... ✗ (merge conflict, skipped)

Summary: 2/5 successful, 1 failed
```

### Dry Run Mode
```bash
repoindex git push /by-tag/ready-to-publish --dry-run

Would push to remote:
  myproject (main): 2 commits
  another-project (develop): 1 commit

Use --confirm to actually push.
```

## Implementation Plan

### Phase 1: Read-Only Commands
1. Implement `git status`
2. Implement `git log`
3. Implement `git diff`
4. Implement `git show`
5. Implement `git branch`

### Phase 2: Fetch Operations
1. Implement `git fetch`
2. Implement `git pull` (with confirmation)
3. Implement `git remote`

### Phase 3: Write Operations
1. Implement `git add`
2. Implement `git commit`
3. Implement `git push` (with confirmation)
4. Implement `git stash`

### Phase 4: Advanced Operations
1. Implement `git checkout` / `git switch`
2. Implement `git merge`
3. Implement `git rebase`
4. Implement `git reset`

## File Structure

```
repoindex/commands/git.py          # Main git command group
repoindex/git_ops/
    __init__.py
    status.py                   # Git status operations
    log.py                      # Git log operations
    diff.py                     # Git diff operations
    pull.py                     # Git pull operations
    commit.py                   # Git commit operations
    utils.py                    # Common git utilities
```

## Key Implementation Details

### Multi-Repo Execution
```python
def execute_git_on_repos(repos: List[str], git_command: str,
                        parallel: bool = False,
                        confirm: bool = True) -> Generator[Dict, None, None]:
    """Execute git command on multiple repositories."""

    if confirm and len(repos) > 1:
        if not click.confirm(f"Execute on {len(repos)} repositories?"):
            return

    if parallel:
        # Use threading/multiprocessing
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(run_git, repo, git_command): repo
                      for repo in repos}
            for future in as_completed(futures):
                yield future.result()
    else:
        # Sequential execution
        for repo in repos:
            yield run_git(repo, git_command)
```

### VFS Path Resolution
```python
def get_repos_from_vfs_path(vfs_path: str) -> List[str]:
    """Get all repository paths from a VFS path."""
    vfs = build_vfs_structure(load_config())
    node = resolve_vfs_path(vfs, vfs_path)

    if node['type'] == 'repository':
        return [node['path']]
    elif node['type'] == 'symlink':
        return [node['path']]
    elif node['type'] == 'directory':
        # Collect all repos in this directory recursively
        return collect_repos_from_node(node)
```

## Benefits

1. **Familiar Commands**: Users already know git
2. **Multi-Repo Power**: Operate on many repos at once
3. **VFS Integration**: Natural fit with VFS navigation
4. **Flexible**: Works in both CLI and shell
5. **Safe**: Confirmation prompts prevent accidents
6. **Scriptable**: JSONL output for automation

## Example Workflows

### Daily Status Check
```bash
# In shell
repoindex:/> cd /by-tag/work/active
repoindex:/by-tag/work/active> git status --dirty-only

# Shows only repos with uncommitted changes
```

### Pull All Work Repos
```bash
# In CLI
repoindex git pull /by-tag/work --confirm

# Pulls updates for all work-tagged repos with confirmation
```

### View Recent Activity
```bash
# In shell
repoindex:/by-tag/client/acme> git log --since="1 week ago" --oneline

# Shows commits from last week across all client repos
```

### Bulk Operations
```bash
# Push all ready repos
repoindex git push /by-tag/ready-to-publish --dry-run  # Check first
repoindex git push /by-tag/ready-to-publish --confirm  # Then push
```

## Questions to Consider

1. Should we allow glob patterns in VFS paths? `/by-tag/work/*`
2. Should we support git aliases/custom shortcuts?
3. Should there be a `--all` flag to run on all repos?
4. How to handle repos in different states (some ahead, some behind)?
5. Should we add repoindex-specific enhancements (like auto-fix, bulk tagging based on git state)?

## Next Steps

1. Implement basic `git status` command
2. Test with multiple repos
3. Add to shell as a command
4. Iterate based on usage
