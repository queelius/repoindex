"""
Unit tests for repoindex shell commands.

Tests for shell commands:
- do_config() with subcommands
- do_export() informational message
- Edge cases and error handling

Note: do_git, do_clone, do_docs, and do_events were removed in v0.10.0
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call, ANY
import click

from repoindex.shell.shell import RepoIndexShell


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary config directory."""
    config_dir = tmp_path / ".repoindex"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def mock_repos(tmp_path):
    """Create mock git repositories for testing."""
    repos = []
    for i, name in enumerate(['project-a', 'project-b', 'project-c']):
        repo_path = tmp_path / name
        repo_path.mkdir()
        (repo_path / '.git').mkdir()
        repos.append(str(repo_path))
    return repos


@pytest.fixture
def mock_config(mock_repos):
    """Create mock config with test repositories."""
    return {
        'general': {
            'repository_directories': [str(Path(mock_repos[0]).parent)]
        },
        'repository_tags': {
            mock_repos[0]: ['alex/beta', 'topic:ml'],
            mock_repos[1]: ['alex/production', 'lang:python'],
            mock_repos[2]: ['topic:scientific/engineering/ai']
        }
    }


@pytest.fixture
def mock_metadata():
    """Create mock metadata store."""
    return {
        'language': 'Python',
        'status': {
            'has_uncommitted_changes': False,
            'branch': 'main'
        }
    }


