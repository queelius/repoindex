"""
Tests for GitHubOpsService.

Tests cover:
- NWO (name-with-owner) parsing from remote URLs
- set_topics: dry-run, success, failure, no remote, no topics, from_pyproject, sanitization
- set_description: dry-run, success, failure, no remote, no description, from_pyproject, truncation
- gh CLI not found handling
- Timeout handling
"""

import subprocess
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from repoindex.services.github_ops_service import (
    GitHubOpsService,
    GitHubOpsOptions,
)
from repoindex.domain.operation import OperationStatus


# ============================================================================
# NWO Parsing Tests
# ============================================================================

class TestGetRepoNWO:
    """Test owner/repo extraction from remote URLs."""

    def setup_method(self):
        self.service = GitHubOpsService(config={})

    def test_ssh_url(self):
        repo = {'remote_url': 'git@github.com:queelius/repoindex.git'}
        assert self.service._get_repo_nwo(repo) == 'queelius/repoindex'

    def test_https_url(self):
        repo = {'remote_url': 'https://github.com/queelius/repoindex.git'}
        assert self.service._get_repo_nwo(repo) == 'queelius/repoindex'

    def test_https_no_git_suffix(self):
        repo = {'remote_url': 'https://github.com/queelius/repoindex'}
        assert self.service._get_repo_nwo(repo) == 'queelius/repoindex'

    def test_no_remote(self):
        repo = {'remote_url': ''}
        assert self.service._get_repo_nwo(repo) is None

    def test_no_remote_key(self):
        repo = {}
        assert self.service._get_repo_nwo(repo) is None

    def test_non_github_remote(self):
        repo = {'remote_url': 'https://gitlab.com/user/repo.git'}
        assert self.service._get_repo_nwo(repo) is None


# ============================================================================
# set_topics Tests
# ============================================================================

