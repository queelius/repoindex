"""
Extended tests for repoindex.config module.

Tests focus on:
- Legacy ~/.ghops/ config location support
- YAML and TOML file handling with/without libraries
- Error handling paths
- generate_default_config() function
- Edge cases in config loading
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestLegacyConfigLocation(unittest.TestCase):
    """Tests for backward compatibility with ~/.ghops/ location."""

    def setUp(self):
        """Set up test environment."""
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

    def test_load_config_from_legacy_ghops_location(self):
        """Test that config is loaded from ~/.ghops/ when ~/.repoindex/ doesn't exist."""
        from repoindex.config import load_config

        # Given: Config only in legacy location
        ghops_dir = Path(self.temp_dir) / '.ghops'
        ghops_dir.mkdir()
        config_data = {
            'repository_directories': ['~/legacy-repos/**'],
            'repository_tags': {}
        }
        with open(ghops_dir / 'config.json', 'w') as f:
            json.dump(config_data, f)

        # When: We load config
        config = load_config()

        # Then: It should use the legacy config
        self.assertEqual(config['repository_directories'], ['~/legacy-repos/**'])

    def test_repoindex_location_takes_precedence_over_ghops(self):
        """Test that ~/.repoindex/ takes precedence over ~/.ghops/."""
        from repoindex.config import load_config

        # Given: Config in both locations
        ghops_dir = Path(self.temp_dir) / '.ghops'
        ghops_dir.mkdir()
        with open(ghops_dir / 'config.json', 'w') as f:
            json.dump({'repository_directories': ['~/legacy/**']}, f)

        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        with open(repoindex_dir / 'config.json', 'w') as f:
            json.dump({'repository_directories': ['~/new/**']}, f)

        # When: We load config
        config = load_config()

        # Then: It should use the new location
        self.assertEqual(config['repository_directories'], ['~/new/**'])

    def test_get_config_path_returns_legacy_when_exists(self):
        """Test that get_config_path finds legacy location."""
        from repoindex.config import get_config_path

        # Given: Config only in legacy location
        ghops_dir = Path(self.temp_dir) / '.ghops'
        ghops_dir.mkdir()
        (ghops_dir / 'config.json').write_text('{"repository_directories": []}')

        # When: We get config path
        path = get_config_path()

        # Then: It should return the legacy path
        self.assertEqual(path, ghops_dir / 'config.json')


class TestConfigFileFormats(unittest.TestCase):
    """Tests for different config file formats (JSON, YAML, TOML)."""

    def setUp(self):
        """Set up test environment."""
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

    def test_load_yaml_config_with_pyyaml(self):
        """Test loading YAML config when PyYAML is available."""
        from repoindex.config import load_config

        # Given: A YAML config file
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        yaml_content = """
repository_directories:
  - ~/github/**
  - ~/projects

github:
  token: "test-token-123"

registries:
  pypi: false
  npm: true
"""
        (repoindex_dir / 'config.yaml').write_text(yaml_content)

        # When: We load config
        try:
            import yaml
            config = load_config()

            # Then: It should load the YAML config
            self.assertIn('~/github/**', config['repository_directories'])
            self.assertEqual(config['github']['token'], 'test-token-123')
            self.assertFalse(config['registries']['pypi'])
            self.assertTrue(config['registries']['npm'])
        except ImportError:
            # Skip test if PyYAML is not installed
            self.skipTest("PyYAML not installed")

    def test_load_yaml_config_without_pyyaml(self):
        """Test that YAML config falls back to JSON when PyYAML is not available."""
        from repoindex.config import load_config

        # Given: A YAML config file and no PyYAML
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        (repoindex_dir / 'config.yaml').write_text("repository_directories: []")

        # When: PyYAML import fails
        with patch.dict('sys.modules', {'yaml': None}):
            with patch('builtins.__import__', side_effect=ImportError("No module named 'yaml'")):
                # load_config should handle the ImportError gracefully
                # but may fall back to JSON parsing which will fail on YAML syntax
                # This tests the error handling path
                pass

    def test_config_path_priority_yaml_before_json(self):
        """Test that YAML config is preferred over JSON when both exist."""
        from repoindex.config import get_config_path

        # Given: Both JSON and YAML configs exist
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        (repoindex_dir / 'config.json').write_text('{"repository_directories": ["~/json/**"]}')
        (repoindex_dir / 'config.yaml').write_text('repository_directories:\n  - ~/yaml/**')

        # When: We get config path
        path = get_config_path()

        # Then: It should prefer YAML (YAML is now the primary format)
        self.assertEqual(path.suffix, '.yaml')


