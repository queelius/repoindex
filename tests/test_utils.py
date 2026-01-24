"""
Unit tests for ghops.utils module
"""
import unittest
import tempfile
import os
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.utils import (
    run_command, 
    find_git_repos, 
    get_git_status, 
    is_git_repo
)


class TestRunCommand(unittest.TestCase):
    """Test the run_command utility function

    Note: run_command returns (stdout, returncode) tuple when capture_output=True,
    and (None, returncode) when capture_output=False.
    """

    def test_run_command_capture_output(self):
        """Test run_command with capture_output=True returns (stdout, returncode)"""
        output, returncode = run_command("echo 'test'", capture_output=True)
        self.assertEqual(output.strip(), "test")
        self.assertEqual(returncode, 0)

    def test_run_command_no_capture(self):
        """Test run_command with capture_output=False returns (None, returncode)"""
        output, returncode = run_command("echo 'test'", capture_output=False)
        self.assertIsNone(output)
        self.assertEqual(returncode, 0)

    def test_run_command_dry_run(self):
        """Test run_command with dry_run=True returns simulated output"""
        output, returncode = run_command("echo 'test'", dry_run=True, capture_output=True)
        self.assertEqual(output, "Dry run output")
        self.assertEqual(returncode, 0)

    def test_run_command_failure(self):
        """Test run_command with failing command returns non-zero returncode"""
        output, returncode = run_command("false", capture_output=True, check=False)
        self.assertEqual(output, "")
        self.assertEqual(returncode, 1)

    def test_run_command_with_cwd(self):
        """Test run_command with different working directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            output, returncode = run_command("pwd", cwd=temp_dir, capture_output=True)
            self.assertEqual(output.strip(), temp_dir)
            self.assertEqual(returncode, 0)


class TestGitRepoDetection(unittest.TestCase):
    """Test git repository detection functions"""
    
    def setUp(self):
        """Set up test directories"""
        self.temp_dir = tempfile.mkdtemp()
        
        # Create a fake git repo
        self.git_repo_dir = os.path.join(self.temp_dir, "git_repo")
        os.makedirs(self.git_repo_dir)
        os.makedirs(os.path.join(self.git_repo_dir, ".git"))
        
        # Create a non-git directory
        self.non_git_dir = os.path.join(self.temp_dir, "non_git")
        os.makedirs(self.non_git_dir)
        
        # Create nested git repo
        self.nested_git_dir = os.path.join(self.temp_dir, "parent", "nested_git")
        os.makedirs(self.nested_git_dir)
        os.makedirs(os.path.join(self.nested_git_dir, ".git"))
    
    def tearDown(self):
        """Clean up test directories"""
        shutil.rmtree(self.temp_dir)
    
    def test_is_git_repo_positive(self):
        """Test is_git_repo with actual git repository"""
        self.assertTrue(is_git_repo(self.git_repo_dir))
    
    def test_is_git_repo_negative(self):
        """Test is_git_repo with non-git directory"""
        self.assertFalse(is_git_repo(self.non_git_dir))
    
    def test_find_git_repos_non_recursive(self):
        """Test find_git_repos without recursion"""
        repos = find_git_repos(self.temp_dir, recursive=False)
        self.assertIn(self.git_repo_dir, repos)
        self.assertNotIn(self.nested_git_dir, repos)
    
    def test_find_git_repos_recursive(self):
        """Test find_git_repos with recursion"""
        repos = find_git_repos(self.temp_dir, recursive=True)
        self.assertIn(self.git_repo_dir, repos)
        self.assertIn(self.nested_git_dir, repos)


class TestGetGitStatus(unittest.TestCase):
    """Test the get_git_status function

    Note: run_command returns (stdout, returncode) tuple, so mocks must return tuples.
    """

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        os.chdir(self.temp_dir)

    def tearDown(self):
        """Clean up test environment"""
        os.chdir("/")
        shutil.rmtree(self.temp_dir)

    @patch('repoindex.utils.run_command')
    def test_get_git_status_clean_repo(self, mock_run_command):
        """Test get_git_status with clean repository"""
        mock_run_command.side_effect = [
            ("main", 0),              # git rev-parse --abbrev-ref HEAD
            ("", 0),                  # git status --porcelain
            ("fatal: no upstream", 1) # git rev-parse --abbrev-ref @{u}
        ]

        result = get_git_status(self.temp_dir)

        self.assertEqual(result['status'], 'clean')
        self.assertEqual(result['current_branch'], 'main')

    @patch('repoindex.utils.run_command')
    def test_get_git_status_modified_files(self, mock_run_command):
        """Test get_git_status with modified files"""
        mock_run_command.side_effect = [
            ("main", 0),                                      # git rev-parse --abbrev-ref HEAD
            (" M file1.py\nM  file2.py\n?? new_file.py", 0), # git status --porcelain
            ("fatal: no upstream", 1)                         # git rev-parse --abbrev-ref @{u}
        ]

        result = get_git_status(self.temp_dir)

        self.assertEqual(result['current_branch'], 'main')
        self.assertIn('modified', result['status'])
        self.assertIn('untracked', result['status'])

    @patch('repoindex.utils.run_command')
    def test_get_git_status_error(self, mock_run_command):
        """Test get_git_status with command failure"""
        mock_run_command.side_effect = Exception("Git command failed")

        result = get_git_status(self.temp_dir)

        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['current_branch'], 'unknown')

    @patch('repoindex.utils.run_command')
    def test_get_git_status_various_changes(self, mock_run_command):
        """Test get_git_status with various types of changes"""
        mock_run_command.side_effect = [
            ("feature-branch", 0),                                               # git rev-parse --abbrev-ref HEAD
            ("A  added.py\n D deleted.py\nM  modified.py\n?? untracked.py", 0), # git status --porcelain
            ("fatal: no upstream", 1)                                            # git rev-parse --abbrev-ref @{u}
        ]

        result = get_git_status(self.temp_dir)

        self.assertEqual(result['current_branch'], 'feature-branch')
        status = result['status']
        self.assertIn('1 added', status)
        self.assertIn('1 deleted', status)
        self.assertIn('1 modified', status)
        self.assertIn('1 untracked', status)


if __name__ == '__main__':
    unittest.main()

import pytest
from repoindex.utils import find_git_repos


@pytest.fixture
def mock_git_repos(fs):
    """Create a mock file system with git repositories."""
    fs.create_dir("/test/repo1/.git")
    fs.create_dir("/test/repo2/.git")
    fs.create_dir("/test/not_a_repo/subdir")
    fs.create_dir("/test/level2/repo3/.git")
    fs.create_dir("/test_single_repo/.git")
    fs.create_dir("/test_single_repo/subdir/repo4/.git")


def test_find_git_repos_single_dir_no_recursion(mock_git_repos):
    # Test with a single directory, no recursion
    repos = find_git_repos("/test", recursive=False)
    assert sorted(repos) == ["/test/repo1", "/test/repo2"]


def test_find_git_repos_single_dir_recursive(mock_git_repos):
    # Test with a single directory, with recursion
    repos = find_git_repos("/test", recursive=True)
    assert sorted(repos) == ["/test/level2/repo3", "/test/repo1", "/test/repo2"]


def test_find_git_repos_list_of_dirs(mock_git_repos):
    # Test with a list of directories
    repos = find_git_repos(["/test", "/test_single_repo"], recursive=True)
    assert sorted(repos) == [
        "/test/level2/repo3",
        "/test/repo1",
        "/test/repo2",
        "/test_single_repo",
        "/test_single_repo/subdir/repo4",
    ]


def test_find_git_repos_base_dir_is_repo(mock_git_repos):
    # Test when the base directory itself is a repo
    # Without recursion, should only find the base
    repos = find_git_repos("/test_single_repo", recursive=False)
    assert repos == ["/test_single_repo"]

    # With recursion, should find both the parent and the nested repo
    repos_recursive = find_git_repos("/test_single_repo", recursive=True)
    assert sorted(repos_recursive) == ["/test_single_repo", "/test_single_repo/subdir/repo4"]


def test_find_git_repos_empty(fs):
    # Test with no git repos in the specified path
    fs.create_dir("/empty_dir/subdir")
    repos = find_git_repos("/empty_dir", recursive=True)
    assert repos == []


def test_find_git_repos_nonexistent_dir(mock_git_repos):
    # Test with a non-existent directory
    repos = find_git_repos("/nonexistent")
    assert repos == []


def test_find_git_repos_handles_string_and_list_input(mock_git_repos):
    # The function should handle both a single string and a list of strings
    repos_str = find_git_repos("/test", recursive=True)
    repos_list = find_git_repos(["/test"], recursive=True)
    assert sorted(repos_str) == sorted(repos_list)
    assert sorted(repos_str) == ["/test/level2/repo3", "/test/repo1", "/test/repo2"]


# ============================================================================
# Tests for parse_repo_url
# ============================================================================

from repoindex.utils import parse_repo_url


class TestParseRepoUrl:
    """Tests for parse_repo_url function."""

    def test_https_url(self):
        """Parse HTTPS GitHub URL."""
        owner, repo = parse_repo_url("https://github.com/octocat/Hello-World.git")
        assert owner == "octocat"
        assert repo == "Hello-World"

    def test_https_url_no_git_suffix(self):
        """Parse HTTPS URL without .git suffix."""
        owner, repo = parse_repo_url("https://github.com/octocat/Hello-World")
        assert owner == "octocat"
        assert repo == "Hello-World"

    def test_ssh_url(self):
        """Parse SSH GitHub URL."""
        owner, repo = parse_repo_url("git@github.com:octocat/Hello-World.git")
        assert owner == "octocat"
        assert repo == "Hello-World"

    def test_ssh_url_no_git_suffix(self):
        """Parse SSH URL without .git suffix."""
        owner, repo = parse_repo_url("git@github.com:octocat/Hello-World")
        assert owner == "octocat"
        assert repo == "Hello-World"

    def test_empty_url(self):
        """Empty URL returns None, None."""
        owner, repo = parse_repo_url("")
        assert owner is None
        assert repo is None

    def test_none_url(self):
        """None URL returns None, None."""
        owner, repo = parse_repo_url(None)
        assert owner is None
        assert repo is None

    def test_invalid_url(self):
        """Invalid URL returns None, None."""
        owner, repo = parse_repo_url("https://gitlab.com/user/repo")
        assert owner is None
        assert repo is None

    def test_url_with_subdirectory(self):
        """URL parsing handles repo names correctly."""
        owner, repo = parse_repo_url("https://github.com/org-name/my-project.git")
        assert owner == "org-name"
        assert repo == "my-project"


# ============================================================================
# Tests for get_git_remote_url
# ============================================================================

from repoindex.utils import get_git_remote_url


class TestGetGitRemoteUrl:
    """Tests for get_git_remote_url function."""

    @patch('repoindex.utils.run_command')
    def test_returns_url_on_success(self, mock_run):
        """Returns remote URL when git command succeeds."""
        mock_run.return_value = ("https://github.com/user/repo.git", 0)
        url = get_git_remote_url("/path/to/repo")
        assert url == "https://github.com/user/repo.git"

    @patch('repoindex.utils.run_command')
    def test_returns_none_on_empty_result(self, mock_run):
        """Returns None when git command returns empty."""
        mock_run.return_value = ("", 0)
        url = get_git_remote_url("/path/to/repo")
        assert url is None

    @patch('repoindex.utils.run_command')
    def test_returns_none_on_exception(self, mock_run):
        """Returns None when git command raises exception."""
        mock_run.side_effect = Exception("Git error")
        url = get_git_remote_url("/path/to/repo")
        assert url is None

    @patch('repoindex.utils.run_command')
    def test_custom_remote_name(self, mock_run):
        """Works with custom remote name."""
        mock_run.return_value = ("https://github.com/upstream/repo.git", 0)
        url = get_git_remote_url("/path/to/repo", remote_name="upstream")
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "upstream" in call_args[0][0]


# ============================================================================
# Tests for get_license_info
# ============================================================================

from repoindex.utils import get_license_info


class TestGetLicenseInfo:
    """Tests for get_license_info function."""

    def test_mit_license(self, fs):
        """Detects MIT license."""
        fs.create_file("/repo/LICENSE", contents="MIT License\n\nCopyright (c) 2024")
        result = get_license_info("/repo")
        assert result == "MIT"

    def test_apache_license(self, fs):
        """Detects Apache license."""
        fs.create_file("/repo/LICENSE", contents="Apache License\nVersion 2.0")
        result = get_license_info("/repo")
        assert result == "Apache-2.0"

    def test_gpl3_license(self, fs):
        """Detects GPL-3.0 license."""
        fs.create_file("/repo/LICENSE", contents="GNU GENERAL PUBLIC LICENSE\nVersion 3")
        result = get_license_info("/repo")
        assert result == "GPL-3.0"

    def test_gpl2_license(self, fs):
        """Detects GPL-2.0 license."""
        fs.create_file("/repo/LICENSE", contents="GNU GENERAL PUBLIC LICENSE\nVersion 2")
        result = get_license_info("/repo")
        assert result == "GPL-2.0"

    def test_bsd_license(self, fs):
        """Detects BSD license."""
        fs.create_file("/repo/LICENSE", contents="BSD 3-Clause License")
        result = get_license_info("/repo")
        assert result == "BSD"

    def test_other_license(self, fs):
        """Returns Other for unrecognized license."""
        fs.create_file("/repo/LICENSE", contents="Some custom license text")
        result = get_license_info("/repo")
        assert result == "Other"

    def test_no_license_file(self, fs):
        """Returns None when no license file exists."""
        fs.create_dir("/repo")
        result = get_license_info("/repo")
        assert result == "None"

    def test_license_txt_extension(self, fs):
        """Detects license in LICENSE.txt file."""
        fs.create_file("/repo/LICENSE.txt", contents="MIT License")
        result = get_license_info("/repo")
        assert result == "MIT"

    def test_licence_spelling(self, fs):
        """Detects license in LICENCE file (British spelling)."""
        fs.create_file("/repo/LICENCE", contents="MIT License")
        result = get_license_info("/repo")
        assert result == "MIT"


# ============================================================================
# Tests for find_git_repos_from_config
# ============================================================================

from repoindex.utils import find_git_repos_from_config


class TestFindGitReposFromConfig:
    """Tests for find_git_repos_from_config function."""

    def test_empty_config(self):
        """Returns empty list for empty config."""
        result = find_git_repos_from_config([])
        assert result == []

    def test_none_config(self):
        """Returns empty list for None config."""
        result = find_git_repos_from_config(None)
        assert result == []

    def test_simple_directory(self, fs):
        """Finds repos in simple directory path."""
        fs.create_dir("/home/user/projects/repo1/.git")
        fs.create_dir("/home/user/projects/repo2/.git")
        result = find_git_repos_from_config(["/home/user/projects"])
        assert len(result) == 2
        assert "/home/user/projects/repo1" in result
        assert "/home/user/projects/repo2" in result

    def test_recursive_pattern(self, fs):
        """Finds repos with ** recursive pattern."""
        fs.create_dir("/home/user/projects/repo1/.git")
        fs.create_dir("/home/user/projects/nested/repo2/.git")
        result = find_git_repos_from_config(["/home/user/projects/**"])
        assert len(result) == 2
        assert "/home/user/projects/repo1" in result
        assert "/home/user/projects/nested/repo2" in result

    def test_glob_pattern(self, fs):
        """Finds repos with glob pattern."""
        fs.create_dir("/home/user/proj-a/repo/.git")
        fs.create_dir("/home/user/proj-b/repo/.git")
        fs.create_dir("/home/user/other/repo/.git")
        result = find_git_repos_from_config(["/home/user/proj-*"])
        # proj-a and proj-b match, other doesn't
        assert len(result) == 2

    def test_nonexistent_directory(self, fs, caplog):
        """Warns about nonexistent directory."""
        fs.create_dir("/home/user")
        result = find_git_repos_from_config(["/home/user/nonexistent"])
        assert result == []


# ============================================================================
# Tests for detect_github_pages_locally
# ============================================================================

from repoindex.utils import detect_github_pages_locally


class TestDetectGithubPagesLocally:
    """Tests for detect_github_pages_locally function."""

    @patch('repoindex.utils.run_command')
    def test_gh_pages_branch(self, mock_run, fs):
        """Detects gh-pages branch."""
        fs.create_dir("/repo/.git")
        mock_run.return_value = ("origin/gh-pages\norigin/main", 0)
        result = detect_github_pages_locally("/repo")
        assert result is not None
        assert result['has_gh_pages_branch'] is True
        assert result['likely_enabled'] is True

    def test_jekyll_config(self, fs):
        """Detects Jekyll config file."""
        fs.create_dir("/repo/.git")
        fs.create_file("/repo/_config.yml", contents="title: My Site")
        with patch('repoindex.utils.run_command', return_value=("", 0)):
            result = detect_github_pages_locally("/repo")
        assert result is not None
        assert result['has_jekyll_config'] is True
        assert result['likely_enabled'] is True

    def test_docs_folder_with_index(self, fs):
        """Docs folder alone doesn't enable Pages without other indicators."""
        fs.create_dir("/repo/.git")
        fs.create_file("/repo/docs/index.md", contents="# Docs")
        with patch('repoindex.utils.run_command', return_value=("", 0)):
            result = detect_github_pages_locally("/repo")
        # docs folder alone doesn't set likely_enabled (needs gh-pages, workflow, jekyll, or cname)
        assert result is None

    def test_cname_file(self, fs):
        """Detects CNAME file for custom domain."""
        fs.create_dir("/repo/.git")
        fs.create_file("/repo/CNAME", contents="example.com")
        with patch('repoindex.utils.run_command', return_value=("", 0)):
            result = detect_github_pages_locally("/repo")
        assert result is not None
        assert result['has_cname'] is True
        assert result['likely_enabled'] is True

    def test_pages_workflow(self, fs):
        """Detects GitHub Actions Pages workflow."""
        fs.create_dir("/repo/.git")
        fs.create_file("/repo/.github/workflows/pages.yml",
                      contents="name: Deploy Pages\njobs:\n  deploy:")
        with patch('repoindex.utils.run_command', return_value=("", 0)):
            result = detect_github_pages_locally("/repo")
        assert result is not None
        assert result['has_pages_workflow'] is True

    def test_no_pages_indicators(self, fs):
        """Returns None when no Pages indicators found."""
        fs.create_dir("/repo/.git")
        with patch('repoindex.utils.run_command', return_value=("origin/main", 0)):
            result = detect_github_pages_locally("/repo")
        assert result is None


