"""
Tests for copy service and command.
"""

import json
import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from repoindex.services.copy_service import (
    CopyService, CopyOptions, CopyResult, CollisionStrategy
)


class TestCopyOptions:
    """Tests for CopyOptions dataclass."""

    def test_default_options(self, tmp_path):
        """Test default copy options."""
        options = CopyOptions(destination=tmp_path)

        assert options.destination == tmp_path
        assert options.exclude_git is False
        assert options.preserve_structure is False
        assert options.collision_strategy == CollisionStrategy.RENAME
        assert options.dry_run is False

    def test_all_options_set(self, tmp_path):
        """Test copy with all options set."""
        options = CopyOptions(
            destination=tmp_path,
            exclude_git=True,
            preserve_structure=True,
            collision_strategy=CollisionStrategy.SKIP,
            dry_run=True,
        )

        assert options.exclude_git is True
        assert options.preserve_structure is True
        assert options.collision_strategy == CollisionStrategy.SKIP
        assert options.dry_run is True


class TestCopyResult:
    """Tests for CopyResult dataclass."""

    def test_default_result(self):
        """Test default copy result."""
        result = CopyResult()

        assert result.repos_copied == 0
        assert result.repos_skipped == 0
        assert result.bytes_copied == 0
        assert result.errors == []
        assert result.details == []
        assert result.success is True

    def test_result_with_errors(self):
        """Test copy result with errors."""
        result = CopyResult(errors=["Error 1", "Error 2"])

        assert result.success is False
        assert len(result.errors) == 2


class TestCollisionStrategy:
    """Tests for CollisionStrategy enum."""

    def test_enum_values(self):
        """Test that enum has expected values."""
        assert CollisionStrategy.RENAME.value == "rename"
        assert CollisionStrategy.SKIP.value == "skip"
        assert CollisionStrategy.OVERWRITE.value == "overwrite"

    def test_enum_from_string(self):
        """Test creating enum from string."""
        assert CollisionStrategy("rename") == CollisionStrategy.RENAME
        assert CollisionStrategy("skip") == CollisionStrategy.SKIP
        assert CollisionStrategy("overwrite") == CollisionStrategy.OVERWRITE


