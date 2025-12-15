"""
Git operations module for ghops.

Provides utilities for executing git commands on single or multiple repositories.
"""

from .utils import run_git, get_repos_from_vfs_path

__all__ = ['run_git', 'get_repos_from_vfs_path']
