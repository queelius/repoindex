"""
Handles the 'update' command for updating Git repositories.

This command follows our design principles:
- Default output is JSONL streaming or table based on TTY
- --verbose/-v for progress output
- --quiet/-q to suppress data output
- Core logic returns generators for streaming
- No side effects in core functions
"""

import click
import json
import os
from pathlib import Path
from typing import Generator, Dict, Any

from ..core import get_repositories_from_path
from ..render import render_update_table
from ..utils import run_command, get_git_status, get_remote_url, parse_repo_url, find_git_repos_from_config, is_git_repo
from ..config import logger, load_config
from ..cli_utils import standard_command, add_common_options
from ..exit_codes import NoReposFoundError


def update_repository(repo_path: str, auto_commit: bool = False, 
                     commit_message: str = "Auto commit", 
                     dry_run: bool = False) -> Dict[str, Any]:
    """
    Update a single repository.
    
    Returns a dictionary with update results following standard schema.
    """
    repo_name = os.path.basename(repo_path)
    result = {
        "path": os.path.abspath(repo_path),
        "name": repo_name,
        "actions": {
            "committed": False,
            "pulled": False,
            "pushed": False,
            "conflicts": False,
            "error": None
        },
        "details": {}
    }
    
    try:
        # Check for uncommitted changes
        status_output, _ = run_command("git status --porcelain", cwd=repo_path, capture_output=True)
        has_changes = bool(status_output and status_output.strip())
        
        if has_changes and auto_commit:
            # Commit changes
            if not dry_run:
                run_command("git add -A", cwd=repo_path)
                commit_output, _ = run_command(
                    f'git commit -m "{commit_message}"', 
                    cwd=repo_path, 
                    capture_output=True
                )
                if commit_output and "nothing to commit" not in commit_output.lower():
                    result["actions"]["committed"] = True
                    result["details"]["commit_message"] = commit_message
            else:
                result["actions"]["committed"] = True
                result["details"]["commit_message"] = f"[DRY RUN] {commit_message}"
        
        # Pull latest changes
        if not dry_run:
            pull_output, _ = run_command(
                "git pull --rebase --autostash", 
                cwd=repo_path, 
                capture_output=True,
                check=False
            )
            
            if pull_output:
                if "already up to date" not in pull_output.lower():
                    result["actions"]["pulled"] = True
                    result["details"]["pull_output"] = pull_output.strip()
                
                # Check for conflicts
                if "conflict" in pull_output.lower():
                    result["actions"]["conflicts"] = True
                    result["details"]["conflict_type"] = "rebase"
        else:
            result["details"]["pull_output"] = "[DRY RUN] Would pull latest changes"
        
        # Push if we committed
        if result["actions"]["committed"] and not dry_run:
            push_output, _ = run_command("git push", cwd=repo_path, capture_output=True)
            if push_output and "everything up-to-date" not in push_output.lower():
                result["actions"]["pushed"] = True
                result["details"]["push_output"] = push_output.strip()
        elif result["actions"]["committed"] and dry_run:
            result["details"]["push_output"] = "[DRY RUN] Would push changes"
        
        # Add remote info
        remote_url = get_remote_url(repo_path)
        if remote_url:
            result["remote"] = {
                "url": remote_url,
                "owner": parse_repo_url(remote_url)[0],
                "name": parse_repo_url(remote_url)[1]
            }
            
    except Exception as e:
        result["actions"]["error"] = str(e)
        result["error"] = str(e)
        result["type"] = "update_error"
        result["context"] = {
            "path": repo_path,
            "operation": "update"
        }
    
    return result


def update_repositories(base_dir: str = None, recursive: bool = False,
                       auto_commit: bool = False, commit_message: str = "Auto commit",
                       dry_run: bool = False, tag_filters: list = None, 
                       all_tags: bool = False) -> Generator[Dict[str, Any], None, None]:
    """
    Generator that yields update results for repositories.
    
    This is a pure function that returns a generator of update result dictionaries.
    It does not print, format, or interact with the terminal.
    """
    from ..config import load_config
    from ..utils import find_git_repos_from_config
    
    # Get repositories based on base_dir or config
    if base_dir and base_dir != ".":
        repos = list(get_repositories_from_path(base_dir, recursive))
    else:
        config = load_config()
        repo_dirs = config.get("general", {}).get("repository_directories", [])
        repos = list(find_git_repos_from_config(repo_dirs))
    
    # Apply tag filtering if specified
    if tag_filters:
        from ..commands.catalog import get_repositories_by_tags
        config = load_config()
        
        # Get filtered repos
        filtered_repos = list(get_repositories_by_tags(tag_filters, config, all_tags))
        filtered_paths = {r["path"] for r in filtered_repos}
        
        # Filter the discovered repos
        repos = [r for r in repos if os.path.abspath(r) in filtered_paths]
    
    for repo_path in repos:
        yield update_repository(repo_path, auto_commit, commit_message, dry_run)


