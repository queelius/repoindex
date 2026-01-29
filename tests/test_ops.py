"""
Tests for ops services and commands.

Tests cover:
- GitOpsService (push, pull, status operations)
- BoilerplateService (codemeta, license, gitignore, code of conduct, contributing)
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
from repoindex.services.boilerplate_service import (
    BoilerplateService,
    GenerationOptions,
    AuthorInfo,
    LICENSES,
    GITIGNORE_TEMPLATES,
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
        """Create sample repo data with real directories on disk."""
        repos = []
        for name in ['repo-a', 'repo-b', 'repo-c']:
            repo_path = tmp_path / name
            repo_path.mkdir()
            repos.append({
                'path': str(repo_path),
                'name': name,
            })
        return repos

    @pytest.fixture
    def missing_repos(self):
        """Repo dicts whose paths do not exist on disk."""
        return [
            {'path': '/nonexistent/path/repo-a', 'name': 'repo-a'},
            {'path': '/nonexistent/path/repo-b', 'name': 'repo-b'},
        ]

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

    def test_push_repos_skips_missing_path(self, mock_git_client, missing_repos):
        """Test that push_repos skips repos whose paths don't exist."""
        service = GitOpsService(config={}, git_client=mock_git_client)
        messages = list(service.push_repos(missing_repos, GitOpsOptions()))

        mock_git_client.get_commits_ahead.assert_not_called()
        assert sum('path not found' in m for m in messages) == len(missing_repos)

    def test_pull_repos_skips_missing_path(self, mock_git_client, missing_repos):
        """Test that pull_repos skips repos whose paths don't exist."""
        service = GitOpsService(config={}, git_client=mock_git_client)
        messages = list(service.pull_repos(missing_repos, GitOpsOptions()))

        mock_git_client.remote_url.assert_not_called()
        assert sum('path not found' in m for m in messages) == len(missing_repos)

    def test_status_repos_skips_missing_path(self, mock_git_client, missing_repos):
        """Test that status_repos skips repos whose paths don't exist."""
        service = GitOpsService(config={}, git_client=mock_git_client)
        messages = list(service.status_repos(missing_repos, GitOpsOptions()))

        mock_git_client.status.assert_not_called()
        assert service.last_status.total == 0
        assert sum('path not found' in m for m in messages) == len(missing_repos)

    def test_get_repos_needing_push_skips_missing_path(self, mock_git_client, missing_repos):
        """Test that get_repos_needing_push skips missing paths silently."""
        service = GitOpsService(config={}, git_client=mock_git_client)

        assert service.get_repos_needing_push(missing_repos) == []
        mock_git_client.get_commits_ahead.assert_not_called()

    def test_get_repos_needing_pull_skips_missing_path(self, mock_git_client, missing_repos):
        """Test that get_repos_needing_pull skips missing paths silently."""
        service = GitOpsService(config={}, git_client=mock_git_client)

        assert service.get_repos_needing_pull(missing_repos) == []
        mock_git_client.fetch.assert_not_called()

    def test_status_repos_mixed_existing_and_missing(self, mock_git_client, sample_repos):
        """Test status with a mix of existing and non-existent paths."""
        repos = sample_repos + [
            {'path': '/nonexistent/stale/repo', 'name': 'stale-repo'},
        ]
        mock_git_client.status.return_value = GitStatus(
            branch="main", clean=True, ahead=0, behind=0
        )

        service = GitOpsService(config={}, git_client=mock_git_client)
        messages = list(service.status_repos(repos, GitOpsOptions()))
        status = service.last_status

        assert status.total == 3
        assert status.clean == 3
        assert mock_git_client.status.call_count == 3
        assert sum('path not found' in m for m in messages) == 1


# ============================================================================
# BoilerplateService Tests
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


