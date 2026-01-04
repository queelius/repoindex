"""
Tests for repoindex.vfs_utils module.

Tests focus on:
- VFS structure building
- Config node population
- Path resolution
- Tag hierarchy parsing
"""

import unittest
from unittest.mock import patch, MagicMock


class TestBuildConfigVFS(unittest.TestCase):
    """Tests for _build_config_vfs function."""

    def test_build_config_vfs_adds_repos_node(self):
        """Test that config VFS includes repository directories."""
        from repoindex.vfs_utils import _build_config_vfs

        # Given: A config with repository directories
        config = {
            'repository_directories': ['~/github/**', '~/projects']
        }
        config_node = {}

        # When: We build the config VFS
        _build_config_vfs(config_node, config)

        # Then: repos node should exist with entries
        self.assertIn('repos', config_node)
        self.assertEqual(config_node['repos']['type'], 'directory')
        self.assertIn('children', config_node['repos'])

    def test_build_config_vfs_masks_github_token(self):
        """Test that GitHub token is masked in VFS."""
        from repoindex.vfs_utils import _build_config_vfs

        # Given: A config with a GitHub token
        config = {
            'repository_directories': [],
            'github': {
                'token': 'ghp_abcdefghijklmnop1234567890'
            }
        }
        config_node = {}

        # When: We build the config VFS
        _build_config_vfs(config_node, config)

        # Then: Token should be masked
        token_value = config_node['github']['children']['token']['value']
        self.assertIn('...', token_value)
        # Should show first 4 and last 4 chars
        self.assertTrue(token_value.startswith('ghp_'))
        self.assertNotEqual(token_value, 'ghp_abcdefghijklmnop1234567890')

    def test_build_config_vfs_masks_short_token(self):
        """Test that short tokens are fully masked."""
        from repoindex.vfs_utils import _build_config_vfs

        # Given: A config with a short token
        config = {
            'repository_directories': [],
            'github': {
                'token': 'short'
            }
        }
        config_node = {}

        # When: We build the config VFS
        _build_config_vfs(config_node, config)

        # Then: Token should be fully masked
        token_value = config_node['github']['children']['token']['value']
        self.assertEqual(token_value, '***')

    def test_build_config_vfs_adds_rate_limit_settings(self):
        """Test that rate limit settings are included."""
        from repoindex.vfs_utils import _build_config_vfs

        # Given: A config with rate limit settings
        config = {
            'repository_directories': [],
            'github': {
                'rate_limit': {
                    'max_retries': 3,
                    'max_delay_seconds': 60,
                    'respect_reset_time': True
                }
            }
        }
        config_node = {}

        # When: We build the config VFS
        _build_config_vfs(config_node, config)

        # Then: Rate limit settings should be present
        rate_limit = config_node['github']['children']['rate_limit']
        self.assertEqual(rate_limit['type'], 'directory')
        self.assertIn('max_retries', rate_limit['children'])
        self.assertEqual(rate_limit['children']['max_retries']['value'], '3')

    def test_build_config_vfs_handles_empty_token(self):
        """Test handling of empty GitHub token."""
        from repoindex.vfs_utils import _build_config_vfs

        # Given: A config with empty token
        config = {
            'repository_directories': [],
            'github': {
                'token': ''
            }
        }
        config_node = {}

        # When: We build the config VFS
        _build_config_vfs(config_node, config)

        # Then: Token should still be masked
        token_value = config_node['github']['children']['token']['value']
        self.assertEqual(token_value, '***')


