"""
Unit tests for ghops.commands.clone module
"""
import unittest
import tempfile
import os
import shutil
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.commands.clone import get_user_repositories, clone_repositories


class TestGetCommand(unittest.TestCase):
    """Test the get command functionality

    Note: run_command returns (stdout, returncode) tuple, so mocks must return tuples.
    """

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)

    @patch('repoindex.commands.clone.run_command')
    def test_get_user_repositories_basic(self, mock_run_command):
        """Test getting repository list from GitHub"""
        # Mock GitHub CLI response - must return tuple (stdout, returncode)
        mock_run_command.return_value = (json.dumps([
            {"nameWithOwner": "user/repo1", "isPrivate": False, "isFork": False,
             "description": "Test repo 1", "repositoryTopics": {"nodes": []}},
            {"nameWithOwner": "user/repo2", "isPrivate": False, "isFork": False,
             "description": "Test repo 2", "repositoryTopics": {"nodes": []}}
        ]), 0)

        repos = list(get_user_repositories('testuser', limit=10))

        # Verify GitHub CLI was called
        mock_run_command.assert_called_once()
        call_args = mock_run_command.call_args[0][0]
        self.assertIn('gh repo list testuser', call_args)
        self.assertIn('--limit 10', call_args)

        # Check returned repos
        self.assertEqual(len(repos), 2)
        self.assertEqual(repos[0]['name'], 'repo1')
        self.assertEqual(repos[1]['name'], 'repo2')

    @patch('repoindex.commands.clone.run_command')
    def test_clone_repositories_with_ignore_list(self, mock_run_command):
        """Test repository cloning with ignore list"""
        # Mock git clone responses - must return tuple (stdout, returncode)
        mock_run_command.side_effect = [
            ("Cloning into 'repo1'...", 0),  # git clone response
            ("Cloning into 'repo2'...", 0),  # git clone response
        ]

        repos = [
            {"name": "repo1", "url": "https://github.com/user/repo1"},
            {"name": "ignored-repo", "url": "https://github.com/user/ignored-repo"},
            {"name": "repo2", "url": "https://github.com/user/repo2"}
        ]

        results = list(clone_repositories(
            repos,
            target_dir=self.temp_dir,
            ignore_list=['ignored-repo'],
            dry_run=False
        ))

        # Should have 2 clone calls (ignoring one)
        self.assertEqual(mock_run_command.call_count, 2)

        # Verify results
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0]['actions']['cloned'])  # repo1
        self.assertFalse(results[1]['actions']['cloned'])  # ignored-repo
        self.assertTrue(results[2]['actions']['cloned'])  # repo2
        clone_calls = [call[0][0] for call in mock_run_command.call_args_list[1:]]
        self.assertNotIn('git clone "https://github.com/user/ignored-repo.git"', clone_calls)


    @patch('repoindex.commands.clone.run_command')
    def test_get_user_repositories_no_repos_found(self, mock_run_command):
        """Test behavior when no repositories are found"""
        # Mock empty GitHub CLI response - must return tuple
        mock_run_command.return_value = ("", 0)

        repos = list(get_user_repositories('nonexistentuser', limit=10))

        # Should only call gh repo list
        self.assertEqual(mock_run_command.call_count, 1)
        # Should return no repos
        self.assertEqual(len(repos), 0)


    @patch('repoindex.commands.clone.run_command')
    def test_clone_repositories_failure(self, mock_run_command):
        """Test behavior when git clone fails"""
        # Mock git clone failure
        mock_run_command.side_effect = Exception("Clone failed")

        repos = [{"name": "repo1", "url": "https://github.com/user/repo1"}]

        results = list(clone_repositories(
            repos,
            target_dir=self.temp_dir,
            dry_run=False
        ))

        # Should handle the failure gracefully
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]['actions']['cloned'])
        self.assertIn('error', results[0]['actions'])

    @patch('repoindex.commands.clone.run_command')
    def test_get_user_repositories_multiple_calls(self, mock_run_command):
        """Test getting repositories for multiple users separately"""
        # First call for user1 - must return tuple
        mock_run_command.return_value = (json.dumps([
            {"nameWithOwner": "user1/repo1", "isPrivate": False, "isFork": False,
             "description": "User1 repo", "repositoryTopics": {"nodes": []}}
        ]), 0)

        repos1 = list(get_user_repositories('user1', limit=10))

        # Second call for user2 - must return tuple
        mock_run_command.return_value = (json.dumps([
            {"nameWithOwner": "user2/repo2", "isPrivate": False, "isFork": False,
             "description": "User2 repo", "repositoryTopics": {"nodes": []}}
        ]), 0)

        repos2 = list(get_user_repositories('user2', limit=10))

        # Should have 2 calls total
        self.assertEqual(mock_run_command.call_count, 2)

        # Verify results
        self.assertEqual(len(repos1), 1)
        self.assertEqual(repos1[0]['name'], 'repo1')
        self.assertEqual(len(repos2), 1)
        self.assertEqual(repos2[0]['name'], 'repo2')


if __name__ == '__main__':
    unittest.main()
