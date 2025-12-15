"""
Unit tests for ghops.commands.license module
"""
import unittest
import tempfile
import os
import shutil
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.core import (
    get_available_licenses as list_licenses,
    get_license_template as show_license_template,
    add_license_to_repo
)


class TestLicenseCommands(unittest.TestCase):
    """Test the license command functionality

    Note: run_command returns (stdout, returncode) tuple, so mocks must return tuples.
    """

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()

        # Create test repository structure
        self.test_repo = os.path.join(self.temp_dir, "test_repo")
        os.makedirs(self.test_repo)
        os.makedirs(os.path.join(self.test_repo, ".git"))

    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)

    @patch('repoindex.core.run_command')
    def test_list_licenses_success(self, mock_run_command):
        """Test successful listing of licenses"""
        mock_response = json.dumps([
            {"key": "mit", "name": "MIT License"},
            {"key": "apache-2.0", "name": "Apache License 2.0"},
            {"key": "gpl-3.0", "name": "GNU General Public License v3.0"}
        ])
        mock_run_command.return_value = (mock_response, 0)

        # Note: This function doesn't return anything, it prints to console
        # We're just testing it doesn't raise an exception
        list_licenses()

        mock_run_command.assert_called_once_with("gh api /licenses", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_list_licenses_command_failure(self, mock_run_command):
        """Test listing licenses when command fails"""
        mock_run_command.return_value = (None, 1)

        # Should not raise exception on command failure
        list_licenses()

        mock_run_command.assert_called_once_with("gh api /licenses", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_list_licenses_table_output(self, mock_run_command):
        """Test listing licenses with table output"""
        mock_response = json.dumps([
            {"key": "mit", "name": "MIT License"}
        ])
        mock_run_command.return_value = (mock_response, 0)

        # Should not raise exception with table output
        list_licenses()

        mock_run_command.assert_called_once_with("gh api /licenses", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_show_license_template_success(self, mock_run_command):
        """Test successful showing of a license template"""
        mock_response = json.dumps({
            "key": "mit",
            "name": "MIT License",
            "body": "MIT License\n\nCopyright (c) [year] [fullname]"
        })
        mock_run_command.return_value = (mock_response, 0)

        # Should not raise exception
        show_license_template("mit")

        mock_run_command.assert_called_once_with("gh api /licenses/mit", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_show_license_template_command_failure(self, mock_run_command):
        """Test showing license when command fails"""
        mock_run_command.return_value = (None, 1)

        # Should not raise exception on command failure
        show_license_template("invalid")

        mock_run_command.assert_called_once_with("gh api /licenses/invalid", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_show_license_template_table_output(self, mock_run_command):
        """Test showing license template with table output"""
        mock_response = json.dumps({
            "key": "mit",
            "name": "MIT License",
            "body": "MIT License\n\nCopyright (c) [year] [fullname]"
        })
        mock_run_command.return_value = (mock_response, 0)

        # Should not raise exception with table output
        show_license_template("mit")

        mock_run_command.assert_called_once_with("gh api /licenses/mit", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_add_license_to_repo_success(self, mock_run_command):
        """Test successful addition of license to repository"""
        mock_response = json.dumps({
            "body": "MIT License\n\nCopyright (c) [year] [fullname]\n\nPermission is hereby granted..."
        })
        mock_run_command.return_value = (mock_response, 0)

        result = add_license_to_repo(
            self.test_repo,
            "mit",
            "Test Author",
            "test@example.com",
            "2023",
            False,
            False
        )

        # Should succeed
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["path"], str(Path(self.test_repo) / "LICENSE"))

        # Check that LICENSE file was created
        license_file = Path(self.test_repo) / "LICENSE"
        self.assertTrue(license_file.exists())

        # Check file contents
        with open(license_file, 'r') as f:
            content = f.read()
            self.assertIn("MIT License", content)
            self.assertIn("Copyright (c) 2023 Test Author", content)

        mock_run_command.assert_called_once_with("gh api /licenses/mit", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_add_license_to_repo_dry_run(self, mock_run_command):
        """Test adding license in dry run mode"""
        mock_response = json.dumps({
            "body": "MIT License\n\nCopyright (c) [year] [fullname]"
        })
        mock_run_command.return_value = (mock_response, 0)

        result = add_license_to_repo(
            self.test_repo,
            "mit",
            "Test Author",
            "test@example.com",
            "2023",
            True,
            True  # dry_run should be True
        )

        # Should return dry run status
        self.assertEqual(result["status"], "success_dry_run")
        self.assertEqual(result["path"], str(Path(self.test_repo) / "LICENSE"))

        # Check that LICENSE file was NOT created
        license_file = Path(self.test_repo) / "LICENSE"
        self.assertFalse(license_file.exists())

        mock_run_command.assert_called_once_with("gh api /licenses/mit", capture_output=True, check=False)
    
    def test_add_license_to_repo_existing_file_no_force(self):
        """Test adding license when file exists and force is False"""
        # Create existing LICENSE file
        license_file = Path(self.test_repo) / "LICENSE"
        with open(license_file, 'w') as f:
            f.write("Existing license content")
        
        result = add_license_to_repo(
            self.test_repo,
            "mit",
            "Test Author",
            "test@example.com",
            "2023",
            False,  # force=False
            False   # dry_run=False
        )
        
        # Should return skipped status
        self.assertEqual(result["status"], "skipped")
        
        # File should remain unchanged
        with open(license_file, 'r') as f:
            content = f.read()
            self.assertEqual(content, "Existing license content")
    
    @patch('repoindex.core.run_command')
    def test_add_license_to_repo_existing_file_with_force(self, mock_run_command):
        """Test adding license when file exists and force is True"""
        # Create existing LICENSE file
        license_file = Path(self.test_repo) / "LICENSE"
        with open(license_file, 'w') as f:
            f.write("Existing license content")

        mock_response = json.dumps({
            "body": "MIT License\n\nCopyright (c) [year] [fullname]"
        })
        mock_run_command.return_value = (mock_response, 0)

        result = add_license_to_repo(
            self.test_repo,
            "mit",
            "Test Author",
            "test@example.com",
            "2023",
            True,   # force=True
            False   # dry_run=False
        )

        # Should succeed
        self.assertEqual(result["status"], "success")

        # File should be overwritten
        with open(license_file, 'r') as f:
            content = f.read()
            self.assertIn("MIT License", content)
            self.assertIn("Test Author", content)

        mock_run_command.assert_called_once_with("gh api /licenses/mit", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_add_license_to_repo_command_failure(self, mock_run_command):
        """Test adding license when GitHub API command fails"""
        mock_run_command.return_value = (None, 1)

        result = add_license_to_repo(
            self.test_repo,
            "invalid",
            "Test Author",
            "test@example.com",
            "2023",
            False,
            False
        )

        # Should return error status
        self.assertEqual(result["status"], "error")
        self.assertIn("Failed to get template for license", result["reason"])

        # LICENSE file should not be created
        license_file = Path(self.test_repo) / "LICENSE"
        self.assertFalse(license_file.exists())

        mock_run_command.assert_called_once_with("gh api /licenses/invalid", capture_output=True, check=False)

    @patch('repoindex.core.run_command')
    def test_add_license_to_repo_invalid_json(self, mock_run_command):
        """Test adding license with invalid JSON response"""
        mock_run_command.return_value = ("invalid json", 0)

        result = add_license_to_repo(
            self.test_repo,
            "mit",
            "Test Author",
            "test@example.com",
            "2023",
            False,
            False
        )

        # Should return error status
        self.assertEqual(result["status"], "error")
        self.assertIn("Failed to get template for license", result["reason"])

        # LICENSE file should not be created due to the error
        license_file = Path(self.test_repo) / "LICENSE"
        self.assertFalse(license_file.exists())

    @patch('repoindex.core.run_command')
    @patch('repoindex.core.datetime')
    def test_add_license_to_repo_default_year(self, mock_datetime, mock_run_command):
        """Test adding license with default year"""
        # Mock datetime to return a specific year
        mock_datetime.now.return_value.year = 2023
        mock_response = json.dumps({
            "body": "MIT License\n\nCopyright (c) [year] [fullname]"
        })
        mock_run_command.return_value = (mock_response, 0)

        result = add_license_to_repo(
            self.test_repo,
            "mit",
            "Test Author",
            "test@example.com",
            None,  # Should use default year
            False,
            False
        )

        # Should succeed
        self.assertEqual(result["status"], "success")

        # Check that the mocked year was used (2023, not 2025)
        license_file = Path(self.test_repo) / "LICENSE"
        self.assertTrue(license_file.exists())
        with open(license_file, 'r') as f:
            content = f.read()
            self.assertIn("Copyright (c) 2023 Test Author", content)

    @patch('repoindex.core.run_command')
    def test_add_license_to_repo_no_author_info(self, mock_run_command):
        """Test adding license without author information"""
        mock_response = json.dumps({
            "body": "MIT License\n\nCopyright (c) [year] [fullname]\n\nContact: [email]"
        })
        mock_run_command.return_value = (mock_response, 0)

        result = add_license_to_repo(
            self.test_repo,
            "mit",
            None,  # No author info
            None,  # No author info
            "2023",
            False,
            False
        )

        # Should succeed
        self.assertEqual(result["status"], "success")

        # Check that year was replaced but author placeholders remain
        license_file = Path(self.test_repo) / "LICENSE"
        self.assertTrue(license_file.exists())
        with open(license_file, 'r') as f:
            content = f.read()
            # Year should be replaced but author placeholders are replaced with empty string
            self.assertIn("Copyright (c) 2023", content)
            self.assertNotIn("[fullname]", content)  # Should be replaced with empty string
            self.assertNotIn("[email]", content)  # Should be replaced with empty string
            self.assertNotIn("[year]", content)  # Year should be replaced


if __name__ == '__main__':
    unittest.main()
