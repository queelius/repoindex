"""
Git operations service for repoindex.

Orchestrates git push/pull/status operations across multiple repositories.
Used by the `repoindex ops git` command group.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, Any, Generator, List, Optional

from ..config import load_config
from ..infra.git_client import GitClient
from ..domain.operation import (
    OperationStatus,
    OperationSummary,
    GitPushResult,
    GitPullResult,
)

logger = logging.getLogger(__name__)


@dataclass
class GitOpsOptions:
    """Options for git operations."""
    remote: str = "origin"
    branch: Optional[str] = None
    dry_run: bool = False
    parallel: int = 1  # Number of concurrent operations (1 = sequential)
    set_upstream: bool = False


@dataclass
class MultiRepoStatus:
    """Status information for multiple repositories."""
    total: int = 0
    clean: int = 0
    dirty: int = 0
    ahead: int = 0  # Repos with unpushed commits
    behind: int = 0  # Repos with commits to pull
    no_remote: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total': self.total,
            'clean': self.clean,
            'dirty': self.dirty,
            'ahead': self.ahead,
            'behind': self.behind,
            'no_remote': self.no_remote,
        }


class GitOpsService:
    """
    Service for git operations across multiple repositories.

    Orchestrates push, pull, and status operations with support
    for parallel execution, dry-run mode, and progress reporting.

    Example:
        service = GitOpsService()
        options = GitOpsOptions(dry_run=True)

        for progress in service.push_repos(repos, options):
            print(progress)  # "Pushing myproject..."

        result = service.last_result
        print(f"Pushed {result.successful} repos")
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        git_client: Optional[GitClient] = None
    ):
        """
        Initialize GitOpsService.

        Args:
            config: Configuration dict (loads default if None)
            git_client: GitClient instance (creates new if None)
        """
        self.config = config or load_config()
        self.git = git_client or GitClient()
        self.last_result: Optional[OperationSummary] = None
        self.last_status: Optional[MultiRepoStatus] = None

    @staticmethod
    def _repo_path(repo: Dict[str, Any]) -> Optional[str]:
        """Return the repo's path if it is a non-empty, existing directory.

        Returns None if the path is missing, empty, or does not exist on disk.
        """
        path = repo.get('path', '')
        if path and os.path.isdir(path):
            return path
        return None

    def push_repos(
        self,
        repos: List[Dict[str, Any]],
        options: GitOpsOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Push commits to remote for multiple repositories.

        Only pushes repos that have commits ahead of the remote.

        Args:
            repos: List of repository dicts (from query)
            options: Git operation options

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        result = OperationSummary(operation="git_push", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to push"
            return result

        # Filter to repos with commits to push
        pushable_repos = []
        for repo in repos:
            path = self._repo_path(repo)
            if not path:
                name = repo.get('name', repo.get('path', ''))
                if repo.get('path'):
                    yield f"Skipping {name} (path not found)"
                continue

            commits_ahead = self.git.get_commits_ahead(path, options.remote)
            if commits_ahead > 0:
                pushable_repos.append((repo, commits_ahead))
            else:
                # Check if repo has no remote
                remote_url = self.git.remote_url(path, options.remote)
                if not remote_url:
                    yield f"Skipping {repo.get('name', path)} (no remote)"

        if not pushable_repos:
            yield "No repositories have unpushed commits"
            return result

        yield f"Found {len(pushable_repos)} repos with unpushed commits"

        if options.parallel > 1:
            yield from self._push_parallel(pushable_repos, options, result)
        else:
            yield from self._push_sequential(pushable_repos, options, result)

        return result

    def _push_sequential(
        self,
        repos_with_commits: List[tuple],
        options: GitOpsOptions,
        result: OperationSummary
    ) -> Generator[str, None, None]:
        """Push repos sequentially."""
        for repo, commits_ahead in repos_with_commits:
            path = repo.get('path', '')
            name = repo.get('name', path)

            if options.dry_run:
                yield f"Would push {name} ({commits_ahead} commits)"
                detail = GitPushResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.DRY_RUN,
                    action="would_push",
                    commits_pushed=commits_ahead,
                    remote=options.remote,
                    branch=options.branch,
                )
            else:
                yield f"Pushing {name}..."
                success, output = self.git.push(
                    path,
                    remote=options.remote,
                    branch=options.branch,
                    set_upstream=options.set_upstream,
                    dry_run=False
                )

                if success:
                    detail = GitPushResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="pushed",
                        commits_pushed=commits_ahead,
                        remote=options.remote,
                        branch=options.branch,
                        message=output,
                    )
                    yield f"  ✓ {name}: pushed {commits_ahead} commits"
                else:
                    detail = GitPushResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.FAILED,
                        action="push_failed",
                        error=output or "Unknown error",
                        remote=options.remote,
                        branch=options.branch,
                    )
                    yield f"  ✗ {name}: {output or 'push failed'}"

            result.add_detail(detail)

    def _push_parallel(
        self,
        repos_with_commits: List[tuple],
        options: GitOpsOptions,
        result: OperationSummary
    ) -> Generator[str, None, None]:
        """Push repos in parallel."""
        yield f"Pushing {len(repos_with_commits)} repos (parallel={options.parallel})..."

        def push_one(repo_tuple):
            repo, commits_ahead = repo_tuple
            path = repo.get('path', '')
            name = repo.get('name', path)

            if options.dry_run:
                return GitPushResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.DRY_RUN,
                    action="would_push",
                    commits_pushed=commits_ahead,
                    remote=options.remote,
                    branch=options.branch,
                )

            success, output = self.git.push(
                path,
                remote=options.remote,
                branch=options.branch,
                set_upstream=options.set_upstream,
                dry_run=False
            )

            if success:
                return GitPushResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.SUCCESS,
                    action="pushed",
                    commits_pushed=commits_ahead,
                    remote=options.remote,
                    branch=options.branch,
                    message=output,
                )
            else:
                return GitPushResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.FAILED,
                    action="push_failed",
                    error=output or "Unknown error",
                    remote=options.remote,
                    branch=options.branch,
                )

        with ThreadPoolExecutor(max_workers=options.parallel) as executor:
            futures = {executor.submit(push_one, r): r for r in repos_with_commits}

            for future in as_completed(futures):
                detail = future.result()
                result.add_detail(detail)

                if detail.status == OperationStatus.SUCCESS:
                    yield f"  ✓ {detail.repo_name}: pushed {detail.commits_pushed} commits"
                elif detail.status == OperationStatus.DRY_RUN:
                    yield f"  Would push {detail.repo_name} ({detail.commits_pushed} commits)"
                else:
                    yield f"  ✗ {detail.repo_name}: {detail.error}"

    def pull_repos(
        self,
        repos: List[Dict[str, Any]],
        options: GitOpsOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Pull updates from remote for multiple repositories.

        Args:
            repos: List of repository dicts (from query)
            options: Git operation options

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        result = OperationSummary(operation="git_pull", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to pull"
            return result

        # Optionally fetch first to get accurate behind counts
        pullable_repos = []
        for repo in repos:
            path = self._repo_path(repo)
            if not path:
                name = repo.get('name', repo.get('path', ''))
                if repo.get('path'):
                    yield f"Skipping {name} (path not found)"
                continue

            # Check if repo has a remote
            remote_url = self.git.remote_url(path, options.remote)
            if not remote_url:
                yield f"Skipping {repo.get('name', path)} (no remote)"
                continue

            pullable_repos.append(repo)

        if not pullable_repos:
            yield "No repositories have remotes configured"
            return result

        yield f"Pulling {len(pullable_repos)} repositories..."

        for repo in pullable_repos:
            path = repo.get('path', '')
            name = repo.get('name', path)

            if options.dry_run:
                # Fetch to check what would be pulled
                self.git.fetch(path, options.remote)
                commits_behind = self.git.get_commits_behind(path, options.remote)

                yield f"Would pull {name} ({commits_behind} commits behind)"
                detail = GitPullResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.DRY_RUN,
                    action="would_pull",
                    commits_pulled=commits_behind,
                    remote=options.remote,
                    branch=options.branch,
                )
            else:
                yield f"Pulling {name}..."
                success = self.git.pull(path, options.remote, options.branch)

                if success:
                    detail = GitPullResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="pulled",
                        remote=options.remote,
                        branch=options.branch,
                    )
                    yield f"  ✓ {name}: pulled"
                else:
                    detail = GitPullResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.FAILED,
                        action="pull_failed",
                        error="Pull failed (possible merge conflict)",
                        remote=options.remote,
                        branch=options.branch,
                    )
                    yield f"  ✗ {name}: pull failed"

            result.add_detail(detail)

        return result

    def status_repos(
        self,
        repos: List[Dict[str, Any]],
        options: GitOpsOptions
    ) -> Generator[str, None, MultiRepoStatus]:
        """
        Get git status for multiple repositories.

        Args:
            repos: List of repository dicts (from query)
            options: Git operation options

        Yields:
            Progress messages

        Returns:
            MultiRepoStatus with aggregated stats
        """
        status = MultiRepoStatus()
        self.last_status = status

        if not repos:
            yield "No repositories to check"
            return status

        yield f"Checking status of {len(repos)} repositories..."

        for repo in repos:
            name = repo.get('name', repo.get('path', ''))
            path = self._repo_path(repo)
            if not path:
                if repo.get('path'):
                    yield f"  {name}: path not found (stale entry)"
                continue

            status.total += 1
            git_status = self.git.status(path)

            # Check remote
            remote_url = self.git.remote_url(path, options.remote)
            has_remote = bool(remote_url)

            repo_detail = {
                'name': name,
                'path': path,
                'branch': git_status.branch,
                'clean': git_status.clean,
                'ahead': git_status.ahead,
                'behind': git_status.behind,
                'has_remote': has_remote,
                'uncommitted_changes': git_status.uncommitted_changes,
                'untracked_files': git_status.untracked_files,
            }

            if git_status.clean:
                status.clean += 1
            else:
                status.dirty += 1

            if git_status.ahead > 0:
                status.ahead += 1

            if git_status.behind > 0:
                status.behind += 1

            if not has_remote:
                status.no_remote += 1

            status.details.append(repo_detail)

            # Yield status for each repo
            status_str = []
            if not git_status.clean:
                status_str.append("dirty")
            if git_status.ahead > 0:
                status_str.append(f"↑{git_status.ahead}")
            if git_status.behind > 0:
                status_str.append(f"↓{git_status.behind}")
            if not has_remote:
                status_str.append("no-remote")

            if status_str:
                yield f"  {name}: {', '.join(status_str)}"

        return status

    def get_repos_needing_push(
        self,
        repos: List[Dict[str, Any]],
        remote: str = "origin"
    ) -> List[Dict[str, Any]]:
        """
        Filter repos to those with commits to push.

        Args:
            repos: List of repository dicts
            remote: Remote name to check

        Returns:
            Filtered list of repos with commits ahead
        """
        needing_push = []

        for repo in repos:
            path = self._repo_path(repo)
            if not path:
                continue

            commits_ahead = self.git.get_commits_ahead(path, remote)
            if commits_ahead > 0:
                repo_copy = repo.copy()
                repo_copy['commits_ahead'] = commits_ahead
                needing_push.append(repo_copy)

        return needing_push

    def get_repos_needing_pull(
        self,
        repos: List[Dict[str, Any]],
        remote: str = "origin",
        fetch_first: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Filter repos to those with commits to pull.

        Args:
            repos: List of repository dicts
            remote: Remote name to check
            fetch_first: Whether to fetch before checking

        Returns:
            Filtered list of repos with commits behind
        """
        needing_pull = []

        for repo in repos:
            path = self._repo_path(repo)
            if not path:
                continue

            if fetch_first:
                self.git.fetch(path, remote)

            commits_behind = self.git.get_commits_behind(path, remote)
            if commits_behind > 0:
                repo_copy = repo.copy()
                repo_copy['commits_behind'] = commits_behind
                needing_pull.append(repo_copy)

        return needing_pull
