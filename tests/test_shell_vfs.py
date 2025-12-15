"""
Tests for hierarchical tag-based virtual filesystem in ghops shell.
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestShellVFSHierarchicalTags:
    """Test hierarchical tag-based VFS."""

    def test_parse_tag_levels_simple(self):
        """Test parsing simple tags into levels."""
        shell = RepoIndexShell.__new__(RepoIndexShell)

        # Simple tag without hierarchy
        assert shell._parse_tag_levels('deprecated') == ['deprecated']

        # Simple key:value tag
        assert shell._parse_tag_levels('lang:python') == ['lang', 'python']

        # Hierarchical tag without key
        assert shell._parse_tag_levels('alex/beta') == ['alex', 'beta']

        # Hierarchical tag with key
        assert shell._parse_tag_levels('topic:scientific/engineering/ai') == [
            'topic', 'scientific', 'engineering', 'ai'
        ]

    def test_path_to_tag_conversion(self):
        """Test converting VFS paths to tags."""
        shell = RepoIndexShell.__new__(RepoIndexShell)

        # Simple hierarchical tag
        assert shell._path_to_tag('/by-tag/alex/beta') == 'alex/beta'

        # Tag with known key
        assert shell._path_to_tag('/by-tag/lang/python') == 'lang:python'
        assert shell._path_to_tag('/by-tag/topic/ml') == 'topic:ml'

        # Multi-level hierarchical tag with key
        assert shell._path_to_tag('/by-tag/topic/scientific/engineering/ai') == \
               'topic:scientific/engineering/ai'

        # Invalid paths
        assert shell._path_to_tag('/repos/myproject') is None
        assert shell._path_to_tag('/by-tag/') is None

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_build_hierarchical_tag_vfs(self, mock_get_tags, mock_metadata_store,
                                        mock_find_repos, mock_load_config, mock_repos):
        """Test building VFS with hierarchical tags."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        # Setup tag returns
        mock_get_tags.side_effect = [
            ['alex/beta', 'topic:ml'],
            ['alex/production'],
            ['topic:scientific/engineering/ai']
        ]

        # Create shell
        shell = RepoIndexShell()

        # Verify VFS structure
        assert '/' in shell.vfs
        assert 'by-tag' in shell.vfs['/']['children']

        # Check that hierarchical structure was created
        by_tag = shell.vfs['/']['children']['by-tag']['children']

        # Check alex/ hierarchy
        assert 'alex' in by_tag
        assert 'beta' in by_tag['alex']['children']
        assert 'production' in by_tag['alex']['children']

        # Check topic/ hierarchy
        assert 'topic' in by_tag
        assert 'ml' in by_tag['topic']['children']
        assert 'scientific' in by_tag['topic']['children']

        # Check deep hierarchy
        scientific = by_tag['topic']['children']['scientific']['children']
        assert 'engineering' in scientific
        assert 'ai' in scientific['engineering']['children']

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.save_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_add_tag_with_cp(self, mock_get_tags, mock_metadata_store, mock_find_repos,
                            mock_save_config, mock_load_config, mock_repos, capsys):
        """Test adding tags using cp command."""
        # Setup mocks
        config = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_load_config.return_value = config
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.return_value = []

        # Create shell
        shell = RepoIndexShell()

        # Execute cp command
        repo_name = Path(mock_repos[0]).name
        shell.do_cp(f'/repos/{repo_name} /by-tag/work/active')

        # Check output
        captured = capsys.readouterr()
        assert 'Added tag' in captured.out
        assert 'work/active' in captured.out

        # Verify save_config was called
        assert mock_save_config.called

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.save_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_move_tag_with_mv(self, mock_get_tags, mock_metadata_store, mock_find_repos,
                             mock_save_config, mock_load_config, mock_repos, capsys):
        """Test moving repos between tags using mv command."""
        # Setup mocks
        config = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {
                mock_repos[0]: ['alex/beta']
            }
        }
        mock_load_config.return_value = config
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        # Need enough side_effect values for initial build + rebuild
        mock_get_tags.side_effect = [
            ['alex/beta'],  # project-a initial
            [],             # project-b initial
            [],             # project-c initial
            ['alex/production'],  # project-a rebuild
            [],             # project-b rebuild
            []              # project-c rebuild
        ]

        # Create shell
        shell = RepoIndexShell()

        # Execute mv command
        repo_name = Path(mock_repos[0]).name
        shell.do_mv(f'/by-tag/alex/beta/{repo_name} /by-tag/alex/production')

        # Check output
        captured = capsys.readouterr()
        assert 'Moved' in captured.out
        assert 'alex/beta' in captured.out
        assert 'alex/production' in captured.out

        # Verify save_config was called
        assert mock_save_config.called

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.save_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_remove_tag_with_rm(self, mock_get_tags, mock_metadata_store, mock_find_repos,
                               mock_save_config, mock_load_config, mock_repos, capsys):
        """Test removing tags using rm command."""
        # Setup mocks
        config = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {
                mock_repos[0]: ['alex/beta']
            }
        }
        mock_load_config.return_value = config
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        # Need enough side_effect values for initial build + rebuild
        mock_get_tags.side_effect = [
            ['alex/beta'],  # project-a initial
            [],             # project-b initial
            [],             # project-c initial
            [],             # project-a rebuild (tag removed)
            [],             # project-b rebuild
            []              # project-c rebuild
        ]

        # Create shell
        shell = RepoIndexShell()

        # Execute rm command
        repo_name = Path(mock_repos[0]).name
        shell.do_rm(f'/by-tag/alex/beta/{repo_name}')

        # Check output
        captured = capsys.readouterr()
        assert 'Removed tag' in captured.out
        assert 'alex/beta' in captured.out

        # Verify save_config was called
        assert mock_save_config.called

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_ls_hierarchical_tags(self, mock_get_tags, mock_metadata_store,
                                  mock_find_repos, mock_load_config, mock_repos, capsys):
        """Test listing hierarchical tag directories."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.side_effect = [
            ['alex/beta'],
            ['alex/production'],
            ['alex/beta']
        ]

        # Create shell
        shell = RepoIndexShell()

        # List /by-tag/ with --json flag for testing
        shell.do_ls('/by-tag --json')
        captured = capsys.readouterr()

        # Should show alex as a directory
        output_lines = captured.out.strip().split('\n')
        assert len(output_lines) > 0

        # Check that we get JSON output
        first_line = json.loads(output_lines[0])
        assert 'name' in first_line
        assert 'type' in first_line

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_ls_default_pretty_output(self, mock_get_tags, mock_metadata_store,
                                      mock_find_repos, mock_load_config, mock_repos, capsys):
        """Test that ls defaults to pretty formatted output."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.side_effect = [
            ['alex/beta'],
            ['alex/production'],
            ['alex/beta']
        ]

        # Create shell
        shell = RepoIndexShell()

        # List /by-tag/ without flags (should get Rich table output)
        shell.do_ls('/by-tag')
        captured = capsys.readouterr()

        # Should have table output (not JSON)
        assert 'alex' in captured.out  # Directory name should appear
        # Should NOT be JSON (no opening brace on first character of first line)
        assert not captured.out.strip().startswith('{')

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    @patch('repoindex.shell.shell.get_repository_tags')
    def test_cd_through_hierarchical_tags(self, mock_get_tags, mock_metadata_store,
                                         mock_find_repos, mock_load_config, mock_repos):
        """Test navigating through hierarchical tag directories."""
        # Setup mocks
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        mock_get_tags.side_effect = [
            ['topic:scientific/engineering/ai'],
            [],
            []
        ]

        # Create shell
        shell = RepoIndexShell()

        # Navigate into hierarchy
        shell.do_cd('/by-tag')
        assert str(shell.cwd) == '/by-tag'

        shell.do_cd('topic')
        assert str(shell.cwd) == '/by-tag/topic'

        shell.do_cd('scientific')
        assert str(shell.cwd) == '/by-tag/topic/scientific'

        shell.do_cd('engineering')
        assert str(shell.cwd) == '/by-tag/topic/scientific/engineering'


