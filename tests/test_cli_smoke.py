"""
Smoke tests using real configuration and repositories.

These tests validate that the CLI works with actual user configuration.
They skip if no real config exists (e.g., in CI environments).

This catches bugs like the one where tests passed but CLI was broken
because tests mocked the config structure incorrectly.
"""

import os
import json
import subprocess
import sys
import unittest
from pathlib import Path


def get_real_config_path():
    """Get the real config path if it exists."""
    config_path = Path.home() / '.repoindex' / 'config.json'
    if config_path.exists():
        return config_path
    return None


def real_config_exists():
    """Check if real config exists and has repository_directories."""
    config_path = get_real_config_path()
    if not config_path:
        return False
    try:
        with open(config_path) as f:
            config = json.load(f)
        return bool(config.get('repository_directories'))
    except (json.JSONDecodeError, IOError):
        return False


SKIP_REASON = "No real config at ~/.repoindex/config.json with repository_directories"


@unittest.skipUnless(real_config_exists(), SKIP_REASON)
class TestCLISmokeWithRealConfig(unittest.TestCase):
    """
    Smoke tests that use the real ~/.repoindex/config.json.

    These tests ensure the CLI actually works with real configuration,
    catching bugs that mock-based tests might miss.
    """

    def run_cli(self, *args, timeout=180):
        """Run the CLI and return result.

        Default timeout is 180 seconds for commands that scan many repositories.
        """
        cmd = [sys.executable, '-m', 'repoindex.cli'] + list(args)
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).parent.parent)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )
        return result

    def test_config_show_returns_valid_json(self):
        """config show should return valid JSON with expected structure."""
        result = self.run_cli('config', 'show')

        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")

        config = json.loads(result.stdout)
        self.assertIn('repository_directories', config)
        self.assertIsInstance(config['repository_directories'], list)
        self.assertIn('github', config)
        self.assertIn('repository_tags', config)  # Updated from 'registries'

    def test_status_dashboard_json(self):
        """status --json should return dashboard data."""
        result = self.run_cli('status', '--json')

        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")

        # Should output valid JSON with dashboard structure
        data = json.loads(result.stdout)
        self.assertIn('database', data)
        self.assertIn('repos', data['database'])

    def test_status_repos_list(self):
        """status --repos --json should list individual repos."""
        result = self.run_cli('status', '--repos', '--json')

        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")

        # Should output JSON array of repos
        repos = json.loads(result.stdout)
        self.assertGreater(len(repos), 0, "Expected at least one repository")

        # Each repo should have expected fields
        for repo in repos[:5]:  # Check first 5
            self.assertIn('name', repo)
            self.assertIn('path', repo)

    def test_events_command_works(self):
        """events should scan for git events."""
        result = self.run_cli('events', '--since', '7d')

        # events might return 0 even with no events
        self.assertIn(result.returncode, [0, 64], f"Failed: {result.stderr}")

    def test_query_command_works(self):
        """query should filter repositories."""
        result = self.run_cli('query', "name contains 'a'")

        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")

    def test_config_repos_list_works(self):
        """config repos list should show configured directories."""
        result = self.run_cli('config', 'repos', 'list', '--json')

        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")

        # Should have at least one configured directory
        lines = [l for l in result.stdout.strip().split('\n') if l]
        self.assertGreater(len(lines), 0)

    def test_help_works(self):
        """--help should work for main and subcommands."""
        commands_to_test = [
            ['--help'],
            ['status', '--help'],
            ['config', '--help'],
            ['config', 'init', '--help'],
            ['query', '--help'],
        ]

        for cmd in commands_to_test:
            with self.subTest(cmd=cmd):
                result = self.run_cli(*cmd)
                self.assertEqual(result.returncode, 0, f"{cmd} failed: {result.stderr}")
                self.assertIn('--help', result.stdout)


@unittest.skipUnless(real_config_exists(), SKIP_REASON)
class TestCLIRealConfigIntegrity(unittest.TestCase):
    """
    Tests that validate the config loading path works correctly.

    These specifically target the bugs we found where config.get('general', {})
    was used instead of config.get('repository_directories', []).
    """

    def run_cli(self, *args, timeout=180):
        """Run the CLI and return result.

        Default timeout is 180 seconds for commands that scan many repositories.
        """
        cmd = [sys.executable, '-m', 'repoindex.cli'] + list(args)
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).parent.parent)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )
        return result

    def test_status_dashboard_structure(self):
        """
        status --json should return dashboard data with expected structure.
        """
        result = self.run_cli('status', '--json')

        # Should succeed
        self.assertEqual(result.returncode, 0, f"Failed: {result.stderr}")

        # Should have dashboard data structure
        data = json.loads(result.stdout)
        self.assertIn('database', data)
        self.assertIn('repos', data['database'])
        # Repo count can be 0 if database hasn't been refreshed
        self.assertIsInstance(data['database']['repos'], int)

    def test_config_structure_is_new_format(self):
        """
        Verify config uses new flat structure, not old nested 'general' structure.
        """
        result = self.run_cli('config', 'show')

        self.assertEqual(result.returncode, 0)
        config = json.loads(result.stdout)

        # New structure: repository_directories at top level
        self.assertIn('repository_directories', config)

        # Old structure should NOT exist
        self.assertNotIn('general', config)

        # repository_directories should be a list
        self.assertIsInstance(config['repository_directories'], list)

    def test_status_repos_matches_query_count(self):
        """
        The number of repos from status --repos should match query result.

        This catches bugs where discovery works but database sync fails.
        """
        # Get repo count from status --repos
        status_result = self.run_cli('status', '--repos', '--json')
        if status_result.returncode != 0:
            self.skipTest("status --repos failed, database may be empty")

        status_repos = json.loads(status_result.stdout)

        # Get repo count from query (all repos)
        query_result = self.run_cli('query', '--brief')
        query_lines = [l for l in query_result.stdout.strip().split('\n') if l.strip()]

        # Should match
        self.assertEqual(len(status_repos), len(query_lines),
            "status --repos and query returned different repo counts")


if __name__ == '__main__':
    unittest.main()
