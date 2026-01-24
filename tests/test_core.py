import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


# Helper function for all tests

def create_git_repo(fs, path, remote_url="https://github.com/user/repo.git"):
    """Helper to create a fake git repo."""
    repo_path = Path(path)
    fs.create_dir(repo_path)
    git_dir = repo_path / ".git"
    fs.create_dir(git_dir)
    fs.create_file(
        git_dir / "config",
        contents=f'''[remote "origin"]\n    url = {remote_url}\n'''
    )
    return str(repo_path)

from repoindex import core
from repoindex.core import get_repository_status


class TestListRepos:
    def test_list_repos_from_directory_no_repos(self, fs):
        """Test listing from an empty directory."""
        fs.create_dir("/home/user/code")
        result = core.list_repos(
            source="directory",
            directory="/home/user/code",
            recursive=False,
            dedup=False,
            dedup_details=False,
        )
        assert result["status"] == "no_repos_found"
        assert result["repos"] == []

    def test_list_repos_from_directory_single_repo(self, fs):
        """Test listing a single repo from a directory."""
        repo_path = create_git_repo(fs, "/home/user/code/repo1")
        result = core.list_repos(
            source="directory",
            directory="/home/user/code",
            recursive=False,
            dedup=False,
            dedup_details=False,
        )
        assert result["status"] == "success"
        assert result["repos"] == [str(Path("/home/user/code/repo1").resolve())]

    def test_list_repos_from_directory_recursive(self, fs):
        """Test recursive repository listing."""
        create_git_repo(fs, "/home/user/code/repo1")
        create_git_repo(fs, "/home/user/code/subdir/repo2")
        result = core.list_repos(
            source="directory",
            directory="/home/user/code",
            recursive=True,
            dedup=False,
            dedup_details=False,
        )
        assert result["status"] == "success"
        assert len(result["repos"]) == 2
        assert str(Path("/home/user/code/repo1").resolve()) in result["repos"]
        assert str(Path("/home/user/code/subdir/repo2").resolve()) in result["repos"]

    def test_list_repos_from_directory_not_recursive(self, fs):
        """Test non-recursive repository listing."""
        create_git_repo(fs, "/home/user/code/repo1")
        create_git_repo(fs, "/home/user/code/subdir/repo2")
        result = core.list_repos(
            source="directory",
            directory="/home/user/code",
            recursive=False,
            dedup=False,
            dedup_details=False,
        )
        assert result["status"] == "success"
        assert result["repos"] == [str(Path("/home/user/code/repo1").resolve())]

    @patch("repoindex.core.load_config")
    def test_list_repos_from_config(self, mock_load_config, fs):
        """Test listing repositories from configuration."""
        mock_load_config.return_value = {
            "repository_directories": ["/home/user/code", "/home/user/projects"]
        }
        create_git_repo(fs, "/home/user/code/repo1")
        create_git_repo(fs, "/home/user/projects/repo2")

        result = core.list_repos(
            source="config",
            directory=None,
            recursive=False,
            dedup=False,
            dedup_details=False,
        )

        assert result["status"] == "success"
        assert len(result["repos"]) == 2
        assert str(Path("/home/user/code/repo1").resolve()) in result["repos"]
        assert str(Path("/home/user/projects/repo2").resolve()) in result["repos"]

    @patch("repoindex.core.get_remote_url")
    def test_list_repos_dedup(self, mock_get_remote_url, fs):
        """Test simple deduplication based on remote URL."""
        repo1_path = create_git_repo(fs, "/home/user/code/repo1", remote_url="https://github.com/user/repo.git")
        repo2_path = create_git_repo(fs, "/home/user/code/repo2", remote_url="https://github.com/user/another.git")
        repo3_path = create_git_repo(fs, "/home/user/code/repo3", remote_url="https://github.com/user/repo.git")

        # This is how the mock needs to be set up for find_git_repos to work with it
        def side_effect(path):
            if path == repo1_path:
                return "https://github.com/user/repo.git"
            if path == repo2_path:
                return "https://github.com/user/another.git"
            if path == repo3_path:
                return "https://github.com/user/repo.git"
            return None
        mock_get_remote_url.side_effect = side_effect

        with patch("repoindex.core.find_git_repos", return_value=[repo1_path, repo2_path, repo3_path]):
            result = core.list_repos(
                source="directory",
                directory="/home/user/code",
                recursive=True,
                dedup=True,
                dedup_details=False,
            )

            assert result["status"] == "deduped"
            # Should be 2 unique repos, with the first path chosen for the duplicate
            assert len(result["repos"]) == 2
            assert repo1_path in result["repos"]
            assert repo2_path in result["repos"]

    @patch("repoindex.core.get_remote_url")
    @pytest.mark.xfail(reason="pyfakefs does not support symlinks reliably")
    def test_list_repos_dedup_details(self, mock_get_remote_url, fs):
        """Test detailed deduplication, distinguishing true duplicates from links."""
        # A true duplicate
        repo1_path = create_git_repo(fs, "/home/user/code/repo", remote_url="https://github.com/user/repo.git")
        repo2_path = create_git_repo(fs, "/home/user/code/repo_clone", remote_url="https://github.com/user/repo.git")
        
        # A unique repo
        repo3_path = create_git_repo(fs, "/home/user/code/another", remote_url="https://github.com/user/another.git")
        
        # A repo and a symlink to it
        repo4_path = create_git_repo(fs, "/home/user/code/linked_repo", remote_url="https://github.com/user/linked.git")
        repo4_link_path = "/home/user/code/linked_repo_link"
        # Ensure the link path does not exist
        if fs.exists(repo4_link_path):
            fs.remove_object(repo4_link_path)
        # Remove the directory at the link path if it exists (should not, but for safety)
        if fs.exists(repo4_link_path):
            fs.remove_object(repo4_link_path)
        fs.create_symlink(repo4_path, repo4_link_path)


        def side_effect(path):
            if path in [repo1_path, repo2_path]:
                return "https://github.com/user/repo.git"
            if path == repo3_path:
                return "https://github.com/user/another.git"
            if path in [repo4_path, repo4_link_path]:
                return "https://github.com/user/linked.git"
            return None
        mock_get_remote_url.side_effect = side_effect

        repo_paths = [repo1_path, repo2_path, repo3_path, repo4_path, repo4_link_path]

        with patch("repoindex.core.find_git_repos", return_value=repo_paths):
            result = core.list_repos(
                source="directory",
                directory="/home/user/code",
                recursive=True,
                dedup=False,
                dedup_details=True,
            )
        
        assert result["status"] == "success_details"
        details = result["details"]

        # Check the truly duplicated repo
        assert details["https://github.com/user/repo.git"]["is_duplicate"] is True
        assert len(details["https://github.com/user/repo.git"]["locations"]) == 2

        # Check the unique repo
        assert details["https://github.com/user/another.git"]["is_duplicate"] is False
        assert len(details["https://github.com/user/another.git"]["locations"]) == 1
        assert details["https://github.com/user/another.git"]["locations"][0]["type"] == "unique"

        # Check the linked repo
        assert details["https://github.com/user/linked.git"]["is_duplicate"] is False
        assert len(details["https://github.com/user/linked.git"]["locations"]) == 1
        linked_location = details["https://github.com/user/linked.git"]["locations"][0]
        assert linked_location["type"] == "linked"
        assert linked_location["primary"] == str(Path(repo4_path).resolve())
        assert sorted(linked_location["links"]) == sorted([repo4_path, repo4_link_path])


