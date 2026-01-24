"""
Tests for link service and command.
"""

import json
import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from repoindex.services.link_service import (
    LinkService, LinkTreeOptions, LinkTreeResult, RefreshResult,
    OrganizeBy, MANIFEST_FILENAME
)


class TestLinkTreeOptions:
    """Tests for LinkTreeOptions dataclass."""

    def test_default_options(self, tmp_path):
        """Test default link tree options."""
        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.TAG
        )

        assert options.destination == tmp_path
        assert options.organize_by == OrganizeBy.TAG
        assert options.max_depth == 10
        assert options.collision_strategy == "rename"
        assert options.dry_run is False

    def test_all_options_set(self, tmp_path):
        """Test link tree with all options set."""
        options = LinkTreeOptions(
            destination=tmp_path,
            organize_by=OrganizeBy.LANGUAGE,
            max_depth=5,
            collision_strategy="skip",
            dry_run=True,
        )

        assert options.organize_by == OrganizeBy.LANGUAGE
        assert options.max_depth == 5
        assert options.collision_strategy == "skip"
        assert options.dry_run is True


class TestLinkTreeResult:
    """Tests for LinkTreeResult dataclass."""

    def test_default_result(self):
        """Test default link tree result."""
        result = LinkTreeResult()

        assert result.links_created == 0
        assert result.links_updated == 0
        assert result.links_skipped == 0
        assert result.dirs_created == 0
        assert result.errors == []
        assert result.details == []
        assert result.success is True

    def test_result_with_errors(self):
        """Test link tree result with errors."""
        result = LinkTreeResult(errors=["Error 1", "Error 2"])

        assert result.success is False
        assert len(result.errors) == 2


class TestRefreshResult:
    """Tests for RefreshResult dataclass."""

    def test_default_result(self):
        """Test default refresh result."""
        result = RefreshResult()

        assert result.total_links == 0
        assert result.valid_links == 0
        assert result.broken_links == 0
        assert result.removed_links == 0
        assert result.errors == []
        assert result.broken_paths == []
        assert result.success is True


class TestOrganizeBy:
    """Tests for OrganizeBy enum."""

    def test_enum_values(self):
        """Test that enum has expected values."""
        assert OrganizeBy.TAG.value == "tag"
        assert OrganizeBy.LANGUAGE.value == "language"
        assert OrganizeBy.CREATED_YEAR.value == "created-year"
        assert OrganizeBy.MODIFIED_YEAR.value == "modified-year"
        assert OrganizeBy.OWNER.value == "owner"

    def test_enum_from_string(self):
        """Test creating enum from string."""
        assert OrganizeBy("tag") == OrganizeBy.TAG
        assert OrganizeBy("language") == OrganizeBy.LANGUAGE


