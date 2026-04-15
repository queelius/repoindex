"""Tests for GiteaSource (Codeberg/Gitea/Forgejo)."""
import json
import pytest
from unittest.mock import patch, MagicMock


class TestParseGiteaRemote:
    """Tests for the _parse_gitea_remote URL parsing helper."""

    def test_codeberg_https(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/user/repo.git', _DEFAULT_HOSTS
        )
        assert host == 'codeberg.org'
        assert owner == 'user'
        assert name == 'repo'

    def test_codeberg_no_git_suffix(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/user/repo', _DEFAULT_HOSTS
        )
        assert host == 'codeberg.org'
        assert owner == 'user'
        assert name == 'repo'

    def test_codeberg_trailing_slash(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/user/repo/', _DEFAULT_HOSTS
        )
        assert host == 'codeberg.org'
        assert owner == 'user'
        assert name == 'repo'

    def test_codeberg_ssh(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'git@codeberg.org:user/repo.git', _DEFAULT_HOSTS
        )
        assert host == 'codeberg.org'
        assert owner == 'user'
        assert name == 'repo'

    def test_codeberg_ssh_no_suffix(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'git@codeberg.org:user/repo', _DEFAULT_HOSTS
        )
        assert host == 'codeberg.org'
        assert owner == 'user'
        assert name == 'repo'

    def test_custom_host(self):
        from repoindex.sources.gitea import _parse_gitea_remote
        host, owner, name = _parse_gitea_remote(
            'https://git.mycompany.com/team/project.git',
            ['git.mycompany.com']
        )
        assert host == 'git.mycompany.com'
        assert owner == 'team'
        assert name == 'project'

    def test_multiple_hosts_first_match(self):
        from repoindex.sources.gitea import _parse_gitea_remote
        hosts = ['git.internal.com', 'codeberg.org']
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/user/repo.git', hosts
        )
        assert host == 'codeberg.org'
        assert owner == 'user'
        assert name == 'repo'

    def test_non_gitea_url(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'https://github.com/user/repo', _DEFAULT_HOSTS
        )
        assert host is None
        assert owner is None
        assert name is None

    def test_empty_url(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote('', _DEFAULT_HOSTS)
        assert host is None

    def test_none_url(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(None, _DEFAULT_HOSTS)
        assert host is None

    def test_dotted_repo_name(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/user/my-lib.rs.git', _DEFAULT_HOSTS
        )
        assert name == 'my-lib.rs'

    def test_hyphenated_names(self):
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/my-org/my-project.git', _DEFAULT_HOSTS
        )
        assert owner == 'my-org'
        assert name == 'my-project'

    def test_empty_hosts_list(self):
        from repoindex.sources.gitea import _parse_gitea_remote
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/user/repo.git', []
        )
        assert host is None

    def test_url_with_port(self):
        """HTTPS URLs with explicit ports should parse correctly (port is not owner)."""
        from repoindex.sources.gitea import _parse_gitea_remote
        host, owner, name = _parse_gitea_remote(
            'https://gitea.example.com:3000/user/repo.git',
            ['gitea.example.com']
        )
        assert host == 'gitea.example.com'
        assert owner == 'user'
        assert name == 'repo'

    def test_https_url_with_port_443(self):
        """Explicit https port 443 should be stripped, not treated as owner."""
        from repoindex.sources.gitea import _parse_gitea_remote
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org:443/user/repo', ['codeberg.org']
        )
        assert host == 'codeberg.org'
        assert owner == 'user'
        assert name == 'repo'

    def test_http_url_with_port(self):
        """HTTP URL with port should also work."""
        from repoindex.sources.gitea import _parse_gitea_remote
        host, owner, name = _parse_gitea_remote(
            'http://gitea.internal:8080/team/project.git',
            ['gitea.internal']
        )
        assert host == 'gitea.internal'
        assert owner == 'team'
        assert name == 'project'

    def test_subgroup_path(self):
        """Nested subgroup paths: parent/sub/repo -> owner='parent/sub', name='repo'."""
        from repoindex.sources.gitea import _parse_gitea_remote
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/parent/sub/repo', ['codeberg.org']
        )
        assert host == 'codeberg.org'
        # Repo name is the last segment; nested subgroups are joined as owner
        assert owner == 'parent/sub'
        assert name == 'repo'

    def test_deep_subgroup_path(self):
        """Deeply nested subgroups should still parse."""
        from repoindex.sources.gitea import _parse_gitea_remote
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/a/b/c/d/repo.git', ['codeberg.org']
        )
        assert host == 'codeberg.org'
        assert owner == 'a/b/c/d'
        assert name == 'repo'

    def test_ssh_with_scheme(self):
        """ssh:// scheme URL should work too."""
        from repoindex.sources.gitea import _parse_gitea_remote
        host, owner, name = _parse_gitea_remote(
            'ssh://git@codeberg.org/user/repo.git', ['codeberg.org']
        )
        assert host == 'codeberg.org'
        assert owner == 'user'
        assert name == 'repo'

    def test_missing_owner(self):
        """URL missing owner/repo parts should return None."""
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/onlyone', _DEFAULT_HOSTS
        )
        assert host is None

    def test_just_host_no_path(self):
        """URL with just host, no path, should return None."""
        from repoindex.sources.gitea import _parse_gitea_remote, _DEFAULT_HOSTS
        host, owner, name = _parse_gitea_remote(
            'https://codeberg.org/', _DEFAULT_HOSTS
        )
        assert host is None


