"""
Activity Dashboard screen for real-time monitoring.
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Static, Button, Label, ListView, ListItem, Header, Footer,
    Input, Checkbox, DataTable
)
from textual.binding import Binding
from textual.reactive import reactive
from pathlib import Path
from typing import Dict, List, Set, Optional
from datetime import datetime, timezone
import asyncio

from .activity import ActivityFeed, ActivityEvent, RepositoryStats, EventType, debug_log
from .watcher import GitStatusPoller
from .file_poller import FileModificationPoller


class ActivityDashboard(Screen):
    """Main activity dashboard screen."""

    CSS = """
    ActivityDashboard {
        background: $surface;
        height: 100%;
        width: 100%;
    }

    #activity-header {
        dock: top;
        height: 3;
        background: $primary;
        color: $text;
        content-align: center middle;
    }

    #stats-bar {
        dock: top;
        height: 3;
        background: $panel;
        padding: 0 2;
    }

    Container {
        height: 1fr;
    }

    Vertical {
        height: 1fr;
    }

    #repo-table {
        height: 1fr;
        border: none;
        padding: 0 1;
    }

    .status-good {
        color: green;
    }

    .status-warning {
        color: yellow;
    }

    .status-error {
        color: red;
    }

    .event-line {
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("p", "toggle_pause", "Pause", show=True),
        Binding("c", "clear_feed", "Clear", show=True),
        Binding("e", "action_export_feed", "Export", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    TITLE = "repoindex htop"

    is_paused = reactive(False)

    def __init__(self, repos: List[str]):
        """Initialize dashboard.

        Args:
            repos: List of repository paths to monitor
        """
        super().__init__()
        self.repos = repos
        self.activity_feed = ActivityFeed(max_events=500)
        self.stats = RepositoryStats()

        # Will be initialized in on_mount
        self.file_poller: Optional[FileModificationPoller] = None
        self.git_poller: Optional[GitStatusPoller] = None

        self._update_task: Optional[asyncio.Task] = None
        self._event_listener = None

    def compose(self) -> ComposeResult:
        """Compose the dashboard."""
        yield Header()

        # Compact status bar (like htop header)
        with Horizontal(id="stats-bar"):
            yield Static("●", id="status-indicator")
            yield Static("Repos: 0", id="stat-repos")
            yield Static("Dirty: 0", id="stat-dirty")
            yield Static("Unpushed: 0", id="stat-unpushed")
            yield Static("Active: 0", id="stat-active")

        # Repository table (like htop's process table)
        table = DataTable(id="repo-table")
        table.cursor_type = "row"
        table.zebra_stripes = True
        yield table

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize monitoring when screen is mounted."""
        # Set up the table
        table = self.query_one("#repo-table", DataTable)
        table.add_columns("Repository", "Last Activity", "Status", "Unpushed")

        # Store repo data
        self.repo_data = {}  # Maps repo_path -> repo info dict

        # Start UI update loop that will refresh the table
        self._update_task = asyncio.create_task(self._update_loop())

        self.notify(f"Monitoring {len(self.repos)} repos", severity="information")

        # Initial stats update
        await self.update_stats()

        # Initial table population
        await self.update_table()

    async def on_unmount(self) -> None:
        """Cleanup when screen is unmounted."""
        # Cancel update task
        if self._update_task:
            self._update_task.cancel()

    async def _update_loop(self):
        """Update UI periodically."""
        while True:
            try:
                await asyncio.sleep(2)  # Update every 2 seconds
                if not self.is_paused:
                    await self.update_table()
                    await self.update_stats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Don't crash on errors
                pass

    async def update_table(self):
        """Update the repository table (like repoindex top but real-time)."""
        import subprocess
        from datetime import datetime, timezone

        # Gather repo info (use same logic as repoindex top)
        repo_info = []

        for repo_path in self.repos:
            try:
                info = await self._get_repo_info_async(repo_path)
                if info:
                    repo_info.append(info)
            except Exception:
                continue

        # Sort by most recent activity
        repo_info.sort(key=lambda r: r.get('last_modified', 0), reverse=True)

        # Update table
        table = self.query_one("#repo-table", DataTable)
        table.clear()

        for repo in repo_info:
            status = "✓ clean" if not repo['is_dirty'] else "● dirty"
            unpushed = str(repo['unpushed_count']) if repo['unpushed_count'] > 0 else "-"

            table.add_row(
                repo['name'],
                repo['age_display'],
                status,
                unpushed
            )

    async def _get_repo_info_async(self, repo_path: str):
        """Get repo info asynchronously (same logic as repoindex top)."""
        repo_name = Path(repo_path).name

        # Check if dirty
        try:
            result = await asyncio.create_subprocess_exec(
                'git', 'status', '--porcelain',
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            is_dirty = len(stdout.decode().strip()) > 0
        except Exception:
            is_dirty = False

        # Get unpushed count
        try:
            result = await asyncio.create_subprocess_exec(
                'git', 'log', '@{u}..HEAD', '--oneline',
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            unpushed_count = len(stdout.decode().strip().split('\n')) if stdout.decode().strip() else 0
        except Exception:
            unpushed_count = 0

        # Get last modification time
        last_modified = 0
        age_display = "unknown"

        if is_dirty:
            # Get most recent file modification
            mod_time = await self._get_last_modification_time(repo_path)
            last_modified = mod_time.timestamp()
            age_seconds = datetime.now(timezone.utc).timestamp() - last_modified
            age_display = self._format_age(age_seconds)
        elif unpushed_count > 0:
            # Get last commit time for unpushed commits
            commit_time = await self._get_last_commit_time(repo_path)
            last_modified = commit_time.timestamp()
            age_seconds = datetime.now(timezone.utc).timestamp() - last_modified
            age_display = self._format_age(age_seconds)
        else:
            # For clean repos, get last commit time
            commit_time = await self._get_last_commit_time(repo_path)
            last_modified = commit_time.timestamp()
            age_seconds = datetime.now(timezone.utc).timestamp() - last_modified
            age_display = self._format_age(age_seconds)

        return {
            'name': repo_name,
            'path': repo_path,
            'is_dirty': is_dirty,
            'unpushed_count': unpushed_count,
            'last_modified': last_modified,
            'age_display': age_display
        }

    def _format_age(self, seconds):
        """Format age in seconds to human-readable string."""
        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m ago"
        elif seconds < 86400:
            return f"{int(seconds / 3600)}h ago"
        else:
            return f"{int(seconds / 86400)}d ago"

    async def _get_last_modification_time(self, repo_path: str) -> datetime:
        """Get the last modification time for modified files in a repo."""
        try:
            # Get list of modified files
            result = await asyncio.create_subprocess_exec(
                'git', 'status', '--porcelain',
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()

            if not stdout:
                return datetime.now(timezone.utc)

            # Parse modified files and find most recent mtime
            max_mtime = 0
            for line in stdout.decode().strip().split('\n'):
                if len(line) > 3:
                    filename = line[3:].strip()
                    filepath = Path(repo_path) / filename
                    try:
                        mtime = filepath.stat().st_mtime
                        if mtime > max_mtime:
                            max_mtime = mtime
                    except (OSError, FileNotFoundError):
                        continue

            if max_mtime > 0:
                return datetime.fromtimestamp(max_mtime, tz=timezone.utc)

        except Exception:
            pass

        return datetime.now(timezone.utc)

    async def _get_last_commit_time(self, repo_path: str) -> datetime:
        """Get the timestamp of the last commit."""
        try:
            # Get last commit timestamp
            result = await asyncio.create_subprocess_exec(
                'git', 'log', '-1', '--format=%ct',
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()

            if stdout:
                timestamp = int(stdout.decode().strip())
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)

        except Exception:
            pass

        return datetime.now(timezone.utc)

    async def initial_scan(self):
        """Do initial scan of repositories to populate feed."""
        self.notify("Scanning repositories...", severity="information")

        event_count = 0
        events_to_add = []

        # Check ALL repos to find the most recently active ones
        for i, repo_path in enumerate(self.repos):
            try:
                # Check if dirty
                result = await asyncio.create_subprocess_exec(
                    'git', 'status', '--porcelain',
                    cwd=repo_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await result.communicate()
                is_dirty = len(stdout.decode().strip()) > 0

                repo_name = Path(repo_path).name

                if is_dirty:
                    # Get actual modification time from modified files
                    mod_time = await self._get_last_modification_time(repo_path)
                    await self.stats.mark_dirty(repo_path, mod_time)
                    event = ActivityEvent(
                        timestamp=mod_time,
                        repo_path=repo_path,
                        repo_name=repo_name,
                        event_type=EventType.FILE_MODIFIED,
                        message="Has uncommitted changes"
                    )
                    events_to_add.append(event)

                # Check for unpushed commits
                result = await asyncio.create_subprocess_exec(
                    'git', 'log', '@{u}..HEAD', '--oneline',
                    cwd=repo_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await result.communicate()
                unpushed_count = len(stdout.decode().strip().split('\n')) if stdout.decode().strip() else 0

                if unpushed_count > 0:
                    # Get last commit time
                    commit_time = await self._get_last_commit_time(repo_path)
                    await self.stats.mark_unpushed(repo_path, commit_time)
                    event = ActivityEvent(
                        timestamp=commit_time,
                        repo_path=repo_path,
                        repo_name=repo_name,
                        event_type=EventType.GIT_COMMIT,
                        message=f"{unpushed_count} unpushed commit(s)"
                    )
                    events_to_add.append(event)

            except Exception as e:
                pass  # Skip repos with errors

        # Sort events by timestamp (most recent first) and add top 50
        events_to_add.sort(key=lambda e: e.timestamp, reverse=True)

        # Add to feed in reverse order so oldest is first, then newer ones insert at top
        for event in reversed(events_to_add[:50]):
            await self.activity_feed.add_event(event)
            await self.on_new_event(event)
            event_count += 1

        self.notify(f"Scanned {len(self.repos)} repos, found {event_count} recent events", severity="information")

    async def on_new_event(self, event: ActivityEvent):
        """Handle new activity event.

        Args:
            event: New event
        """
        debug_log(f"[DASHBOARD] on_new_event called: {event.repo_name}/{event.file_path or event.message}")

        # Add to activity feed list
        feed = self.query_one("#activity-feed", ListView)

        # Format event
        event_text = f"{event.icon} {event.age_display:8s} {event.repo_name:20s} {event.file_path or event.message}"

        # Create list item
        item = ListItem(Label(event_text), classes="event-line")

        # Insert at top (most recent first)
        if len(feed.children) > 0:
            await feed.mount(item, before=0)
        else:
            await feed.append(item)

        debug_log(f"[DASHBOARD] Event added to UI, total items: {len(feed.children)}")

        # Limit feed size
        if len(feed.children) > 100:
            feed.children[-1].remove()

    async def update_stats(self):
        """Update statistics bar."""
        stats = await self.stats.get_stats()

        self.query_one("#stat-repos", Static).update(f"Repos: {len(self.repos)}")
        self.query_one("#stat-active", Static).update(f"Active: {stats['active']}")
        self.query_one("#stat-dirty", Static).update(f"Dirty: {stats['dirty']}")
        self.query_one("#stat-unpushed", Static).update(f"Unpushed: {stats['unpushed']}")


    async def action_toggle_pause(self):
        """Toggle pause/resume monitoring (keyboard shortcut: p)."""
        self.is_paused = not self.is_paused

        indicator = self.query_one("#status-indicator", Static)

        if self.is_paused:
            if self.file_poller:
                self.file_poller.stop()
            if self.git_poller:
                self.git_poller.stop()
            indicator.update("⏸")
            self.notify("⏸ Monitoring paused", severity="warning")
        else:
            if self.file_poller:
                self.file_poller.start()
            if self.git_poller:
                self.git_poller.start()
            indicator.update("●")
            self.notify("● Monitoring resumed", severity="information")

    async def action_clear_feed(self):
        """Clear activity feed."""
        await self.activity_feed.clear()
        feed = self.query_one("#activity-feed", ListView)
        await feed.clear()

    async def action_refresh(self):
        """Refresh stats and attention list."""
        await self.update_stats()
        await self.update_attention_list()

    async def action_toggle_select(self):
        """Toggle selection of focused repository."""
        # TODO: Implement multi-select
        pass

    async def action_export_feed(self):
        """Export activity feed to JSON (keyboard shortcut: e)."""
        output_file = f"repoindex-activity-{Path.cwd().name}.json"
        await self.activity_feed.export_json(output_file)
        self.notify(f"✓ Exported to {output_file}", severity="information")
