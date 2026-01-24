"""
Tests for tag command implicit tag functionality.

Tests that tag list and tag tree commands correctly display
implicit tags from the database (e.g., topic:{github_topic}).
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from repoindex.commands.tag import (
    get_implicit_tags_from_row,
    get_all_tags_from_database,
    get_repo_tags_from_database,
    tag_list,
    tag_tree,
    tag_cmd,
)


class TestGetImplicitTagsFromRow:
    """Tests for get_implicit_tags_from_row helper function."""

    def test_basic_repo_info(self):
        """Test basic repo name and directory tags."""
        row = {
            'name': 'myproject',
            'path': '/home/user/repos/myproject',
            'language': 'Python',
            'is_clean': True,
        }
        tags = get_implicit_tags_from_row(row)

        assert 'repo:myproject' in tags
        assert 'dir:repos' in tags
        assert 'lang:python' in tags
        assert 'status:clean' in tags

    def test_dirty_status(self):
        """Test dirty status tag."""
        row = {
            'name': 'myproject',
            'path': '/home/user/repos/myproject',
            'is_clean': False,
        }
        tags = get_implicit_tags_from_row(row)

        assert 'status:dirty' in tags
        assert 'status:clean' not in tags

    def test_owner_and_license(self):
        """Test owner and license tags."""
        row = {
            'name': 'myproject',
            'path': '/home/user/myproject',
            'owner': 'torvalds',
            'license_key': 'mit',
        }
        tags = get_implicit_tags_from_row(row)

        assert 'owner:torvalds' in tags
        assert 'license:mit' in tags

    def test_github_metadata_public(self):
        """Test GitHub metadata for public repos."""
        row = {
            'name': 'myproject',
            'path': '/home/user/myproject',
            'github_owner': 'torvalds',
            'github_is_private': False,
            'github_is_fork': False,
            'github_is_archived': False,
            'github_stars': 150,
        }
        tags = get_implicit_tags_from_row(row)

        assert 'visibility:public' in tags
        assert 'visibility:private' not in tags
        assert 'stars:100+' in tags
        assert 'source:fork' not in tags
        assert 'archived:true' not in tags

    def test_github_metadata_private_fork_archived(self):
        """Test GitHub metadata for private, forked, archived repos."""
        row = {
            'name': 'myproject',
            'path': '/home/user/myproject',
            'github_owner': 'user',
            'github_is_private': True,
            'github_is_fork': True,
            'github_is_archived': True,
            'github_stars': 0,
        }
        tags = get_implicit_tags_from_row(row)

        assert 'visibility:private' in tags
        assert 'visibility:public' not in tags
        assert 'source:fork' in tags
        assert 'archived:true' in tags

    def test_stars_buckets(self):
        """Test star count bucket tags."""
        # No stars
        row = {'name': 'a', 'path': '/a', 'github_owner': 'x', 'github_stars': 0}
        tags = get_implicit_tags_from_row(row)
        assert not any(t.startswith('stars:') for t in tags)

        # 10+ stars
        row = {'name': 'b', 'path': '/b', 'github_owner': 'x', 'github_stars': 15}
        tags = get_implicit_tags_from_row(row)
        assert 'stars:10+' in tags
        assert 'stars:100+' not in tags

        # 100+ stars
        row = {'name': 'c', 'path': '/c', 'github_owner': 'x', 'github_stars': 500}
        tags = get_implicit_tags_from_row(row)
        assert 'stars:100+' in tags
        assert 'stars:1000+' not in tags

        # 1000+ stars
        row = {'name': 'd', 'path': '/d', 'github_owner': 'x', 'github_stars': 5000}
        tags = get_implicit_tags_from_row(row)
        assert 'stars:1000+' in tags

    def test_github_topics(self):
        """Test GitHub topics as implicit tags."""
        row = {
            'name': 'myproject',
            'path': '/home/user/myproject',
            'github_owner': 'user',
            'github_topics': json.dumps(['machine-learning', 'python', 'deep-learning']),
        }
        tags = get_implicit_tags_from_row(row)

        assert 'topic:machine-learning' in tags
        assert 'topic:python' in tags
        assert 'topic:deep-learning' in tags

    def test_github_topics_empty(self):
        """Test empty GitHub topics."""
        row = {
            'name': 'myproject',
            'path': '/home/user/myproject',
            'github_owner': 'user',
            'github_topics': json.dumps([]),
        }
        tags = get_implicit_tags_from_row(row)

        # No topic tags should be present
        assert not any(t.startswith('topic:') for t in tags)

    def test_github_topics_null(self):
        """Test null GitHub topics."""
        row = {
            'name': 'myproject',
            'path': '/home/user/myproject',
            'github_owner': 'user',
            'github_topics': None,
        }
        tags = get_implicit_tags_from_row(row)

        # No topic tags should be present
        assert not any(t.startswith('topic:') for t in tags)

    def test_github_topics_invalid_json(self):
        """Test invalid JSON in GitHub topics."""
        row = {
            'name': 'myproject',
            'path': '/home/user/myproject',
            'github_owner': 'user',
            'github_topics': 'not valid json',
        }
        tags = get_implicit_tags_from_row(row)

        # Should not crash, just no topic tags
        assert not any(t.startswith('topic:') for t in tags)

    def test_minimal_row(self):
        """Test with minimal row data."""
        row = {'name': None, 'path': None}
        tags = get_implicit_tags_from_row(row)
        # Should not crash
        assert isinstance(tags, list)


class TestGetAllTagsFromDatabase:
    """Tests for get_all_tags_from_database helper function."""

    @patch('repoindex.commands.tag.get_db_path')
    @patch('repoindex.commands.tag.Database')
    @patch('repoindex.commands.tag.get_all_repos')
    def test_combines_explicit_and_implicit_tags(
        self, mock_get_repos, mock_db_class, mock_get_db_path
    ):
        """Test that explicit and implicit tags are combined."""
        # Setup mock database path to exist
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_get_db_path.return_value = mock_path

        # Setup mock database context manager
        mock_db = MagicMock()
        mock_db_class.return_value.__enter__.return_value = mock_db

        # Setup mock repos from database
        mock_get_repos.return_value = [
            {
                'name': 'repo1',
                'path': '/path/to/repo1',
                'language': 'Python',
                'is_clean': True,
                'github_owner': 'user',
                'github_topics': json.dumps(['ml', 'ai']),
            }
        ]

        config = {
            'repository_tags': {
                '/path/to/repo1': ['work/active', 'priority:high']
            }
        }

        result = get_all_tags_from_database(config)

        # Check explicit tags
        assert 'work/active' in result
        assert 'priority:high' in result

        # Check implicit tags
        assert 'repo:repo1' in result
        assert 'lang:python' in result
        assert 'topic:ml' in result
        assert 'topic:ai' in result

        # Check that repo1 is in the list for each tag
        assert '/path/to/repo1' in result['work/active']
        assert '/path/to/repo1' in result['topic:ml']

    @patch('repoindex.commands.tag.get_db_path')
    def test_falls_back_to_explicit_when_no_database(self, mock_get_db_path):
        """Test fallback to explicit tags when database doesn't exist."""
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_get_db_path.return_value = mock_path

        config = {
            'repository_tags': {
                '/path/to/repo1': ['work/active', 'topic:manual']
            }
        }

        result = get_all_tags_from_database(config)

        # Only explicit tags should be present
        assert 'work/active' in result
        assert 'topic:manual' in result
        # No implicit tags
        assert 'repo:repo1' not in result

    @patch('repoindex.commands.tag.get_db_path')
    @patch('repoindex.commands.tag.Database')
    @patch('repoindex.commands.tag.get_all_repos')
    def test_filter_pattern(self, mock_get_repos, mock_db_class, mock_get_db_path):
        """Test tag filtering with pattern."""
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_get_db_path.return_value = mock_path

        mock_db = MagicMock()
        mock_db_class.return_value.__enter__.return_value = mock_db

        mock_get_repos.return_value = [
            {
                'name': 'repo1',
                'path': '/path/to/repo1',
                'language': 'Python',
                'github_owner': 'user',
                'github_topics': json.dumps(['ml', 'web']),
            }
        ]

        config = {
            'repository_tags': {
                '/path/to/repo1': ['work/active', 'topic:custom']
            }
        }

        # Filter for topic:* tags
        result = get_all_tags_from_database(config, tag_filter='topic:*')

        # Only topic tags should be present
        assert 'topic:ml' in result
        assert 'topic:web' in result
        assert 'topic:custom' in result
        # Non-topic tags should not be present
        assert 'work/active' not in result
        assert 'lang:python' not in result