class TestGiteaSourceAttributes:
    """Tests for GiteaSource class attributes and identity."""

    def test_source_id(self):
        from repoindex.sources.gitea import source
        assert source.source_id == 'gitea'

    def test_target(self):
        from repoindex.sources.gitea import source
        assert source.target == 'repos'

    def test_name(self):
        from repoindex.sources.gitea import source
        assert source.name == 'Gitea / Codeberg'

    def test_batch_default(self):
        from repoindex.sources.gitea import source
        assert source.batch is False


class TestGiteaSourceDetect:
    """Tests for GiteaSource.detect().

    detect() always returns True so that fetch() (which has access to config)
    can do the actual host matching. This allows self-hosted Gitea users with
    custom hosts in config to use this source. fetch() returns None if the URL
    doesn't match any configured host.
    """

    def test_detect_codeberg(self):
        from repoindex.sources.gitea import source
        assert source.detect('/repo', {'remote_url': 'https://codeberg.org/user/repo.git'})

    def test_detect_codeberg_ssh(self):
        from repoindex.sources.gitea import source
        assert source.detect('/repo', {'remote_url': 'git@codeberg.org:user/repo.git'})

    def test_detect_non_gitea_still_true(self):
        """detect() returns True even for non-Gitea URLs; fetch() filters."""
        from repoindex.sources.gitea import source
        assert source.detect('/repo', {'remote_url': 'https://github.com/user/repo'})

    def test_detect_empty_record_still_true(self):
        from repoindex.sources.gitea import source
        assert source.detect('/repo', {})

    def test_detect_none_record_still_true(self):
        from repoindex.sources.gitea import source
        assert source.detect('/repo', None)

    def test_detect_no_remote_url_still_true(self):
        from repoindex.sources.gitea import source
        assert source.detect('/repo', {'name': 'myrepo'})