class TestSetTopics:
    """Test GitHubOpsService.set_topics()."""

    def setup_method(self):
        self.service = GitHubOpsService(config={})

    def _make_repo(self, name='myrepo', remote='git@github.com:user/myrepo.git', path='/tmp/myrepo'):
        return {
            'name': name,
            'path': path,
            'remote_url': remote,
        }

    def test_dry_run(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=True)
        messages = list(self.service.set_topics([repo], options, topics=['python', 'cli']))
        result = self.service.last_result

        assert any('Would set topics' in m for m in messages)
        assert result.total == 1
        assert result.details[0].status == OperationStatus.DRY_RUN
        assert result.details[0].metadata['topics'] == ['python', 'cli']

    def test_success(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch.object(self.service, '_run_gh', return_value=mock_proc) as mock_gh:
            messages = list(self.service.set_topics([repo], options, topics=['python']))
            mock_gh.assert_called_once()
            args = mock_gh.call_args[0][0]
            assert 'repo' in args
            assert 'edit' in args
            assert '--add-topic' in args
            assert 'python' in args

        result = self.service.last_result
        assert result.successful == 1
        assert result.details[0].status == OperationStatus.SUCCESS

    def test_failure(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = 'permission denied'

        with patch.object(self.service, '_run_gh', return_value=mock_proc):
            messages = list(self.service.set_topics([repo], options, topics=['python']))

        result = self.service.last_result
        assert result.failed == 1
        assert 'permission denied' in result.errors[0]

    def test_no_remote_skipped(self):
        repo = self._make_repo(remote='')
        options = GitHubOpsOptions(dry_run=False)
        messages = list(self.service.set_topics([repo], options, topics=['python']))

        result = self.service.last_result
        assert result.skipped == 1

    def test_no_topics_skipped(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)
        messages = list(self.service.set_topics([repo], options, topics=[]))

        result = self.service.last_result
        assert result.skipped == 1

    def test_from_pyproject(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "myrepo"\nkeywords = ["machine-learning", "python"]\n')

        repo = self._make_repo(path=str(tmp_path))
        options = GitHubOpsOptions(dry_run=True)
        messages = list(self.service.set_topics([repo], options, from_pyproject=True))

        result = self.service.last_result
        assert result.total == 1
        topics = result.details[0].metadata.get('topics', [])
        assert 'machine-learning' in topics
        assert 'python' in topics

    def test_topic_sanitization(self, tmp_path):
        """Keywords with spaces/underscores get sanitized to GitHub topic format."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "myrepo"\nkeywords = ["Machine Learning", "data_science"]\n')

        repo = self._make_repo(path=str(tmp_path))
        options = GitHubOpsOptions(dry_run=True)
        messages = list(self.service.set_topics([repo], options, from_pyproject=True))

        result = self.service.last_result
        topics = result.details[0].metadata.get('topics', [])
        assert 'machine-learning' in topics
        assert 'data-science' in topics

    def test_explicit_plus_pyproject(self, tmp_path):
        """Explicit topics + pyproject keywords are merged without duplicates."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "myrepo"\nkeywords = ["python", "tools"]\n')

        repo = self._make_repo(path=str(tmp_path))
        options = GitHubOpsOptions(dry_run=True)
        messages = list(self.service.set_topics(
            [repo], options, topics=['python', 'cli'], from_pyproject=True
        ))

        result = self.service.last_result
        topics = result.details[0].metadata.get('topics', [])
        # 'python' should not be duplicated
        assert topics.count('python') == 1
        assert 'cli' in topics
        assert 'tools' in topics

    def test_gh_not_found(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)

        with patch.object(self.service, '_run_gh', side_effect=FileNotFoundError):
            messages = list(self.service.set_topics([repo], options, topics=['python']))

        result = self.service.last_result
        assert result.failed == 1
        assert 'gh CLI not installed' in result.errors[0]

    def test_timeout(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)

        with patch.object(self.service, '_run_gh', side_effect=subprocess.TimeoutExpired(cmd='gh', timeout=30)):
            messages = list(self.service.set_topics([repo], options, topics=['python']))

        result = self.service.last_result
        assert result.failed == 1

    def test_empty_repos(self):
        options = GitHubOpsOptions(dry_run=False)
        messages = list(self.service.set_topics([], options, topics=['python']))
        result = self.service.last_result
        assert result.total == 0


# ============================================================================
# set_description Tests
# ============================================================================

class TestSetDescription:
    """Test GitHubOpsService.set_description()."""

    def setup_method(self):
        self.service = GitHubOpsService(config={})

    def _make_repo(self, name='myrepo', remote='git@github.com:user/myrepo.git', path='/tmp/myrepo'):
        return {
            'name': name,
            'path': path,
            'remote_url': remote,
        }

    def test_dry_run(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=True)
        messages = list(self.service.set_description([repo], options, text='A cool project'))

        result = self.service.last_result
        assert result.total == 1
        assert result.details[0].status == OperationStatus.DRY_RUN
        assert result.details[0].metadata['description'] == 'A cool project'

    def test_success(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch.object(self.service, '_run_gh', return_value=mock_proc) as mock_gh:
            messages = list(self.service.set_description([repo], options, text='A cool project'))
            args = mock_gh.call_args[0][0]
            assert '--description' in args
            assert 'A cool project' in args

        result = self.service.last_result
        assert result.successful == 1

    def test_no_remote_skipped(self):
        repo = self._make_repo(remote='')
        options = GitHubOpsOptions(dry_run=False)
        messages = list(self.service.set_description([repo], options, text='A project'))

        result = self.service.last_result
        assert result.skipped == 1

    def test_no_description_skipped(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)
        messages = list(self.service.set_description([repo], options))

        result = self.service.last_result
        assert result.skipped == 1

    def test_from_pyproject(self, tmp_path):
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "myrepo"\ndescription = "A Python toolkit"\n')

        repo = self._make_repo(path=str(tmp_path))
        options = GitHubOpsOptions(dry_run=True)
        messages = list(self.service.set_description([repo], options, from_pyproject=True))

        result = self.service.last_result
        assert result.total == 1
        assert result.details[0].metadata['description'] == 'A Python toolkit'

    def test_truncation(self):
        """Descriptions over 350 chars get truncated."""
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=True)
        long_desc = 'x' * 400
        messages = list(self.service.set_description([repo], options, text=long_desc))

        result = self.service.last_result
        desc = result.details[0].metadata['description']
        assert len(desc) == 350
        assert desc.endswith('...')

    def test_explicit_overrides_pyproject(self, tmp_path):
        """Explicit text takes precedence over pyproject.toml."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "myrepo"\ndescription = "From pyproject"\n')

        repo = self._make_repo(path=str(tmp_path))
        options = GitHubOpsOptions(dry_run=True)
        messages = list(self.service.set_description(
            [repo], options, text='From CLI', from_pyproject=True
        ))

        result = self.service.last_result
        assert result.details[0].metadata['description'] == 'From CLI'

    def test_gh_not_found(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)

        with patch.object(self.service, '_run_gh', side_effect=FileNotFoundError):
            messages = list(self.service.set_description([repo], options, text='desc'))

        result = self.service.last_result
        assert result.failed == 1

    def test_failure(self):
        repo = self._make_repo()
        options = GitHubOpsOptions(dry_run=False)

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = 'not authorized'

        with patch.object(self.service, '_run_gh', return_value=mock_proc):
            messages = list(self.service.set_description([repo], options, text='desc'))

        result = self.service.last_result
        assert result.failed == 1
        assert 'not authorized' in result.errors[0]
