"""
Handles the 'status' command for displaying repository status.

This command follows our design principles:
- Default output is JSONL streaming
- --verbose/-v for progress output
- --quiet/-q to suppress JSON output
- Thin CLI layer that connects core logic to output
"""

import json
import click

from ..core import get_repository_status, _get_repository_status_for_path
from ..render import render_status_table, console
from ..config import load_config
from ..cli_utils import standard_command, add_common_options
from ..exit_codes import NoReposFoundError


@click.command(name='status')
@click.argument('vfs_path', default='/', required=False)
@click.option('-d', '--dir', default=None, help='[DEPRECATED] Use VFS path instead')
@click.option('-r', '--recursive', is_flag=True, help='Search recursively for repositories')
@click.option('--no-pages', is_flag=True, help='Skip GitHub Pages check for faster results')
@click.option('--no-pypi', is_flag=True, help='Skip PyPI package detection')
@click.option('--no-dedup', is_flag=True, help='Show all instances including duplicates and soft links')
@click.option('-t', '--tag', 'tag_filters', multiple=True, help='[DEPRECATED] Use VFS path like /by-tag/work instead')
@click.option('--all-tags', is_flag=True, help='Match all tags (default: match any)')
@click.option('--refresh', is_flag=True, help='Refresh metadata before showing status')
@click.option('--github', is_flag=True, help='Use GitHub API for fresh visibility/fork info (slower)')
@click.option('--table/--no-table', default=None, help='Display as formatted table (auto-detected by default)')
@add_common_options('verbose', 'quiet')
@standard_command(streaming=True)
def status_handler(vfs_path, dir, recursive, no_pages, no_pypi, no_dedup, tag_filters, all_tags, refresh, github, table, progress, quiet, **kwargs):
    """Show repository status.

    VFS_PATH: Virtual filesystem path (default: / for all repos)

    \b
    Shows comprehensive status from the metadata store (fast).
    Use --refresh to update metadata before displaying.
    Use --github to fetch fresh GitHub API data (slower).

    Output format:
    - Interactive terminal: Table format by default
    - Piped/redirected: JSONL streaming by default
    - Use --table to force table output
    - Use --no-table to force JSONL output
    - Use -v/--verbose to show progress
    - Use -q/--quiet to suppress data output

    Examples:

    \b
        repoindex status                       # All repos (fast, from cache)
        repoindex status /by-tag/work/active   # Active work repos
        repoindex status /by-language/Python   # Python projects
        repoindex status /repos/myproject      # Single repo
        repoindex status / --refresh           # Refresh metadata, then show
        repoindex status --github              # Use fresh GitHub API data
        repoindex status --no-table            # Force JSONL output

        # Deprecated (still work):
        repoindex status -d ~/projects         # Use: repoindex status /repos
        repoindex status -t lang:python        # Use: repoindex status /by-language/Python
    """
    # Auto-detect table mode if not specified
    if table is None:
        import sys
        table = sys.stdout.isatty()  # Use table format for interactive terminals

    # Show deprecation warnings
    if dir is not None:
        import sys
        print("⚠️  Warning: -d/--dir is deprecated, use VFS path instead: repoindex status /repos", file=sys.stderr)

    if tag_filters:
        import sys
        print("⚠️  Warning: -t/--tag is deprecated, use VFS path instead: repoindex status /by-tag/...", file=sys.stderr)

    # Override config if flags are provided
    if no_pypi:
        config = load_config()
        config['pypi'] = config.get('pypi', {})
        config['pypi']['check_by_default'] = False

    # Determine repos to check
    from ..git_ops.utils import get_repos_from_vfs_path
    from ..utils import find_git_repos, find_git_repos_from_config, is_git_repo
    import os

    config = load_config()
    progress("Discovering repositories...")

    # Priority: VFS path > -d flag > -t flag > config
    if vfs_path and vfs_path != '/' and not dir and not tag_filters:
        # Use VFS path
        repo_paths = get_repos_from_vfs_path(vfs_path)
        if not repo_paths:
            raise NoReposFoundError(f"No repositories found at VFS path: {vfs_path}")
    elif dir is not None:
        # Deprecated: Use -d flag (backward compatibility)
        expanded_dir = os.path.expanduser(dir)
        expanded_dir = os.path.abspath(expanded_dir)

        if is_git_repo(expanded_dir):
            if not recursive:
                repo_paths = [expanded_dir]
            else:
                repo_paths = [expanded_dir]
                repo_paths.extend(find_git_repos(expanded_dir, recursive=True))
                repo_paths = list(set(repo_paths))
        else:
            repo_paths = find_git_repos(expanded_dir, recursive)
    else:
        # Use config directories (default)
        repo_paths = find_git_repos_from_config(
            config.get('general', {}).get('repository_directories', []),
            recursive
        )
        if not repo_paths:
            repo_paths = find_git_repos('.', recursive)
    
    total_repos = len(repo_paths)

    if total_repos == 0:
        raise NoReposFoundError("No repositories found in specified directories")

    progress(f"Found {total_repos} repositories")

    # Refresh metadata if requested
    if refresh:
        progress(f"Refreshing metadata for {total_repos} repositories...")
        from ..metadata import get_metadata_store
        metadata_store = get_metadata_store()
        for repo_path in repo_paths:
            metadata_store.refresh(repo_path)
        progress("Metadata refresh complete")
    
    # Get repository status as a generator
    # If VFS path was used, iterate over those specific repos
    # Otherwise, use the standard discovery process
    if vfs_path and vfs_path != '/' and not dir and not tag_filters:
        # VFS path was provided - use the filtered repo list
        def repos_from_vfs_paths():
            for repo_path in repo_paths:
                yield from _get_repository_status_for_path(repo_path, skip_pages_check=no_pages, use_github_api=github)
        repos_generator = repos_from_vfs_paths()
    else:
        # Use standard discovery
        repos_generator = get_repository_status(
            base_dir=dir if dir else None,
            recursive=recursive,
            skip_pages_check=no_pages,
            deduplicate=not no_dedup,
            tag_filters=tag_filters,
            all_tags=all_tags,
            use_github_api=github
        )
    
    if table:
        # For table output, we need to collect all repos
        repos = []
        with progress.task("Checking repository status", total=total_repos) as update:
            for i, repo in enumerate(repos_generator, 1):
                repos.append(repo)
                update(i, repo.get('name', ''))
                
                # Update description for GitHub Pages batch check
                if not no_pages and i == total_repos:
                    progress("Finalizing GitHub Pages status...")
        
        # Render as table (table display is not suppressed by quiet)
        render_status_table(repos)
    else:
        # Stream JSONL output (default behavior)
        repo_count = 0
        with progress.task("Checking repository status", total=total_repos) as update:
            for repo in repos_generator:
                repo_count += 1
                update(repo_count, repo.get('name', ''))
                if not quiet:
                    yield repo
        
        # Show summary
        if tag_filters:
            filtered_count = repo_count
            if filtered_count < total_repos:
                progress(f"Filtered: {filtered_count}/{total_repos} repositories matched")