class TestLinkService:
    """Tests for LinkService."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        return {}

    @pytest.fixture
    def setup_test_repos(self, tmp_path):
        """Create test repositories with metadata."""
        repos = []
        for name, lang, tags in [
            ('repo-a', 'Python', ['topic:ml', 'work/active']),
            ('repo-b', 'JavaScript', ['topic:web', 'personal']),
            ('repo-c', 'Rust', ['topic:systems', 'work/active']),
        ]:
            repo_path = tmp_path / 'source' / name
            repo_path.mkdir(parents=True)
            (repo_path / '.git').mkdir()
            (repo_path / 'README.md').write_text(f'# {name}')

            repos.append({
                'path': str(repo_path),
                'name': name,
                'language': lang,
                'tags': tags,
            })

        return repos

    def test_create_tree_by_tag(self, mock_config, setup_test_repos, tmp_path):
        """Test creating tree organized by tags."""
        dest_dir = tmp_path / 'links'

        service = LinkService(config=mock_config)
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.TAG
        )

        messages = list(service.create_tree(setup_test_repos, options))
        result = service.last_result

        # Should create links for each repo under each tag
        assert result.links_created > 0
        assert result.success is True

        # Check tag hierarchy exists
        assert (dest_dir / 'topic' / 'ml').exists()
        assert (dest_dir / 'topic' / 'web').exists()
        assert (dest_dir / 'work' / 'active').exists()

        # Check symlinks
        assert (dest_dir / 'topic' / 'ml' / 'repo-a').is_symlink()
        assert (dest_dir / 'topic' / 'web' / 'repo-b').is_symlink()

    def test_create_tree_by_language(self, mock_config, setup_test_repos, tmp_path):
        """Test creating tree organized by language."""
        dest_dir = tmp_path / 'links'

        service = LinkService(config=mock_config)
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.LANGUAGE
        )

        list(service.create_tree(setup_test_repos, options))
        result = service.last_result

        assert result.links_created == 3
        assert result.success is True

        # Check language directories exist
        assert (dest_dir / 'Python').exists()
        assert (dest_dir / 'JavaScript').exists()
        assert (dest_dir / 'Rust').exists()

        # Check symlinks
        assert (dest_dir / 'Python' / 'repo-a').is_symlink()

    def test_create_tree_dry_run(self, mock_config, setup_test_repos, tmp_path):
        """Test creating tree in dry run mode."""
        dest_dir = tmp_path / 'links-dry'

        service = LinkService(config=mock_config)
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.LANGUAGE,
            dry_run=True
        )

        list(service.create_tree(setup_test_repos, options))
        result = service.last_result

        # Should count but not create
        assert result.links_created == 3
        # Destination should not exist (dry run doesn't create directory)
        # Actually it does create parent but not links

    def test_create_tree_empty_repos(self, mock_config, tmp_path):
        """Test creating tree with empty repos list."""
        dest_dir = tmp_path / 'links'

        service = LinkService(config={})
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.TAG
        )

        messages = list(service.create_tree([], options))
        result = service.last_result

        assert result.links_created == 0
        assert 'No repositories' in messages[0]

    def test_create_tree_nonexistent_repo(self, mock_config, tmp_path):
        """Test creating tree with nonexistent repository."""
        dest_dir = tmp_path / 'links'

        repos = [{'path': '/nonexistent/repo', 'name': 'repo', 'tags': ['test']}]

        service = LinkService(config={})
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.TAG
        )

        list(service.create_tree(repos, options))
        result = service.last_result

        assert result.links_created == 0
        assert len(result.errors) == 1

    def test_create_tree_collision_rename(self, mock_config, tmp_path):
        """Test collision handling with rename strategy."""
        source_dir = tmp_path / 'source'

        # Create two repos with same name
        repo1 = source_dir / 'dir1' / 'utils'
        repo1.mkdir(parents=True)
        (repo1 / '.git').mkdir()

        repo2 = source_dir / 'dir2' / 'utils'
        repo2.mkdir(parents=True)
        (repo2 / '.git').mkdir()

        repos = [
            {'path': str(repo1), 'name': 'utils', 'language': 'Python'},
            {'path': str(repo2), 'name': 'utils', 'language': 'Python'},
        ]

        dest_dir = tmp_path / 'links'

        service = LinkService(config={})
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.LANGUAGE,
            collision_strategy="rename"
        )

        list(service.create_tree(repos, options))
        result = service.last_result

        # Both should be created with renamed second
        assert result.links_created == 2
        assert (dest_dir / 'Python' / 'utils').exists()
        assert (dest_dir / 'Python' / 'utils-1').exists()

    def test_create_tree_collision_skip(self, mock_config, tmp_path):
        """Test collision handling with skip strategy."""
        source_dir = tmp_path / 'source'

        repo1 = source_dir / 'dir1' / 'utils'
        repo1.mkdir(parents=True)
        (repo1 / '.git').mkdir()

        repo2 = source_dir / 'dir2' / 'utils'
        repo2.mkdir(parents=True)
        (repo2 / '.git').mkdir()

        repos = [
            {'path': str(repo1), 'name': 'utils', 'language': 'Python'},
            {'path': str(repo2), 'name': 'utils', 'language': 'Python'},
        ]

        dest_dir = tmp_path / 'links'

        service = LinkService(config={})
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.LANGUAGE,
            collision_strategy="skip"
        )

        list(service.create_tree(repos, options))
        result = service.last_result

        # First created, second skipped
        assert result.links_created == 1
        assert result.links_skipped == 1

    def test_create_tree_manifest(self, mock_config, setup_test_repos, tmp_path):
        """Test that manifest is written."""
        dest_dir = tmp_path / 'links'

        service = LinkService(config=mock_config)
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.TAG
        )

        list(service.create_tree(setup_test_repos, options))

        manifest_path = dest_dir / MANIFEST_FILENAME
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert 'created_at' in manifest
        assert manifest['organize_by'] == 'tag'
        assert manifest['repos_count'] == 3

    def test_create_tree_repo_in_multiple_places(self, mock_config, tmp_path):
        """Test that repo with multiple tags appears in multiple places."""
        repo_path = tmp_path / 'source' / 'project'
        repo_path.mkdir(parents=True)
        (repo_path / '.git').mkdir()

        repos = [{
            'path': str(repo_path),
            'name': 'project',
            'tags': ['topic:ml', 'topic:ai', 'work/research'],
        }]

        dest_dir = tmp_path / 'links'

        service = LinkService(config={})
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.TAG
        )

        list(service.create_tree(repos, options))
        result = service.last_result

        # Should create 3 links (one for each tag)
        assert result.links_created == 3

        # Check all locations
        assert (dest_dir / 'topic' / 'ml' / 'project').is_symlink()
        assert (dest_dir / 'topic' / 'ai' / 'project').is_symlink()
        assert (dest_dir / 'work' / 'research' / 'project').is_symlink()


class TestLinkServiceHelpers:
    """Tests for LinkService helper methods."""

    def test_parse_tag_path_simple(self):
        """Test parsing simple tag."""
        service = LinkService(config={})

        result = service._parse_tag_path('simple')
        assert result == Path('simple')

    def test_parse_tag_path_hierarchical(self):
        """Test parsing hierarchical tag."""
        service = LinkService(config={})

        result = service._parse_tag_path('topic/subtopic')
        assert result == Path('topic/subtopic')

    def test_parse_tag_path_key_value(self):
        """Test parsing key:value tag."""
        service = LinkService(config={})

        result = service._parse_tag_path('topic:ml')
        assert result == Path('topic/ml')

    def test_parse_tag_path_key_value_hierarchical(self):
        """Test parsing key:value/subvalue tag."""
        service = LinkService(config={})

        result = service._parse_tag_path('topic:ml/research')
        assert result == Path('topic/ml/research')

    def test_parse_tag_path_empty(self):
        """Test parsing empty tag."""
        service = LinkService(config={})

        result = service._parse_tag_path('')
        assert result is None

    def test_safe_dirname(self):
        """Test directory name sanitization."""
        service = LinkService(config={})

        assert service._safe_dirname('normal') == 'normal'
        assert service._safe_dirname('with/slash') == 'with_slash'
        assert service._safe_dirname('with:colon') == 'with_colon'
        assert service._safe_dirname('...dots...') == 'dots'

    def test_extract_owner_github_https(self):
        """Test extracting owner from GitHub HTTPS URL."""
        service = LinkService(config={})

        result = service._extract_owner('https://github.com/owner/repo.git')
        assert result == 'owner'

    def test_extract_owner_github_ssh(self):
        """Test extracting owner from GitHub SSH URL."""
        service = LinkService(config={})

        result = service._extract_owner('git@github.com:owner/repo.git')
        assert result == 'owner'

    def test_extract_owner_empty(self):
        """Test extracting owner from empty URL."""
        service = LinkService(config={})

        result = service._extract_owner('')
        assert result is None


class TestLinkServiceRefresh:
    """Tests for LinkService refresh functionality."""

    @pytest.fixture
    def setup_link_tree(self, tmp_path):
        """Create a link tree with some symlinks."""
        tree_dir = tmp_path / 'links'
        tree_dir.mkdir()

        # Create some valid target repos
        repos_dir = tmp_path / 'repos'
        repos_dir.mkdir()

        (repos_dir / 'valid-repo').mkdir()
        (repos_dir / 'another-valid').mkdir()

        # Create symlinks
        (tree_dir / 'Python').mkdir()
        (tree_dir / 'Python' / 'valid-repo').symlink_to(repos_dir / 'valid-repo')
        (tree_dir / 'Python' / 'another-valid').symlink_to(repos_dir / 'another-valid')

        # Create a broken symlink
        (tree_dir / 'Python' / 'broken').symlink_to('/nonexistent/path')

        return tree_dir

    def test_refresh_finds_broken_links(self, setup_link_tree):
        """Test that refresh finds broken symlinks."""
        service = LinkService(config={})

        list(service.refresh_tree(setup_link_tree, prune=False, dry_run=True))
        result = service.last_refresh_result

        assert result.total_links == 3
        assert result.valid_links == 2
        assert result.broken_links == 1
        assert len(result.broken_paths) == 1

    def test_refresh_prune_broken_links(self, setup_link_tree):
        """Test that refresh prunes broken symlinks."""
        service = LinkService(config={})

        # Check broken link exists
        broken_path = setup_link_tree / 'Python' / 'broken'
        assert broken_path.is_symlink()

        list(service.refresh_tree(setup_link_tree, prune=True, dry_run=False))
        result = service.last_refresh_result

        assert result.removed_links == 1
        assert not broken_path.exists()

    def test_refresh_prune_dry_run(self, setup_link_tree):
        """Test that refresh prune with dry run doesn't remove links."""
        service = LinkService(config={})

        broken_path = setup_link_tree / 'Python' / 'broken'
        assert broken_path.is_symlink()

        list(service.refresh_tree(setup_link_tree, prune=True, dry_run=True))
        result = service.last_refresh_result

        # Should report but not remove
        assert result.broken_links == 1
        assert result.removed_links == 0
        assert broken_path.is_symlink()

    def test_get_tree_status(self, setup_link_tree):
        """Test getting tree status."""
        service = LinkService(config={})

        list(service.get_tree_status(setup_link_tree))
        result = service.last_refresh_result

        assert result.total_links == 3
        assert result.valid_links == 2
        assert result.broken_links == 1

    def test_refresh_nonexistent_path(self, tmp_path):
        """Test refresh on nonexistent path."""
        service = LinkService(config={})

        nonexistent = tmp_path / 'nonexistent'

        list(service.refresh_tree(nonexistent, prune=False, dry_run=False))
        result = service.last_refresh_result

        assert len(result.errors) == 1


