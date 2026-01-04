"""
Common repository filtering utilities for repoindex commands.

Provides a consistent interface for filtering repositories by:
- Directory path (-d/--dir)
- Recursive scanning (-r/--recursive)
- Tags (-t/--tag)
- Query language (--query)
"""

import os
import sys
from typing import List, Dict, Optional, Tuple

from repoindex.config import load_config, get_repository_directories
from repoindex.utils import find_git_repos, find_git_repos_from_config, is_git_repo
from repoindex.query import Query
from repoindex.metadata import MetadataStore
from repoindex.commands.catalog import get_repositories_by_tags, get_implicit_tags


def get_filtered_repos(
    dir: Optional[str] = None,
    recursive: bool = False,
    tag_filters: Optional[List[str]] = None,
    all_tags: bool = False,
    query: Optional[str] = None,
    config: Optional[Dict] = None
) -> Tuple[List[str], Optional[str]]:
    """
    Get filtered list of repository paths based on various criteria.

    Discovery priority:
    1. --dir flag (explicit override)
    2. repository_directories from config
    3. Current directory (fallback)

    Filter priority:
    1. Query language (most flexible)
    2. Tag filters
    3. No filter (all discovered repos)

    Args:
        dir: Directory to search in (overrides config)
        recursive: Whether to search recursively
        tag_filters: List of tag filters (e.g., ["lang:python", "has:docs"])
        all_tags: Whether to match all tags (True) or any (False)
        query: Query language expression
        config: Configuration dict (will load if not provided)

    Returns:
        Tuple of (list of repo paths, filter description for errors)
    """
    if config is None:
        config = load_config()

    repos = []
    filter_desc = None

    # Step 1: Discover repositories
    if dir:
        # Explicit directory provided
        expanded_dir = os.path.abspath(os.path.expanduser(dir))
        repos = find_git_repos(expanded_dir, recursive)
    else:
        # Check config
        repo_dirs = get_repository_directories(config)
        if repo_dirs:
            repos = find_git_repos_from_config(repo_dirs, recursive)
        else:
            # Fallback: current directory
            cwd = os.getcwd()
            if is_git_repo(cwd):
                repos = [cwd]
            else:
                repos = find_git_repos(cwd, recursive=True)
                if not repos:
                    # Helpful message to stderr
                    print(
                        "No repositories found. Either:\n"
                        "  1. Configure repository_directories in ~/.repoindex/config.json\n"
                        "  2. Use -d/--dir to specify a directory\n"
                        "  3. Run from within a git repository",
                        file=sys.stderr
                    )

    # Step 2: Apply filters
    if query:
        filter_desc = f"query: {query}"
        store = MetadataStore()
        query_obj = Query(query)

        filtered_repos = []
        for repo_path in repos:
            metadata = store.get(repo_path) or {}
            tags = get_implicit_tags(repo_path, metadata)

            context = {
                'path': repo_path,
                'name': os.path.basename(repo_path),
                'tags': list(tags),
                **metadata
            }

            if query_obj.evaluate(context):
                filtered_repos.append(repo_path)

        repos = filtered_repos

    elif tag_filters:
        filter_desc = "tags: " + (" AND " if all_tags else " OR ").join(tag_filters)

        filtered = list(get_repositories_by_tags(tag_filters, config, all_tags))
        tag_paths = {r["path"] for r in filtered}

        # Intersect with discovered repos
        repos = [r for r in repos if r in tag_paths]

    return repos, filter_desc


def add_repo_discovery_options(func):
    """
    Decorator to add standard repository discovery options to a Click command.

    Adds:
    - -d/--dir: Directory to search (overrides config)
    - -r/--recursive: Recursive search
    - -t/--tag: Tag filters
    - --all-tags: Match all tags
    - --query: Query language expression
    """
    import click

    # Add options in reverse order (they get applied bottom-up)
    func = click.option(
        "--query",
        help="Filter with query (e.g., \"language == 'Python' and stars > 10\")"
    )(func)
    func = click.option(
        "--all-tags",
        is_flag=True,
        help="Match all tags (default: match any)"
    )(func)
    func = click.option(
        "-t", "--tag",
        "tag_filters",
        multiple=True,
        help="Filter by tag (e.g., lang:python)"
    )(func)
    func = click.option(
        "-r", "--recursive",
        is_flag=True,
        help="Search subdirectories recursively"
    )(func)
    func = click.option(
        "-d", "--dir",
        "dir",
        help="Directory to search (overrides config)"
    )(func)

    return func


# Alias for backward compatibility with existing code
add_common_repo_options = add_repo_discovery_options