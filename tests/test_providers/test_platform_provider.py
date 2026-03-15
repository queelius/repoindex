"""Tests for PlatformProvider ABC and discovery."""
import pytest
from unittest.mock import MagicMock


class TestPlatformProviderABC:
    """Test the PlatformProvider ABC interface contract."""

    def test_cannot_instantiate_abstract(self):
        from repoindex.providers import PlatformProvider
        with pytest.raises(TypeError):
            PlatformProvider()

    def test_concrete_implementation(self):
        from repoindex.providers import PlatformProvider

        class FakePlatform(PlatformProvider):
            platform_id = "fake"
            name = "Fake Platform"
            prefix = "fake"

            def detect(self, repo_path, repo_record=None):
                return 'fake.com' in (repo_record or {}).get('remote_url', '')

            def enrich(self, repo_path, repo_record=None, config=None):
                return {'fake_stars': 10}

        p = FakePlatform()
        assert p.platform_id == "fake"
        assert p.prefix == "fake"
        assert p.detect("/repo", {'remote_url': 'https://fake.com/user/repo'})
        assert not p.detect("/repo", {'remote_url': 'https://other.com/user/repo'})
        result = p.enrich("/repo")
        assert result == {'fake_stars': 10}

    def test_platform_provider_in_exports(self):
        from repoindex.providers import PlatformProvider, discover_platforms
        assert PlatformProvider is not None
        assert discover_platforms is not None

    def test_enrich_can_return_none(self):
        from repoindex.providers import PlatformProvider

        class NullPlatform(PlatformProvider):
            platform_id = "null"
            name = "Null"
            prefix = "null"

            def detect(self, repo_path, repo_record=None):
                return True

            def enrich(self, repo_path, repo_record=None, config=None):
                return None

        p = NullPlatform()
        assert p.detect("/repo") is True
        assert p.enrich("/repo") is None

    def test_detect_returns_bool(self):
        from repoindex.providers import PlatformProvider

        class BoolPlatform(PlatformProvider):
            platform_id = "booltest"
            name = "Bool Test"
            prefix = "booltest"

            def detect(self, repo_path, repo_record=None):
                return False

            def enrich(self, repo_path, repo_record=None, config=None):
                return {}

        p = BoolPlatform()
        assert p.detect("/repo") is False

    def test_enrich_receives_config(self):
        from repoindex.providers import PlatformProvider

        class ConfigPlatform(PlatformProvider):
            platform_id = "cfgtest"
            name = "Config Test"
            prefix = "cfgtest"

            def detect(self, repo_path, repo_record=None):
                return True

            def enrich(self, repo_path, repo_record=None, config=None):
                if config and config.get('token'):
                    return {'cfgtest_authenticated': True}
                return {'cfgtest_authenticated': False}

        p = ConfigPlatform()
        result = p.enrich("/repo", config={'token': 'abc123'})
        assert result == {'cfgtest_authenticated': True}
        result_no_config = p.enrich("/repo")
        assert result_no_config == {'cfgtest_authenticated': False}

    def test_default_class_attributes(self):
        from repoindex.providers import PlatformProvider

        class MinimalPlatform(PlatformProvider):
            def detect(self, repo_path, repo_record=None):
                return False

            def enrich(self, repo_path, repo_record=None, config=None):
                return None

        p = MinimalPlatform()
        assert p.platform_id == ""
        assert p.name == ""
        assert p.prefix == ""

    def test_missing_detect_raises_type_error(self):
        from repoindex.providers import PlatformProvider

        with pytest.raises(TypeError):
            class IncompletePlatform(PlatformProvider):
                platform_id = "incomplete"
                name = "Incomplete"
                prefix = "incomplete"

                def enrich(self, repo_path, repo_record=None, config=None):
                    return None

            IncompletePlatform()

    def test_missing_enrich_raises_type_error(self):
        from repoindex.providers import PlatformProvider

        with pytest.raises(TypeError):
            class IncompletePlatform(PlatformProvider):
                platform_id = "incomplete"
                name = "Incomplete"
                prefix = "incomplete"

                def detect(self, repo_path, repo_record=None):
                    return False

            IncompletePlatform()