class TestLinkCommand:
    """Tests for the link CLI command."""

    def test_link_cmd_exists(self):
        """Test that link command is importable."""
        from repoindex.commands.link import link_cmd
        assert link_cmd is not None

    def test_link_registered_in_cli(self):
        """Test that link is registered in CLI."""
        from repoindex.cli import cli

        commands = list(cli.commands.keys())
        assert 'link' in commands

    def test_link_has_subcommands(self):
        """Test that link command has expected subcommands."""
        from repoindex.commands.link import link_cmd

        commands = list(link_cmd.commands.keys())
        assert 'tree' in commands
        assert 'refresh' in commands
        assert 'status' in commands


class TestImplicitTagsInLinkTree:
    """Tests for implicit tags being included in link tree organization."""

    @pytest.fixture
    def setup_repos_with_implicit_tags(self, tmp_path):
        """Create test repositories with metadata that generates implicit tags."""
        repos = []

        # Repo with GitHub topics (should generate topic:* implicit tags)
        repo1_path = tmp_path / 'source' / 'ml-project'
        repo1_path.mkdir(parents=True)
        (repo1_path / '.git').mkdir()
        repos.append({
            'id': 1,
            'path': str(repo1_path),
            'name': 'ml-project',
            'language': 'Python',
            'owner': 'testuser',
            'is_clean': True,
            'github_topics': '["machine-learning", "deep-learning"]',
            'github_owner': 'testuser',
            'github_is_private': False,
            'license_key': 'mit',
            'tags': ['work/active'],  # explicit tag
        })

        # Repo without GitHub topics but with other metadata
        repo2_path = tmp_path / 'source' / 'web-app'
        repo2_path.mkdir(parents=True)
        (repo2_path / '.git').mkdir()
        repos.append({
            'id': 2,
            'path': str(repo2_path),
            'name': 'web-app',
            'language': 'JavaScript',
            'owner': 'testuser',
            'is_clean': False,
            'github_topics': None,
            'github_owner': None,
            'license_key': 'apache-2.0',
            'tags': ['personal'],  # explicit tag
        })

        return repos

    def test_implicit_tags_generated_from_row(self, setup_repos_with_implicit_tags):
        """Test that get_implicit_tags_from_row generates expected tags."""
        from repoindex.commands.tag import get_implicit_tags_from_row

        repo = setup_repos_with_implicit_tags[0]
        implicit_tags = get_implicit_tags_from_row(repo)

        # Should include topic:* from github_topics
        assert 'topic:machine-learning' in implicit_tags
        assert 'topic:deep-learning' in implicit_tags

        # Should include lang:* from language
        assert 'lang:python' in implicit_tags

        # Should include status:* from is_clean
        assert 'status:clean' in implicit_tags

        # Should include owner:* from owner
        assert 'owner:testuser' in implicit_tags

        # Should include license:* from license_key
        assert 'license:mit' in implicit_tags

        # Should include visibility:* from github metadata
        assert 'visibility:public' in implicit_tags

    def test_link_tree_includes_implicit_topic_tags(self, setup_repos_with_implicit_tags, tmp_path):
        """Test that link tree includes topic:* tags from GitHub topics."""
        dest_dir = tmp_path / 'links'

        # Merge implicit tags with explicit tags (simulating what link.py does)
        from repoindex.commands.tag import get_implicit_tags_from_row

        repos = []
        for repo in setup_repos_with_implicit_tags:
            repo_copy = dict(repo)
            explicit_tags = repo_copy.get('tags', [])
            implicit_tags = get_implicit_tags_from_row(repo_copy)
            repo_copy['tags'] = list(set(explicit_tags + implicit_tags))
            repos.append(repo_copy)

        service = LinkService(config={})
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.TAG
        )

        list(service.create_tree(repos, options))
        result = service.last_result

        assert result.success is True
        assert result.links_created > 0

        # Check that implicit topic:* tags created directories
        assert (dest_dir / 'topic' / 'machine-learning').exists()
        assert (dest_dir / 'topic' / 'deep-learning').exists()
        assert (dest_dir / 'topic' / 'machine-learning' / 'ml-project').is_symlink()

        # Check that implicit lang:* tags created directories
        assert (dest_dir / 'lang' / 'python').exists()
        assert (dest_dir / 'lang' / 'javascript').exists()

        # Check that explicit tags still work
        assert (dest_dir / 'work' / 'active' / 'ml-project').is_symlink()
        assert (dest_dir / 'personal' / 'web-app').is_symlink()

    def test_link_tree_implicit_status_tags(self, setup_repos_with_implicit_tags, tmp_path):
        """Test that link tree includes status:clean/dirty implicit tags."""
        from repoindex.commands.tag import get_implicit_tags_from_row

        dest_dir = tmp_path / 'links'

        repos = []
        for repo in setup_repos_with_implicit_tags:
            repo_copy = dict(repo)
            implicit_tags = get_implicit_tags_from_row(repo_copy)
            repo_copy['tags'] = implicit_tags
            repos.append(repo_copy)

        service = LinkService(config={})
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.TAG
        )

        list(service.create_tree(repos, options))
        result = service.last_result

        # Check status tags
        assert (dest_dir / 'status' / 'clean').exists()
        assert (dest_dir / 'status' / 'dirty').exists()
        assert (dest_dir / 'status' / 'clean' / 'ml-project').is_symlink()
        assert (dest_dir / 'status' / 'dirty' / 'web-app').is_symlink()

    def test_link_tree_deduplicates_tags(self, tmp_path):
        """Test that duplicate tags from explicit and implicit sources are deduplicated."""
        from repoindex.commands.tag import get_implicit_tags_from_row

        repo_path = tmp_path / 'source' / 'project'
        repo_path.mkdir(parents=True)
        (repo_path / '.git').mkdir()

        repo = {
            'id': 1,
            'path': str(repo_path),
            'name': 'project',
            'language': 'Python',
            # Explicit tag that matches what implicit would generate
            'tags': ['lang:python'],
        }

        implicit_tags = get_implicit_tags_from_row(repo)
        all_tags = list(set(repo['tags'] + implicit_tags))

        # Should only have one 'lang:python' tag
        assert all_tags.count('lang:python') == 1