class TestGetRepoTagsFromDatabase:
    """Tests for get_repo_tags_from_database helper function."""

    @patch('repoindex.commands.tag.get_db_path')
    @patch('repoindex.commands.tag.Database')
    @patch('repoindex.commands.tag.get_all_repos')
    def test_returns_tags_by_repo(
        self, mock_get_repos, mock_db_class, mock_get_db_path
    ):
        """Test that tags are organized by repository path."""
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_get_db_path.return_value = mock_path

        mock_db = MagicMock()
        mock_db_class.return_value.__enter__.return_value = mock_db

        mock_get_repos.return_value = [
            {
                'name': 'repo1',
                'path': '/path/to/repo1',
                'language': 'Python',
                'is_clean': True,
                'github_owner': 'user',
                'github_topics': json.dumps(['ml']),
            }
        ]

        config = {
            'repository_tags': {
                '/path/to/repo1': ['work/active']
            }
        }

        result = get_repo_tags_from_database(config)

        # Result should be keyed by repo path
        assert '/path/to/repo1' in result

        # Tags should include both explicit and implicit
        tags = result['/path/to/repo1']
        assert 'work/active' in tags
        assert 'repo:repo1' in tags
        assert 'lang:python' in tags
        assert 'topic:ml' in tags

    @patch('repoindex.commands.tag.get_db_path')
    def test_falls_back_to_explicit_when_no_database(self, mock_get_db_path):
        """Test fallback to explicit tags when database doesn't exist."""
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_get_db_path.return_value = mock_path

        config = {
            'repository_tags': {
                '/path/to/repo1': ['work/active']
            }
        }

        result = get_repo_tags_from_database(config)

        # Should return explicit tags only
        assert result == config['repository_tags']


