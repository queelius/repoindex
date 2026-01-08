"""
Tests for the 'repoindex config init' command.

Tests focus on:
- detect_default_repo_dir() function behavior
- Command-line options (-d, -y, --recursive/--no-recursive)
- Configuration file creation
- Edge cases (no repos found, invalid directories)
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestDetectDefaultRepoDir(unittest.TestCase):
    """Tests for the detect_default_repo_dir function."""

    def setUp(self):
        """Set up test environment with temp directory as HOME."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_home = os.environ.get('HOME')
        os.environ['HOME'] = self.temp_dir

    def tearDown(self):
        """Clean up test environment."""
        if self.original_home:
            os.environ['HOME'] = self.original_home
        else:
            del os.environ['HOME']
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_git_repo(self, path: Path) -> Path:
        """Create a minimal git repo at the given path."""
        path.mkdir(parents=True, exist_ok=True)
        git_dir = path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text('[core]\nrepositoryformatversion = 0\n')
        return path

    def test_detect_default_repo_dir_finds_github_directory(self):
        """Test that ~/github is detected when it exists with repos."""
        from repoindex.commands.config import detect_default_repo_dir

        # Given: ~/github directory with a git repo
        github_dir = Path(self.temp_dir) / "github"
        self._create_git_repo(github_dir / "my-repo")

        # When: We detect the default repo dir
        result = detect_default_repo_dir()

        # Then: It should find the github directory
        self.assertEqual(result, str(github_dir))

    def test_detect_default_repo_dir_prefers_github_over_repos(self):
        """Test that ~/github is preferred over ~/repos."""
        from repoindex.commands.config import detect_default_repo_dir

        # Given: Both ~/github and ~/repos exist with repos
        github_dir = Path(self.temp_dir) / "github"
        repos_dir = Path(self.temp_dir) / "repos"
        self._create_git_repo(github_dir / "repo1")
        self._create_git_repo(repos_dir / "repo2")

        # When: We detect the default repo dir
        result = detect_default_repo_dir()

        # Then: It should prefer ~/github
        self.assertEqual(result, str(github_dir))

    def test_detect_default_repo_dir_finds_repos_directory(self):
        """Test that ~/repos is detected when github doesn't exist."""
        from repoindex.commands.config import detect_default_repo_dir

        # Given: Only ~/repos exists with a git repo
        repos_dir = Path(self.temp_dir) / "repos"
        self._create_git_repo(repos_dir / "my-repo")

        # When: We detect the default repo dir
        result = detect_default_repo_dir()

        # Then: It should find the repos directory
        self.assertEqual(result, str(repos_dir))

    def test_detect_default_repo_dir_finds_projects_directory(self):
        """Test that ~/projects is detected when github/repos don't exist."""
        from repoindex.commands.config import detect_default_repo_dir

        # Given: Only ~/projects exists with a git repo
        projects_dir = Path(self.temp_dir) / "projects"
        self._create_git_repo(projects_dir / "my-project")

        # When: We detect the default repo dir
        result = detect_default_repo_dir()

        # Then: It should find the projects directory
        self.assertEqual(result, str(projects_dir))

    def test_detect_default_repo_dir_finds_src_directory(self):
        """Test that ~/src is detected when higher priority dirs don't exist."""
        from repoindex.commands.config import detect_default_repo_dir

        # Given: Only ~/src exists with a git repo
        src_dir = Path(self.temp_dir) / "src"
        self._create_git_repo(src_dir / "my-code")

        # When: We detect the default repo dir
        result = detect_default_repo_dir()

        # Then: It should find the src directory
        self.assertEqual(result, str(src_dir))

    def test_detect_default_repo_dir_finds_code_directory(self):
        """Test that ~/code is detected when higher priority dirs don't exist."""
        from repoindex.commands.config import detect_default_repo_dir

        # Given: Only ~/code exists with a git repo
        code_dir = Path(self.temp_dir) / "code"
        self._create_git_repo(code_dir / "project")

        # When: We detect the default repo dir
        result = detect_default_repo_dir()

        # Then: It should find the code directory
        self.assertEqual(result, str(code_dir))

    def test_detect_default_repo_dir_skips_empty_directories(self):
        """Test that empty directories without git repos are skipped."""
        from repoindex.commands.config import detect_default_repo_dir

        # Given: ~/github exists but has no git repos, ~/repos has repos
        github_dir = Path(self.temp_dir) / "github"
        github_dir.mkdir()  # Empty directory
        repos_dir = Path(self.temp_dir) / "repos"
        self._create_git_repo(repos_dir / "my-repo")

        # When: We detect the default repo dir
        result = detect_default_repo_dir()

        # Then: It should skip empty github and find repos
        self.assertEqual(result, str(repos_dir))

    def test_detect_default_repo_dir_fallback_to_home(self):
        """Test that home directory is returned when no candidates exist."""
        from repoindex.commands.config import detect_default_repo_dir

        # Given: No standard directories exist
        # (temp_dir is already empty)

        # When: We detect the default repo dir
        result = detect_default_repo_dir()

        # Then: It should fallback to home directory
        self.assertEqual(result, self.temp_dir)


