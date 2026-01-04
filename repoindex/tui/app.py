"""
Simplified TUI application - just the activity dashboard.
"""

from textual.app import App
from typing import Optional

from .dashboard import ActivityDashboard


class RepoIndexApp(App):
    """Simple htop-style activity monitor."""

    TITLE = "repoindex htop - Repository Activity Monitor"

    def __init__(self, config_path: Optional[str] = None):
        """Initialize app.

        Args:
            config_path: Optional path to config file
        """
        super().__init__()
        self.config_path = config_path

    def on_mount(self) -> None:
        """Mount the dashboard screen directly."""
        from ..config import load_config
        from ..utils import find_git_repos_from_config

        # Load config
        if self.config_path:
            import os
            os.environ['REPOINDEX_CONFIG'] = self.config_path

        config = load_config()

        # Find all repos
        repo_dirs = config.get('repository_directories', [])
        if not repo_dirs:
            repo_dirs = ['.']

        repos = find_git_repos_from_config(repo_dirs, recursive=False)

        # Push the activity dashboard as the only screen
        dashboard = ActivityDashboard(repos)
        self.push_screen(dashboard)


def run_tui(config_path: Optional[str] = None) -> None:
    """Run the htop application.

    Args:
        config_path: Path to configuration file
    """
    app = RepoIndexApp(config_path)
    app.run()
