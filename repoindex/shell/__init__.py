"""
repoindex shell - Interactive filesystem-like interface for repository management.

Provides a VFS (Virtual File System) interface with Unix-like commands.
"""

from .shell import RepoIndexShell, run_shell

__all__ = ['RepoIndexShell', 'run_shell']