class TestBuildVFSStructure(unittest.TestCase):
    """Tests for build_vfs_structure function."""

    def test_build_vfs_structure_creates_root_directories(self):
        """Test that VFS has expected root directories."""
        from repoindex.vfs_utils import build_vfs_structure

        # When: We build VFS structure
        with patch('repoindex.vfs_utils.find_git_repos_from_config') as mock_find:
            mock_find.return_value = []
            with patch('repoindex.vfs_utils.get_metadata_store') as mock_store:
                mock_store.return_value.get.return_value = None

                vfs = build_vfs_structure({'repository_directories': []})

        # Then: Root should have expected directories
        root_children = vfs['/']['children']
        self.assertIn('repos', root_children)
        self.assertIn('by-language', root_children)
        self.assertIn('by-tag', root_children)
        self.assertIn('by-status', root_children)
        self.assertIn('config', root_children)

    def test_build_vfs_structure_uses_current_dir_when_empty_config(self):
        """Test that current directory is used when config is empty."""
        from repoindex.vfs_utils import build_vfs_structure

        # When: We build VFS with empty config
        with patch('repoindex.vfs_utils.find_git_repos_from_config') as mock_find:
            mock_find.return_value = []
            with patch('repoindex.vfs_utils.get_metadata_store') as mock_store:
                mock_store.return_value.get.return_value = None

                vfs = build_vfs_structure({'repository_directories': []})

        # Then: find_git_repos_from_config should be called with ['.']
        mock_find.assert_called_with(['.'], recursive=False)

    def test_build_vfs_structure_adds_repos_to_repos_node(self):
        """Test that discovered repos are added to /repos."""
        from repoindex.vfs_utils import build_vfs_structure

        # Given: Some discovered repos
        with patch('repoindex.vfs_utils.find_git_repos_from_config') as mock_find:
            mock_find.return_value = ['/home/user/repos/project-a', '/home/user/repos/project-b']
            with patch('repoindex.vfs_utils.get_metadata_store') as mock_store:
                mock_store.return_value.get.return_value = {}
                with patch('repoindex.vfs_utils.get_repository_tags') as mock_tags:
                    mock_tags.return_value = []

                    vfs = build_vfs_structure({'repository_directories': ['~/repos/**']})

        # Then: Repos should be in /repos
        repos_node = vfs['/']['children']['repos']['children']
        self.assertIn('project-a', repos_node)
        self.assertIn('project-b', repos_node)
        self.assertEqual(repos_node['project-a']['type'], 'repository')

    def test_build_vfs_structure_groups_by_language(self):
        """Test that repos are grouped by language."""
        from repoindex.vfs_utils import build_vfs_structure

        # Given: Repos with different languages
        with patch('repoindex.vfs_utils.find_git_repos_from_config') as mock_find:
            mock_find.return_value = ['/repos/python-proj', '/repos/go-proj']
            with patch('repoindex.vfs_utils.get_metadata_store') as mock_store:
                def get_metadata(path):
                    if 'python' in path:
                        return {'language': 'Python'}
                    return {'language': 'Go'}
                mock_store.return_value.get.side_effect = get_metadata
                with patch('repoindex.vfs_utils.get_repository_tags') as mock_tags:
                    mock_tags.return_value = []

                    vfs = build_vfs_structure({'repository_directories': ['~/repos/**']})

        # Then: Repos should be grouped by language
        by_lang = vfs['/']['children']['by-language']['children']
        self.assertIn('Python', by_lang)
        self.assertIn('Go', by_lang)
        self.assertIn('python-proj', by_lang['Python']['children'])

    def test_build_vfs_structure_groups_by_status(self):
        """Test that repos are grouped by clean/dirty status."""
        from repoindex.vfs_utils import build_vfs_structure

        # Given: Repos with different statuses
        with patch('repoindex.vfs_utils.find_git_repos_from_config') as mock_find:
            mock_find.return_value = ['/repos/clean-repo', '/repos/dirty-repo']
            with patch('repoindex.vfs_utils.get_metadata_store') as mock_store:
                def get_metadata(path):
                    if 'dirty' in path:
                        return {'status': {'has_uncommitted_changes': True}}
                    return {'status': {'has_uncommitted_changes': False}}
                mock_store.return_value.get.side_effect = get_metadata
                with patch('repoindex.vfs_utils.get_repository_tags') as mock_tags:
                    mock_tags.return_value = []

                    vfs = build_vfs_structure({'repository_directories': ['~/repos/**']})

        # Then: Repos should be grouped by status
        by_status = vfs['/']['children']['by-status']['children']
        self.assertIn('clean', by_status)
        self.assertIn('dirty', by_status)


class TestParseTagLevels(unittest.TestCase):
    """Tests for _parse_tag_levels function."""

    def test_parse_simple_tag(self):
        """Test parsing a simple single-level tag."""
        from repoindex.vfs_utils import _parse_tag_levels

        result = _parse_tag_levels("work")
        self.assertEqual(result, ["work"])

    def test_parse_hierarchical_tag_with_slash(self):
        """Test parsing a tag with / separator."""
        from repoindex.vfs_utils import _parse_tag_levels

        result = _parse_tag_levels("alex/beta")
        self.assertEqual(result, ["alex", "beta"])

    def test_parse_namespaced_tag_with_colon(self):
        """Test parsing a tag with : namespace separator."""
        from repoindex.vfs_utils import _parse_tag_levels

        result = _parse_tag_levels("lang:python")
        self.assertEqual(result, ["lang", "python"])

    def test_parse_mixed_colon_and_slash(self):
        """Test parsing a tag with both : and / separators."""
        from repoindex.vfs_utils import _parse_tag_levels

        result = _parse_tag_levels("topic:ml/research")
        self.assertEqual(result, ["topic", "ml", "research"])

    def test_parse_empty_tag(self):
        """Test parsing an empty tag."""
        from repoindex.vfs_utils import _parse_tag_levels

        result = _parse_tag_levels("")
        self.assertEqual(result, [])

    def test_parse_tag_with_only_colon(self):
        """Test parsing a tag with colon but no value."""
        from repoindex.vfs_utils import _parse_tag_levels

        result = _parse_tag_levels("lang:")
        self.assertEqual(result, ["lang"])

    def test_parse_multi_level_slash_tag(self):
        """Test parsing a deeply nested slash tag."""
        from repoindex.vfs_utils import _parse_tag_levels

        result = _parse_tag_levels("org/team/project")
        self.assertEqual(result, ["org", "team", "project"])


