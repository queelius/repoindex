"""
Unit tests for repoindex.config module
"""
import unittest
import tempfile
import os
import shutil
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.config import (
    load_config,
    save_config,
    generate_config_example,
    get_default_config,
    get_repository_directories,
    get_exclude_directories
)


class TestConfigManagement(unittest.TestCase):
    """Test configuration management functionality"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_home = os.environ.get('HOME')
        os.environ['HOME'] = self.temp_dir

    def tearDown(self):
        """Clean up test environment"""
        if self.original_home:
            os.environ['HOME'] = self.original_home
        else:
            del os.environ['HOME']
        shutil.rmtree(self.temp_dir)

    def test_get_default_config(self):
        """Test default configuration structure"""
        config = get_default_config()

        # Check that all required sections exist
        self.assertIn('repository_directories', config)
        self.assertIn('exclude_directories', config)
        self.assertIn('github', config)
        self.assertIn('repository_tags', config)

        # Check repository_directories is empty list by default
        self.assertEqual(config['repository_directories'], [])

        # Check exclude_directories is empty list by default
        self.assertEqual(config['exclude_directories'], [])

        # Check GitHub config
        self.assertIn('token', config['github'])
        self.assertIn('rate_limit', config['github'])
        self.assertEqual(config['github']['token'], '')

    def test_load_config_no_file(self):
        """Test loading config when no file exists"""
        config = load_config()

        # Should return default config
        default_config = get_default_config()
        self.assertEqual(config['repository_directories'],
                        default_config['repository_directories'])
        self.assertEqual(config['github']['token'],
                        default_config['github']['token'])

    def test_load_config_json_file(self):
        """Test loading config from JSON file"""
        config_data = {
            'repository_directories': ['~/projects'],
            'registries': {'pypi': False, 'npm': True}
        }

        # Create .repoindex directory
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir(exist_ok=True)
        config_path = repoindex_dir / 'config.json'
        with open(config_path, 'w') as f:
            json.dump(config_data, f)

        config = load_config()

        self.assertEqual(config['repository_directories'], ['~/projects'])
        self.assertFalse(config['registries']['pypi'])
        self.assertTrue(config['registries']['npm'])

    def test_load_config_toml_file(self):
        """Test loading config from TOML file"""
        config_content = """
[github]
token = "test-token"

[registries]
pypi = false
npm = true
"""

        # Create .repoindex directory
        repoindex_dir = Path(self.temp_dir) / '.repoindex'
        repoindex_dir.mkdir(exist_ok=True)
        config_path = repoindex_dir / 'config.toml'
        config_path.write_text(config_content)

        config = load_config()

        self.assertEqual(config['github']['token'], 'test-token')
        self.assertFalse(config['registries']['pypi'])
        self.assertTrue(config['registries']['npm'])

    @patch.dict(os.environ, {'GITHUB_TOKEN': 'env-token-123'})
    def test_github_token_environment_override(self):
        """Test GITHUB_TOKEN environment variable override"""
        config = load_config()

        # Environment should override config file
        self.assertEqual(config['github']['token'], 'env-token-123')

    def test_save_config_yaml(self):
        """Test saving config to YAML file"""
        config_data = {
            'repository_directories': ['/path/to/repos'],
            'github': {'token': 'test-token'}
        }

        save_config(config_data)

        # Check in .repoindex directory (now saves as YAML)
        config_path = Path(self.temp_dir) / '.repoindex' / 'config.yaml'
        self.assertTrue(config_path.exists())

        import yaml
        with open(config_path, 'r') as f:
            saved_config = yaml.safe_load(f)

        self.assertEqual(saved_config['repository_directories'], ['/path/to/repos'])
        self.assertEqual(saved_config['github']['token'], 'test-token')

    def test_generate_config_example(self):
        """Test config example generation"""
        generate_config_example()

        config_path = Path(self.temp_dir) / '.repoindex' / 'config.example.yaml'
        self.assertTrue(config_path.exists())

        # Verify content contains expected sections
        content = config_path.read_text()
        self.assertIn('repository_directories', content)
        self.assertIn('github', content)
        self.assertIn('repository_tags', content)

    def test_get_repository_directories(self):
        """Test get_repository_directories helper"""
        config = {'repository_directories': ['/path1', '/path2']}
        dirs = get_repository_directories(config)
        self.assertEqual(dirs, ['/path1', '/path2'])

        # Empty config
        config = {}
        dirs = get_repository_directories(config)
        self.assertEqual(dirs, [])

    def test_get_exclude_directories(self):
        """Test get_exclude_directories helper"""
        config = {'exclude_directories': ['/excluded1', '/excluded2']}
        dirs = get_exclude_directories(config)
        self.assertEqual(dirs, ['/excluded1', '/excluded2'])

        # Empty config
        config = {}
        dirs = get_exclude_directories(config)
        self.assertEqual(dirs, [])

        # Config with empty list
        config = {'exclude_directories': []}
        dirs = get_exclude_directories(config)
        self.assertEqual(dirs, [])


class TestConfigValidation(unittest.TestCase):
    """Test configuration validation"""

    def test_merge_configs(self):
        """Test configuration merging"""
        from repoindex.config import merge_configs

        base_config = {
            'github': {'token': '', 'rate_limit': {'max_retries': 3}},
            'registries': {'pypi': True}
        }

        override_config = {
            'github': {'token': 'my-token'},
            'repository_directories': ['/new/path']
        }

        merged = merge_configs(base_config, override_config)

        # Should preserve base values not overridden
        self.assertEqual(merged['github']['rate_limit']['max_retries'], 3)
        self.assertTrue(merged['registries']['pypi'])

        # Should override specified values
        self.assertEqual(merged['github']['token'], 'my-token')

        # Should add new sections
        self.assertEqual(merged['repository_directories'], ['/new/path'])


if __name__ == '__main__':
    unittest.main()