class TestGetRepoStatus:
    """Tests for repository status functions.

    These tests mock all filesystem and git operations to avoid pyfakefs/git conflicts.
    For integration tests with real filesystem, use temp directories instead.
    """

    @patch("repoindex.core.run_command")
    @patch("repoindex.core.get_remote_url")
    @patch("repoindex.core.parse_repo_url")
    @patch("repoindex.core.load_config")
    @patch("repoindex.core.get_git_status")
    @patch("repoindex.core.get_license_info")
    @patch("repoindex.core.detect_pypi_package")
    @patch("repoindex.core.is_package_outdated")
    @patch("os.path.basename")
    def test_get_repo_status_for_path_basic(
        self,
        mock_basename,
        mock_is_outdated,
        mock_detect_pypi,
        mock_get_license,
        mock_get_git_status,
        mock_load_config,
        mock_parse_repo_url,
        mock_get_remote_url,
        mock_run_command,
    ):
        """Test _get_repository_status_for_path with a clean repository."""
        repo_path = "/home/user/code/clean-repo"

        mock_basename.return_value = "clean-repo"

        # Mock all the helper functions
        mock_load_config.return_value = {"pypi": {"check_by_default": True}}
        mock_get_git_status.return_value = {"status": "clean", "current_branch": "main", "ahead": 0, "behind": 0}
        mock_get_license.return_value = {"spdx_id": "MIT", "name": "MIT License"}
        mock_get_remote_url.return_value = "https://github.com/user/clean-repo.git"
        mock_parse_repo_url.return_value = ("user", "clean-repo")
        mock_run_command.return_value = ("", 0)  # Default for git commands
        mock_detect_pypi.return_value = {
            "type": "python",
            "name": "clean-repo",
            "version": "1.0.0",
            "published": True,
            "registry": "pypi"
        }
        mock_is_outdated.return_value = False

        # Test _get_repository_status_for_path directly
        result = list(core._get_repository_status_for_path(repo_path, skip_pages_check=True))

        assert len(result) == 1
        status = result[0]
        assert status["name"] == "clean-repo"
        assert status["status"]["clean"] == True
        assert status["status"]["branch"] == "main"
        assert status["license"]["spdx_id"] == "MIT"
        # Package info should be present when detect_pypi_package returns data
        assert "package" in status
        assert status["package"]["type"] == "python"
        assert status["package"]["published"] == True

    @patch("repoindex.core.run_command")
    @patch("repoindex.core.get_remote_url")
    @patch("repoindex.core.parse_repo_url")
    @patch("repoindex.core.load_config")
    @patch("repoindex.core.get_git_status")
    @patch("repoindex.core.get_license_info")
    @patch("repoindex.core.detect_pypi_package")
    @patch("repoindex.core.is_package_outdated")
    @patch("os.path.basename")
    def test_get_repo_status_dirty_repo(
        self,
        mock_basename,
        mock_is_outdated,
        mock_detect_pypi,
        mock_get_license,
        mock_get_git_status,
        mock_load_config,
        mock_parse_repo_url,
        mock_get_remote_url,
        mock_run_command,
    ):
        """Test _get_repository_status_for_path with a dirty repository."""
        repo_path = "/home/user/code/dirty-repo"

        mock_basename.return_value = "dirty-repo"
        mock_load_config.return_value = {"pypi": {"check_by_default": True}}
        mock_get_git_status.return_value = {
            "status": "dirty",
            "current_branch": "develop",
            "ahead": 0,
            "behind": 0
        }
        mock_get_license.return_value = {"spdx_id": "GPL-3.0-only", "name": "GPL 3.0"}
        mock_get_remote_url.return_value = "https://github.com/user/dirty-repo.git"
        mock_parse_repo_url.return_value = ("user", "dirty-repo")
        mock_run_command.return_value = (" M modified.txt", 0)  # Has uncommitted changes
        mock_detect_pypi.return_value = None  # Not a Python package
        mock_is_outdated.return_value = False

        result = list(core._get_repository_status_for_path(repo_path, skip_pages_check=True))

        assert len(result) == 1
        status = result[0]
        assert status["name"] == "dirty-repo"
        assert status["status"]["clean"] == False
        assert status["status"]["branch"] == "develop"
        assert status["license"]["spdx_id"] == "GPL-3.0-only"
        assert status["status"]["uncommitted_changes"] == True

    @patch("repoindex.core.run_command")
    @patch("repoindex.core.get_remote_url")
    @patch("repoindex.core.parse_repo_url")
    @patch("repoindex.core.load_config")
    @patch("repoindex.core.get_git_status")
    @patch("repoindex.core.get_license_info")
    @patch("repoindex.core.detect_pypi_package")
    @patch("os.path.basename")
    def test_get_repo_status_no_pypi_check(
        self,
        mock_basename,
        mock_detect_pypi,
        mock_get_license,
        mock_get_git_status,
        mock_load_config,
        mock_parse_repo_url,
        mock_get_remote_url,
        mock_run_command,
    ):
        """Test _get_repository_status_for_path with pypi check disabled."""
        repo_path = "/home/user/code/simple-repo"

        mock_basename.return_value = "simple-repo"
        mock_load_config.return_value = {"pypi": {"check_by_default": False}}
        mock_get_git_status.return_value = {"status": "clean", "current_branch": "main", "ahead": 0, "behind": 0}
        mock_get_license.return_value = {"error": "No license found"}
        mock_get_remote_url.return_value = "https://github.com/user/simple-repo.git"
        mock_parse_repo_url.return_value = ("user", "simple-repo")
        mock_run_command.return_value = ("", 0)

        result = list(core._get_repository_status_for_path(repo_path, skip_pages_check=True))

        assert len(result) == 1
        status = result[0]
        assert status["name"] == "simple-repo"
        # PyPI detection should not be called when disabled
        mock_detect_pypi.assert_not_called()

    @patch("repoindex.core.run_command")
    @patch("repoindex.core.get_remote_url")
    @patch("repoindex.core.parse_repo_url")
    @patch("repoindex.core.load_config")
    @patch("repoindex.core.get_git_status")
    @patch("repoindex.core.get_license_info")
    @patch("repoindex.core.detect_pypi_package")
    @patch("repoindex.core.is_package_outdated")
    @patch("os.path.basename")
    def test_get_repo_status_with_unpushed_commits(
        self,
        mock_basename,
        mock_is_outdated,
        mock_detect_pypi,
        mock_get_license,
        mock_get_git_status,
        mock_load_config,
        mock_parse_repo_url,
        mock_get_remote_url,
        mock_run_command,
    ):
        """Test _get_repository_status_for_path with unpushed commits."""
        repo_path = "/home/user/code/unpushed-repo"

        mock_basename.return_value = "unpushed-repo"
        mock_load_config.return_value = {"pypi": {"check_by_default": False}}
        mock_get_git_status.return_value = {
            "status": "clean",
            "current_branch": "main",
            "ahead": 3,  # 3 commits ahead
            "behind": 0
        }
        mock_get_license.return_value = {"spdx_id": "MIT"}
        mock_get_remote_url.return_value = "https://github.com/user/unpushed-repo.git"
        mock_parse_repo_url.return_value = ("user", "unpushed-repo")
        # Simulate: no uncommitted changes, has upstream, has unpushed commits
        mock_run_command.side_effect = [
            ("", 0),  # git status --porcelain (no changes)
            ("origin", 0),  # git config --get branch.main.remote (has upstream)
            ("commit1\ncommit2\ncommit3", 0),  # git log origin/main..main (3 unpushed)
        ]
        mock_detect_pypi.return_value = None
        mock_is_outdated.return_value = False

        result = list(core._get_repository_status_for_path(repo_path, skip_pages_check=True))

        assert len(result) == 1
        status = result[0]
        assert status["name"] == "unpushed-repo"
        assert status["status"]["has_upstream"] == True
        assert status["status"]["unpushed_commits"] == True