@click.command("update")
@click.option("-d", "--dir", default=None, help="Directory to search for repositories (overrides config)")
@click.option("-r", "--recursive", is_flag=True, help="Search recursively for repositories")
@click.option("--auto-commit", is_flag=True, help="Automatically commit changes before pulling")
@click.option("--commit-message", default="Auto commit", help="Commit message for auto-commits")
@click.option("--dry-run", is_flag=True, help="Simulate actions without making changes")
@click.option("-t", "--tag", "tag_filters", multiple=True, help="Filter by tags (e.g., org:torvalds, lang:python)")
@click.option("--all-tags", is_flag=True, help="Match all tags (default: match any)")
@click.option("--table/--no-table", default=None, help="Display as formatted table (auto-detected by default)")
@add_common_options('verbose', 'quiet')
@standard_command(streaming=True)
def update_repos_handler(dir, recursive, auto_commit, commit_message, dry_run, tag_filters, all_tags, table, progress, quiet, **kwargs):
    """
    Update Git repositories by pulling latest changes.
    
    \b
    Output format:
    - Interactive terminal: Table format by default
    - Piped/redirected: JSONL streaming by default
    - Use --table to force table output
    - Use --no-table to force JSONL output
    
    Examples:
    
    \b
        repoindex update                    # Update all repos from config
        repoindex update -d .               # Update current repo only
        repoindex update -d . -r            # Update all repos under current
        repoindex update --auto-commit      # Commit changes before pulling
        repoindex update --dry-run          # Preview changes without applying
        repoindex update -t type:work       # Update only work repos
    """
    # Auto-detect table mode if not specified
    if table is None:
        import sys
        table = sys.stdout.isatty()
    
    config = load_config()
    
    progress("Discovering repositories...")
    
    # Get repository paths (same logic as status/list)
    repos = []
    if dir is not None:
        # Use specified directory
        expanded_dir = os.path.expanduser(dir)
        expanded_dir = os.path.abspath(expanded_dir)
        
        if is_git_repo(expanded_dir) and not recursive:
            repos = [expanded_dir]
        else:
            from ..utils import find_git_repos
            repos = find_git_repos(expanded_dir, recursive)
    else:
        # Use config
        repo_dirs = config.get("general", {}).get("repository_directories", [])
        repos = list(find_git_repos_from_config(repo_dirs, recursive))
    
    if not repos:
        raise NoReposFoundError("No repositories found to update")
    
    progress(f"Found {len(repos)} repositories")
    
    # Apply tag filtering if specified
    if tag_filters:
        from ..commands.catalog import get_repositories_by_tags
        
        progress("Applying tag filters...")
        filtered_repos = list(get_repositories_by_tags(tag_filters, config, all_tags))
        filtered_paths = {r["path"] for r in filtered_repos}
        repos = [r for r in repos if os.path.abspath(r) in filtered_paths]
        
        if not repos:
            filter_desc = " AND ".join(tag_filters) if all_tags else " OR ".join(tag_filters)
            raise NoReposFoundError(f"No repositories found matching: {filter_desc}")
        
        progress(f"Filtered to {len(repos)} repositories")
    
    if dry_run:
        progress.warning("DRY RUN - no changes will be made")
    
    # Process updates
    updated_count = 0
    error_count = 0
    
    if table:
        # Collect all updates for table display
        updates = []
        with progress.task("Updating repositories", total=len(repos)) as update_progress:
            for i, repo_path in enumerate(repos, 1):
                update_progress(i, os.path.basename(repo_path))
                result = update_repository(repo_path, auto_commit, commit_message, dry_run)
                updates.append(result)
                
                if result.get("actions", {}).get("error"):
                    error_count += 1
                elif any(result.get("actions", {}).values()):
                    updated_count += 1
        
        # Show table
        render_update_table(updates)
    else:
        # Stream updates as JSONL
        with progress.task("Updating repositories", total=len(repos)) as update_progress:
            for i, repo_path in enumerate(repos, 1):
                update_progress(i, os.path.basename(repo_path))
                result = update_repository(repo_path, auto_commit, commit_message, dry_run)
                
                if result.get("actions", {}).get("error"):
                    error_count += 1
                    progress.error(f"Failed to update {result['name']}: {result['actions']['error']}")
                elif any([result.get("actions", {}).get(k) for k in ["committed", "pulled", "pushed"]]):
                    updated_count += 1
                    actions = []
                    if result["actions"].get("committed"):
                        actions.append("committed")
                    if result["actions"].get("pulled"):
                        actions.append("pulled")
                    if result["actions"].get("pushed"):
                        actions.append("pushed")
                    progress.success(f"Updated {result['name']}: {', '.join(actions)}")
                
                if not quiet:
                    yield result
    
    # Summary
    progress("")
    progress("Summary:")
    progress(f"  Total repositories: {len(repos)}")
    if updated_count > 0:
        progress.success(f"  Updated: {updated_count}")
    unchanged_count = len(repos) - updated_count - error_count
    if unchanged_count > 0:
        progress(f"  Unchanged: {unchanged_count}")
    if error_count > 0:
        progress.error(f"  Errors: {error_count}")