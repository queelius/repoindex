"""
Common repository filtering utilities for repoindex commands.

Provides a consistent interface for filtering repositories by:
- Directory path
- Tags (simple key:value filtering)
- Query language (complex expressions with fuzzy matching)
"""

import os
from typing import List, Dict, Optional, Tuple

from repoindex.config import load_config
from repoindex.utils import find_git_repos, find_git_repos_from_config
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
    
    Priority order:
    1. Query language (most flexible)
    2. Tag filters (simple but powerful)
    3. Directory path (basic filtering)
    
    Args:
        dir: Directory to search in
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
    
    if query:
        # Query language takes precedence
        filter_desc = f"query: {query}"
        store = MetadataStore()
        query_obj = Query(query)
        
        # Get all repos from config or dir
        if dir:
            all_repos = find_git_repos(dir, recursive)
        else:
            repo_dirs = config.get("general", {}).get("repository_directories", [])
            all_repos = find_git_repos_from_config(repo_dirs, recursive)
        
        # Filter with query
        for repo_path in all_repos:
            metadata = store.get(repo_path) or {}
            tags = get_implicit_tags(repo_path, metadata)
            
            # Create evaluation context
            context = {
                'path': repo_path,
                'name': os.path.basename(repo_path),
                'tags': list(tags),
                **metadata
            }
            
            if query_obj.evaluate(context):
                repos.append(repo_path)
                
    elif tag_filters:
        # Tag filtering
        filter_desc = "tags: " + (" AND " if all_tags else " OR ").join(tag_filters)
        
        filtered = list(get_repositories_by_tags(tag_filters, config, all_tags))
        repos = [r["path"] for r in filtered]
        
        # If dir specified, further filter by directory
        if dir:
            dir_path = os.path.abspath(os.path.expanduser(dir))
            repos = [r for r in repos if r.startswith(dir_path)]
            
    else:
        # Default behavior - directory based
        if dir:
            repos = find_git_repos(dir, recursive)
        else:
            repo_dirs = config.get("general", {}).get("repository_directories", [])
            repos = find_git_repos_from_config(repo_dirs, recursive)
    
    return repos, filter_desc


def add_common_repo_options(func):
    """
    Decorator to add common repository filtering options to a Click command.
    
    Adds:
    - --dir: Directory to search
    - -r/--recursive: Recursive search
    - -t/--tag: Tag filters
    - --all-tags: Match all tags
    - --query: Query language
    """
    import click
    
    # Add options in reverse order (they get applied bottom-up)
    func = click.option("--query", help="Filter with query language (e.g., 'lang:python and stars > 10')")(func)
    func = click.option("--all-tags", is_flag=True, help="Match all tags (default: match any)")(func)
    func = click.option("-t", "--tag", "tag_filters", multiple=True, help="Filter by tags (e.g., lang:python, dir:projects)")(func)
    func = click.option("-r", "--recursive", is_flag=True, help="Search recursively")(func)
    func = click.option("--dir", help="Directory to search for repositories")(func)
    
    return func