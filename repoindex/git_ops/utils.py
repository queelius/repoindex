"""
Common utilities for git operations.
"""

from typing import List, Dict, Any, Optional, Tuple
import subprocess

from ..config import load_config
from ..vfs_utils import build_vfs_structure, resolve_vfs_path


def run_git(repo_path: str, command: List[str], capture_output: bool = True) -> Tuple[Optional[str], int]:
    """Run a git command in a repository.

    Args:
        repo_path: Path to repository
        command: Git command as list (e.g., ['status', '--short'])
        capture_output: Whether to capture output

    Returns:
        Tuple of (output, returncode)
    """
    full_command = ['git'] + command

    try:
        if capture_output:
            result = subprocess.run(
                full_command,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.stdout, result.returncode
        else:
            result = subprocess.run(
                full_command,
                cwd=repo_path,
                timeout=30
            )
            return None, result.returncode
    except subprocess.TimeoutExpired:
        return None, -1
    except Exception as e:
        return f"Error: {str(e)}", -1


def get_repos_from_vfs_path(vfs_path: Optional[str] = None) -> List[str]:
    """Get all repository paths from a VFS path.

    Args:
        vfs_path: VFS path (e.g., "/by-tag/work/active")
                 If None, returns all repos

    Returns:
        List of repository absolute paths
    """
    config = load_config()
    vfs = build_vfs_structure(config)

    if vfs_path is None or vfs_path == '/':
        # Return all repos
        return collect_all_repos(vfs)

    node = resolve_vfs_path(vfs, vfs_path)

    if not node:
        return []

    if node['type'] == 'repository':
        return [node['path']]
    elif node['type'] == 'symlink':
        return [node['path']]
    elif node['type'] == 'directory':
        return collect_repos_from_node(node)

    return []


def collect_repos_from_node(node: Dict[str, Any]) -> List[str]:
    """Recursively collect all repository paths from a VFS node.

    Args:
        node: VFS node dictionary

    Returns:
        List of repository paths
    """
    repos = []

    if 'children' not in node:
        return repos

    for child in node['children'].values():
        if child.get('type') == 'repository':
            repos.append(child['path'])
        elif child.get('type') == 'symlink':
            repos.append(child['path'])
        elif child.get('type') == 'directory' and 'children' in child:
            repos.extend(collect_repos_from_node(child))

    return repos


def collect_all_repos(vfs: Dict[str, Any]) -> List[str]:
    """Collect all repositories from VFS.

    Args:
        vfs: VFS structure

    Returns:
        List of all repository paths
    """
    root = vfs.get('/')
    if not root:
        return []

    repos_node = root.get('children', {}).get('repos', {})
    return collect_repos_from_node(repos_node)


def parse_git_status_output(output: str) -> Dict[str, Any]:
    """Parse git status output into structured data.

    Args:
        output: Output from 'git status --porcelain'

    Returns:
        Dictionary with status information
    """
    lines = output.strip().split('\n') if output else []

    modified = []
    added = []
    deleted = []
    renamed = []
    untracked = []

    for line in lines:
        if not line:
            continue

        status = line[:2]
        filename = line[3:]

        if status[0] == 'M' or status[1] == 'M':
            modified.append(filename)
        elif status[0] == 'A':
            added.append(filename)
        elif status[0] == 'D' or status[1] == 'D':
            deleted.append(filename)
        elif status[0] == 'R':
            renamed.append(filename)
        elif status == '??':
            untracked.append(filename)

    return {
        'modified': modified,
        'added': added,
        'deleted': deleted,
        'renamed': renamed,
        'untracked': untracked,
        'clean': len(lines) == 0 or all(not line for line in lines)
    }