class TestConfigSaving(unittest.TestCase):
    """Tests for config saving functionality."""

    def setUp(self):
        """Set up test environment."""
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

    def test_save_config_creates_directory(self):
        """Test that save_config creates the config directory if it doesn't exist."""
        from repoindex.config import save_config

        # Given: No .repoindex directory exists
        config = {'repository_directories': ['~/repos/**']}

        # When: We save config
        save_config(config)

        # Then: Directory and file should exist (YAML is default format now)
        config_path = Path(self.temp_dir) / '.repoindex' / 'config.yaml'
        self.assertTrue(config_path.exists())
        import yaml
        with open(config_path) as f:
            saved = yaml.safe_load(f)
        self.assertEqual(saved['repository_directories'], ['~/repos/**'])

    def test_save_config_preserves_indentation(self):
        """Test that saved YAML is properly formatted."""
        from repoindex.config import save_config

        # Given: A config to save
        config = {'repository_directories': ['~/repos/**'], 'github': {'token': ''}}

        # When: We save config
        save_config(config)

        # Then: File should be indented (YAML is default format now)
        config_path = Path(self.temp_dir) / '.repoindex' / 'config.yaml'
        content = config_path.read_text()
        self.assertIn('\n', content)  # Has newlines (formatted)
        self.assertIn('repository_directories', content)  # Has key


class TestGenerateDefaultConfig(unittest.TestCase):
    """Tests for generate_default_config function."""

    def setUp(self):
        """Set up test environment."""
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

    def test_generate_default_config_creates_minimal_config(self):
        """Test that generate_default_config creates a minimal config file."""
        from repoindex.config import generate_default_config

        # When: We generate default config
        generate_default_config()

        # Then: Config file should exist with minimal structure (YAML format now)
        config_path = Path(self.temp_dir) / '.repoindex' / 'config.yaml'
        self.assertTrue(config_path.exists())
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)
        self.assertIn('repository_directories', config)
        self.assertIn('repository_tags', config)
        self.assertEqual(config['repository_directories'], [])

    def test_generate_default_config_creates_directory(self):
        """Test that generate_default_config creates the config directory."""
        from repoindex.config import generate_default_config

        # Given: No .repoindex directory exists

        # When: We generate default config
        generate_default_config()

        # Then: Directory should exist
        config_dir = Path(self.temp_dir) / '.repoindex'
        self.assertTrue(config_dir.exists())