# ============================================================================
# Tests for get_github_repo_info
# ============================================================================

from repoindex.utils import get_github_repo_info


class TestGetGithubRepoInfo:
    """Tests for get_github_repo_info function."""

    @patch('repoindex.utils.run_command')
    def test_returns_repo_info(self, mock_run):
        """Returns parsed repo info on success."""
        mock_run.return_value = ('{"name": "repo", "full_name": "user/repo", "stars": 42}', 0)
        result = get_github_repo_info("user", "repo")
        assert result is not None
        assert result['name'] == "repo"
        assert result['stars'] == 42

    @patch('repoindex.utils.run_command')
    def test_returns_none_on_empty(self, mock_run):
        """Returns None when command returns empty."""
        mock_run.return_value = ("", 0)
        result = get_github_repo_info("user", "repo")
        assert result is None

    @patch('repoindex.utils.run_command')
    def test_returns_none_on_exception(self, mock_run):
        """Returns None when exception occurs."""
        mock_run.side_effect = Exception("API error")
        result = get_github_repo_info("user", "repo")
        assert result is None

    @patch('repoindex.utils.run_command')
    def test_returns_none_on_invalid_json(self, mock_run):
        """Returns None on invalid JSON response."""
        mock_run.return_value = ("not json", 0)
        result = get_github_repo_info("user", "repo")
        assert result is None


# ============================================================================
# Additional run_command tests
# ============================================================================

class TestRunCommandAdvanced:
    """Additional tests for run_command edge cases."""

    def test_list_command_format(self):
        """Test run_command with list command format."""
        output, returncode = run_command(["echo", "test"], capture_output=True)
        assert output.strip() == "test"
        assert returncode == 0

    def test_check_false_doesnt_raise(self):
        """Test check=False doesn't raise on failure."""
        # Should not raise
        output, returncode = run_command("exit 1", capture_output=True, check=False)
        assert returncode == 1

    def test_check_true_raises(self):
        """Test check=True raises CalledProcessError."""
        import subprocess
        with pytest.raises(subprocess.CalledProcessError):
            run_command("exit 1", check=True)

    def test_dry_run_no_capture(self):
        """Test dry_run with capture_output=False."""
        output, returncode = run_command("rm -rf /", dry_run=True, capture_output=False)
        assert output is None
        assert returncode == 0
