"""
GitHub write operations service for repoindex.

Provides operations that modify GitHub repository settings:
- Set topics (from CLI args or pyproject.toml keywords)
- Set description (from CLI arg or pyproject.toml)
Uses the `gh` CLI tool for authenticated GitHub API access.
"""

import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

from ..config import load_config
from ..domain.operation import (
    OperationDetail,
    OperationStatus,
    OperationSummary,
)
from ..pypi import extract_project_metadata

logger = logging.getLogger(__name__)


@dataclass
class GitHubOpsOptions:
    """Options for GitHub write operations."""
    dry_run: bool = False


class GitHubOpsService:
    """
    Service for GitHub write operations.

    Uses the `gh` CLI to set topics, descriptions, and other
    repository settings on GitHub.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.last_result: Optional[OperationSummary] = None

    def _get_repo_nwo(self, repo: Dict[str, Any]) -> Optional[str]:
        """Get owner/name from remote URL for gh CLI."""
        remote_url = repo.get('remote_url', '')
        if not remote_url:
            return None

        # Parse git@github.com:owner/repo.git or https://github.com/owner/repo.git
        if remote_url.startswith('git@github.com:'):
            nwo = remote_url[len('git@github.com:'):]
        elif 'github.com/' in remote_url:
            nwo = remote_url.split('github.com/')[-1]
        else:
            return None

        if nwo.endswith('.git'):
            nwo = nwo[:-4]
        return nwo.strip('/')

    def _run_gh(self, args: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
        """Run a gh CLI command."""
        cmd = ['gh'] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )

    def set_topics(
        self,
        repos: List[Dict[str, Any]],
        options: GitHubOpsOptions,
        topics: Optional[List[str]] = None,
        from_pyproject: bool = False,
    ) -> Generator[str, None, OperationSummary]:
        """
        Set GitHub topics for repositories.

        Args:
            repos: List of repository dicts
            options: Operation options
            topics: Explicit list of topics to set
            from_pyproject: Read keywords from pyproject.toml

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        result = OperationSummary(operation="github_set_topics", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to process"
            return result

        for repo in repos:
            name = repo.get('name', '')
            path = repo.get('path', '')
            nwo = self._get_repo_nwo(repo)

            if not nwo:
                yield f"Skipping {name} (no GitHub remote)"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="No GitHub remote",
                ))
                continue

            # Determine topics
            repo_topics = list(topics) if topics else []
            if from_pyproject and path:
                proj = extract_project_metadata(path)
                kw = proj.get('keywords', [])
                # Sanitize keywords for GitHub topics (lowercase, hyphens, max 50 chars)
                for k in kw:
                    topic = k.lower().replace(' ', '-').replace('_', '-')[:50]
                    if topic and topic not in repo_topics:
                        repo_topics.append(topic)

            if not repo_topics:
                yield f"Skipping {name} (no topics to set)"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="No topics to set",
                ))
                continue

            if options.dry_run:
                yield f"Would set topics for {name}: {', '.join(repo_topics)}"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.DRY_RUN,
                    action="would_set_topics",
                    metadata={'topics': repo_topics},
                ))
                continue

            try:
                # Build gh command: gh repo edit owner/repo --add-topic t1 --add-topic t2
                args = ['repo', 'edit', nwo]
                for t in repo_topics:
                    args.extend(['--add-topic', t])

                proc = self._run_gh(args, cwd=path)
                if proc.returncode == 0:
                    yield f"Set topics for {name}: {', '.join(repo_topics)}"
                    result.add_detail(OperationDetail(
                        repo_path=path, repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="set_topics",
                        metadata={'topics': repo_topics},
                    ))
                else:
                    error_msg = proc.stderr.strip() or f"gh exited with {proc.returncode}"
                    yield f"Failed to set topics for {name}: {error_msg}"
                    result.add_detail(OperationDetail(
                        repo_path=path, repo_name=name,
                        status=OperationStatus.FAILED,
                        action="set_topics_failed",
                        error=error_msg,
                    ))

            except subprocess.TimeoutExpired:
                yield f"Timeout setting topics for {name}"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.FAILED,
                    action="set_topics_failed",
                    error="Timeout",
                ))
            except FileNotFoundError:
                yield "Error: gh CLI not found. Install from https://cli.github.com/"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.FAILED,
                    action="set_topics_failed",
                    error="gh CLI not installed",
                ))
                return result  # No point continuing without gh

        return result

    def set_description(
        self,
        repos: List[Dict[str, Any]],
        options: GitHubOpsOptions,
        text: Optional[str] = None,
        from_pyproject: bool = False,
    ) -> Generator[str, None, OperationSummary]:
        """
        Set GitHub description for repositories.

        Args:
            repos: List of repository dicts
            options: Operation options
            text: Explicit description text
            from_pyproject: Read description from pyproject.toml

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        result = OperationSummary(operation="github_set_description", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to process"
            return result

        for repo in repos:
            name = repo.get('name', '')
            path = repo.get('path', '')
            nwo = self._get_repo_nwo(repo)

            if not nwo:
                yield f"Skipping {name} (no GitHub remote)"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="No GitHub remote",
                ))
                continue

            # Determine description
            desc = text
            if from_pyproject and path and not desc:
                proj = extract_project_metadata(path)
                desc = proj.get('description', '')

            if not desc:
                yield f"Skipping {name} (no description to set)"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="No description to set",
                ))
                continue

            # Truncate to GitHub's 350 char limit
            if len(desc) > 350:
                desc = desc[:347] + '...'

            if options.dry_run:
                yield f"Would set description for {name}: {desc}"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.DRY_RUN,
                    action="would_set_description",
                    metadata={'description': desc},
                ))
                continue

            try:
                proc = self._run_gh(['repo', 'edit', nwo, '--description', desc], cwd=path)
                if proc.returncode == 0:
                    yield f"Set description for {name}"
                    result.add_detail(OperationDetail(
                        repo_path=path, repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="set_description",
                        metadata={'description': desc},
                    ))
                else:
                    error_msg = proc.stderr.strip() or f"gh exited with {proc.returncode}"
                    yield f"Failed to set description for {name}: {error_msg}"
                    result.add_detail(OperationDetail(
                        repo_path=path, repo_name=name,
                        status=OperationStatus.FAILED,
                        action="set_description_failed",
                        error=error_msg,
                    ))

            except subprocess.TimeoutExpired:
                yield f"Timeout setting description for {name}"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.FAILED,
                    action="set_description_failed",
                    error="Timeout",
                ))
            except FileNotFoundError:
                yield "Error: gh CLI not found. Install from https://cli.github.com/"
                result.add_detail(OperationDetail(
                    repo_path=path, repo_name=name,
                    status=OperationStatus.FAILED,
                    action="set_description_failed",
                    error="gh CLI not installed",
                ))
                return result

        return result