class TestBoilerplateService:
    """Tests for BoilerplateService."""

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

    def test_generate_codemeta_empty(self):
        """Test generation with empty repos list."""
        service = BoilerplateService(config={})
        options = GenerationOptions()

        messages = list(service.generate_codemeta([], options))
        result = service.last_result

        assert "No repositories to process" in messages[0]
        assert result.total == 0

    def test_generate_codemeta_creates_file(self, sample_repos):
        """Test that codemeta generation creates files."""
        author = AuthorInfo(name='Test Author')
        service = BoilerplateService(config={})
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
        service = BoilerplateService(config={})
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
        service = BoilerplateService(config={})
        options = GenerationOptions(author=author)

        list(service.generate_license(sample_repos, options, 'apache-2.0'))
        result = service.last_result

        for repo in sample_repos:
            lic_path = Path(repo['path']) / 'LICENSE'
            content = lic_path.read_text()
            assert 'Apache License' in content

    def test_generate_license_unknown_type(self, sample_repos):
        """Test unknown license type handling."""
        service = BoilerplateService(config={})
        options = GenerationOptions()

        messages = list(service.generate_license(sample_repos, options, 'unknown-license'))
        result = service.last_result

        assert "Unknown license type" in messages[0]
        assert result.total == 0

    def test_generate_gitignore_creates_file(self, sample_repos):
        """Test that gitignore generation creates files."""
        service = BoilerplateService(config={})
        options = GenerationOptions()

        list(service.generate_gitignore(sample_repos, options, 'python'))
        result = service.last_result

        assert result.successful == 2

        for repo in sample_repos:
            gi_path = Path(repo['path']) / '.gitignore'
            assert gi_path.exists()
            content = gi_path.read_text()
            assert '__pycache__/' in content
            assert '.venv/' in content

    def test_generate_gitignore_node(self, sample_repos):
        """Test Node.js gitignore generation."""
        service = BoilerplateService(config={})
        options = GenerationOptions()

        list(service.generate_gitignore(sample_repos, options, 'node'))
        result = service.last_result

        for repo in sample_repos:
            gi_path = Path(repo['path']) / '.gitignore'
            content = gi_path.read_text()
            assert 'node_modules/' in content

    def test_generate_gitignore_unknown_lang(self, sample_repos):
        """Test unknown language handling for gitignore."""
        service = BoilerplateService(config={})
        options = GenerationOptions()

        messages = list(service.generate_gitignore(sample_repos, options, 'unknown-lang'))
        result = service.last_result

        assert "Unknown language" in messages[0]
        assert result.total == 0

    def test_generate_code_of_conduct_creates_file(self, sample_repos):
        """Test that code of conduct generation creates files."""
        author = AuthorInfo(name='Test', email='test@example.com')
        service = BoilerplateService(config={})
        options = GenerationOptions(author=author)

        list(service.generate_code_of_conduct(sample_repos, options))
        result = service.last_result

        assert result.successful == 2

        for repo in sample_repos:
            coc_path = Path(repo['path']) / 'CODE_OF_CONDUCT.md'
            assert coc_path.exists()
            content = coc_path.read_text()
            assert 'Contributor Covenant' in content
            assert 'test@example.com' in content

    def test_generate_contributing_creates_file(self, sample_repos):
        """Test that contributing generation creates files."""
        service = BoilerplateService(config={})
        options = GenerationOptions()

        list(service.generate_contributing(sample_repos, options))
        result = service.last_result

        assert result.successful == 2

        for repo in sample_repos:
            contrib_path = Path(repo['path']) / 'CONTRIBUTING.md'
            assert contrib_path.exists()
            content = contrib_path.read_text()
            assert 'Contributing to' in content
            assert repo['name'] in content

    def test_generate_contributing_skips_existing(self, sample_repos):
        """Test that existing files are skipped without --force."""
        existing_path = Path(sample_repos[0]['path']) / 'CONTRIBUTING.md'
        existing_path.write_text('# Existing')

        service = BoilerplateService(config={})
        options = GenerationOptions()

        list(service.generate_contributing(sample_repos, options))
        result = service.last_result

        assert result.successful == 1
        assert result.skipped == 1

        # Original should be preserved
        assert existing_path.read_text() == '# Existing'


class TestGitignoreTemplates:
    """Tests for gitignore template constants."""

    def test_templates_defined(self):
        """Test that common language templates are defined."""
        assert 'python' in GITIGNORE_TEMPLATES
        assert 'node' in GITIGNORE_TEMPLATES
        assert 'rust' in GITIGNORE_TEMPLATES
        assert 'go' in GITIGNORE_TEMPLATES
        assert 'cpp' in GITIGNORE_TEMPLATES
        assert 'java' in GITIGNORE_TEMPLATES

    def test_templates_have_content(self):
        """Test that templates have content."""
        for lang, template in GITIGNORE_TEMPLATES.items():
            assert len(template) > 0
            assert '# ' in template  # Should have comments


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
        assert 'codemeta' in commands
        assert 'license' in commands
        assert 'gitignore' in commands
        assert 'code-of-conduct' in commands
        assert 'contributing' in commands

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

