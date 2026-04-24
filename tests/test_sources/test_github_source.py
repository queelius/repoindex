"""Tests for the GitHub platform metadata source."""

import pytest
from unittest.mock import patch

from repoindex.sources import MetadataSource


class TestParseGithubRemote:
    """Test the _parse_github_remote helper."""

    def test_https_url(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/queelius/repoindex.git')
        assert owner == 'queelius'
        assert name == 'repoindex'

    def test_ssh_url(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('git@github.com:queelius/repoindex.git')
        assert owner == 'queelius'
        assert name == 'repoindex'

    def test_no_git_suffix(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/queelius/repoindex')
        assert owner == 'queelius'
        assert name == 'repoindex'

    def test_non_github_url(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('https://gitlab.com/user/repo')
        assert owner is None
        assert name is None

    def test_empty_url(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('')
        assert owner is None

    def test_none_url(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote(None)
        assert owner is None

    def test_https_with_trailing_slash(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/user/repo/')
        assert owner == 'user'
        assert name == 'repo'

    def test_ssh_with_port(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('ssh://git@github.com/user/repo.git')
        assert owner == 'user'
        assert name == 'repo'

    def test_parses_dotted_repo_name(self):
        """Names with dots (three.js, Chart.js) must not be truncated."""
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/mrdoob/three.js.git')
        assert owner == 'mrdoob'
        assert name == 'three.js'

    def test_parses_dotted_repo_no_suffix(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/chartjs/Chart.js')
        assert owner == 'chartjs'
        assert name == 'Chart.js'

    def test_parses_rust_repo(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/user/my-lib.rs.git')
        assert owner == 'user'
        assert name == 'my-lib.rs'

    def test_parses_python_repo(self):
        from repoindex.sources.github import _parse_github_remote
        owner, name = _parse_github_remote('git@github.com:user/tool.py.git')
        assert owner == 'user'
        assert name == 'tool.py'


class TestGitHubSource:
    """Test the GitHubSource concrete implementation."""

    @pytest.fixture(autouse=True)
    def _clear_client_cache(self):
        """Clear the cached GitHubClient between tests (singleton pattern)."""
        from repoindex.sources.github import source
        source._client_cache.clear()
        yield
        source._client_cache.clear()

    def test_source_attributes(self):
        from repoindex.sources.github import source
        assert source.source_id == 'github'
        assert source.name == 'GitHub'
        assert source.target == 'repos'
        assert source.batch is False

    def test_is_metadata_source_instance(self):
        from repoindex.sources.github import source
        assert isinstance(source, MetadataSource)

    def test_detect_github_remote(self):
        from repoindex.sources.github import source
        assert source.detect('/repo', {'remote_url': 'https://github.com/user/repo.git'})
        assert source.detect('/repo', {'remote_url': 'git@github.com:user/repo.git'})

    def test_detect_non_github(self):
        from repoindex.sources.github import source
        assert not source.detect('/repo', {'remote_url': 'https://gitlab.com/user/repo'})
        assert not source.detect('/repo', {'remote_url': ''})
        assert not source.detect('/repo', {})
        assert not source.detect('/repo', None)

    def test_fetch_returns_prefixed_fields(self):
        from repoindex.sources.github import source
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

        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            result = source.fetch(
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

    def test_fetch_returns_none_for_non_github(self):
        from repoindex.sources.github import source
        result = source.fetch('/repo', {'remote_url': 'https://gitlab.com/user/repo'})
        assert result is None

    def test_fetch_returns_none_when_api_fails(self):
        from repoindex.sources.github import source
        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = None
            result = source.fetch(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
            )
        assert result is None

    def test_fetch_no_topics_omits_field(self):
        from repoindex.sources.github import source
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

        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            result = source.fetch(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
                config={'github': {'token': 'fake'}},
            )

        assert 'github_topics' not in result
        assert 'github_pushed_at' not in result
        assert result['github_description'] == ''

    def test_fetch_token_from_config(self):
        from repoindex.sources.github import source
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

        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            source.fetch(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
                config={'github': {'token': 'my-token'}},
            )
            MockClient.assert_called_once_with(token='my-token')

    def test_fetch_token_from_env(self):
        from repoindex.sources.github import source
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

        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            with patch.dict('os.environ', {'GITHUB_TOKEN': 'env-token'}, clear=False):
                source.fetch(
                    '/repo',
                    repo_record={'remote_url': 'https://github.com/user/repo.git'},
                    config={},
                )
            MockClient.assert_called_once_with(token='env-token')

    def test_fetch_returns_none_for_no_record(self):
        from repoindex.sources.github import source
        result = source.fetch('/repo', repo_record=None)
        assert result is None

    def test_fetch_returns_none_for_empty_remote(self):
        from repoindex.sources.github import source
        result = source.fetch('/repo', repo_record={'remote_url': ''})
        assert result is None

    def test_fetch_writes_owner_name_and_description(self):
        """Fetch must populate github_owner, github_name, and top-level description.

        record_to_domain() gates GitHubMetadata construction on github_owner,
        and FTS5 search uses the top-level description column.
        """
        from repoindex.sources.github import source
        from repoindex.infra.github_client import GitHubRepo

        mock_repo = GitHubRepo(
            owner='queelius', name='three.js', full_name='queelius/three.js',
            description='A 3D JS library', homepage=None, language='JavaScript',
            stars=100, forks=5, watchers=10, open_issues=2,
            is_fork=False, is_private=False, is_archived=False,
            default_branch='main', topics=[],
            license_key=None, has_issues=True, has_wiki=True, has_pages=False,
            created_at=None, updated_at=None, pushed_at=None,
        )

        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            result = source.fetch(
                '/repo',
                repo_record={'remote_url': 'https://github.com/queelius/three.js.git'},
                config={'github': {'token': 'fake'}},
            )

        assert result['github_owner'] == 'queelius'
        assert result['github_name'] == 'three.js'
        assert result['description'] == 'A 3D JS library'

    def test_fetch_no_description_omits_toplevel_description(self):
        """When GitHub description is empty, don't overwrite top-level description."""
        from repoindex.sources.github import source
        from repoindex.infra.github_client import GitHubRepo

        mock_repo = GitHubRepo(
            owner='user', name='repo', full_name='user/repo',
            description=None, homepage=None, language=None,
            stars=0, forks=0, watchers=0, open_issues=0,
            is_fork=False, is_private=False, is_archived=False,
            default_branch='main', topics=[],
            license_key=None, has_issues=True, has_wiki=True, has_pages=False,
            created_at=None, updated_at=None, pushed_at=None,
        )

        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_repo
            result = source.fetch(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
                config={'github': {'token': 'fake'}},
            )

        # github_owner/name still set, but description NOT in result (won't clobber local)
        assert result['github_owner'] == 'user'
        assert 'description' not in result

    def test_fetch_reuses_client_across_calls(self):
        """GitHubClient should be cached per-token, not re-instantiated per call."""
        from repoindex.sources.github import GitHubSource

        s = GitHubSource()
        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = None
            s.fetch('/r1', {'remote_url': 'https://github.com/a/b.git'}, config={'github': {'token': 't'}})
            s.fetch('/r2', {'remote_url': 'https://github.com/c/d.git'}, config={'github': {'token': 't'}})

        # Same token -> single client construction
        assert MockClient.call_count == 1

    def test_fetch_separate_clients_per_token(self):
        """Different tokens should get separate cached clients."""
        from repoindex.sources.github import GitHubSource

        s = GitHubSource()
        with patch('repoindex.sources.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = None
            s.fetch('/r1', {'remote_url': 'https://github.com/a/b.git'}, config={'github': {'token': 't1'}})
            s.fetch('/r2', {'remote_url': 'https://github.com/c/d.git'}, config={'github': {'token': 't2'}})

        assert MockClient.call_count == 2

    def test_discovered_by_discover_sources(self):
        from repoindex.sources import discover_sources
        sources = discover_sources()
        ids = [s.source_id for s in sources]
        assert 'github' in ids
