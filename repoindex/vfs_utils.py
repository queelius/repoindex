"""
Virtual filesystem utilities.

Provides VFS structure building and path resolution functions
that can be shared across modules without circular dependencies.
"""

from typing import Dict, Any, List
from pathlib import Path

from .utils import find_git_repos_from_config
from .metadata import get_metadata_store
from .commands.catalog import get_repository_tags


def _build_config_vfs(config_node: Dict[str, Any], config: Dict[str, Any]):
    """Populate the /config VFS node with configuration structure.

    Args:
        config_node: The /config VFS node to populate
        config: Configuration dictionary
    """
    # Add repos node with configured repository directories
    config_node["repos"] = {"type": "directory", "children": {}}
    repos = config.get('repository_directories', [])
    for i, repo_dir in enumerate(repos):
        # Use index as key to avoid conflicts
        key = f"dir_{i}"
        # But show the full path in the name for clarity
        display_name = repo_dir.replace('~/', '') if '~/' in repo_dir else repo_dir
        config_node["repos"]["children"][display_name] = {
            "type": "config_value",
            "value": repo_dir,
            "path": f"/config/repos/{key}",
            "index": i
        }

    # Add github node
    config_node["github"] = {"type": "directory", "children": {}}
    github_config = config.get('github', {})
    if 'token' in github_config:
        token_value = github_config['token']
        # Mask the token for display
        masked = token_value[:4] + "..." + token_value[-4:] if len(token_value) > 8 else "***"
        config_node["github"]["children"]["token"] = {
            "type": "config_value",
            "value": masked,
            "path": "/config/github/token"
        }

    # Add rate_limit settings
    if 'rate_limit' in github_config:
        config_node["github"]["children"]["rate_limit"] = {"type": "directory", "children": {}}
        rate_limit = github_config['rate_limit']
        for key, value in rate_limit.items():
            config_node["github"]["children"]["rate_limit"]["children"][key] = {
                "type": "config_value",
                "value": str(value),
                "path": f"/config/github/rate_limit/{key}"
            }

    # Add pypi node
    if 'pypi' in config:
        config_node["pypi"] = {"type": "directory", "children": {}}
        pypi_config = config['pypi']
        for key, value in pypi_config.items():
            config_node["pypi"]["children"][key] = {
                "type": "config_value",
                "value": str(value),
                "path": f"/config/pypi/{key}"
            }



def build_vfs_structure(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build the VFS structure for stateless access.

    Returns:
        VFS tree structure
    """
    repo_dirs = config.get('repository_directories', [])
    if not repo_dirs:
        repo_dirs = ['.']

    repo_paths = find_git_repos_from_config(
        repo_dirs, recursive=False,
        exclude_dirs_config=config.get('exclude_directories', [])
    )
    metadata_store = get_metadata_store()

    # Build VFS structure
    vfs: Dict[str, Any] = {
        "/": {
            "type": "directory",
            "children": {
                "repos": {"type": "directory", "children": {}},
                "by-language": {"type": "directory", "children": {}},
                "by-tag": {"type": "directory", "children": {}},
                "by-status": {"type": "directory", "children": {}},
                "config": {"type": "directory", "children": {}},
            }
        }
    }

    repos_node: Dict[str, Any] = vfs["/"]["children"]["repos"]["children"]
    by_lang_node: Dict[str, Any] = vfs["/"]["children"]["by-language"]["children"]
    by_tag_node: Dict[str, Any] = vfs["/"]["children"]["by-tag"]["children"]
    by_status_node: Dict[str, Any] = vfs["/"]["children"]["by-status"]["children"]
    config_node: Dict[str, Any] = vfs["/"]["children"]["config"]["children"]

    # Populate /config with configuration structure
    _build_config_vfs(config_node, config)

    for repo_path in repo_paths:
        repo_name = Path(repo_path).name

        # Add to /repos/
        repos_node[repo_name] = {
            "type": "repository",
            "path": repo_path,
            "children": {}
        }

        # Get metadata for grouping
        metadata = metadata_store.get(repo_path)
        if not metadata:
            metadata = {}

        # Group by language
        language = metadata.get('language', 'Unknown')
        if language not in by_lang_node:
            by_lang_node[language] = {"type": "directory", "children": {}}
        by_lang_node[language]["children"][repo_name] = {
            "type": "symlink",
            "target": f"/repos/{repo_name}",
            "path": repo_path
        }

        # Group by status
        status = metadata.get('status', {})
        if status.get('has_uncommitted_changes') or status.get('has_unpushed_commits'):
            status_key = 'dirty'
        else:
            status_key = 'clean'

        if status_key not in by_status_node:
            by_status_node[status_key] = {"type": "directory", "children": {}}
        by_status_node[status_key]["children"][repo_name] = {
            "type": "symlink",
            "target": f"/repos/{repo_name}",
            "path": repo_path
        }

        # Group by tags (hierarchical)
        tags = get_repository_tags(repo_path, metadata)
        for tag in tags:
            _add_tag_to_vfs(by_tag_node, tag, repo_name, repo_path)

    return vfs


def _add_tag_to_vfs(vfs_node: Dict[str, Any], tag: str, repo_name: str, repo_path: str):
    """Add a repository to the VFS under a hierarchical tag."""
    levels = _parse_tag_levels(tag)

    current = vfs_node
    for i, level in enumerate(levels):
        if i == len(levels) - 1:
            # Leaf level - add repository symlink
            if level not in current:
                current[level] = {"type": "directory", "children": {}}
            current[level]["children"][repo_name] = {
                "type": "symlink",
                "target": f"/repos/{repo_name}",
                "path": repo_path
            }
        else:
            # Directory level
            if level not in current:
                current[level] = {"type": "directory", "children": {}}
            current = current[level]["children"]


def _parse_tag_levels(tag: str) -> List[str]:
    """Parse a tag into hierarchical levels."""
    if not tag:
        return []

    if ':' in tag:
        key, value = tag.split(':', 1)
        if value and '/' in value:
            return [key] + value.split('/')
        elif value:
            return [key, value]
        else:
            return [key]
    elif '/' in tag:
        levels = tag.split('/')
        return [level for level in levels if level]
    else:
        return [tag]


def resolve_vfs_path(vfs: Dict[str, Any], path: str) -> Dict[str, Any]:
    """Resolve a VFS path to a node.

    Args:
        vfs: VFS structure
        path: Path to resolve (e.g., "/by-tag/alex/beta")

    Returns:
        VFS node or None if not found
    """
    if path == '/':
        return vfs['/']

    # Normalize path
    path = path.strip('/')
    parts = path.split('/')

    current = vfs['/']['children']
    for i, part in enumerate(parts):
        if part in current:
            node = current[part]

            # If this is the last part, return the node directly
            if i == len(parts) - 1:
                return node

            # If it's a leaf node (repository/symlink), can't descend further
            if node['type'] in ('repository', 'symlink'):
                return None  # Path doesn't exist

            # Descend into children
            if 'children' in node:
                current = node['children']
            else:
                return None
        else:
            return None

    # Shouldn't reach here, but just in case
    return {"type": "directory", "children": current}