class TestDiscoverPlatforms:
    """Test the platform discovery mechanism."""

    def test_returns_list(self):
        from repoindex.providers import discover_platforms
        result = discover_platforms()
        assert isinstance(result, list)

    def test_only_filter(self):
        from repoindex.providers import discover_platforms
        # Filter for non-existent platform returns empty
        result = discover_platforms(only=['nonexistent'])
        assert result == []

    def test_only_empty_list_returns_empty(self):
        from repoindex.providers import discover_platforms
        result = discover_platforms(only=[])
        assert result == []

    def test_nonexistent_user_dir(self, tmp_path):
        from repoindex.providers import discover_platforms
        result = discover_platforms(user_dir=str(tmp_path / 'nonexistent'))
        assert isinstance(result, list)

    def test_user_platform_loaded(self, tmp_path):
        """User-provided platforms are loaded from user_dir."""
        from repoindex.providers import discover_platforms
        user_dir = tmp_path / "providers"
        user_dir.mkdir()
        (user_dir / "my_platform.py").write_text('''
from repoindex.providers import PlatformProvider

class MyPlatform(PlatformProvider):
    platform_id = "myplat"
    name = "My Platform"
    prefix = "myplat"
    def detect(self, repo_path, repo_record=None):
        return False
    def enrich(self, repo_path, repo_record=None, config=None):
        return None

platform = MyPlatform()
''')
        result = discover_platforms(user_dir=str(user_dir))
        ids = [p.platform_id for p in result]
        assert "myplat" in ids

    def test_user_platform_with_only_filter(self, tmp_path):
        """User platforms are subject to the 'only' filter."""
        from repoindex.providers import discover_platforms
        user_dir = tmp_path / "providers"
        user_dir.mkdir()
        (user_dir / "my_platform.py").write_text('''
from repoindex.providers import PlatformProvider

class MyPlatform(PlatformProvider):
    platform_id = "myplat"
    name = "My Platform"
    prefix = "myplat"
    def detect(self, repo_path, repo_record=None):
        return False
    def enrich(self, repo_path, repo_record=None, config=None):
        return None

platform = MyPlatform()
''')
        # Match: should include
        result = discover_platforms(user_dir=str(user_dir), only=['myplat'])
        assert any(p.platform_id == 'myplat' for p in result)

        # No match: should exclude
        result = discover_platforms(user_dir=str(user_dir), only=['other'])
        assert not any(p.platform_id == 'myplat' for p in result)

    def test_broken_user_platform_is_skipped(self, tmp_path):
        """A broken user platform file should be skipped with a warning."""
        from repoindex.providers import discover_platforms
        broken = tmp_path / "broken.py"
        broken.write_text("raise RuntimeError('broken')")

        # Should not raise
        result = discover_platforms(user_dir=str(tmp_path))
        assert isinstance(result, list)

    def test_user_file_without_platform_attr_is_skipped(self, tmp_path):
        """A user file that has no 'platform' attribute is silently skipped."""
        from repoindex.providers import discover_platforms
        (tmp_path / "no_attr.py").write_text("x = 42\n")

        result = discover_platforms(user_dir=str(tmp_path))
        assert isinstance(result, list)

    def test_user_file_with_wrong_type_platform_is_skipped(self, tmp_path):
        """A user file whose 'platform' is not a PlatformProvider is skipped."""
        from repoindex.providers import discover_platforms
        (tmp_path / "wrong_type.py").write_text("platform = 'not a provider'\n")

        result = discover_platforms(user_dir=str(tmp_path))
        # Should not include the string
        for p in result:
            assert hasattr(p, 'platform_id')

    def test_underscore_files_are_skipped(self, tmp_path):
        """Files starting with _ are not loaded."""
        from repoindex.providers import discover_platforms
        (tmp_path / "_helper.py").write_text('''
from repoindex.providers import PlatformProvider

class Helper(PlatformProvider):
    platform_id = "helper"
    name = "Helper"
    prefix = "helper"
    def detect(self, repo_path, repo_record=None):
        return False
    def enrich(self, repo_path, repo_record=None, config=None):
        return None

platform = Helper()
''')
        result = discover_platforms(user_dir=str(tmp_path))
        assert not any(p.platform_id == 'helper' for p in result)

    def test_non_py_files_are_skipped(self, tmp_path):
        """Non-.py files are not loaded."""
        from repoindex.providers import discover_platforms
        (tmp_path / "readme.txt").write_text("not a provider")

        result = discover_platforms(user_dir=str(tmp_path))
        assert isinstance(result, list)

    def test_builtin_platforms_list_exists(self):
        from repoindex.providers import BUILTIN_PLATFORMS
        assert isinstance(BUILTIN_PLATFORMS, list)
        assert 'github' in BUILTIN_PLATFORMS

    def test_all_discovered_are_platform_provider_instances(self, tmp_path):
        """All discovered platforms must be PlatformProvider instances."""
        from repoindex.providers import discover_platforms, PlatformProvider
        user_dir = tmp_path / "providers"
        user_dir.mkdir()
        (user_dir / "my_platform.py").write_text('''
from repoindex.providers import PlatformProvider

class MyPlatform(PlatformProvider):
    platform_id = "myplat"
    name = "My Platform"
    prefix = "myplat"
    def detect(self, repo_path, repo_record=None):
        return False
    def enrich(self, repo_path, repo_record=None, config=None):
        return None

platform = MyPlatform()
''')
        result = discover_platforms(user_dir=str(user_dir))
        for p in result:
            assert isinstance(p, PlatformProvider)