class TestGiteaSourceFetch:
    """Tests for GiteaSource.fetch()."""

    def _make_api_response(self, **overrides):
        """Build a mock Gitea API response with sensible defaults."""
        data = {
            'stars_count': 10,
            'forks_count': 2,
            'watchers_count': 5,
            'open_issues_count': 1,
            'fork': False,
            'private': False,
            'archived': False,
            'description': 'A cool project',
            'created_at': '2025-01-01T00:00:00Z',
            'updated_at': '2026-03-15T00:00:00Z',
            'topics': ['python', 'tool'],
            'has_issues': True,
            'has_wiki': True,
            'has_pull_requests': True,
        }
        data.update(overrides)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = data
        return mock_resp

    def test_fetch_returns_prefixed_fields(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result['gitea_stars'] == 10
        assert result['gitea_forks'] == 2
        assert result['gitea_watchers'] == 5
        assert result['gitea_open_issues'] == 1
        assert result['gitea_owner'] == 'user'
        assert result['gitea_name'] == 'repo'
        assert result['gitea_host'] == 'codeberg.org'

    def test_fetch_description_also_sets_top_level(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response(description='A cool project')
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result['description'] == 'A cool project'
        assert result['gitea_description'] == 'A cool project'

    def test_fetch_empty_description(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response(description='')
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result['gitea_description'] == ''
        assert 'description' not in result  # not set when empty

    def test_fetch_null_description(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response(description=None)
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result['gitea_description'] == ''
        assert 'description' not in result

    def test_fetch_topics_json_serialized(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response(topics=['python', 'tool'])
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        parsed = json.loads(result['gitea_topics'])
        assert parsed == ['python', 'tool']

    def test_fetch_no_topics(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response(topics=None)
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert 'gitea_topics' not in result

    def test_fetch_empty_topics_list(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response(topics=[])
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert 'gitea_topics' not in result

    def test_fetch_boolean_flags(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response(
            fork=True, private=True, archived=True,
            has_issues=False, has_wiki=False, has_pull_requests=False,
        )
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result['gitea_is_fork'] == 1
        assert result['gitea_is_private'] == 1
        assert result['gitea_is_archived'] == 1
        assert result['gitea_has_issues'] == 0
        assert result['gitea_has_wiki'] == 0
        assert result['gitea_has_pull_requests'] == 0

    def test_fetch_timestamps(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response(
            created_at='2025-01-01T00:00:00Z',
            updated_at='2026-03-15T12:30:00Z',
        )
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result['gitea_created_at'] == '2025-01-01T00:00:00Z'
        assert result['gitea_updated_at'] == '2026-03-15T12:30:00Z'

    def test_fetch_api_404(self):
        from repoindex.sources.gitea import source
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result is None

    def test_fetch_api_500(self):
        from repoindex.sources.gitea import source
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result is None

    def test_fetch_network_error(self):
        from repoindex.sources.gitea import source
        with patch('repoindex.sources.gitea.requests.Session.get', side_effect=Exception('timeout')):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result is None

    def test_fetch_non_gitea_returns_none(self):
        from repoindex.sources.gitea import source
        result = source.fetch('/repo', {'remote_url': 'https://github.com/user/repo'})
        assert result is None

    def test_fetch_no_record_returns_none(self):
        from repoindex.sources.gitea import source
        result = source.fetch('/repo', None)
        assert result is None

    def test_fetch_empty_record_returns_none(self):
        from repoindex.sources.gitea import source
        result = source.fetch('/repo', {})
        assert result is None

    def test_fetch_with_token(self):
        from repoindex.sources.gitea import GiteaSource
        # Use a fresh instance so we can inspect its session cache
        src = GiteaSource()
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            src.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {
                    'hosts': ['codeberg.org'],
                    'tokens': {'codeberg.org': 'my-token'},
                }},
            )
        session = src._client_cache[('codeberg.org', 'my-token')]
        assert session.headers['Authorization'] == 'token my-token'

    def test_fetch_without_token(self):
        from repoindex.sources.gitea import GiteaSource
        src = GiteaSource()
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            src.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        session = src._client_cache[('codeberg.org', None)]
        assert 'Authorization' not in session.headers

    def test_fetch_api_url_construction(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp) as mock_get:
            source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/myorg/myrepo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        call_url = mock_get.call_args[0][0]
        assert call_url == 'https://codeberg.org/api/v1/repos/myorg/myrepo'

    def test_fetch_custom_host_api_url(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp) as mock_get:
            source.fetch(
                '/repo',
                {'remote_url': 'https://git.example.com/team/proj.git'},
                config={'gitea': {'hosts': ['git.example.com']}},
            )
        call_url = mock_get.call_args[0][0]
        assert call_url == 'https://git.example.com/api/v1/repos/team/proj'

    def test_fetch_uses_config_hosts(self):
        """fetch() uses hosts from config, not just defaults."""
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://git.custom.org/user/repo.git'},
                config={'gitea': {'hosts': ['git.custom.org']}},
            )
        assert result is not None
        assert result['gitea_host'] == 'git.custom.org'

    def test_fetch_default_hosts_when_no_config(self):
        """fetch() uses default hosts when config is None."""
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config=None,
            )
        assert result is not None
        assert result['gitea_host'] == 'codeberg.org'

    def test_fetch_sparse_api_response(self):
        """fetch() handles an API response with minimal fields."""
        from repoindex.sources.gitea import source
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}  # Minimal response
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            result = source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert result is not None
        assert result['gitea_stars'] == 0
        assert result['gitea_forks'] == 0
        assert result['gitea_is_fork'] == 0
        assert result['gitea_description'] == ''

    def test_fetch_timeout_parameter(self):
        from repoindex.sources.gitea import source
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp) as mock_get:
            source.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        assert mock_get.call_args[1]['timeout'] == 10

    def test_fetch_user_agent(self):
        from repoindex.sources.gitea import GiteaSource
        src = GiteaSource()
        mock_resp = self._make_api_response()
        with patch('repoindex.sources.gitea.requests.Session.get', return_value=mock_resp):
            src.fetch(
                '/repo',
                {'remote_url': 'https://codeberg.org/user/repo.git'},
                config={'gitea': {'hosts': ['codeberg.org']}},
            )
        session = src._client_cache[('codeberg.org', None)]
        assert 'repoindex' in session.headers['User-Agent']


class TestGiteaSourceConfig:
    """Tests for configuration handling."""

    def test_get_hosts_default(self):
        from repoindex.sources.gitea import GiteaSource
        s = GiteaSource()
        assert s._get_hosts(None) == ['codeberg.org']
        assert s._get_hosts({}) == ['codeberg.org']

    def test_get_hosts_custom(self):
        from repoindex.sources.gitea import GiteaSource
        s = GiteaSource()
        hosts = s._get_hosts({'gitea': {'hosts': ['git.example.com', 'codeberg.org']}})
        assert hosts == ['git.example.com', 'codeberg.org']

    def test_get_token_found(self):
        from repoindex.sources.gitea import GiteaSource
        s = GiteaSource()
        token = s._get_token(
            {'gitea': {'tokens': {'codeberg.org': 'abc123'}}},
            'codeberg.org'
        )
        assert token == 'abc123'

    def test_get_token_not_found(self):
        from repoindex.sources.gitea import GiteaSource
        s = GiteaSource()
        assert s._get_token({'gitea': {'tokens': {}}}, 'codeberg.org') is None
        assert s._get_token({}, 'codeberg.org') is None
        assert s._get_token(None, 'codeberg.org') is None


class TestGiteaSourceDiscovery:
    """Test that GiteaSource is discoverable via discover_sources."""

    def test_discovered_by_discover_sources(self):
        from repoindex.sources import discover_sources
        # Clear the cache to force re-discovery
        import repoindex.sources as sources_mod
        sources_mod._BUILTIN_SOURCES_CACHE = None
        try:
            sources = discover_sources()
            ids = [s.source_id for s in sources]
            assert 'gitea' in ids
        finally:
            # Reset cache so other tests aren't affected
            sources_mod._BUILTIN_SOURCES_CACHE = None

    def test_only_filter_gitea(self):
        from repoindex.sources import discover_sources
        import repoindex.sources as sources_mod
        sources_mod._BUILTIN_SOURCES_CACHE = None
        try:
            sources = discover_sources(only=['gitea'])
            assert len(sources) == 1
            assert sources[0].source_id == 'gitea'
            assert sources[0].target == 'repos'
        finally:
            sources_mod._BUILTIN_SOURCES_CACHE = None


class TestGiteaSchemaColumns:
    """Test that the database schema includes gitea columns."""

    def test_schema_has_gitea_columns(self):
        from repoindex.database.schema import SCHEMA_V1
        gitea_cols = [
            'gitea_owner', 'gitea_name', 'gitea_host',
            'gitea_stars', 'gitea_forks', 'gitea_watchers',
            'gitea_open_issues', 'gitea_is_fork', 'gitea_is_private',
            'gitea_is_archived', 'gitea_description', 'gitea_topics',
            'gitea_created_at', 'gitea_updated_at',
            'gitea_has_issues', 'gitea_has_wiki', 'gitea_has_pull_requests',
        ]
        for col in gitea_cols:
            assert col in SCHEMA_V1, f"Column {col} not found in schema"

    def test_schema_version_bumped(self):
        from repoindex.database.schema import CURRENT_VERSION
        assert CURRENT_VERSION >= 8

    def test_schema_creates_table_with_gitea_columns(self):
        """Verify the schema can be applied to a real SQLite database."""
        import sqlite3
        from repoindex.database.schema import apply_schema
        conn = sqlite3.connect(':memory:')
        apply_schema(conn)
        # Check that gitea columns exist
        cursor = conn.execute("PRAGMA table_info(repos)")
        columns = {row[1] for row in cursor.fetchall()}
        assert 'gitea_stars' in columns
        assert 'gitea_host' in columns
        assert 'gitea_topics' in columns
        assert 'gitea_has_pull_requests' in columns
        conn.close()