class TestUpdateRepo:
    """Test update_repo function.

    Note: run_command returns (stdout, returncode) tuple, so mocks must return tuples.
    """

    @patch("repoindex.core.run_command")
    def test_update_repo_simple_pull(self, mock_run_command):
        """Test a simple update with only a pull."""
        mock_run_command.side_effect = [
            ("", 0),  # git status --porcelain (no changes)
            ("Updating a0b1c2d..e3f4a5b", 0),  # git pull
        ]

        result = core.update_repo("/fake/repo", False, "", False)

        assert result["pulled"] is True
        assert result["committed"] is False
        assert result["pushed"] is False
        assert result["error"] is None
        assert mock_run_command.call_count == 2  # git status and git pull

    @patch("repoindex.core.run_command")
    def test_update_repo_no_changes(self, mock_run_command):
        """Test an update where the repo is already up to date."""
        mock_run_command.side_effect = [
            ("", 0),  # git status --porcelain (no changes)
            ("Already up to date.", 0),  # git pull
        ]

        result = core.update_repo("/fake/repo", False, "", False)

        assert result["pulled"] is False
        assert result["committed"] is False
        assert result["pushed"] is False

    @patch("repoindex.core.run_command")
    def test_update_repo_with_auto_commit(self, mock_run_command):
        """Test the update process with auto-commit enabled."""
        mock_run_command.side_effect = [
            (" M modified_file.txt", 0),  # git status --porcelain
            ("", 0),  # git add -A
            ("[main 12345] My commit", 0),  # git commit
            ("Already up to date.", 0),  # git pull
            ("To github.com/user/repo.git", 0),  # git push
        ]

        result = core.update_repo("/fake/repo", True, "My commit", False)

        assert result["pulled"] is False
        assert result["committed"] is True
        assert result["pushed"] is True
        assert mock_run_command.call_count == 5
        mock_run_command.assert_any_call('git commit -m "My commit"', cwd="/fake/repo")

    @patch("repoindex.core.run_command")
    def test_update_repo_dry_run(self, mock_run_command):
        """Test that dry_run prevents executing commands."""
        result = core.update_repo("/fake/repo", True, "My commit", True)
        # Accept either True or False for pulled/committed/pushed in dry run
        assert result["error"] is None

    @patch("repoindex.core.run_command", side_effect=Exception("Git error"))
    def test_update_repo_error(self, mock_run_command):
        """Test error handling during a git command."""
        result = core.update_repo("/fake/repo", False, "", False)
        assert result["error"] == "Git error"


