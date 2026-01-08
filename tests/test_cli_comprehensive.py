"""
Comprehensive CLI tests for repoindex using the --config option.

These tests use real temporary config files and git repositories
to test CLI commands end-to-end with the --config option.

Tests focus on observable behavior (command output, exit codes, file effects)
rather than internal implementation details.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


class CLITestBase(unittest.TestCase):
    """Base class for CLI tests with common setup/teardown."""

    @classmethod
    def setUpClass(cls):
        """Get the project root for PYTHONPATH setup."""
        cls.project_root = Path(__file__).parent.parent.absolute()

    def setUp(self):
        """Set up test environment with temp directories."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "config.yaml"  # Now YAML
        self.repos_dir = Path(self.temp_dir) / "repos"
        self.repos_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up temp directories."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_config(self, config: dict):
        """Write a YAML config file to the temp directory."""
        with open(self.config_path, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False)

    def create_git_repo(self, name: str, with_files: dict = None) -> Path:
        """
        Create a minimal git repository for testing.

        Args:
            name: Repository name/directory name
            with_files: Optional dict of {filename: content} to create

        Returns:
            Path to the created repository
        """
        repo_path = self.repos_dir / name
        repo_path.mkdir(parents=True)

        # Initialize as a real git repo
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            capture_output=True,
            check=True
        )

        # Configure git user for commits
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            capture_output=True
        )

        # Create default files
        readme = repo_path / "README.md"
        readme.write_text(f"# {name}\n\nTest repository.")

        # Create any additional files
        if with_files:
            for filename, content in with_files.items():
                file_path = repo_path / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content)

        # Make initial commit
        subprocess.run(
            ["git", "add", "."],
            cwd=repo_path,
            capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            capture_output=True
        )

        return repo_path

    def run_cli(self, *args, expect_success: bool = True) -> subprocess.CompletedProcess:
        """
        Run a repoindex CLI command with --config pointing to temp config.

        Args:
            *args: CLI arguments (without the 'repoindex' command)
            expect_success: If True, assert that returncode is 0

        Returns:
            CompletedProcess with stdout, stderr, returncode
        """
        cmd = ["python", "-m", "repoindex.cli", "--config", str(self.config_path)] + list(args)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.project_root) + os.pathsep + env.get("PYTHONPATH", "")
        # Prevent any interference from user's actual config
        env.pop("REPOINDEX_CONFIG", None)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=self.temp_dir
        )

        if expect_success and result.returncode != 0:
            # Provide helpful debug info on failure
            self.fail(
                f"Command failed with exit code {result.returncode}:\n"
                f"Command: {' '.join(cmd)}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )

        return result

    def run_cli_allow_failure(self, *args) -> subprocess.CompletedProcess:
        """Run CLI command that may fail (for testing error handling)."""
        return self.run_cli(*args, expect_success=False)

    def parse_jsonl(self, output: str) -> list:
        """Parse JSONL output into a list of dicts."""
        results = []
        for line in output.strip().split("\n"):
            if line.strip():
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # Skip non-JSON lines
        return results


class TestConfigOption(CLITestBase):
    """Test that the --config option works correctly."""

    def test_config_option_is_respected(self):
        """Test that --config option overrides default config location."""
        # Given: A config file with specific repository directories
        self.write_config({
            "repository_directories": [str(self.repos_dir) + "/**"],
            "github": {"token": ""},
            "registries": {"pypi": False, "cran": False},
            "cache": {"enabled": False},
            "repository_tags": {}
        })

        # When: We run 'config show' with --config
        result = self.run_cli("config", "show")

        # Then: The output should match our config file
        config = json.loads(result.stdout)
        self.assertEqual(config["repository_directories"], [str(self.repos_dir) + "/**"])

    def test_config_show_with_path_flag(self):
        """Test 'config show --path' returns the config file path."""
        self.write_config({
            "repository_directories": [],
            "repository_tags": {}
        })

        result = self.run_cli("config", "show", "--path")

        output = json.loads(result.stdout)
        self.assertIn("config_path", output)
        self.assertEqual(output["config_path"], str(self.config_path))


class TestInitCommand(CLITestBase):
    """Test the 'repoindex config init' command."""

    def run_init_cli(self, *args, expect_success: bool = True) -> subprocess.CompletedProcess:
        """
        Run repoindex config init without --config (since init creates config).

        Uses HOME env var to control where config is saved (~/.repoindex/config.yaml).
        """
        cmd = ["python", "-m", "repoindex.cli"] + list(args)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.project_root) + os.pathsep + env.get("PYTHONPATH", "")
        # Override HOME so config goes to our temp directory's .repoindex
        env["HOME"] = str(self.temp_dir)
        # Clear any existing REPOINDEX_CONFIG to ensure init uses default path
        env.pop("REPOINDEX_CONFIG", None)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=self.temp_dir
        )

        if expect_success and result.returncode != 0:
            self.fail(
                f"Command failed with exit code {result.returncode}:\n"
                f"Command: {' '.join(cmd)}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )

        return result

    def test_init_creates_config_with_directory(self):
        """Test config init with -d flag creates proper config."""
        # Given: An empty temp directory with a git repo
        repo = self.create_git_repo("test-project")

        # When: We run config init with -y -d pointing to our repos directory
        # Note: init creates config at ~/.repoindex/config.yaml (we override HOME)
        result = self.run_init_cli("config", "init", "-y", "-d", str(self.repos_dir))

        # Then: The command should succeed and mention creating config
        self.assertEqual(result.returncode, 0)
        self.assertIn("Configuration created", result.stdout)

        # Verify config file was created at the default location (now YAML)
        expected_config_path = Path(self.temp_dir) / ".repoindex" / "config.yaml"
        self.assertTrue(expected_config_path.exists())
        with open(expected_config_path) as f:
            created_config = yaml.safe_load(f)
        self.assertIn("repository_directories", created_config)

    def test_init_with_directory_creates_config(self):
        """Test config init creates config for specified directory."""
        # Given: An empty directory
        empty_dir = Path(self.temp_dir) / "empty"
        empty_dir.mkdir()

        # When: We run config init
        result = self.run_init_cli("config", "init", "-y", "-d", str(empty_dir))

        # Then: Should succeed and create config
        self.assertEqual(result.returncode, 0)
        self.assertIn("Configuration created", result.stdout)

        # Verify config file was created (now YAML)
        expected_config_path = Path(self.temp_dir) / ".repoindex" / "config.yaml"
        self.assertTrue(expected_config_path.exists())


class TestConfigShowCommand(CLITestBase):
    """Test the 'repoindex config show' command."""

    def test_config_show_outputs_json(self):
        """Test config show outputs valid JSON with all sections."""
        # Given: A valid config file
        self.write_config({
            "repository_directories": ["~/github/**"],
            "github": {"token": "", "rate_limit": {"max_retries": 3}},
            "registries": {"pypi": True, "cran": True},
            "cache": {"enabled": True, "ttl_minutes": 15},
            "repository_tags": {"project-a": ["work", "python"]}
        })

        # When: We run config show
        result = self.run_cli("config", "show")

        # Then: Output is valid JSON with expected structure
        config = json.loads(result.stdout)
        self.assertIn("repository_directories", config)
        self.assertIn("github", config)
        self.assertIn("registries", config)
        self.assertIn("cache", config)
        self.assertIn("repository_tags", config)

    def test_config_show_pretty_format(self):
        """Test config show --pretty outputs indented JSON."""
        self.write_config({
            "repository_directories": ["~/projects"],
            "repository_tags": {}
        })

        result = self.run_cli("config", "show", "--pretty")

        # Pretty output should have newlines and indentation
        self.assertIn("\n", result.stdout)
        # Should still be valid JSON
        config = json.loads(result.stdout)
        self.assertEqual(config["repository_directories"], ["~/projects"])


class TestConfigReposCommands(CLITestBase):
    """Test the 'repoindex config repos' subcommands."""

    def test_config_repos_add_new_path(self):
        """Test adding a new repository path."""
        # Given: A config with no repository directories
        self.write_config({
            "repository_directories": [],
            "repository_tags": {}
        })

        # When: We add a new path
        result = self.run_cli("config", "repos", "add", "~/new-repos/**")

        # Then: The path should be added
        self.assertEqual(result.returncode, 0)
        self.assertIn("Added repository directory", result.stdout)

        # Verify the config file was updated (now YAML)
        with open(self.config_path) as f:
            updated_config = yaml.safe_load(f)
        self.assertIn("~/new-repos/**", updated_config["repository_directories"])

    def test_config_repos_add_duplicate_path(self):
        """Test adding a duplicate path shows warning."""
        # Given: A config with an existing path
        self.write_config({
            "repository_directories": ["~/existing/**"],
            "repository_tags": {}
        })

        # When: We try to add the same path
        result = self.run_cli("config", "repos", "add", "~/existing/**")

        # Then: Should warn about duplicate
        self.assertEqual(result.returncode, 0)
        self.assertIn("already in configuration", result.stdout)

    def test_config_repos_remove_path(self):
        """Test removing a repository path."""
        # Given: A config with multiple paths
        self.write_config({
            "repository_directories": ["~/path-a/**", "~/path-b/**"],
            "repository_tags": {}
        })

        # When: We remove one path
        result = self.run_cli("config", "repos", "remove", "~/path-a/**")

        # Then: The path should be removed
        self.assertEqual(result.returncode, 0)
        self.assertIn("Removed repository directory", result.stdout)

        # Verify the config file was updated (now YAML)
        with open(self.config_path) as f:
            updated_config = yaml.safe_load(f)
        self.assertNotIn("~/path-a/**", updated_config["repository_directories"])
        self.assertIn("~/path-b/**", updated_config["repository_directories"])

    def test_config_repos_remove_nonexistent_path(self):
        """Test removing a path that doesn't exist."""
        # Given: A config with some paths
        self.write_config({
            "repository_directories": ["~/existing/**"],
            "repository_tags": {}
        })

        # When: We try to remove a non-existent path
        result = self.run_cli("config", "repos", "remove", "~/nonexistent/**")

        # Then: Should indicate path not found
        self.assertEqual(result.returncode, 0)
        self.assertIn("not found in configuration", result.stdout)

    def test_config_repos_list_json_output(self):
        """Test listing repository paths with JSON output."""
        # Given: A config with multiple paths
        self.write_config({
            "repository_directories": ["~/path-a/**", "~/path-b/**"],
            "repository_tags": {}
        })

        # When: We list with --json
        result = self.run_cli("config", "repos", "list", "--json")

        # Then: Should output JSONL
        lines = self.parse_jsonl(result.stdout)
        self.assertEqual(len(lines), 2)
        paths = [line["path"] for line in lines]
        self.assertIn("~/path-a/**", paths)
        self.assertIn("~/path-b/**", paths)

    def test_config_repos_list_empty(self):
        """Test listing when no repository paths are configured."""
        # Given: A config with no repository directories
        self.write_config({
            "repository_directories": [],
            "repository_tags": {}
        })

        # When: We list with --json
        result = self.run_cli("config", "repos", "list", "--json")

        # Then: Should output empty structure
        output = json.loads(result.stdout)
        self.assertEqual(output["repository_directories"], [])

    def test_config_repos_clear(self):
        """Test clearing all repository paths."""
        # Given: A config with paths
        self.write_config({
            "repository_directories": ["~/path-a/**", "~/path-b/**"],
            "repository_tags": {}
        })

        # When: We clear with --yes
        result = self.run_cli("config", "repos", "clear", "--yes")

        # Then: All paths should be cleared
        self.assertEqual(result.returncode, 0)
        self.assertIn("Cleared all repository directories", result.stdout)

        # Verify the config file was updated (now YAML)
        with open(self.config_path) as f:
            updated_config = yaml.safe_load(f)
        self.assertEqual(updated_config["repository_directories"], [])


class TestStatusCommand(CLITestBase):
    """Test the 'repoindex status' command (dashboard)."""

    def test_status_shows_dashboard_structure(self):
        """Test status command returns dashboard with expected structure."""
        db_path = Path(self.temp_dir) / "test.db"
        self.write_config({
            "repository_directories": [str(self.repos_dir) + "/**"],
            "registries": {"pypi": False, "cran": False},
            "cache": {"enabled": False},
            "repository_tags": {},
            "database": {"path": str(db_path)}
        })

        # When: We run status with --json for structured output
        result = self.run_cli("status", "--json")

        # Then: Should show dashboard data structure
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("database", data)
        self.assertIn("repos", data["database"])
        self.assertIsInstance(data["database"]["repos"], int)

    def test_status_repos_lists_individual_repos(self):
        """Test status --repos lists individual repositories."""
        # Given: A config and populated database
        self.create_git_repo("project-alpha")
        self.create_git_repo("project-beta")

        db_path = Path(self.temp_dir) / "test.db"
        self.write_config({
            "repository_directories": [str(self.repos_dir) + "/**"],
            "registries": {"pypi": False, "cran": False},
            "cache": {"enabled": False},
            "repository_tags": {},
            "database": {"path": str(db_path)}
        })

        # First refresh the database
        refresh_result = self.run_cli("refresh", "--quiet")
        self.assertEqual(refresh_result.returncode, 0)

        # When: We run status with --repos --json
        result = self.run_cli("status", "--repos", "--json")

        # Then: Should list repos
        self.assertEqual(result.returncode, 0)
        repos = json.loads(result.stdout)
        self.assertEqual(len(repos), 2)
        names = [r.get("name") for r in repos]
        self.assertIn("project-alpha", names)
        self.assertIn("project-beta", names)

    def test_status_empty_database(self):
        """Test status works with empty database (no repos)."""
        # Given: A config with no repos
        db_path = Path(self.temp_dir) / "test.db"
        self.write_config({
            "repository_directories": [str(self.repos_dir) + "/**"],
            "registries": {"pypi": False, "cran": False},
            "cache": {"enabled": False},
            "repository_tags": {},
            "database": {"path": str(db_path)}
        })

        # Refresh to create empty database
        refresh_result = self.run_cli("refresh", "--quiet")
        self.assertEqual(refresh_result.returncode, 0)

        # When: We run status with --json
        result = self.run_cli("status", "--json")

        # Then: Should succeed but show 0 repos
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["database"]["repos"], 0)




