"""
ghops shell - Interactive filesystem-like interface for repository management.

Provides a VFS (Virtual File System) interface with Unix-like commands.
"""

from .shell import GhopsShell, run_shell

__all__ = ['GhopsShell', 'run_shell']