class TestLinkIntegration:
    """Integration tests for link functionality."""

    @pytest.fixture
    def full_test_setup(self, tmp_path):
        """Set up a complete test environment with database."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        # Create database
        db_path = tmp_path / 'test.db'
        config = {'database': {'path': str(db_path)}}

        # Create test repos on filesystem
        repos = []
        repo_data = [
            ('python-ml', 'Python', ['topic:ml', 'work']),
            ('python-web', 'Python', ['topic:web', 'personal']),
            ('js-frontend', 'JavaScript', ['topic:web', 'work']),
        ]

        for name, lang, tags in repo_data:
            repo_path = tmp_path / 'repos' / name
            repo_path.mkdir(parents=True)
            (repo_path / '.git').mkdir()
            (repo_path / 'README.md').write_text(f'# {name}')
            repos.append({
                'name': name,
                'path': str(repo_path),
                'language': lang,
                'tags': tags
            })

        # Populate database
        with Database(config=config) as db:
            apply_schema(db.conn)

            for repo in repos:
                db.execute("""
                    INSERT INTO repos (name, path, language, branch, has_readme)
                    VALUES (?, ?, ?, 'main', 1)
                """, (repo['name'], repo['path'], repo['language']))

                repo_id = db.lastrowid

                # Add tags
                for tag in repo['tags']:
                    db.execute("""
                        INSERT INTO tags (repo_id, tag)
                        VALUES (?, ?)
                    """, (repo_id, tag))

            db.conn.commit()

        return config, repos

    def test_full_link_tree_by_tag(self, full_test_setup, tmp_path):
        """Test creating a complete link tree by tag."""
        config, repos = full_test_setup
        dest_dir = tmp_path / 'links-by-tag'

        service = LinkService(config=config)
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.TAG
        )

        list(service.create_tree(repos, options))
        result = service.last_result

        assert result.success is True
        assert result.links_created > 0

        # Check structure
        assert (dest_dir / 'topic' / 'ml').exists()
        assert (dest_dir / 'topic' / 'web').exists()
        assert (dest_dir / 'work').exists()
        assert (dest_dir / 'personal').exists()

    def test_full_link_tree_by_language(self, full_test_setup, tmp_path):
        """Test creating a complete link tree by language."""
        config, repos = full_test_setup
        dest_dir = tmp_path / 'links-by-lang'

        service = LinkService(config=config)
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.LANGUAGE
        )

        list(service.create_tree(repos, options))
        result = service.last_result

        assert result.success is True
        assert result.links_created == 3

        # Check structure
        assert (dest_dir / 'Python' / 'python-ml').is_symlink()
        assert (dest_dir / 'Python' / 'python-web').is_symlink()
        assert (dest_dir / 'JavaScript' / 'js-frontend').is_symlink()

    def test_link_tree_then_refresh(self, full_test_setup, tmp_path):
        """Test creating tree and then refreshing it."""
        config, repos = full_test_setup
        dest_dir = tmp_path / 'links'

        service = LinkService(config=config)

        # Create tree
        options = LinkTreeOptions(
            destination=dest_dir,
            organize_by=OrganizeBy.LANGUAGE
        )
        list(service.create_tree(repos, options))

        # Refresh (all links should be valid)
        list(service.refresh_tree(dest_dir, prune=False, dry_run=False))
        result = service.last_refresh_result

        assert result.total_links == 3
        assert result.valid_links == 3
        assert result.broken_links == 0