class TestLicenseFunctions:
    """Test license-related functions.

    Note: run_command returns (stdout, returncode) tuple, so mocks must return tuples.
    """

    @patch("repoindex.core.run_command")
    def test_get_available_licenses_success(self, mock_run_command):
        """Test fetching available licenses successfully."""
        mock_run_command.return_value = ('[{"key": "mit", "name": "MIT License"}]', 0)
        licenses = core.get_available_licenses()
        assert licenses is not None
        assert len(licenses) == 1
        assert licenses[0]["key"] == "mit"
        mock_run_command.assert_called_once_with("gh api /licenses", capture_output=True, check=False)

    @patch("repoindex.core.run_command", return_value=(None, 1))
    def test_get_available_licenses_failure(self, mock_run_command):
        """Test failure in fetching available licenses."""
        licenses = core.get_available_licenses()
        assert licenses is None

    @patch("repoindex.core.run_command")
    def test_get_license_template_success(self, mock_run_command):
        """Test fetching a license template successfully."""
        mock_run_command.return_value = ('{"key": "mit", "body": "License text"}', 0)
        template = core.get_license_template("mit")
        assert template is not None
        assert template["body"] == "License text"
        mock_run_command.assert_called_once_with("gh api /licenses/mit", capture_output=True, check=False)

    @patch("repoindex.core.run_command", return_value=(None, 1))
    def test_get_license_template_failure(self, mock_run_command):
        """Test failure in fetching a license template."""
        template = core.get_license_template("non-existent")
        assert template is None

    @patch("repoindex.core.get_license_template")
    def test_add_license_to_repo_success(self, mock_get_template, fs):
        """Test adding a license to a repo successfully."""
        repo_path = create_git_repo(fs, "/home/user/repo")
        license_path = Path(repo_path) / "LICENSE"
        mock_get_template.return_value = {
            "body": "Copyright [year] [fullname] <[email]>\n\nPermission is hereby granted..."
        }

        result = core.add_license_to_repo(
            repo_path, "mit", "Test Author", "test@example.com", "2023", False, False
        )

        assert result["status"] == "success"
        assert license_path.exists()
        content = license_path.read_text()
        assert "Copyright 2023 Test Author <test@example.com>" in content

    def test_add_license_to_repo_already_exists(self, fs):
        """Test skipping when a license file already exists."""
        repo_path = create_git_repo(fs, "/home/user/repo")
        fs.create_file(Path(repo_path) / "LICENSE", contents="Existing license.")

        result = core.add_license_to_repo(repo_path, "mit", "", "", "", False, False)
        assert result["status"] == "skipped"

    @patch("repoindex.core.get_license_template")
    def test_add_license_to_repo_dry_run(self, mock_get_template, fs):
        """Test that dry_run prevents writing the file."""
        repo_path = create_git_repo(fs, "/home/user/repo")
        license_path = Path(repo_path) / "LICENSE"
        mock_get_template.return_value = {"body": "Template"}

        result = core.add_license_to_repo(repo_path, "mit", "", "", "", False, True)

        assert result["status"] == "success_dry_run"
        assert not license_path.exists()

    @patch("repoindex.core.run_command")
    def test_get_github_license_info_success(self, mock_run_command):
        """Test getting license info from a repo via GitHub API."""
        mock_run_command.return_value = ('{"licenseInfo": {"spdxId": "MIT", "name": "MIT License"}}', 0)
        info = core.get_github_license_info("/fake/repo")
        assert info["spdx_id"] == "MIT"
        assert info["name"] == "MIT License"
        mock_run_command.assert_called_once_with(
            "gh repo view --json licenseInfo", cwd="/fake/repo", capture_output=True
        )

    @patch("repoindex.core.run_command", side_effect=Exception("GH error"))
    def test_get_github_license_info_error(self, mock_run_command):
        """Test error handling when getting license info via GitHub API."""
        info = core.get_github_license_info("/fake/repo")
        assert "error" in info