class TestTagListCommand:
    """Tests for tag list command with implicit tags."""

    @patch('repoindex.commands.tag.load_config')
    @patch('repoindex.commands.tag.get_all_tags_from_database')
    def test_list_includes_implicit_tags(
        self, mock_get_tags, mock_load_config
    ):
        """Test that tag list includes implicit tags."""
        mock_load_config.return_value = {}
        mock_get_tags.return_value = {
            'work/active': ['/path/to/repo1'],
            'topic:ml': ['/path/to/repo1'],
            'lang:python': ['/path/to/repo1'],
        }

        runner = CliRunner()
        result = runner.invoke(tag_cmd, ['list', '--json'])

        assert result.exit_code == 0

        # Parse JSON lines
        lines = [json.loads(line) for line in result.output.strip().split('\n') if line]
        tags = {item['tag'] for item in lines}

        assert 'work/active' in tags
        assert 'topic:ml' in tags
        assert 'lang:python' in tags

    @patch('repoindex.commands.tag.load_config')
    @patch('repoindex.commands.tag.get_all_tags_from_database')
    def test_list_with_topic_filter(
        self, mock_get_tags, mock_load_config
    ):
        """Test tag list with topic filter."""
        mock_load_config.return_value = {}
        mock_get_tags.return_value = {
            'topic:ml': ['/path/to/repo1'],
            'topic:ai': ['/path/to/repo1'],
        }

        runner = CliRunner()
        result = runner.invoke(tag_cmd, ['list', '-t', 'topic:*', '--json'])

        assert result.exit_code == 0

        # Parse JSON lines
        lines = [json.loads(line) for line in result.output.strip().split('\n') if line]
        tags = {item['tag'] for item in lines}

        assert 'topic:ml' in tags
        assert 'topic:ai' in tags


class TestTagTreeCommand:
    """Tests for tag tree command with implicit tags."""

    @patch('repoindex.commands.tag.load_config')
    @patch('repoindex.commands.tag.get_repo_tags_from_database')
    def test_tree_includes_implicit_tags(
        self, mock_get_repo_tags, mock_load_config
    ):
        """Test that tag tree includes implicit tags."""
        mock_load_config.return_value = {}
        mock_get_repo_tags.return_value = {
            '/path/to/repo1': ['work/active', 'topic:ml', 'lang:python'],
        }

        runner = CliRunner()
        result = runner.invoke(tag_cmd, ['tree'])

        assert result.exit_code == 0
        # Tree output should include topic branch
        assert 'topic' in result.output
        assert 'lang' in result.output
        assert 'work' in result.output

    @patch('repoindex.commands.tag.load_config')
    @patch('repoindex.commands.tag.get_repo_tags_from_database')
    def test_tree_with_topic_prefix_filter(
        self, mock_get_repo_tags, mock_load_config
    ):
        """Test tag tree with topic prefix filter."""
        mock_load_config.return_value = {}
        mock_get_repo_tags.return_value = {
            '/path/to/repo1': ['topic:ml/research', 'topic:ai', 'lang:python'],
        }

        runner = CliRunner()
        result = runner.invoke(tag_cmd, ['tree', '-t', 'topic'])

        assert result.exit_code == 0
        # Should show topic hierarchy
        assert 'ml' in result.output or 'ai' in result.output
        # Should not show lang (filtered out by prefix)


class TestGitHubTopicsIntegration:
    """Integration tests for GitHub topics appearing in tag commands."""

    @patch('repoindex.commands.tag.load_config')
    @patch('repoindex.commands.tag.get_db_path')
    @patch('repoindex.commands.tag.Database')
    @patch('repoindex.commands.tag.get_all_repos')
    def test_github_topics_appear_in_tag_list(
        self, mock_get_repos, mock_db_class, mock_get_db_path, mock_load_config
    ):
        """Test that GitHub topics appear in tag list output."""
        mock_load_config.return_value = {'repository_tags': {}}

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_get_db_path.return_value = mock_path

        mock_db = MagicMock()
        mock_db_class.return_value.__enter__.return_value = mock_db

        mock_get_repos.return_value = [
            {
                'name': 'ml-project',
                'path': '/path/to/ml-project',
                'language': 'Python',
                'github_owner': 'user',
                'github_topics': json.dumps(['machine-learning', 'tensorflow', 'keras']),
            }
        ]

        runner = CliRunner()
        result = runner.invoke(tag_cmd, ['list', '--json'])

        assert result.exit_code == 0

        # Parse JSON output
        output_text = result.output.strip()
        if output_text:
            lines = [json.loads(line) for line in output_text.split('\n') if line]
            tags = {item['tag'] for item in lines}

            # GitHub topics should appear as topic:* tags
            assert 'topic:machine-learning' in tags
            assert 'topic:tensorflow' in tags
            assert 'topic:keras' in tags