class TestShellVFSEdgeCases:
    """Test edge cases and error handling."""

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    def test_cp_invalid_destination(self, mock_metadata_store, mock_find_repos,
                                    mock_load_config, mock_repos, capsys):
        """Test cp command with invalid destination."""
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = mock_repos

        mock_store = MagicMock()
        mock_store.get.return_value = {'language': 'Python', 'status': {}}
        mock_metadata_store.return_value = mock_store

        shell = RepoIndexShell()

        # Try to cp to non-tag location
        repo_name = Path(mock_repos[0]).name
        shell.do_cp(f'/repos/{repo_name} /repos/other')

        captured = capsys.readouterr()
        assert 'must be under /by-tag/' in captured.out

    @patch('repoindex.shell.shell.load_config')
    @patch('repoindex.shell.shell.find_git_repos_from_config')
    @patch('repoindex.shell.shell.get_metadata_store')
    def test_mkdir_creates_namespace(self, mock_metadata_store, mock_find_repos,
                                     mock_load_config, capsys):
        """Test mkdir creates tag namespace."""
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']},
            'repository_tags': {}
        }
        mock_find_repos.return_value = []

        mock_store = MagicMock()
        mock_metadata_store.return_value = mock_store

        shell = RepoIndexShell()

        # Create new tag namespace
        shell.do_mkdir('-p /by-tag/work/client/acme')

        captured = capsys.readouterr()
        assert 'ready for use' in captured.out

    def test_empty_tag_handling(self):
        """Test handling of empty tags."""
        shell = RepoIndexShell.__new__(RepoIndexShell)

        # Empty string
        assert shell._parse_tag_levels('') == []

        # Path to tag with empty result
        assert shell._path_to_tag('/by-tag/') is None