class TestQueryCommand(CLITestBase):
    """Test the 'repoindex query' command."""

    def test_query_matches_repo_name(self):
        """Test query can match repository names."""
        # Given: Repos with different names
        self.create_git_repo("python-utils")
        self.create_git_repo("go-tools")

        self.write_config({
            "repository_directories": [str(self.repos_dir) + "/**"],
            "registries": {"pypi": False, "cran": False},
            "cache": {"enabled": False},
            "repository_tags": {}
        })

        # Refresh database first (required for SQL-based queries)
        refresh_result = self.run_cli("refresh", "--quiet")
        self.assertEqual(refresh_result.returncode, 0)

        # When: We query for "python"
        result = self.run_cli("query", "python", "--brief")

        # Then: Should find the python repo
        self.assertEqual(result.returncode, 0)
        names = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        self.assertIn("python-utils", names)
        self.assertNotIn("go-tools", names)

    def test_query_field_match_no_results(self):
        """Test query with field match that returns no results."""
        # Given: A repo
        self.create_git_repo("test-project")

        self.write_config({
            "repository_directories": [str(self.repos_dir) + "/**"],
            "registries": {"pypi": False, "cran": False},
            "cache": {"enabled": False},
            "repository_tags": {}
        })

        # Refresh database first (required for SQL-based queries)
        refresh_result = self.run_cli("refresh", "--quiet")
        self.assertEqual(refresh_result.returncode, 0)

        # When: We query for a specific field value that doesn't exist
        # Using name == 'nonexistent' is an exact match query
        result = self.run_cli("query", "name == 'nonexistent-repo-xyz'", "--brief")

        # Then: Should succeed but with empty output
        self.assertEqual(result.returncode, 0)
        # Output should be empty or whitespace only
        self.assertEqual(result.stdout.strip(), "")

    def test_query_limit_option(self):
        """Test query with --limit option."""
        # Given: Multiple repos
        for i in range(5):
            self.create_git_repo(f"project-{i}")

        self.write_config({
            "repository_directories": [str(self.repos_dir) + "/**"],
            "registries": {"pypi": False, "cran": False},
            "cache": {"enabled": False},
            "repository_tags": {}
        })

        # Refresh database first (required for SQL-based queries)
        refresh_result = self.run_cli("refresh", "--quiet")
        self.assertEqual(refresh_result.returncode, 0)

        # When: We query with a limit
        result = self.run_cli("query", "project", "--brief", "--limit", "2")

        # Then: Should only return up to the limit
        self.assertEqual(result.returncode, 0)
        names = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        self.assertLessEqual(len(names), 2)


