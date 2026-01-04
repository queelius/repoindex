"""
Tests for repoindex.repo_filter module.

Tests focus on:
- get_filtered_repos() with various filter combinations
- Discovery priority (--dir > config > current directory)
- Tag and query filtering
- Error handling and edge cases
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestGetFilteredRepos(unittest.TestCase):
    """Tests for the get_filtered_repos function."""

    def setUp(self):
        """Set up test environment with temp directories."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        self.repos_dir = Path(self.temp_dir) / "repos"
        self.repos_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up test environment."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_git_repo(self, name: str) -> Path:
        """Create a minimal git repo."""
        repo_path = self.repos_dir / name
        repo_path.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, capture_output=True)
        (repo_path / "README.md").write_text(f"# {name}\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_path, capture_output=True)
        return repo_path

    def test_get_filtered_repos_with_dir_option(self):
        """Test that --dir option overrides config and discovers repos."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: Git repos in our repos directory
        self._create_git_repo("project-a")
        self._create_git_repo("project-b")

        # And: A config pointing elsewhere
        config = {'repository_directories': ['/nonexistent/path/**']}

        # When: We get repos with dir option
        repos, filter_desc = get_filtered_repos(
            dir=str(self.repos_dir),
            recursive=False,
            config=config
        )

        # Then: It should find repos in the specified directory
        self.assertEqual(len(repos), 2)
        names = [os.path.basename(r) for r in repos]
        self.assertIn("project-a", names)
        self.assertIn("project-b", names)

    def test_get_filtered_repos_from_config(self):
        """Test that repos are discovered from config when no --dir option."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: Git repos in our repos directory
        self._create_git_repo("config-repo")

        # And: A config pointing to our repos
        config = {'repository_directories': [str(self.repos_dir) + "/**"]}

        # When: We get repos without dir option
        repos, filter_desc = get_filtered_repos(
            dir=None,
            recursive=False,
            config=config
        )

        # Then: It should find repos from config
        self.assertEqual(len(repos), 1)
        self.assertIn("config-repo", repos[0])

    def test_get_filtered_repos_fallback_to_current_directory(self):
        """Test fallback to current directory when no dir or config."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: We're in a git repo
        repo_path = self._create_git_repo("cwd-repo")
        os.chdir(repo_path)

        # And: Empty config
        config = {'repository_directories': []}

        # When: We get repos
        repos, filter_desc = get_filtered_repos(
            dir=None,
            recursive=False,
            config=config
        )

        # Then: It should find the current repo
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0], str(repo_path))

    def test_get_filtered_repos_recursive_finds_nested_repos(self):
        """Test that recursive mode finds nested repositories."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: Nested repos
        self._create_git_repo("top-level")
        nested_dir = self.repos_dir / "nested"
        nested_dir.mkdir()
        subprocess.run(["git", "init"], cwd=nested_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=nested_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=nested_dir, capture_output=True)
        (nested_dir / "README.md").write_text("# Nested\n")
        subprocess.run(["git", "add", "."], cwd=nested_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=nested_dir, capture_output=True)

        # When: We get repos recursively
        repos, filter_desc = get_filtered_repos(
            dir=str(self.repos_dir),
            recursive=True,
            config={}
        )

        # Then: It should find both repos
        self.assertEqual(len(repos), 2)

    def test_get_filtered_repos_loads_config_when_not_provided(self):
        """Test that config is loaded when not provided."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: A directory with repos
        self._create_git_repo("auto-config-repo")

        # When: We get repos with explicit dir but no config
        with patch('repoindex.repo_filter.load_config') as mock_load:
            mock_load.return_value = {'repository_directories': []}
            repos, filter_desc = get_filtered_repos(
                dir=str(self.repos_dir),
                recursive=False
                # Note: config=None, so it should call load_config
            )

            # Then: load_config should have been called
            mock_load.assert_called_once()

    def test_get_filtered_repos_returns_filter_description_for_query(self):
        """Test that query filter returns proper description."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: A repo
        self._create_git_repo("query-test-repo")

        # When: We get repos with a query filter
        with patch('repoindex.repo_filter.MetadataStore') as mock_store:
            mock_store.return_value.get.return_value = {'name': 'query-test-repo'}
            with patch('repoindex.repo_filter.Query') as mock_query:
                mock_query.return_value.evaluate.return_value = True
                repos, filter_desc = get_filtered_repos(
                    dir=str(self.repos_dir),
                    recursive=False,
                    query="name == 'query-test-repo'",
                    config={}
                )

        # Then: Filter description should include the query
        self.assertIsNotNone(filter_desc)
        self.assertIn("query:", filter_desc)

    def test_get_filtered_repos_returns_filter_description_for_tags(self):
        """Test that tag filter returns proper description."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: A repo
        self._create_git_repo("tagged-repo")

        # When: We get repos with tag filters
        with patch('repoindex.repo_filter.get_repositories_by_tags') as mock_get_by_tags:
            mock_get_by_tags.return_value = [
                {"path": str(self.repos_dir / "tagged-repo")}
            ]
            repos, filter_desc = get_filtered_repos(
                dir=str(self.repos_dir),
                recursive=False,
                tag_filters=["lang:python"],
                all_tags=False,
                config={}
            )

        # Then: Filter description should include the tags
        self.assertIsNotNone(filter_desc)
        self.assertIn("tags:", filter_desc)
        self.assertIn("lang:python", filter_desc)

    def test_get_filtered_repos_all_tags_mode(self):
        """Test that all_tags mode shows AND in filter description."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: A repo
        self._create_git_repo("multi-tag-repo")

        # When: We get repos with multiple tag filters in AND mode
        with patch('repoindex.repo_filter.get_repositories_by_tags') as mock_get_by_tags:
            mock_get_by_tags.return_value = [
                {"path": str(self.repos_dir / "multi-tag-repo")}
            ]
            repos, filter_desc = get_filtered_repos(
                dir=str(self.repos_dir),
                recursive=False,
                tag_filters=["lang:python", "status:active"],
                all_tags=True,
                config={}
            )

        # Then: Filter description should show AND mode
        self.assertIsNotNone(filter_desc)
        self.assertIn("AND", filter_desc)

    def test_get_filtered_repos_empty_directory(self):
        """Test behavior with directory containing no git repos."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: An empty directory
        empty_dir = Path(self.temp_dir) / "empty"
        empty_dir.mkdir()

        # When: We get repos
        repos, filter_desc = get_filtered_repos(
            dir=str(empty_dir),
            recursive=False,
            config={}
        )

        # Then: Should return empty list
        self.assertEqual(repos, [])

    def test_get_filtered_repos_expands_user_in_dir(self):
        """Test that ~ is expanded in directory path."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: A directory using ~ notation
        # We need to mock expanduser for reliable testing
        with patch('os.path.abspath') as mock_abspath:
            mock_abspath.return_value = str(self.repos_dir)
            with patch('repoindex.repo_filter.find_git_repos') as mock_find:
                mock_find.return_value = [str(self.repos_dir / "test-repo")]

                repos, filter_desc = get_filtered_repos(
                    dir="~/repos",
                    recursive=False,
                    config={}
                )

        # Then: expanduser should have been called via abspath
        mock_abspath.assert_called()


class TestRepoDiscoveryDecorator(unittest.TestCase):
    """Tests for the add_repo_discovery_options decorator."""

    def test_decorator_adds_all_options(self):
        """Test that decorator adds all expected Click options."""
        from repoindex.repo_filter import add_repo_discovery_options
        import click

        @add_repo_discovery_options
        @click.command()
        def test_cmd(dir, recursive, tag_filters, all_tags, query):
            pass

        # Check that the command has the expected parameters
        param_names = [p.name for p in test_cmd.params]
        self.assertIn("dir", param_names)
        self.assertIn("recursive", param_names)
        self.assertIn("tag_filters", param_names)
        self.assertIn("all_tags", param_names)
        self.assertIn("query", param_names)

    def test_backward_compatibility_alias(self):
        """Test that add_common_repo_options is an alias."""
        from repoindex.repo_filter import add_repo_discovery_options, add_common_repo_options

        # Then: They should be the same function
        self.assertIs(add_common_repo_options, add_repo_discovery_options)


class TestFilteredReposWithQuery(unittest.TestCase):
    """Tests for query-based filtering in get_filtered_repos."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.repos_dir = Path(self.temp_dir) / "repos"
        self.repos_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_git_repo(self, name: str) -> Path:
        """Create a minimal git repo."""
        repo_path = self.repos_dir / name
        repo_path.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, capture_output=True)
        (repo_path / "README.md").write_text(f"# {name}\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_path, capture_output=True)
        return repo_path

    def test_query_filters_out_non_matching_repos(self):
        """Test that query filter excludes non-matching repos."""
        from repoindex.repo_filter import get_filtered_repos

        # Given: Two repos
        self._create_git_repo("python-project")
        self._create_git_repo("go-project")

        # When: We filter with a query that only matches one
        with patch('repoindex.repo_filter.MetadataStore') as mock_store:
            def get_metadata(path):
                if "python" in path:
                    return {'language': 'Python'}
                return {'language': 'Go'}
            mock_store.return_value.get.side_effect = get_metadata

            with patch('repoindex.repo_filter.get_implicit_tags') as mock_tags:
                mock_tags.return_value = []

                repos, filter_desc = get_filtered_repos(
                    dir=str(self.repos_dir),
                    recursive=False,
                    query="language == 'Python'",
                    config={}
                )

        # Then: Only matching repo should be returned
        self.assertEqual(len(repos), 1)
        self.assertIn("python-project", repos[0])


if __name__ == "__main__":
    unittest.main()