@pytest.fixture
def shell_instance(mock_repos):
    """Create a shell instance with mocked dependencies."""
    with patch('repoindex.shell.shell.load_config') as mock_load_config, \
         patch('repoindex.shell.shell.find_git_repos_from_config') as mock_find_repos, \
         patch('repoindex.shell.shell.get_metadata_store') as mock_metadata_store, \
         patch('repoindex.shell.shell.get_repository_tags') as mock_get_tags:

        mock_load_config.return_value = {
            'general': {'repository_directories': [str(Path(mock_repos[0]).parent)]},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        shell = RepoIndexShell()
        return shell


@pytest.mark.skip(reason="Tests unimplemented git command module")
class TestShellGitRecursive:
    """Test git command with recursive flag."""

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.git_ops.utils.get_repos_from_vfs_path')
    @patch('repoindex.commands.git.git_status')
    def test_git_recursive_status_multiple_repos(self, mock_git_status, mock_get_repos,
                                                  mock_get_tags, mock_metadata_store,
                                                  mock_find_repos, mock_load_config,
                                                  mock_repos, capsys):
        """Test git -r status on multiple repos."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock VFS resolution to return all repos
        mock_get_repos.return_value = mock_repos

        # Mock git_status callback
        mock_git_status.callback = MagicMock()

        # Create shell and execute
        shell = RepoIndexShell()
        shell.do_git('-r status')

        # Verify get_repos_from_vfs_path was called
        mock_get_repos.assert_called_once_with('/')

        # Verify git_status was called for each repo
        assert mock_git_status.callback.call_count == len(mock_repos)

        # Check output shows progress
        captured = capsys.readouterr()
        assert f"Running 'git status' on {len(mock_repos)} repositories" in captured.out
        assert 'project-a' in captured.out or 'project-b' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.git_ops.utils.get_repos_from_vfs_path')
    def test_git_recursive_pull_on_vfs_path(self, mock_get_repos,
                                             mock_get_tags, mock_metadata_store,
                                             mock_find_repos, mock_load_config,
                                             mock_repos, capsys):
        """Test git -r pull shows deprecation message (pull removed)."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock VFS resolution
        mock_get_repos.return_value = mock_repos

        # Create shell
        shell = RepoIndexShell()

        # Change to specific VFS path
        shell.do_cd('/repos')

        # Execute git pull - should show error (command removed)
        shell.do_git('pull')

        # Verify error message shown
        captured = capsys.readouterr()
        assert 'not a supported git command' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.git.git_status')
    def test_git_status_non_recursive(self, mock_git_status, mock_get_tags,
                                       mock_metadata_store, mock_find_repos,
                                       mock_load_config, mock_repos):
        """Test git status (non-recursive) on single repo."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock git_status callback
        mock_git_status.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute non-recursive status
        shell.do_git('status')

        # Should be called once for current path
        mock_git_status.callback.assert_called_once()

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.git_ops.utils.get_repos_from_vfs_path')
    def test_git_recursive_no_repos(self, mock_get_repos, mock_get_tags,
                                     mock_metadata_store, mock_find_repos,
                                     mock_load_config, capsys):
        """Test git -r when VFS path has no repos."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock VFS resolution returning no repos
        mock_get_repos.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute recursive git command
        shell.do_git('-r status')

        # Check error message
        captured = capsys.readouterr()
        assert 'No repositories found' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.git.git_log')
    def test_git_log_with_args(self, mock_git_log, mock_get_tags,
                               mock_metadata_store, mock_find_repos,
                               mock_load_config, mock_repos):
        """Test git log with additional arguments."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock git_log callback
        mock_git_log.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute git log with flags
        shell.do_git('log --oneline -n 5')

        # Verify callback was called with correct args
        mock_git_log.callback.assert_called_once()
        call_args = mock_git_log.callback.call_args
        # Shell calls callback with positional args:
        # git_log.callback(vfs_path, oneline, max_count, since, author, graph, all_branches, False)
        assert len(call_args[0]) >= 3  # At least vfs_path, oneline, max_count
        # Second arg is oneline (should be True)
        assert call_args[0][1] == True  # oneline
        # Third arg is max_count (should be 5)
        assert call_args[0][2] == 5  # max_count


@pytest.mark.skip(reason="Tests unimplemented clone command module")
class TestShellClone:
    """Test clone command."""

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.clone.clone_handler')
    def test_clone_single_repo(self, mock_handler, mock_get_tags,
                               mock_metadata_store, mock_find_repos,
                               mock_load_config, capsys):
        """Test cloning single repo."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock clone handler
        mock_handler.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute clone
        shell.do_clone('user/repo')

        # Verify clone_handler was called
        mock_handler.callback.assert_called_once()
        call_args = mock_handler.callback.call_args
        assert call_args[1]['repos'] == ['user/repo']
        assert call_args[1]['user'] is None

        # Check VFS refresh message
        captured = capsys.readouterr()
        assert 'Refreshing VFS' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.clone.clone_handler')
    def test_clone_multiple_repos(self, mock_handler, mock_get_tags,
                                   mock_metadata_store, mock_find_repos,
                                   mock_load_config):
        """Test cloning multiple repos."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock clone handler
        mock_handler.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute clone with multiple repos
        shell.do_clone('user/repo1 user/repo2 user/repo3')

        # Verify clone_handler was called with all repos
        mock_handler.callback.assert_called_once()
        call_args = mock_handler.callback.call_args
        assert call_args[1]['repos'] == ['user/repo1', 'user/repo2', 'user/repo3']

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.clone.clone_handler')
    def test_clone_user_repos(self, mock_handler, mock_get_tags,
                              mock_metadata_store, mock_find_repos,
                              mock_load_config):
        """Test cloning all repos for user."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock clone handler
        mock_handler.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute clone --user
        shell.do_clone('--user username')

        # Verify clone_handler was called with user
        mock_handler.callback.assert_called_once()
        call_args = mock_handler.callback.call_args
        assert call_args[1]['user'] == 'username'
        assert call_args[1]['repos'] == []
        assert call_args[1]['limit'] == 100

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.clone.clone_handler')
    def test_clone_user_with_limit(self, mock_handler, mock_get_tags,
                                    mock_metadata_store, mock_find_repos,
                                    mock_load_config):
        """Test cloning user repos with limit."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock clone handler
        mock_handler.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute clone --user with --limit
        shell.do_clone('--user username --limit 10')

        # Verify clone_handler was called with correct limit
        mock_handler.callback.assert_called_once()
        call_args = mock_handler.callback.call_args
        assert call_args[1]['user'] == 'username'
        assert call_args[1]['limit'] == 10

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.clone.clone_handler')
    def test_clone_url(self, mock_handler, mock_get_tags,
                       mock_metadata_store, mock_find_repos,
                       mock_load_config):
        """Test cloning from URL."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock clone handler
        mock_handler.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute clone with URL
        shell.do_clone('https://github.com/user/repo')

        # Verify clone_handler was called with URL
        mock_handler.callback.assert_called_once()
        call_args = mock_handler.callback.call_args
        assert call_args[1]['repos'] == ['https://github.com/user/repo']

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_clone_no_args(self, mock_get_tags, mock_metadata_store,
                          mock_find_repos, mock_load_config, capsys):
        """Test clone with no arguments."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute clone without args
        shell.do_clone('')

        # Check error message
        captured = capsys.readouterr()
        assert 'Usage:' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.clone.clone_handler')
    def test_clone_error_handling(self, mock_handler, mock_get_tags,
                                   mock_metadata_store, mock_find_repos,
                                   mock_load_config, capsys):
        """Test clone error handling."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock clone handler to raise exception
        mock_handler.callback = MagicMock(side_effect=Exception("Clone failed"))

        # Create shell
        shell = RepoIndexShell()

        # Execute clone
        shell.do_clone('user/repo')

        # Check error message
        captured = capsys.readouterr()
        assert 'error' in captured.out.lower()


class TestShellConfig:
    """Test config command."""

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.config.show_config')
    def test_config_show(self, mock_show_config, mock_get_tags,
                        mock_metadata_store, mock_find_repos,
                        mock_load_config):
        """Test config show command."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock show_config
        mock_show_config.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute config show
        shell.do_config('show')

        # Verify show_config was called
        mock_show_config.callback.assert_called_once()

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.config_repos.repos_list')
    def test_config_repos_list(self, mock_repos_list, mock_get_tags,
                               mock_metadata_store, mock_find_repos,
                               mock_load_config):
        """Test config repos list command."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock repos_list
        mock_repos_list.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute config repos list
        shell.do_config('repos list')

        # Verify repos_list was called
        mock_repos_list.callback.assert_called_once()
        call_args = mock_repos_list.callback.call_args
        assert call_args[1]['json_output'] == False

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.config_repos.repos_add')
    def test_config_repos_add(self, mock_repos_add, mock_get_tags,
                             mock_metadata_store, mock_find_repos,
                             mock_load_config, capsys):
        """Test config repos add command."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock repos_add
        mock_repos_add.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute config repos add
        shell.do_config('repos add /path/to/repos')

        # Verify repos_add was called
        mock_repos_add.callback.assert_called_once()
        call_args = mock_repos_add.callback.call_args
        assert call_args[1]['path'] == '/path/to/repos'
        assert call_args[1]['refresh'] == False

        # Check VFS refresh message
        captured = capsys.readouterr()
        assert 'Refreshing VFS' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.config_repos.repos_remove')
    def test_config_repos_remove(self, mock_repos_remove, mock_get_tags,
                                 mock_metadata_store, mock_find_repos,
                                 mock_load_config, capsys):
        """Test config repos remove command."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock repos_remove
        mock_repos_remove.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute config repos remove
        shell.do_config('repos remove /path/to/repos')

        # Verify repos_remove was called
        mock_repos_remove.callback.assert_called_once()
        call_args = mock_repos_remove.callback.call_args
        assert call_args[1]['path'] == '/path/to/repos'

        # Check VFS refresh message
        captured = capsys.readouterr()
        assert 'Refreshing VFS' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.config_repos.repos_clear')
    def test_config_repos_clear(self, mock_repos_clear, mock_get_tags,
                                mock_metadata_store, mock_find_repos,
                                mock_load_config, capsys):
        """Test config repos clear command."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock repos_clear
        mock_repos_clear.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Execute config repos clear
        shell.do_config('repos clear')

        # Verify repos_clear was called
        mock_repos_clear.callback.assert_called_once()

        # Check VFS refresh message
        captured = capsys.readouterr()
        assert 'Refreshing VFS' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_config_no_args(self, mock_get_tags, mock_metadata_store,
                           mock_find_repos, mock_load_config, capsys):
        """Test config with no arguments."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute config without args
        shell.do_config('')

        # Check error message
        captured = capsys.readouterr()
        assert 'Usage:' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_config_invalid_subcommand(self, mock_get_tags, mock_metadata_store,
                                       mock_find_repos, mock_load_config, capsys):
        """Test config with invalid subcommand."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute config with invalid subcommand
        shell.do_config('invalid')

        # Check error message
        captured = capsys.readouterr()
        assert 'Unknown' in captured.out


class TestShellExport:
    """Test export command (now shows help about using VFS for exports)."""

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_export_shows_vfs_help(self, mock_get_tags, mock_metadata_store,
                                   mock_find_repos, mock_load_config, capsys):
        """Test export command shows VFS-based export guidance."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute export with any args - should show guidance
        shell.do_export('markdown')

        # Check output contains VFS guidance
        captured = capsys.readouterr()
        assert 'VFS' in captured.out
        assert 'metadata' in captured.out.lower() or 'JSON' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_export_no_args(self, mock_get_tags, mock_metadata_store,
                           mock_find_repos, mock_load_config, capsys):
        """Test export with no arguments shows guidance."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute export without args
        shell.do_export('')

        # Check output contains guidance
        captured = capsys.readouterr()
        assert 'VFS' in captured.out or 'external tools' in captured.out


@pytest.mark.skip(reason="Tests unimplemented docs command module")
class TestShellDocs:
    """Test docs command (simplified detection-only)."""

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.docs.get_docs_status')
    def test_docs_detection(self, mock_get_docs_status, mock_get_tags,
                           mock_metadata_store, mock_find_repos,
                           mock_load_config, mock_repos, capsys):
        """Test docs detection command."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock get_docs_status
        mock_get_docs_status.return_value = {
            'name': 'project-a',
            'has_docs': True,
            'docs_tool': 'mkdocs',
            'docs_config': 'mkdocs.yml'
        }

        # Create shell
        shell = RepoIndexShell()

        # Navigate to repo
        shell.do_cd('/repos/project-a')

        # Execute docs
        shell.do_docs('')

        # Verify get_docs_status was called
        mock_get_docs_status.assert_called()

        # Check output
        captured = capsys.readouterr()
        assert 'mkdocs' in captured.out or 'project-a' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.docs.get_docs_status')
    def test_docs_no_docs(self, mock_get_docs_status, mock_get_tags,
                         mock_metadata_store, mock_find_repos,
                         mock_load_config, mock_repos, capsys):
        """Test docs when no documentation found."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock get_docs_status - no docs
        mock_get_docs_status.return_value = {
            'name': 'project-a',
            'has_docs': False,
            'docs_tool': None,
            'docs_config': None
        }

        # Create shell
        shell = RepoIndexShell()

        # Navigate to repo
        shell.do_cd('/repos/project-a')

        # Execute docs
        shell.do_docs('')

        # Check output
        captured = capsys.readouterr()
        assert 'no documentation detected' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.git_ops.utils.get_repos_from_vfs_path')
    def test_docs_no_repo_found(self, mock_get_repos_from_vfs, mock_get_tags,
                                mock_metadata_store, mock_find_repos,
                                mock_load_config, capsys):
        """Test docs when no repository found in current directory."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock VFS path resolution returning no repos
        mock_get_repos_from_vfs.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Stay at root (no repo)
        shell.do_docs('')

        # Check error message
        captured = capsys.readouterr()
        assert 'No repository' in captured.out


class TestShellEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.skip(reason="do_git command was removed")
    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_git_no_args(self, mock_get_tags, mock_metadata_store,
                        mock_find_repos, mock_load_config, capsys):
        """Test git with no arguments."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute git without args
        shell.do_git('')

        # Check error message
        captured = capsys.readouterr()
        assert 'Usage:' in captured.out
        assert 'Supported:' in captured.out

    @pytest.mark.skip(reason="Tests unimplemented git command module")
    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_git_unsupported_command(self, mock_get_tags, mock_metadata_store,
                                     mock_find_repos, mock_load_config,
                                     mock_repos, capsys):
        """Test git with unsupported subcommand."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute git with unsupported command
        shell.do_git('rebase')

        # Check error message
        captured = capsys.readouterr()
        assert 'not a supported' in captured.out

    @pytest.mark.skip(reason="Tests unimplemented clone command module")
    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.clone.clone_handler')
    def test_clone_user_missing_username(self, mock_handler, mock_get_tags,
                                         mock_metadata_store, mock_find_repos,
                                         mock_load_config, capsys):
        """Test clone --user without username."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute clone --user without username
        shell.do_clone('--user')

        # Check error message
        captured = capsys.readouterr()
        assert 'Error' in captured.out or 'requires a username' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.config_repos.repos_add')
    def test_config_repos_add_no_path(self, mock_repos_add, mock_get_tags,
                                      mock_metadata_store, mock_find_repos,
                                      mock_load_config, capsys):
        """Test config repos add without path."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute config repos add without path
        shell.do_config('repos add')

        # Check error message
        captured = capsys.readouterr()
        assert 'Usage:' in captured.out


class TestShellIntegration:
    """Integration tests for shell commands."""

    @pytest.mark.skip(reason="Tests unimplemented git command module")
    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.git_ops.utils.get_repos_from_vfs_path')
    @patch('repoindex.commands.git.git_status')
    def test_git_recursive_from_different_vfs_paths(self, mock_git_status,
                                                     mock_get_repos, mock_get_tags,
                                                     mock_metadata_store,
                                                     mock_find_repos,
                                                     mock_load_config,
                                                     mock_repos, capsys):
        """Test git -r status from different VFS paths."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock git_status
        mock_git_status.callback = MagicMock()

        # Create shell
        shell = RepoIndexShell()

        # Test from /by-language/Python
        shell.do_cd('/by-language')
        mock_get_repos.return_value = [mock_repos[0], mock_repos[1]]  # Two Python repos
        shell.do_git('-r status')

        # Should operate on repos from that VFS path
        captured = capsys.readouterr()
        assert 'Running' in captured.out
        assert 'repositories' in captured.out

    @pytest.mark.skip(reason="Tests unimplemented docs command module")
    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    @patch('repoindex.commands.docs.get_docs_status')
    def test_docs_in_real_fs_mode(self, mock_get_docs_status, mock_get_tags,
                                  mock_metadata_store, mock_find_repos,
                                  mock_load_config, mock_repos, capsys):
        """Test docs command when in real filesystem mode."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Mock get_docs_status
        mock_get_docs_status.return_value = {
            'name': 'project-a',
            'has_docs': True,
            'docs_tool': 'sphinx',
            'docs_config': 'docs/conf.py'
        }

        # Create shell
        shell = RepoIndexShell()

        # Navigate into repo (enters real filesystem mode)
        shell.do_cd('/repos/project-a')

        # Set real filesystem state manually for testing
        shell.in_real_fs = True
        shell.real_fs_repo = mock_repos[0]

        # Execute docs command
        shell.do_docs('')

        # Should use real_fs_repo path
        mock_get_docs_status.assert_called_once()

        # Check output
        captured = capsys.readouterr()
        assert 'sphinx' in captured.out or 'project-a' in captured.out