class TestCopyService:
    """Tests for CopyService."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        return {}

    @pytest.fixture
    def setup_test_repos(self, tmp_path):
        """Create test repositories."""
        repos = []
        for name in ['repo-a', 'repo-b', 'repo-c']:
            repo_path = tmp_path / 'source' / name
            repo_path.mkdir(parents=True)

            # Create .git directory
            (repo_path / '.git').mkdir()
            (repo_path / '.git' / 'config').write_text('[core]\n')

            # Create some files
            (repo_path / 'README.md').write_text(f'# {name}')
            (repo_path / 'main.py').write_text(f'print("{name}")')

            repos.append({
                'path': str(repo_path),
                'name': name,
            })

        return repos

    def test_copy_basic(self, mock_config, setup_test_repos, tmp_path):
        """Test basic copy operation."""
        dest_dir = tmp_path / 'backup'

        service = CopyService(config=mock_config)
        options = CopyOptions(destination=dest_dir)

        messages = list(service.copy(setup_test_repos, options))
        result = service.last_result

        # Check all repos were copied
        assert result.repos_copied == 3
        assert result.repos_skipped == 0
        assert result.success is True

        # Check destination has repos
        assert (dest_dir / 'repo-a').exists()
        assert (dest_dir / 'repo-b').exists()
        assert (dest_dir / 'repo-c').exists()

        # Check files exist
        assert (dest_dir / 'repo-a' / 'README.md').exists()
        assert (dest_dir / 'repo-a' / 'main.py').exists()

    def test_copy_dry_run(self, mock_config, setup_test_repos, tmp_path):
        """Test copy in dry run mode."""
        dest_dir = tmp_path / 'backup-dry'

        service = CopyService(config=mock_config)
        options = CopyOptions(destination=dest_dir, dry_run=True)

        messages = list(service.copy(setup_test_repos, options))
        result = service.last_result

        # Should count repos but not create directories
        assert result.repos_copied == 3
        assert not dest_dir.exists()

    def test_copy_exclude_git(self, mock_config, setup_test_repos, tmp_path):
        """Test copy with .git directories excluded."""
        dest_dir = tmp_path / 'backup-no-git'

        service = CopyService(config=mock_config)
        options = CopyOptions(destination=dest_dir, exclude_git=True)

        messages = list(service.copy(setup_test_repos, options))
        result = service.last_result

        # Check repos were copied
        assert result.repos_copied == 3

        # Check .git directories are excluded
        assert not (dest_dir / 'repo-a' / '.git').exists()
        assert (dest_dir / 'repo-a' / 'README.md').exists()

    def test_copy_collision_rename(self, mock_config, tmp_path):
        """Test collision handling with rename strategy."""
        source_dir = tmp_path / 'source'

        # Create two repos with same name in different directories
        repo1 = source_dir / 'dir1' / 'utils'
        repo1.mkdir(parents=True)
        (repo1 / '.git').mkdir()
        (repo1 / 'README.md').write_text('# Utils 1')

        repo2 = source_dir / 'dir2' / 'utils'
        repo2.mkdir(parents=True)
        (repo2 / '.git').mkdir()
        (repo2 / 'README.md').write_text('# Utils 2')

        repos = [
            {'path': str(repo1), 'name': 'utils'},
            {'path': str(repo2), 'name': 'utils'},
        ]

        dest_dir = tmp_path / 'backup'

        service = CopyService(config={})
        options = CopyOptions(
            destination=dest_dir,
            collision_strategy=CollisionStrategy.RENAME
        )

        list(service.copy(repos, options))
        result = service.last_result

        # Both should be copied with renamed second
        assert result.repos_copied == 2
        assert (dest_dir / 'utils').exists()
        assert (dest_dir / 'utils-1').exists()

    def test_copy_collision_skip(self, mock_config, tmp_path):
        """Test collision handling with skip strategy."""
        source_dir = tmp_path / 'source'

        # Create two repos with same name
        repo1 = source_dir / 'dir1' / 'utils'
        repo1.mkdir(parents=True)
        (repo1 / '.git').mkdir()

        repo2 = source_dir / 'dir2' / 'utils'
        repo2.mkdir(parents=True)
        (repo2 / '.git').mkdir()

        repos = [
            {'path': str(repo1), 'name': 'utils'},
            {'path': str(repo2), 'name': 'utils'},
        ]

        dest_dir = tmp_path / 'backup'

        service = CopyService(config={})
        options = CopyOptions(
            destination=dest_dir,
            collision_strategy=CollisionStrategy.SKIP
        )

        list(service.copy(repos, options))
        result = service.last_result

        # First should be copied, second skipped
        assert result.repos_copied == 1
        assert result.repos_skipped == 1
        assert (dest_dir / 'utils').exists()

    def test_copy_collision_overwrite(self, mock_config, tmp_path):
        """Test collision handling with overwrite strategy."""
        source_dir = tmp_path / 'source'

        # Create two repos with same name
        repo1 = source_dir / 'dir1' / 'utils'
        repo1.mkdir(parents=True)
        (repo1 / '.git').mkdir()
        (repo1 / 'README.md').write_text('# Utils 1')

        repo2 = source_dir / 'dir2' / 'utils'
        repo2.mkdir(parents=True)
        (repo2 / '.git').mkdir()
        (repo2 / 'README.md').write_text('# Utils 2')

        repos = [
            {'path': str(repo1), 'name': 'utils'},
            {'path': str(repo2), 'name': 'utils'},
        ]

        dest_dir = tmp_path / 'backup'

        service = CopyService(config={})
        options = CopyOptions(
            destination=dest_dir,
            collision_strategy=CollisionStrategy.OVERWRITE
        )

        list(service.copy(repos, options))
        result = service.last_result

        # Both should be "copied" (second overwrites first)
        assert result.repos_copied == 2
        assert (dest_dir / 'utils').exists()

        # Content should be from second repo
        content = (dest_dir / 'utils' / 'README.md').read_text()
        assert '# Utils 2' in content

    def test_copy_preserve_structure(self, mock_config, tmp_path):
        """Test copy with preserve_structure option."""
        # Create repo under a specific path
        repo_path = tmp_path / 'source' / 'github' / 'user' / 'project'
        repo_path.mkdir(parents=True)
        (repo_path / '.git').mkdir()
        (repo_path / 'README.md').write_text('# Project')

        repos = [{'path': str(repo_path), 'name': 'project'}]

        dest_dir = tmp_path / 'backup'

        service = CopyService(config={})
        options = CopyOptions(
            destination=dest_dir,
            preserve_structure=True
        )

        list(service.copy(repos, options))
        result = service.last_result

        # Should preserve relative path structure
        assert result.repos_copied == 1
        # The exact path depends on implementation of _get_relative_path

    def test_copy_empty_repos_list(self, mock_config, tmp_path):
        """Test copy with empty repos list."""
        dest_dir = tmp_path / 'backup'

        service = CopyService(config={})
        options = CopyOptions(destination=dest_dir)

        messages = list(service.copy([], options))
        result = service.last_result

        assert result.repos_copied == 0
        assert 'No repositories' in messages[0]

    def test_copy_nonexistent_repo(self, mock_config, tmp_path):
        """Test copy with nonexistent repository."""
        dest_dir = tmp_path / 'backup'

        repos = [{'path': '/nonexistent/repo', 'name': 'repo'}]

        service = CopyService(config={})
        options = CopyOptions(destination=dest_dir)

        list(service.copy(repos, options))
        result = service.last_result

        assert result.repos_copied == 0
        assert len(result.errors) == 1

    def test_copy_bytes_tracked(self, mock_config, setup_test_repos, tmp_path):
        """Test that bytes copied are tracked."""
        dest_dir = tmp_path / 'backup'

        service = CopyService(config={})
        options = CopyOptions(destination=dest_dir)

        list(service.copy(setup_test_repos, options))
        result = service.last_result

        # Should track bytes copied
        assert result.bytes_copied > 0

    def test_copy_details_tracked(self, mock_config, setup_test_repos, tmp_path):
        """Test that copy details are tracked."""
        dest_dir = tmp_path / 'backup'

        service = CopyService(config={})
        options = CopyOptions(destination=dest_dir)

        list(service.copy(setup_test_repos, options))
        result = service.last_result

        # Should have details for each repo
        assert len(result.details) == 3

        for detail in result.details:
            assert 'path' in detail
            assert 'name' in detail
            assert 'status' in detail
            assert detail['status'] == 'copied'


class TestCopyServiceHelpers:
    """Tests for CopyService helper methods."""

    def test_get_relative_path_from_home(self, tmp_path):
        """Test _get_relative_path with home directory path."""
        service = CopyService(config={})

        # Test with path under home
        home = Path.home()
        test_path = home / 'github' / 'project'

        result = service._get_relative_path(test_path)
        assert result == Path('github/project')

    def test_get_relative_path_not_under_home(self, tmp_path):
        """Test _get_relative_path with path not under home."""
        service = CopyService(config={})

        # Use tmp_path which is not under home
        test_path = tmp_path / 'some' / 'path'

        result = service._get_relative_path(test_path)
        # Should use last 2 components
        assert result.parts[-1] == 'path'

    def test_get_dir_size(self, tmp_path):
        """Test _get_dir_size calculation."""
        service = CopyService(config={})

        # Create a directory with known file sizes
        test_dir = tmp_path / 'test'
        test_dir.mkdir()
        (test_dir / 'file1.txt').write_text('12345')  # 5 bytes
        (test_dir / 'file2.txt').write_text('1234567890')  # 10 bytes

        size = service._get_dir_size(test_dir)
        assert size == 15

    def test_get_dir_size_with_exclude_git(self, tmp_path):
        """Test _get_dir_size with .git exclusion."""
        service = CopyService(config={})

        # Create directory with .git
        test_dir = tmp_path / 'test'
        test_dir.mkdir()
        (test_dir / 'file.txt').write_text('12345')  # 5 bytes

        git_dir = test_dir / '.git'
        git_dir.mkdir()
        (git_dir / 'objects').write_text('a' * 1000)  # 1000 bytes

        size_with_git = service._get_dir_size(test_dir, exclude_git=False)
        size_without_git = service._get_dir_size(test_dir, exclude_git=True)

        assert size_with_git > size_without_git
        assert size_without_git == 5


class TestCopyCommand:
    """Tests for the copy CLI command."""

    def test_copy_handler_exists(self):
        """Test that copy handler is importable."""
        from repoindex.commands.copy import copy_handler
        assert copy_handler is not None

    def test_copy_registered_in_cli(self):
        """Test that copy is registered in CLI."""
        from repoindex.cli import cli

        commands = list(cli.commands.keys())
        assert 'copy' in commands

    def test_format_bytes_helper(self):
        """Test the _format_bytes helper function."""
        from repoindex.commands.copy import _format_bytes

        assert 'B' in _format_bytes(100)
        assert 'KB' in _format_bytes(1024)
        assert 'MB' in _format_bytes(1024 * 1024)
        assert 'GB' in _format_bytes(1024 * 1024 * 1024)


class TestCopyIntegration:
    """Integration tests for copy functionality."""

    @pytest.fixture
    def full_test_setup(self, tmp_path):
        """Set up a complete test environment with database."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        # Create database
        db_path = tmp_path / 'test.db'
        config = {'database': {'path': str(db_path)}}

        # Create test repos on filesystem
        repos = []
        for name, lang in [
            ('python-project', 'Python'),
            ('js-project', 'JavaScript'),
            ('rust-project', 'Rust'),
        ]:
            repo_path = tmp_path / 'repos' / name
            repo_path.mkdir(parents=True)
            (repo_path / '.git').mkdir()
            (repo_path / 'README.md').write_text(f'# {name}\n\nA {lang} project.')
            (repo_path / 'main.py').write_text(f'# {lang} code')
            repos.append({'name': name, 'path': str(repo_path), 'language': lang})

        # Populate database
        with Database(config=config) as db:
            apply_schema(db.conn)

            for repo in repos:
                db.execute("""
                    INSERT INTO repos (name, path, language, branch, has_readme)
                    VALUES (?, ?, ?, 'main', 1)
                """, (repo['name'], repo['path'], repo['language']))

            db.conn.commit()

        return config, repos

    def test_copy_all_repos(self, full_test_setup, tmp_path):
        """Test copying all repos from database."""
        config, repos = full_test_setup
        dest_dir = tmp_path / 'backup'

        service = CopyService(config=config)
        options = CopyOptions(destination=dest_dir)

        list(service.copy(repos, options))
        result = service.last_result

        assert result.repos_copied == 3
        assert result.success is True

        # Verify all repos exist
        assert (dest_dir / 'python-project').exists()
        assert (dest_dir / 'js-project').exists()
        assert (dest_dir / 'rust-project').exists()

    def test_copy_preserves_content(self, full_test_setup, tmp_path):
        """Test that copy preserves file content."""
        config, repos = full_test_setup
        dest_dir = tmp_path / 'backup'

        service = CopyService(config=config)
        options = CopyOptions(destination=dest_dir)

        list(service.copy(repos, options))

        # Check content is preserved
        source_readme = Path(repos[0]['path']) / 'README.md'
        dest_readme = dest_dir / repos[0]['name'] / 'README.md'

        assert source_readme.read_text() == dest_readme.read_text()

    def test_copy_with_filter_simulation(self, full_test_setup, tmp_path):
        """Test copying filtered repos (simulation)."""
        config, repos = full_test_setup
        dest_dir = tmp_path / 'backup'

        # Filter to only Python repos
        python_repos = [r for r in repos if r['language'] == 'Python']

        service = CopyService(config=config)
        options = CopyOptions(destination=dest_dir)

        list(service.copy(python_repos, options))
        result = service.last_result

        assert result.repos_copied == 1
        assert (dest_dir / 'python-project').exists()
        assert not (dest_dir / 'js-project').exists()