class TestParseGithubRemote:
    """Test the _parse_github_remote helper."""

    def test_https_url(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/queelius/repoindex.git')
        assert owner == 'queelius'
        assert name == 'repoindex'

    def test_ssh_url(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('git@github.com:queelius/repoindex.git')
        assert owner == 'queelius'
        assert name == 'repoindex'

    def test_no_git_suffix(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/queelius/repoindex')
        assert owner == 'queelius'
        assert name == 'repoindex'

    def test_non_github_url(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('https://gitlab.com/user/repo')
        assert owner is None
        assert name is None

    def test_empty_url(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('')
        assert owner is None

    def test_none_url(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote(None)
        assert owner is None

    def test_https_with_trailing_slash(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/user/repo/')
        assert owner == 'user'
        assert name == 'repo'

    def test_ssh_with_port(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('ssh://git@github.com/user/repo.git')
        assert owner == 'user'
        assert name == 'repo'


class TestGitHubPlatformProvider:
    """Test the GitHubPlatformProvider concrete implementation."""

    def test_platform_attributes(self):
        from repoindex.providers.github import platform
        assert platform.platform_id == 'github'
        assert platform.prefix == 'github'
        assert platform.name == 'GitHub'

    def test_detect_github_remote(self):
        from repoindex.providers.github import platform
        assert platform.detect('/repo', {'remote_url': 'https://github.com/user/repo.git'})
        assert platform.detect('/repo', {'remote_url': 'git@github.com:user/repo.git'})

    def test_detect_non_github(self):
        from repoindex.providers.github import platform
        assert not platform.detect('/repo', {'remote_url': 'https://gitlab.com/user/repo'})
        assert not platform.detect('/repo', {'remote_url': ''})
        assert not platform.detect('/repo', {})
        assert not platform.detect('/repo', None)

    def test_enrich_returns_prefixed_fields(self):
        from repoindex.providers.github import platform
        from unittest.mock import patch
        from repoindex.infra.github_client import GitHubRepo

        mock_repo = GitHubRepo(
            owner='user', name='repo', full_name='user/repo',
            description='A test repo', homepage=None, language='Python',
            stars=42, forks=3, watchers=5, open_issues=2,
            is_fork=False, is_private=False, is_archived=False,
            default_branch='main', topics=['python', 'cli'],
            license_key='mit', has_issues=True, has_wiki=True, has_pages=False,
            created_at='2024-01-01T00:00:00Z', updated_at='2026-03-14T00:00:00Z',
            pushed_at='2026-03-14T00:00:00Z',
        )

        with patch('repoindex.providers.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            result = platform.enrich(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
                config={'github': {'token': 'fake'}},
            )

        assert result['github_stars'] == 42
        assert result['github_forks'] == 3
        assert result['github_watchers'] == 5
        assert result['github_open_issues'] == 2
        assert result['github_is_fork'] == 0
        assert result['github_is_private'] == 0
        assert result['github_is_archived'] == 0
        assert result['github_description'] == 'A test repo'
        assert result['github_created_at'] == '2024-01-01T00:00:00Z'
        assert result['github_updated_at'] == '2026-03-14T00:00:00Z'
        assert '"python"' in result['github_topics']
        assert '"cli"' in result['github_topics']
        assert result['github_pushed_at'] == '2026-03-14T00:00:00Z'
        assert result['github_has_issues'] == 1
        assert result['github_has_wiki'] == 1
        assert result['github_has_pages'] == 0

    def test_enrich_returns_none_for_non_github(self):
        from repoindex.providers.github import platform
        result = platform.enrich('/repo', {'remote_url': 'https://gitlab.com/user/repo'})
        assert result is None

    def test_enrich_returns_none_when_api_fails(self):
        from repoindex.providers.github import platform
        from unittest.mock import patch
        with patch('repoindex.providers.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = None
            result = platform.enrich(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
            )
        assert result is None

    def test_enrich_no_topics_omits_field(self):
        from repoindex.providers.github import platform
        from unittest.mock import patch
        from repoindex.infra.github_client import GitHubRepo

        mock_repo = GitHubRepo(
            owner='user', name='repo', full_name='user/repo',
            description=None, homepage=None, language=None,
            stars=0, forks=0, watchers=0, open_issues=0,
            is_fork=False, is_private=False, is_archived=False,
            default_branch='main', topics=[],
            license_key=None, has_issues=False, has_wiki=False, has_pages=False,
            created_at=None, updated_at=None, pushed_at=None,
        )

        with patch('repoindex.providers.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            result = platform.enrich(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
                config={'github': {'token': 'fake'}},
            )

        assert 'github_topics' not in result
        assert 'github_pushed_at' not in result
        assert result['github_description'] == ''

    def test_enrich_token_from_config(self):
        from repoindex.providers.github import platform
        from unittest.mock import patch
        from repoindex.infra.github_client import GitHubRepo

        mock_repo = GitHubRepo(
            owner='user', name='repo', full_name='user/repo',
            description='test', homepage=None, language=None,
            stars=1, forks=0, watchers=0, open_issues=0,
            is_fork=False, is_private=False, is_archived=False,
            default_branch='main', topics=[],
            license_key=None, has_issues=True, has_wiki=False, has_pages=False,
            created_at=None, updated_at=None, pushed_at=None,
        )

        with patch('repoindex.providers.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            platform.enrich(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
                config={'github': {'token': 'my-token'}},
            )
            MockClient.assert_called_once_with(token='my-token')

    def test_enrich_token_from_env(self):
        from repoindex.providers.github import platform
        from unittest.mock import patch
        from repoindex.infra.github_client import GitHubRepo

        mock_repo = GitHubRepo(
            owner='user', name='repo', full_name='user/repo',
            description='test', homepage=None, language=None,
            stars=1, forks=0, watchers=0, open_issues=0,
            is_fork=False, is_private=False, is_archived=False,
            default_branch='main', topics=[],
            license_key=None, has_issues=True, has_wiki=False, has_pages=False,
            created_at=None, updated_at=None, pushed_at=None,
        )

        with patch('repoindex.providers.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            with patch.dict('os.environ', {'GITHUB_TOKEN': 'env-token'}, clear=False):
                platform.enrich(
                    '/repo',
                    repo_record={'remote_url': 'https://github.com/user/repo.git'},
                    config={},
                )
            MockClient.assert_called_once_with(token='env-token')

    def test_enrich_returns_none_for_no_record(self):
        from repoindex.providers.github import platform
        result = platform.enrich('/repo', repo_record=None)
        assert result is None

    def test_enrich_returns_none_for_empty_remote(self):
        from repoindex.providers.github import platform
        result = platform.enrich('/repo', repo_record={'remote_url': ''})
        assert result is None

    def test_discovered_by_discover_platforms(self):
        from repoindex.providers import discover_platforms
        platforms = discover_platforms()
        ids = [p.platform_id for p in platforms]
        assert 'github' in ids

    def test_is_platform_provider_instance(self):
        from repoindex.providers.github import platform
        from repoindex.providers import PlatformProvider
        assert isinstance(platform, PlatformProvider)
