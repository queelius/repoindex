"""
TUI (Text User Interface) for ghops - simplified activity dashboard only.
"""

from .app import GhopsApp, run_tui
from .dashboard import ActivityDashboard

__all__ = [
    'GhopsApp',
    'run_tui',
    'ActivityDashboard',
]