class TestHelpCommands(CLITestBase):
    """Test help output for various commands."""

    def test_main_help(self):
        """Test main help output."""
        self.write_config({"repository_directories": [], "repository_tags": {}})
        result = self.run_cli("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Collection-aware metadata index", result.stdout)
        self.assertIn("--config", result.stdout)

    def test_status_help(self):
        """Test status command help."""
        self.write_config({"repository_directories": [], "repository_tags": {}})
        result = self.run_cli("status", "--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("status", result.stdout.lower())

    def test_config_help(self):
        """Test config command help."""
        self.write_config({"repository_directories": [], "repository_tags": {}})
        result = self.run_cli("config", "--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("show", result.stdout)
        self.assertIn("repos", result.stdout)
        self.assertIn("init", result.stdout)

    def test_config_init_help(self):
        """Test config init command help."""
        self.write_config({"repository_directories": [], "repository_tags": {}})
        result = self.run_cli("config", "init", "--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("init", result.stdout.lower())

    def test_query_help(self):
        """Test query command help."""
        self.write_config({"repository_directories": [], "repository_tags": {}})
        result = self.run_cli("query", "--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("query", result.stdout.lower())


class TestInvalidCommands(CLITestBase):
    """Test error handling for invalid commands and arguments."""

    def test_invalid_command(self):
        """Test invalid command returns non-zero exit code."""
        self.write_config({"repository_directories": [], "repository_tags": {}})
        result = self.run_cli_allow_failure("nonexistent-command")

        self.assertNotEqual(result.returncode, 0)

    def test_sql_without_query_or_flags(self):
        """Test sql without query or info flags shows error."""
        self.write_config({"repository_directories": [], "repository_tags": {}})

        # sql command without query or --info/--path/--schema flags should fail
        result = self.run_cli_allow_failure("sql")

        self.assertNotEqual(result.returncode, 0)


class TestConfigIsolation(CLITestBase):
    """Test that --config properly isolates different config files."""

    def test_different_configs_produce_different_results(self):
        """Test that using different config files gives different results."""
        # Given: Two different config files with different repository directories
        config_a_path = Path(self.temp_dir) / "config_a.json"
        config_b_path = Path(self.temp_dir) / "config_b.json"

        with open(config_a_path, "w") as f:
            json.dump({
                "repository_directories": ["~/path-a/**"],
                "registries": {"pypi": False, "cran": False},
                "cache": {"enabled": False},
                "repository_tags": {}
            }, f)

        with open(config_b_path, "w") as f:
            json.dump({
                "repository_directories": ["~/path-b/**"],
                "registries": {"pypi": False, "cran": False},
                "cache": {"enabled": False},
                "repository_tags": {}
            }, f)

        # When: We run config show with each config
        cmd_base = ["python", "-m", "repoindex.cli"]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.project_root) + os.pathsep + env.get("PYTHONPATH", "")

        result_a = subprocess.run(
            cmd_base + ["--config", str(config_a_path), "config", "show"],
            capture_output=True, text=True, env=env
        )
        result_b = subprocess.run(
            cmd_base + ["--config", str(config_b_path), "config", "show"],
            capture_output=True, text=True, env=env
        )

        # Then: Each should return its own config
        config_a_result = json.loads(result_a.stdout)
        config_b_result = json.loads(result_b.stdout)

        self.assertIn("~/path-a/**", config_a_result["repository_directories"])
        self.assertIn("~/path-b/**", config_b_result["repository_directories"])


if __name__ == "__main__":
    unittest.main()