class TestAddTagToVFS(unittest.TestCase):
    """Tests for _add_tag_to_vfs function."""

    def test_add_simple_tag(self):
        """Test adding a simple tag to VFS."""
        from repoindex.vfs_utils import _add_tag_to_vfs

        vfs_node = {}
        _add_tag_to_vfs(vfs_node, "work", "my-repo", "/path/to/repo")

        self.assertIn("work", vfs_node)
        self.assertIn("my-repo", vfs_node["work"]["children"])
        self.assertEqual(vfs_node["work"]["children"]["my-repo"]["type"], "symlink")

    def test_add_hierarchical_tag(self):
        """Test adding a hierarchical tag creates nested structure."""
        from repoindex.vfs_utils import _add_tag_to_vfs

        vfs_node = {}
        _add_tag_to_vfs(vfs_node, "alex/beta", "test-repo", "/path/to/repo")

        self.assertIn("alex", vfs_node)
        self.assertIn("beta", vfs_node["alex"]["children"])
        self.assertIn("test-repo", vfs_node["alex"]["children"]["beta"]["children"])

    def test_add_multiple_repos_to_same_tag(self):
        """Test adding multiple repos to the same tag."""
        from repoindex.vfs_utils import _add_tag_to_vfs

        vfs_node = {}
        _add_tag_to_vfs(vfs_node, "work", "repo-a", "/path/to/a")
        _add_tag_to_vfs(vfs_node, "work", "repo-b", "/path/to/b")

        self.assertEqual(len(vfs_node["work"]["children"]), 2)
        self.assertIn("repo-a", vfs_node["work"]["children"])
        self.assertIn("repo-b", vfs_node["work"]["children"])


class TestResolveVFSPath(unittest.TestCase):
    """Tests for resolve_vfs_path function."""

    def _create_sample_vfs(self):
        """Create a sample VFS structure for testing."""
        return {
            "/": {
                "type": "directory",
                "children": {
                    "repos": {
                        "type": "directory",
                        "children": {
                            "project-a": {
                                "type": "repository",
                                "path": "/home/user/repos/project-a"
                            },
                            "project-b": {
                                "type": "repository",
                                "path": "/home/user/repos/project-b"
                            }
                        }
                    },
                    "by-tag": {
                        "type": "directory",
                        "children": {
                            "alex": {
                                "type": "directory",
                                "children": {
                                    "beta": {
                                        "type": "directory",
                                        "children": {
                                            "project-a": {
                                                "type": "symlink",
                                                "target": "/repos/project-a"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "config": {
                        "type": "directory",
                        "children": {}
                    }
                }
            }
        }

    def test_resolve_root_path(self):
        """Test resolving the root path."""
        from repoindex.vfs_utils import resolve_vfs_path

        vfs = self._create_sample_vfs()
        result = resolve_vfs_path(vfs, "/")

        self.assertEqual(result, vfs["/"])

    def test_resolve_repos_directory(self):
        """Test resolving /repos directory."""
        from repoindex.vfs_utils import resolve_vfs_path

        vfs = self._create_sample_vfs()
        result = resolve_vfs_path(vfs, "/repos")

        self.assertEqual(result["type"], "directory")
        self.assertIn("project-a", result["children"])

    def test_resolve_specific_repo(self):
        """Test resolving a specific repository path."""
        from repoindex.vfs_utils import resolve_vfs_path

        vfs = self._create_sample_vfs()
        result = resolve_vfs_path(vfs, "/repos/project-a")

        self.assertEqual(result["type"], "repository")
        self.assertEqual(result["path"], "/home/user/repos/project-a")

    def test_resolve_nested_tag_path(self):
        """Test resolving a nested path under /by-tag."""
        from repoindex.vfs_utils import resolve_vfs_path

        vfs = self._create_sample_vfs()
        result = resolve_vfs_path(vfs, "/by-tag/alex/beta")

        self.assertEqual(result["type"], "directory")
        self.assertIn("project-a", result["children"])

    def test_resolve_nonexistent_path(self):
        """Test resolving a path that doesn't exist."""
        from repoindex.vfs_utils import resolve_vfs_path

        vfs = self._create_sample_vfs()
        result = resolve_vfs_path(vfs, "/nonexistent/path")

        self.assertIsNone(result)

    def test_resolve_path_strips_trailing_slash(self):
        """Test that trailing slashes are handled correctly."""
        from repoindex.vfs_utils import resolve_vfs_path

        vfs = self._create_sample_vfs()
        result = resolve_vfs_path(vfs, "/repos/")

        self.assertEqual(result["type"], "directory")

    def test_resolve_cannot_descend_into_repository(self):
        """Test that we can't resolve paths under a repository node."""
        from repoindex.vfs_utils import resolve_vfs_path

        vfs = self._create_sample_vfs()
        result = resolve_vfs_path(vfs, "/repos/project-a/subpath")

        self.assertIsNone(result)

    def test_resolve_path_without_leading_slash(self):
        """Test resolving a path without leading slash."""
        from repoindex.vfs_utils import resolve_vfs_path

        vfs = self._create_sample_vfs()
        result = resolve_vfs_path(vfs, "repos/project-a")

        self.assertEqual(result["type"], "repository")


if __name__ == "__main__":
    unittest.main()