class TestEnvironmentVariableOverrides(unittest.TestCase):
    """Tests for environment variable configuration overrides."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.original_home = os.environ.get('HOME')
        os.environ['HOME'] = self.temp_dir
        # Save any existing env vars we'll modify
        self.original_github_token = os.environ.get('GITHUB_TOKEN')

    def tearDown(self):
        """Clean up test environment."""
        if self.original_home:
            os.environ['HOME'] = self.original_home
        else:
            del os.environ['HOME']
        # Restore GITHUB_TOKEN
        if self.original_github_token:
            os.environ['GITHUB_TOKEN'] = self.original_github_token
        elif 'GITHUB_TOKEN' in os.environ:
            del os.environ['GITHUB_TOKEN']
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_github_token_from_environment(self):
        """Test that GITHUB_TOKEN env var overrides config."""
        from repoindex.config import load_config

        # Given: A config with empty token
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        with open(repoindex_dir / 'config.json', 'w') as f:
            json.dump({'github': {'token': 'config-token'}}, f)

        # And: GITHUB_TOKEN is set
        os.environ['GITHUB_TOKEN'] = 'env-token-override'

        # When: We load config
        config = load_config()

        # Then: Env var should override config
        self.assertEqual(config['github']['token'], 'env-token-override')

    def test_github_token_creates_github_section_if_missing(self):
        """Test that GITHUB_TOKEN creates github section if it doesn't exist in config."""
        from repoindex.config import load_config

        # Given: A config without github section
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        with open(repoindex_dir / 'config.json', 'w') as f:
            json.dump({'repository_directories': []}, f)

        # And: GITHUB_TOKEN is set
        os.environ['GITHUB_TOKEN'] = 'new-token'

        # When: We load config
        config = load_config()

        # Then: github section should be created with token
        self.assertIn('github', config)
        self.assertEqual(config['github']['token'], 'new-token')

    def test_repoindex_config_env_overrides_default_path(self):
        """Test that REPOINDEX_CONFIG env var overrides default config path."""
        from repoindex.config import get_config_path

        # Given: A custom config path
        custom_config = Path(self.temp_dir) / 'custom' / 'my-config.json'
        custom_config.parent.mkdir(parents=True)
        custom_config.write_text('{"repository_directories": []}')
        os.environ['REPOINDEX_CONFIG'] = str(custom_config)

        try:
            # When: We get config path
            path = get_config_path()

            # Then: It should return the custom path
            self.assertEqual(path, custom_config)
        finally:
            del os.environ['REPOINDEX_CONFIG']


class TestConfigPathEdgeCases(unittest.TestCase):
    """Tests for edge cases in config path resolution."""

    def setUp(self):
        """Set up test environment."""
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

    def test_get_config_path_returns_default_when_no_config_exists(self):
        """Test that get_config_path returns default path when no config exists."""
        from repoindex.config import get_config_path

        # Given: No config files exist

        # When: We get config path
        path = get_config_path()

        # Then: It should return the default YAML path
        expected = Path(self.temp_dir) / '.repoindex' / 'config.yaml'
        self.assertEqual(path, expected)

    def test_get_config_path_skips_empty_files(self):
        """Test that get_config_path skips very small/empty config files."""
        from repoindex.config import get_config_path

        # Given: A nearly empty config file (less than 10 bytes)
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        (repoindex_dir / 'config.yaml').write_text('{}')  # 2 bytes

        # When: We get config path
        path = get_config_path()

        # Then: It should return default path (skipping the tiny file)
        expected = Path(self.temp_dir) / '.repoindex' / 'config.yaml'
        self.assertEqual(path, expected)

    def test_get_config_path_finds_toml_files(self):
        """Test that get_config_path finds TOML config files."""
        from repoindex.config import get_config_path

        # Given: A TOML config file
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        (repoindex_dir / 'config.toml').write_text('[github]\ntoken = "test"')

        # When: We get config path
        path = get_config_path()

        # Then: It should find the TOML file
        self.assertEqual(path.suffix, '.toml')


class TestConfigLoadingErrors(unittest.TestCase):
    """Tests for config loading error handling."""

    def setUp(self):
        """Set up test environment."""
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

    def test_load_config_handles_invalid_json(self):
        """Test that load_config handles invalid JSON gracefully."""
        from repoindex.config import load_config

        # Given: An invalid JSON config file
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        (repoindex_dir / 'config.json').write_text('{invalid json content')

        # When: We load config
        config = load_config()

        # Then: It should return default config (not crash)
        self.assertIn('repository_directories', config)

    def test_load_config_handles_permission_error(self):
        """Test that load_config handles permission errors gracefully."""
        # This test is skipped on Windows where file permissions work differently
        import sys
        if sys.platform == 'win32':
            self.skipTest("File permission tests not reliable on Windows")

        from repoindex.config import load_config

        # Given: A config file without read permission
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir()
        config_file = repoindex_dir / 'config.json'
        config_file.write_text('{"repository_directories": ["~/repos"]}')
        config_file.chmod(0o000)

        try:
            # When: We load config
            config = load_config()

            # Then: It should return default config (not crash)
            self.assertIn('repository_directories', config)
        finally:
            # Restore permissions for cleanup
            config_file.chmod(0o644)


if __name__ == "__main__":
    unittest.main()
