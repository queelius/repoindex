"""
TUI (Text User Interface) for repoindex - simplified activity dashboard only.
"""

from .app import RepoIndexApp, run_tui
from .dashboard import ActivityDashboard

__all__ = [
    'RepoIndexApp',
    'run_tui',
    'ActivityDashboard',
]
