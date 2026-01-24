"""
Git client infrastructure for repoindex.

Provides a clean abstraction over git command execution.
All git operations go through this client, making them:
- Easy to mock for testing
- Consistent in error handling
- Isolated from business logic
"""

import subprocess
from dataclasses import dataclass
from typing import Optional, List, Tuple
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class GitStatus:
    """Result of git status command."""
    branch: str = "main"
    clean: bool = True
    ahead: int = 0
    behind: int = 0
    has_upstream: bool = False
    uncommitted_changes: bool = False
    untracked_files: int = 0
    staged_files: int = 0
    modified_files: int = 0


@dataclass
class GitTag:
    """A git tag with metadata."""
    name: str
    commit: str
    date: datetime
    tagger: str = ""
    message: str = ""


@dataclass
class GitCommit:
    """A git commit with metadata."""
    hash: str
    date: datetime
    author: str
    email: str
    message: str


class GitClient:
    """
    Abstraction over git commands.

    Provides methods for common git operations with consistent
    error handling and return types.

    Example:
        client = GitClient()
        status = client.status("/path/to/repo")
        if status.clean:
            print("Repository is clean")
    """

    def __init__(self, timeout: int = 30):
        """
        Initialize GitClient.

        Args:
            timeout: Command timeout in seconds (default: 30)
        """
        self.timeout = timeout

    def _run(
        self,
        cmd: str,
        cwd: str,
        check: bool = False,
        capture_stderr: bool = False
    ) -> Tuple[Optional[str], int]:
        """
        Run a git command.

        Args:
            cmd: Command to run
            cwd: Working directory
            check: Raise on non-zero exit
            capture_stderr: Include stderr in output

        Returns:
            Tuple of (stdout, returncode)
        """
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            output = result.stdout
            if capture_stderr and result.stderr:
                output += result.stderr

            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode,
                    cmd,
                    output=result.stdout,
                    stderr=result.stderr
                )

            return output.strip() if output else None, result.returncode

        except subprocess.TimeoutExpired:
            logger.warning(f"Git command timed out: {cmd}")
            return None, -1
        except Exception as e:
            logger.error(f"Git command failed: {cmd} - {e}")
            return None, -1

    def is_git_repo(self, path: str) -> bool:
        """Check if path is a git repository."""
        git_dir = Path(path) / ".git"
        return git_dir.exists()

    def status(self, path: str) -> GitStatus:
        """
        Get repository status.

        Args:
            path: Path to git repository

        Returns:
            GitStatus with branch, clean status, etc.
        """
        result = GitStatus()

        # Get branch name
        output, code = self._run("git rev-parse --abbrev-ref HEAD", cwd=path)
        if code == 0 and output:
            result = GitStatus(branch=output.strip())

        # Check for uncommitted changes
        output, code = self._run("git status --porcelain", cwd=path)
        if code == 0:
            if output:
                lines = output.strip().split('\n') if output.strip() else []
                result = GitStatus(
                    branch=result.branch,
                    clean=False,
                    uncommitted_changes=True,
                    untracked_files=sum(1 for line in lines if line.startswith('??')),
                    staged_files=sum(1 for line in lines if line[0] in 'MADRC'),
                    modified_files=sum(1 for line in lines if line[1] in 'MADRC')
                )
            else:
                result = GitStatus(branch=result.branch, clean=True)

        # Check upstream status
        output, code = self._run("git rev-parse --abbrev-ref @{upstream}", cwd=path)
        has_upstream = code == 0 and output

        if has_upstream:
            # Get ahead/behind counts
            output, code = self._run("git rev-list --left-right --count HEAD...@{upstream}", cwd=path)
            if code == 0 and output:
                parts = output.strip().split()
                if len(parts) == 2:
                    try:
                        ahead = int(parts[0])
                        behind = int(parts[1])
                        result = GitStatus(
                            branch=result.branch,
                            clean=result.clean,
                            ahead=ahead,
                            behind=behind,
                            has_upstream=True,
                            uncommitted_changes=result.uncommitted_changes,
                            untracked_files=result.untracked_files,
                            staged_files=result.staged_files,
                            modified_files=result.modified_files
                        )
                    except ValueError:
                        pass

        return result

    def remote_url(self, path: str, remote: str = "origin") -> Optional[str]:
        """
        Get remote URL.

        Args:
            path: Path to git repository
            remote: Remote name (default: "origin")

        Returns:
            Remote URL or None if not found
        """
        output, code = self._run(f"git config --get remote.{remote}.url", cwd=path)
        if code == 0 and output:
            return output.strip()
        return None

    def tags(
        self,
        path: str,
        since: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[GitTag]:
        """
        List git tags.

        Args:
            path: Path to git repository
            since: Only tags after this time
            limit: Maximum tags to return

        Returns:
            List of GitTag objects, sorted newest first
        """
        cmd = '''git for-each-ref --sort=-creatordate \
                 --format='%(refname:short)|%(creatordate:iso8601)|%(objectname:short)|%(taggeremail)|%(subject)' \
                 refs/tags'''

        if limit:
            cmd += f' --count={limit * 2}'  # Get extra in case we filter

        output, code = self._run(cmd, cwd=path)
        if code != 0 or not output:
            return []

        tags = []
        for line in output.strip().split('\n'):
            if not line or '|' not in line:
                continue

            parts = line.split('|', 4)
            if len(parts) < 3:
                continue

            name = parts[0].strip()
            date_str = parts[1].strip()
            commit = parts[2].strip()
            tagger = parts[3].strip() if len(parts) > 3 else ''
            message = parts[4].strip() if len(parts) > 4 else ''

            # Parse date
            try:
                date = datetime.fromisoformat(
                    date_str.replace(' ', 'T').replace(' +', '+').replace(' -', '-')
                )
                if date.tzinfo:
                    date = date.replace(tzinfo=None)
            except (ValueError, AttributeError):
                date = datetime.now()

            # Apply time filter
            if since and date < since:
                continue

            tags.append(GitTag(
                name=name,
                commit=commit,
                date=date,
                tagger=tagger,
                message=message
            ))

            if limit and len(tags) >= limit:
                break

        return tags

    def log(
        self,
        path: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50
    ) -> List[GitCommit]:
        """
        Get commit log.

        Args:
            path: Path to git repository
            since: Only commits after this time
            until: Only commits before this time
            limit: Maximum commits to return

        Returns:
            List of GitCommit objects
        """
        cmd = f'git log --format="%H|%aI|%an|%ae|%s" -n {limit}'

        if since:
            cmd += f' --since="{since.isoformat()}"'
        if until:
            cmd += f' --until="{until.isoformat()}"'

        output, code = self._run(cmd, cwd=path)
        if code != 0 or not output:
            return []

        commits = []
        for line in output.strip().split('\n'):
            if not line or '|' not in line:
                continue

            parts = line.split('|', 4)
            if len(parts) < 5:
                continue

            commit_hash = parts[0].strip()
            date_str = parts[1].strip()
            author = parts[2].strip()
            email = parts[3].strip()
            message = parts[4].strip()

            try:
                date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                if date.tzinfo:
                    date = date.replace(tzinfo=None)
            except (ValueError, AttributeError):
                date = datetime.now()

            commits.append(GitCommit(
                hash=commit_hash,
                date=date,
                author=author,
                email=email,
                message=message
            ))

        return commits

    def current_branch(self, path: str) -> Optional[str]:
        """Get current branch name."""
        output, code = self._run("git rev-parse --abbrev-ref HEAD", cwd=path)
        if code == 0 and output:
            return output.strip()
        return None

    def has_uncommitted_changes(self, path: str) -> bool:
        """Check if repo has uncommitted changes."""
        output, code = self._run("git status --porcelain", cwd=path)
        return bool(output and output.strip())

    def fetch(self, path: str, remote: str = "origin") -> bool:
        """
        Fetch from remote.

        Returns:
            True if successful
        """
        _, code = self._run(f"git fetch {remote}", cwd=path)
        return code == 0

    def pull(self, path: str, remote: str = "origin", branch: Optional[str] = None) -> bool:
        """
        Pull from remote.

        Returns:
            True if successful
        """
        cmd = f"git pull {remote}"
        if branch:
            cmd += f" {branch}"
        _, code = self._run(cmd, cwd=path)
        return code == 0