class TestConfigInitCLI(unittest.TestCase):
    """Tests for the config init command CLI behavior."""

    @classmethod
    def setUpClass(cls):
        """Get the project root for PYTHONPATH setup."""
        cls.project_root = Path(__file__).parent.parent.absolute()

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.repos_dir = Path(self.temp_dir) / "repos"
        self.repos_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_git_repo(self, name: str) -> Path:
        """Create a minimal git repo in the repos directory."""
        repo_path = self.repos_dir / name
        repo_path.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True)
        (repo_path / "README.md").write_text(f"# {name}\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, capture_output=True)
        return repo_path

    def _run_config_init(self, *args) -> subprocess.CompletedProcess:
        """Run repoindex config init with HOME pointing to temp directory."""
        cmd = ["python", "-m", "repoindex.cli"] + list(args)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.project_root) + os.pathsep + env.get("PYTHONPATH", "")
        env["HOME"] = str(self.temp_dir)
        env.pop("REPOINDEX_CONFIG", None)

        return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=self.temp_dir)

    def test_config_init_with_recursive_flag(self):
        """Test config init with default recursive mode creates ** pattern."""
        # Given: A repos directory with a git repo
        self._create_git_repo("my-project")

        # When: We run config init with -y -d (recursive is default)
        result = self._run_config_init("config", "init", "-y", "-d", str(self.repos_dir))

        # Then: Config should have ** pattern
        self.assertEqual(result.returncode, 0)
        config_path = Path(self.temp_dir) / ".repoindex" / "config.yaml"
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Should end with /**
        self.assertTrue(any("**" in d for d in config["repository_directories"]))

    def test_config_init_with_no_recursive_flag(self):
        """Test config init with --no-recursive creates path without ** pattern."""
        # Given: A repos directory with a git repo
        self._create_git_repo("my-project")

        # When: We run config init with --no-recursive
        result = self._run_config_init("config", "init", "-y", "-d", str(self.repos_dir), "--no-recursive")

        # Then: Config should NOT have ** pattern
        self.assertEqual(result.returncode, 0)
        config_path = Path(self.temp_dir) / ".repoindex" / "config.yaml"
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Should NOT end with /**
        self.assertFalse(any("**" in d for d in config["repository_directories"]))

    def test_config_init_uses_tilde_for_home_paths(self):
        """Test that config init replaces home directory with ~ in config."""
        # Given: A repos directory inside home
        self._create_git_repo("my-project")

        # When: We run config init
        result = self._run_config_init("config", "init", "-y", "-d", str(self.repos_dir))

        # Then: Config should use ~ prefix
        self.assertEqual(result.returncode, 0)
        config_path = Path(self.temp_dir) / ".repoindex" / "config.yaml"
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Should start with ~
        self.assertTrue(any(d.startswith("~") for d in config["repository_directories"]))

    def test_config_init_with_invalid_directory(self):
        """Test config init handles non-existent directory gracefully."""
        # Given: A non-existent directory
        invalid_dir = Path(self.temp_dir) / "nonexistent"

        # When: We run config init with that directory
        result = self._run_config_init("config", "init", "-y", "-d", str(invalid_dir))

        # Then: Should fail or show error message about the directory
        # Click Path validation should reject non-existent paths
        self.assertNotEqual(result.returncode, 0)

    def test_config_init_creates_config_directory(self):
        """Test that config init creates ~/.repoindex directory if it doesn't exist."""
        # Given: No .repoindex directory exists
        self._create_git_repo("my-project")

        # When: We run config init
        result = self._run_config_init("config", "init", "-y", "-d", str(self.repos_dir))

        # Then: Directory and config should exist
        self.assertEqual(result.returncode, 0)
        config_dir = Path(self.temp_dir) / ".repoindex"
        self.assertTrue(config_dir.exists())
        self.assertTrue((config_dir / "config.yaml").exists())

    def test_config_init_output_shows_next_steps(self):
        """Test that config init output includes helpful next steps."""
        # Given: A repos directory with a git repo
        self._create_git_repo("my-project")

        # When: We run config init
        result = self._run_config_init("config", "init", "-y", "-d", str(self.repos_dir))

        # Then: Output should include next steps
        self.assertEqual(result.returncode, 0)
        self.assertIn("Next steps", result.stdout)
        self.assertIn("repoindex status", result.stdout)


if __name__ == "__main__":
    unittest.main()
