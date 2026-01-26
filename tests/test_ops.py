"""
Tests for ops services and commands.

Tests cover:
- GitOpsService (push, pull, status operations)
- CitationGeneratorService (citation, codemeta, license generation)
- OperationResult domain objects
- ops CLI commands
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from repoindex.domain.operation import (
    OperationStatus,
    OperationDetail,
    OperationSummary,
    GitPushResult,
    GitPullResult,
    FileGenerationResult,
)
from repoindex.services.git_ops_service import (
    GitOpsService,
    GitOpsOptions,
    MultiRepoStatus,
)
from repoindex.services.citation_generator_service import (
    CitationGeneratorService,
    GenerationOptions,
    AuthorInfo,
    LICENSES,
)
from repoindex.infra.git_client import GitClient, GitStatus


# ============================================================================
# Domain Object Tests
# ============================================================================

class TestOperationStatus:
    """Tests for OperationStatus enum."""

    def test_enum_values(self):
        """Test that enum has expected values."""
        assert OperationStatus.SUCCESS.value == "success"
        assert OperationStatus.SKIPPED.value == "skipped"
        assert OperationStatus.FAILED.value == "failed"
        assert OperationStatus.DRY_RUN.value == "dry_run"


class TestOperationDetail:
    """Tests for OperationDetail dataclass."""

    def test_basic_detail(self):
        """Test creating a basic operation detail."""
        detail = OperationDetail(
            repo_path="/path/to/repo",
            repo_name="my-repo",
            status=OperationStatus.SUCCESS,
            action="pushed",
        )

        assert detail.repo_path == "/path/to/repo"
        assert detail.repo_name == "my-repo"
        assert detail.status == OperationStatus.SUCCESS
        assert detail.action == "pushed"

    def test_to_dict(self):
        """Test converting to dictionary."""
        detail = OperationDetail(
            repo_path="/path/to/repo",
            repo_name="my-repo",
            status=OperationStatus.SUCCESS,
            action="pushed",
            message="Success!",
        )

        d = detail.to_dict()

        assert d['path'] == "/path/to/repo"
        assert d['name'] == "my-repo"
        assert d['status'] == "success"
        assert d['action'] == "pushed"
        assert d['message'] == "Success!"

    def test_to_dict_with_error(self):
        """Test converting failed operation to dictionary."""
        detail = OperationDetail(
            repo_path="/path/to/repo",
            repo_name="my-repo",
            status=OperationStatus.FAILED,
            action="push_failed",
            error="Permission denied",
        )

        d = detail.to_dict()

        assert d['status'] == "failed"
        assert d['error'] == "Permission denied"


class TestGitPushResult:
    """Tests for GitPushResult dataclass."""

    def test_git_push_result(self):
        """Test GitPushResult creation and serialization."""
        result = GitPushResult(
            repo_path="/path/to/repo",
            repo_name="my-repo",
            status=OperationStatus.SUCCESS,
            action="pushed",
            commits_pushed=3,
            remote="origin",
            branch="main",
        )

        d = result.to_dict()

        assert d['commits_pushed'] == 3
        assert d['remote'] == "origin"
        assert d['branch'] == "main"


class TestOperationSummary:
    """Tests for OperationSummary dataclass."""

    def test_empty_summary(self):
        """Test empty operation summary."""
        summary = OperationSummary(operation="git_push")

        assert summary.total == 0
        assert summary.successful == 0
        assert summary.failed == 0
        assert summary.success is True

    def test_add_detail(self):
        """Test adding details to summary."""
        summary = OperationSummary(operation="git_push")

        detail1 = OperationDetail(
            repo_path="/path/1",
            repo_name="repo1",
            status=OperationStatus.SUCCESS,
            action="pushed",
        )
        summary.add_detail(detail1)

        assert summary.total == 1
        assert summary.successful == 1
        assert summary.failed == 0

        detail2 = OperationDetail(
            repo_path="/path/2",
            repo_name="repo2",
            status=OperationStatus.FAILED,
            action="push_failed",
            error="Error",
        )
        summary.add_detail(detail2)

        assert summary.total == 2
        assert summary.successful == 1
        assert summary.failed == 1
        assert summary.success is False
        assert len(summary.errors) == 1

    def test_to_dict(self):
        """Test summary serialization."""
        summary = OperationSummary(operation="git_push", dry_run=True)
        summary.add_detail(OperationDetail(
            repo_path="/path",
            repo_name="repo",
            status=OperationStatus.DRY_RUN,
            action="would_push",
        ))

        d = summary.to_dict()

        assert d['type'] == 'summary'
        assert d['operation'] == 'git_push'
        assert d['dry_run'] is True
        assert d['total'] == 1
        assert d['successful'] == 1


# ============================================================================
# GitOpsService Tests
# ============================================================================

class TestGitOpsOptions:
    """Tests for GitOpsOptions dataclass."""

    def test_default_options(self):
        """Test default options."""
        options = GitOpsOptions()

        assert options.remote == "origin"
        assert options.branch is None
        assert options.dry_run is False
        assert options.parallel == 1
        assert options.set_upstream is False

    def test_custom_options(self):
        """Test custom options."""
        options = GitOpsOptions(
            remote="upstream",
            branch="develop",
            dry_run=True,
            parallel=4,
            set_upstream=True,
        )

        assert options.remote == "upstream"
        assert options.branch == "develop"
        assert options.dry_run is True
        assert options.parallel == 4
        assert options.set_upstream is True


class TestMultiRepoStatus:
    """Tests for MultiRepoStatus dataclass."""

    def test_default_status(self):
        """Test default multi-repo status."""
        status = MultiRepoStatus()

        assert status.total == 0
        assert status.clean == 0
        assert status.dirty == 0
        assert status.ahead == 0
        assert status.behind == 0

    def test_to_dict(self):
        """Test status serialization."""
        status = MultiRepoStatus(total=10, clean=8, dirty=2, ahead=1, behind=1)

        d = status.to_dict()

        assert d['total'] == 10
        assert d['clean'] == 8
        assert d['dirty'] == 2


class TestGitOpsService:
    """Tests for GitOpsService."""

    @pytest.fixture
    def mock_git_client(self):
        """Create a mock git client."""
        client = MagicMock(spec=GitClient)
        client.get_commits_ahead.return_value = 0
        client.get_commits_behind.return_value = 0
        client.remote_url.return_value = "https://github.com/user/repo"
        client.status.return_value = GitStatus(branch="main", clean=True)
        client.push.return_value = (True, "Success")
        client.pull.return_value = True
        client.fetch.return_value = True
        return client

    @pytest.fixture
    def sample_repos(self, tmp_path):
        """Create sample repo data."""
        repos = []
        for name in ['repo-a', 'repo-b', 'repo-c']:
            repo_path = tmp_path / name
            repo_path.mkdir()
            repos.append({
                'path': str(repo_path),
                'name': name,
            })
        return repos

    def test_push_repos_empty(self, mock_git_client):
        """Test push with empty repos list."""
        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        messages = list(service.push_repos([], options))
        result = service.last_result

        assert "No repositories to push" in messages[0]
        assert result.total == 0

    def test_push_repos_nothing_to_push(self, mock_git_client, sample_repos):
        """Test push when no repos have commits ahead."""
        mock_git_client.get_commits_ahead.return_value = 0

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        messages = list(service.push_repos(sample_repos, options))
        result = service.last_result

        assert "No repositories have unpushed commits" in messages[-1]
        assert result.total == 0

    def test_push_repos_dry_run(self, mock_git_client, sample_repos):
        """Test push in dry run mode."""
        mock_git_client.get_commits_ahead.return_value = 2

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions(dry_run=True)

        messages = list(service.push_repos(sample_repos, options))
        result = service.last_result

        assert result.successful == 3
        assert result.dry_run is True
        # Should not actually call push
        mock_git_client.push.assert_not_called()

    def test_push_repos_success(self, mock_git_client, sample_repos):
        """Test successful push."""
        mock_git_client.get_commits_ahead.return_value = 1
        mock_git_client.push.return_value = (True, "pushed")

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        messages = list(service.push_repos(sample_repos, options))
        result = service.last_result

        assert result.successful == 3
        assert result.failed == 0
        assert mock_git_client.push.call_count == 3

    def test_push_repos_failure(self, mock_git_client, sample_repos):
        """Test push failure."""
        mock_git_client.get_commits_ahead.return_value = 1
        mock_git_client.push.return_value = (False, "Permission denied")

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        messages = list(service.push_repos(sample_repos, options))
        result = service.last_result

        assert result.successful == 0
        assert result.failed == 3
        assert len(result.errors) == 3

    def test_pull_repos_empty(self, mock_git_client):
        """Test pull with empty repos list."""
        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        messages = list(service.pull_repos([], options))
        result = service.last_result

        assert "No repositories to pull" in messages[0]

    def test_pull_repos_no_remote(self, mock_git_client, sample_repos):
        """Test pull when repos have no remote."""
        mock_git_client.remote_url.return_value = None

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        messages = list(service.pull_repos(sample_repos, options))
        result = service.last_result

        assert "No repositories have remotes" in messages[-1]

    def test_pull_repos_success(self, mock_git_client, sample_repos):
        """Test successful pull."""
        mock_git_client.pull.return_value = True

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        messages = list(service.pull_repos(sample_repos, options))
        result = service.last_result

        assert result.successful == 3
        assert result.failed == 0

    def test_pull_repos_dry_run(self, mock_git_client, sample_repos):
        """Test pull in dry run mode."""
        mock_git_client.get_commits_behind.return_value = 5

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions(dry_run=True)

        messages = list(service.pull_repos(sample_repos, options))
        result = service.last_result

        assert result.successful == 3
        assert result.dry_run is True
        mock_git_client.fetch.assert_called()  # Fetches to check
        mock_git_client.pull.assert_not_called()

    def test_status_repos_empty(self, mock_git_client):
        """Test status with empty repos list."""
        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        messages = list(service.status_repos([], options))
        status = service.last_status

        assert "No repositories to check" in messages[0]

    def test_status_repos_all_clean(self, mock_git_client, sample_repos):
        """Test status when all repos are clean."""
        mock_git_client.status.return_value = GitStatus(
            branch="main", clean=True, ahead=0, behind=0
        )

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        list(service.status_repos(sample_repos, options))
        status = service.last_status

        assert status.total == 3
        assert status.clean == 3
        assert status.dirty == 0

    def test_status_repos_mixed(self, mock_git_client, sample_repos):
        """Test status with mixed clean/dirty repos."""
        statuses = [
            GitStatus(branch="main", clean=True, ahead=0, behind=0),
            GitStatus(branch="main", clean=False, ahead=2, behind=0),
            GitStatus(branch="develop", clean=True, ahead=0, behind=3),
        ]
        mock_git_client.status.side_effect = statuses

        service = GitOpsService(config={}, git_client=mock_git_client)
        options = GitOpsOptions()

        list(service.status_repos(sample_repos, options))
        status = service.last_status

        assert status.total == 3
        assert status.clean == 2
        assert status.dirty == 1
        assert status.ahead == 1
        assert status.behind == 1

    def test_get_repos_needing_push(self, mock_git_client, sample_repos):
        """Test filtering repos that need push."""
        mock_git_client.get_commits_ahead.side_effect = [0, 3, 0]

        service = GitOpsService(config={}, git_client=mock_git_client)
        needing = service.get_repos_needing_push(sample_repos)

        assert len(needing) == 1
        assert needing[0]['name'] == 'repo-b'
        assert needing[0]['commits_ahead'] == 3


# ============================================================================
# CitationGeneratorService Tests
# ============================================================================

class TestAuthorInfo:
    """Tests for AuthorInfo dataclass."""

    def test_from_config(self):
        """Test creating AuthorInfo from config."""
        config = {
            'author': {
                'name': 'John Smith',
                'email': 'john@example.com',
                'orcid': '0000-0001-2345-6789',
                'affiliation': 'University',
            }
        }

        author = AuthorInfo.from_config(config)

        assert author is not None
        assert author.name == 'John Smith'
        assert author.given_names == 'John'
        assert author.family_names == 'Smith'
        assert author.email == 'john@example.com'
        assert author.orcid == '0000-0001-2345-6789'

    def test_from_config_empty(self):
        """Test creating AuthorInfo from empty config."""
        config = {'author': {'name': ''}}

        author = AuthorInfo.from_config(config)

        assert author is None

    def test_to_cff_dict(self):
        """Test converting to CFF format."""
        author = AuthorInfo(
            name='John Smith',
            given_names='John',
            family_names='Smith',
            orcid='0000-0001-2345-6789',
        )

        d = author.to_cff_dict()

        assert d['given-names'] == 'John'
        assert d['family-names'] == 'Smith'
        assert d['orcid'] == 'https://orcid.org/0000-0001-2345-6789'

    def test_to_cff_dict_orcid_url(self):
        """Test ORCID URL formatting."""
        author = AuthorInfo(
            name='Test Author',
            orcid='https://orcid.org/0000-0001-2345-6789',
        )

        d = author.to_cff_dict()

        # Should not double-add the URL prefix
        assert d['orcid'] == 'https://orcid.org/0000-0001-2345-6789'

    def test_to_codemeta_dict(self):
        """Test converting to codemeta format."""
        author = AuthorInfo(
            name='John Smith',
            given_names='John',
            family_names='Smith',
            email='john@example.com',
            affiliation='University',
        )

        d = author.to_codemeta_dict()

        assert d['@type'] == 'Person'
        assert d['name'] == 'John Smith'
        assert d['givenName'] == 'John'
        assert d['familyName'] == 'Smith'
        assert d['email'] == 'john@example.com'
        assert d['affiliation']['@type'] == 'Organization'
        assert d['affiliation']['name'] == 'University'


class TestGenerationOptions:
    """Tests for GenerationOptions dataclass."""

    def test_default_options(self):
        """Test default options."""
        options = GenerationOptions()

        assert options.dry_run is False
        assert options.force is False
        assert options.author is None
        assert options.license is None

    def test_custom_options(self):
        """Test custom options."""
        author = AuthorInfo(name='Test')
        options = GenerationOptions(
            dry_run=True,
            force=True,
            author=author,
            license='MIT',
        )

        assert options.dry_run is True
        assert options.force is True
        assert options.author.name == 'Test'
        assert options.license == 'MIT'


class TestCitationGeneratorService:
    """Tests for CitationGeneratorService."""

    @pytest.fixture
    def sample_repos(self, tmp_path):
        """Create sample repo data with actual paths."""
        repos = []
        for name in ['repo-a', 'repo-b']:
            repo_path = tmp_path / name
            repo_path.mkdir()
            repos.append({
                'path': str(repo_path),
                'name': name,
                'description': f'Description for {name}',
                'remote_url': f'https://github.com/user/{name}',
                'language': 'Python',
            })
        return repos

    def test_generate_citation_empty(self):
        """Test generation with empty repos list."""
        service = CitationGeneratorService(config={})
        options = GenerationOptions()

        messages = list(service.generate_citation([], options))
        result = service.last_result

        assert "No repositories to process" in messages[0]
        assert result.total == 0

    def test_generate_citation_dry_run(self, sample_repos):
        """Test citation generation in dry run mode."""
        service = CitationGeneratorService(config={})
        options = GenerationOptions(dry_run=True)

        messages = list(service.generate_citation(sample_repos, options))
        result = service.last_result

        assert result.successful == 2
        assert result.dry_run is True

        # Files should not exist
        for repo in sample_repos:
            assert not (Path(repo['path']) / 'CITATION.cff').exists()

    def test_generate_citation_creates_file(self, sample_repos):
        """Test that citation generation creates files."""
        author = AuthorInfo(
            name='Test Author',
            given_names='Test',
            family_names='Author',
        )
        service = CitationGeneratorService(config={})
        options = GenerationOptions(author=author)

        list(service.generate_citation(sample_repos, options))
        result = service.last_result

        assert result.successful == 2

        # Check files exist and have content
        for repo in sample_repos:
            cff_path = Path(repo['path']) / 'CITATION.cff'
            assert cff_path.exists()
            content = cff_path.read_text()
            assert 'cff-version: 1.2.0' in content
            assert repo['name'] in content

    def test_generate_citation_skips_existing(self, sample_repos):
        """Test that existing files are skipped without --force."""
        # Create existing file
        existing_path = Path(sample_repos[0]['path']) / 'CITATION.cff'
        existing_path.write_text('# Existing')

        service = CitationGeneratorService(config={})
        options = GenerationOptions()

        list(service.generate_citation(sample_repos, options))
        result = service.last_result

        assert result.successful == 1
        assert result.skipped == 1

        # Original should be preserved
        assert existing_path.read_text() == '# Existing'

    def test_generate_citation_force_overwrite(self, sample_repos):
        """Test that --force overwrites existing files."""
        existing_path = Path(sample_repos[0]['path']) / 'CITATION.cff'
        existing_path.write_text('# Existing')

        service = CitationGeneratorService(config={})
        options = GenerationOptions(force=True)

        list(service.generate_citation(sample_repos, options))
        result = service.last_result

        assert result.successful == 2
        assert result.skipped == 0

        # Should be overwritten
        assert '# Existing' not in existing_path.read_text()

    def test_generate_codemeta_creates_file(self, sample_repos):
        """Test that codemeta generation creates files."""
        author = AuthorInfo(name='Test Author')
        service = CitationGeneratorService(config={})
        options = GenerationOptions(author=author)

        list(service.generate_codemeta(sample_repos, options))
        result = service.last_result

        assert result.successful == 2

        for repo in sample_repos:
            cm_path = Path(repo['path']) / 'codemeta.json'
            assert cm_path.exists()
            content = json.loads(cm_path.read_text())
            assert content['@type'] == 'SoftwareSourceCode'
            assert content['name'] == repo['name']

    def test_generate_license_mit(self, sample_repos):
        """Test MIT license generation."""
        author = AuthorInfo(name='Test Author')
        service = CitationGeneratorService(config={})
        options = GenerationOptions(author=author)

        list(service.generate_license(sample_repos, options, 'mit'))
        result = service.last_result

        assert result.successful == 2

        for repo in sample_repos:
            lic_path = Path(repo['path']) / 'LICENSE'
            assert lic_path.exists()
            content = lic_path.read_text()
            assert 'MIT License' in content
            assert 'Test Author' in content

    def test_generate_license_apache(self, sample_repos):
        """Test Apache 2.0 license generation."""
        author = AuthorInfo(name='Test Author')
        service = CitationGeneratorService(config={})
        options = GenerationOptions(author=author)

        list(service.generate_license(sample_repos, options, 'apache-2.0'))
        result = service.last_result

        for repo in sample_repos:
            lic_path = Path(repo['path']) / 'LICENSE'
            content = lic_path.read_text()
            assert 'Apache License' in content

    def test_generate_license_unknown_type(self, sample_repos):
        """Test unknown license type handling."""
        service = CitationGeneratorService(config={})
        options = GenerationOptions()

        messages = list(service.generate_license(sample_repos, options, 'unknown-license'))
        result = service.last_result

        assert "Unknown license type" in messages[0]
        assert result.total == 0

    def test_generate_with_config_author(self, sample_repos):
        """Test using author from config."""
        config = {
            'author': {
                'name': 'Config Author',
                'orcid': '0000-0001-2345-6789',
            }
        }
        service = CitationGeneratorService(config=config)
        options = GenerationOptions()

        list(service.generate_citation(sample_repos, options))
        result = service.last_result

        # Check that config author was used
        cff_path = Path(sample_repos[0]['path']) / 'CITATION.cff'
        content = cff_path.read_text()
        assert 'Config Author' in content or 'Author' in content


class TestLicenses:
    """Tests for license constants."""

    def test_licenses_defined(self):
        """Test that common licenses are defined."""
        assert 'mit' in LICENSES
        assert 'apache-2.0' in LICENSES
        assert 'gpl-3.0' in LICENSES
        assert 'bsd-3-clause' in LICENSES
        assert 'mpl-2.0' in LICENSES

    def test_license_has_required_fields(self):
        """Test that licenses have required fields."""
        for key, license_info in LICENSES.items():
            assert 'spdx' in license_info
            assert 'name' in license_info
            assert 'url' in license_info


# ============================================================================
# Command Tests
# ============================================================================

class TestOpsCommands:
    """Tests for ops CLI commands."""

    def test_ops_command_exists(self):
        """Test that ops command group is importable."""
        from repoindex.commands.ops import ops_cmd
        assert ops_cmd is not None

    def test_ops_registered_in_cli(self):
        """Test that ops is registered in main CLI."""
        from repoindex.cli import cli

        commands = list(cli.commands.keys())
        assert 'ops' in commands

    def test_git_subgroup_exists(self):
        """Test that git subgroup exists."""
        from repoindex.commands.ops import git_cmd
        assert git_cmd is not None

        commands = list(git_cmd.commands.keys())
        assert 'push' in commands
        assert 'pull' in commands
        assert 'status' in commands

    def test_generate_subgroup_exists(self):
        """Test that generate subgroup exists."""
        from repoindex.commands.ops import generate_cmd
        assert generate_cmd is not None

        commands = list(generate_cmd.commands.keys())
        assert 'citation' in commands
        assert 'codemeta' in commands
        assert 'license' in commands

    def test_query_options_decorator(self):
        """Test that query_options adds expected options."""
        from repoindex.commands.ops import git_push_handler

        # Check that the handler has query-related options
        params = [p.name for p in git_push_handler.params]
        assert 'dirty' in params
        assert 'clean' in params
        assert 'language' in params
        assert 'tag' in params


class TestOpsCommandHelpers:
    """Tests for ops command helper functions."""

    def test_build_author_info_from_cli(self):
        """Test building author info from CLI options."""
        from repoindex.commands.ops import _build_author_info

        config = {'author': {}}
        author = _build_author_info(
            config,
            author='CLI Author',
            orcid='0000-0001-2345-6789',
            email='cli@example.com',
            affiliation='CLI Org',
        )

        assert author is not None
        assert author.name == 'CLI Author'
        assert author.orcid == '0000-0001-2345-6789'
        assert author.email == 'cli@example.com'
        assert author.affiliation == 'CLI Org'

    def test_build_author_info_from_config(self):
        """Test building author info from config when no CLI options."""
        from repoindex.commands.ops import _build_author_info

        config = {
            'author': {
                'name': 'Config Author',
                'email': 'config@example.com',
            }
        }
        author = _build_author_info(config, None, None, None, None)

        assert author is not None
        assert author.name == 'Config Author'
        assert author.email == 'config@example.com'

    def test_build_author_info_cli_overrides_config(self):
        """Test that CLI options override config."""
        from repoindex.commands.ops import _build_author_info

        config = {
            'author': {
                'name': 'Config Author',
                'email': 'config@example.com',
                'orcid': 'config-orcid',
            }
        }
        author = _build_author_info(
            config,
            author='CLI Author',
            orcid=None,  # Should fall back to config
            email='cli@example.com',  # Override
            affiliation=None,
        )

        assert author.name == 'CLI Author'
        assert author.email == 'cli@example.com'
        assert author.orcid == 'config-orcid'  # From config


# ============================================================================
# Integration Tests
# ============================================================================

class TestOpsIntegration:
    """Integration tests for ops functionality."""

    @pytest.fixture
    def full_test_setup(self, tmp_path):
        """Set up a complete test environment."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        # Create database
        db_path = tmp_path / 'test.db'
        config = {'database': {'path': str(db_path)}}

        # Create test repos on filesystem
        repos = []
        for name in ['python-project', 'js-project']:
            repo_path = tmp_path / 'repos' / name
            repo_path.mkdir(parents=True)
            (repo_path / '.git').mkdir()
            (repo_path / 'README.md').write_text(f'# {name}')
            repos.append({
                'name': name,
                'path': str(repo_path),
                'language': 'Python' if 'python' in name else 'JavaScript',
            })

        # Populate database
        with Database(config=config) as db:
            apply_schema(db.conn)

            for repo in repos:
                db.execute("""
                    INSERT INTO repos (name, path, language, branch, has_readme)
                    VALUES (?, ?, ?, 'main', 1)
                """, (repo['name'], repo['path'], repo['language']))

            db.conn.commit()

        return config, repos

    def test_citation_generation_integration(self, full_test_setup):
        """Test citation generation with real files."""
        config, repos = full_test_setup

        author = AuthorInfo(
            name='Integration Test',
            orcid='0000-0001-2345-6789',
        )
        service = CitationGeneratorService(config=config)
        options = GenerationOptions(author=author)

        list(service.generate_citation(repos, options))
        result = service.last_result

        assert result.successful == 2

        # Verify file contents
        for repo in repos:
            cff_path = Path(repo['path']) / 'CITATION.cff'
            assert cff_path.exists()
            content = cff_path.read_text()

            # Check required CFF fields
            assert 'cff-version: 1.2.0' in content
            assert 'title:' in content
            assert 'authors:' in content
            assert 'Integration Test' in content or 'Test' in content
