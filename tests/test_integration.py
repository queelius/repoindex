"""
Integration tests for ghops CLI commands
"""
import unittest
import tempfile
import os
import shutil
import subprocess
import json
from pathlib import Path
from unittest.mock import patch


class TestCLIIntegration(unittest.TestCase):
    """Integration tests for the CLI interface"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        
        # Create a fake git repository
        self.test_repo = os.path.join(self.temp_dir, "test_repo")
        os.makedirs(self.test_repo)
        os.makedirs(os.path.join(self.test_repo, ".git"))
        
        # Create a pyproject.toml file
        pyproject_content = """
[project]
name = "test-package"
version = "1.0.0"
description = "A test package"
"""
        with open(os.path.join(self.test_repo, "pyproject.toml"), "w") as f:
            f.write(pyproject_content)
        
        # Create a LICENSE file
        license_content = "MIT License\n\nCopyright (c) 2023 Test User"
        with open(os.path.join(self.test_repo, "LICENSE"), "w") as f:
            f.write(license_content)
    
    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)
    
    def run_ghops_command(self, *args):
        """Helper to run ghops commands"""
        cmd = ["python", "-m", "repoindex.cli"] + list(args)
        env = os.environ.copy()
        # Add the project root to PYTHONPATH so the module can be found
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['PYTHONPATH'] = project_root + (os.pathsep + env.get('PYTHONPATH', ''))
        result = subprocess.run(
            cmd,
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
            env=env
        )
        return result
    
    def test_status_command_json_output(self):
        """Test status command with JSON output"""
        result = self.run_ghops_command("status", "--json")

        self.assertEqual(result.returncode, 0)

        # Parse JSON output
        if result.stdout.strip():
            try:
                status_data = json.loads(result.stdout)
                # Status command outputs a dashboard summary object
                self.assertIsInstance(status_data, dict)
            except json.JSONDecodeError:
                self.fail(f"Output is not valid JSON: {result.stdout}")
    
    def test_init_command(self):
        """Test config init command"""
        # Override HOME to avoid writing to real config
        env = os.environ.copy()
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['PYTHONPATH'] = project_root + (os.pathsep + env.get('PYTHONPATH', ''))
        env['HOME'] = self.temp_dir  # Use temp dir as HOME

        cmd = ["python", "-m", "repoindex.cli", "config", "init", "-y", "-d", self.temp_dir]
        result = subprocess.run(
            cmd,
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
            env=env
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Configuration created", result.stdout)

        # Check that config file was created in temp HOME (now YAML)
        config_file = Path(self.temp_dir) / ".repoindex" / "config.yaml"
        self.assertTrue(config_file.exists())
    
    def test_config_show(self):
        """Test config show command"""
        result = self.run_ghops_command("config", "show")

        self.assertEqual(result.returncode, 0)

        # Should output JSON configuration
        try:
            config_data = json.loads(result.stdout)
            self.assertIn('repository_directories', config_data)
            self.assertIn('github', config_data)
            self.assertIn('repository_tags', config_data)
        except json.JSONDecodeError:
            self.fail(f"Config show did not output valid JSON: {result.stdout}")
    
    def test_command_help(self):
        """Test that help is displayed for various commands"""
        # Main help
        result = self.run_ghops_command("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Collection-aware metadata index", result.stdout)
        
        # Status help
        result = self.run_ghops_command("status", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--json", result.stdout)  # --json option for scripting
        
        # Config help
        result = self.run_ghops_command("config", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("show", result.stdout)  # Check for config-specific commands
        self.assertIn("repos", result.stdout)  # Check for repos subcommand
    
    def test_invalid_command(self):
        """Test handling of invalid commands"""
        result = self.run_ghops_command("invalid_command")
        
        self.assertNotEqual(result.returncode, 0)
    
    def test_status_with_json_flag(self):
        """Test status command with JSON output flag"""
        result = self.run_ghops_command("status", "--json")

        self.assertEqual(result.returncode, 0)
        # JSON output should be valid
        self.assertIn("{", result.stdout)


class TestCLIErrorHandling(unittest.TestCase):
    """Test CLI error handling scenarios"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)
    
    def tearDown(self):
        """Clean up test environment"""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)
    
    def run_ghops_command(self, *args):
        """Helper to run ghops commands"""
        cmd = ["python", "-m", "repoindex.cli"] + list(args)
        env = os.environ.copy()
        # Add the project root to PYTHONPATH so the module can be found
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['PYTHONPATH'] = project_root + (os.pathsep + env.get('PYTHONPATH', ''))
        result = subprocess.run(
            cmd,
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
            env=env
        )
        return result
    
    def test_status_empty_database(self):
        """Test status command with empty database"""
        # Status shows dashboard from database, works even with no repos
        result = self.run_ghops_command("status", "--json")

        # Should succeed even with empty database
        self.assertEqual(result.returncode, 0)
        # Output should be valid JSON
        if result.stdout.strip():
            try:
                status_data = json.loads(result.stdout)
                self.assertIsInstance(status_data, dict)
            except json.JSONDecodeError:
                self.fail(f"Output is not valid JSON: {result.stdout}")
    


if __name__ == '__main__':
    unittest.main()