class TestGetReposFromQueryExclude:
    """Tests for exclude_directories filtering in _get_repos_from_query."""

    @pytest.fixture
    def db_setup(self, tmp_path):
        """Set up database with repos including some in excluded dirs."""
        from repoindex.database import Database
        from repoindex.database.schema import apply_schema

        db_path = tmp_path / 'test.db'
        config = {'database': {'path': str(db_path)}}

        repo_data = [
            ('active-repo', '/home/user/github/active-repo', 'Python'),
            ('archived-repo', '/home/user/github/archived/old-repo', 'Python'),
            ('another-archived', '/home/user/github/archived/another', 'Rust'),
            ('work-repo', '/home/user/github/work/project', 'Python'),
        ]

        with Database(config=config) as db:
            apply_schema(db.conn)
            for name, path, lang in repo_data:
                db.execute("""
                    INSERT INTO repos (name, path, language, branch)
                    VALUES (?, ?, ?, 'main')
                """, (name, path, lang))
            db.conn.commit()

        return config, repo_data

    def test_no_excludes_returns_all(self, db_setup):
        """Without exclude_directories, all repos are returned."""
        from repoindex.commands.ops import _get_repos_from_query

        config, repo_data = db_setup
        repos = _get_repos_from_query(
            config, '', False, False, None, None, False, (),
            False, False, False, False, False, False, False, False, False
        )
        assert len(repos) == len(repo_data)

    def test_exclude_filters_matching_repos(self, db_setup):
        """Repos under excluded directories are filtered out."""
        from repoindex.commands.ops import _get_repos_from_query

        config, repo_data = db_setup
        config['exclude_directories'] = ['/home/user/github/archived/']

        repos = _get_repos_from_query(
            config, '', False, False, None, None, False, (),
            False, False, False, False, False, False, False, False, False
        )
        names = [r['name'] for r in repos]
        assert 'active-repo' in names
        assert 'work-repo' in names
        assert 'archived-repo' not in names
        assert 'another-archived' not in names

    def test_exclude_without_trailing_slash(self, db_setup):
        """Exclude works regardless of trailing slash."""
        from repoindex.commands.ops import _get_repos_from_query

        config, repo_data = db_setup
        config['exclude_directories'] = ['/home/user/github/archived']

        repos = _get_repos_from_query(
            config, '', False, False, None, None, False, (),
            False, False, False, False, False, False, False, False, False
        )
        names = [r['name'] for r in repos]
        assert 'archived-repo' not in names
        assert 'another-archived' not in names
        assert len(repos) == 2

    def test_exclude_multiple_directories(self, db_setup):
        """Multiple directories can be excluded."""
        from repoindex.commands.ops import _get_repos_from_query

        config, repo_data = db_setup
        config['exclude_directories'] = [
            '/home/user/github/archived/',
            '/home/user/github/work/',
        ]

        repos = _get_repos_from_query(
            config, '', False, False, None, None, False, (),
            False, False, False, False, False, False, False, False, False
        )
        names = [r['name'] for r in repos]
        assert names == ['active-repo']

    def test_exclude_with_tilde_expansion(self, db_setup):
        """Exclude paths with ~ are expanded."""
        from repoindex.commands.ops import _get_repos_from_query
        from pathlib import Path

        config, repo_data = db_setup
        home = str(Path.home())
        # Use a tilde path that won't match any test repo (home != /home/user)
        config['exclude_directories'] = [f'{home}/nonexistent/']

        repos = _get_repos_from_query(
            config, '', False, False, None, None, False, (),
            False, False, False, False, False, False, False, False, False
        )
        # Nothing excluded since paths don't match
        assert len(repos) == 4

    def test_empty_exclude_list(self, db_setup):
        """Empty exclude list returns all repos."""
        from repoindex.commands.ops import _get_repos_from_query

        config, repo_data = db_setup
        config['exclude_directories'] = []

        repos = _get_repos_from_query(
            config, '', False, False, None, None, False, (),
            False, False, False, False, False, False, False, False, False
        )
        assert len(repos) == len(repo_data)


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

    def test_gitignore_generation_integration(self, full_test_setup):
        """Test gitignore generation with real files."""
        config, repos = full_test_setup

        service = BoilerplateService(config=config)
        options = GenerationOptions()

        list(service.generate_gitignore(repos, options, 'python'))
        result = service.last_result

        assert result.successful == 2

        # Verify file contents
        for repo in repos:
            gi_path = Path(repo['path']) / '.gitignore'
            assert gi_path.exists()
            content = gi_path.read_text()

            # Check Python gitignore patterns
            assert '__pycache__/' in content
            assert '*.py[cod]' in content

    def test_code_of_conduct_generation_integration(self, full_test_setup):
        """Test code of conduct generation with real files."""
        config, repos = full_test_setup

        author = AuthorInfo(name='Tester', email='tester@example.com')
        service = BoilerplateService(config=config)
        options = GenerationOptions(author=author)

        list(service.generate_code_of_conduct(repos, options))
        result = service.last_result

        assert result.successful == 2

        for repo in repos:
            coc_path = Path(repo['path']) / 'CODE_OF_CONDUCT.md'
            assert coc_path.exists()
            content = coc_path.read_text()
            assert 'Contributor Covenant' in content

    def test_contributing_generation_integration(self, full_test_setup):
        """Test contributing generation with real files."""
        config, repos = full_test_setup

        service = BoilerplateService(config=config)
        options = GenerationOptions()

        list(service.generate_contributing(repos, options))
        result = service.last_result

        assert result.successful == 2

        for repo in repos:
            contrib_path = Path(repo['path']) / 'CONTRIBUTING.md'
            assert contrib_path.exists()
            content = contrib_path.read_text()
            assert 'Contributing to' in content
            assert repo['name'] in content
