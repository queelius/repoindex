"""Tests for provider integration with the refresh command."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.commands.refresh import (
    _resolve_provider_names,
    _update_repo_platform_fields,
)


class TestResolveProviderNames:
    """Test the provider name resolution logic."""

    def test_no_flags_returns_empty(self):
        result = _resolve_provider_names(
            provider_names=(),
            external=False, provider_config={},
        )
        assert result == []

    def test_explicit_provider_names(self):
        result = _resolve_provider_names(
            provider_names=('npm', 'cargo'),
            external=False, provider_config={},
        )
        assert set(result) == {'npm', 'cargo'}

    def test_pypi_as_explicit_provider(self):
        """PyPI is passed as an explicit provider name."""
        result = _resolve_provider_names(
            provider_names=('pypi',),
            external=False, provider_config={},
        )
        assert 'pypi' in result

    def test_mixed_explicit_providers(self):
        result = _resolve_provider_names(
            provider_names=('npm', 'pypi', 'cran'),
            external=False, provider_config={},
        )
        assert set(result) == {'npm', 'pypi', 'cran'}

    def test_external_flag_adds_sentinel(self):
        result = _resolve_provider_names(
            provider_names=(),
            external=True, provider_config={},
        )
        assert '__all__' in result

    def test_config_defaults(self):
        """Providers enabled in config are auto-activated."""
        result = _resolve_provider_names(
            provider_names=(),
            external=False,
            provider_config={'npm': True, 'cargo': False},
        )
        assert 'npm' in result
        assert 'cargo' not in result

    def test_config_enables_pypi(self):
        """Setting pypi: true in config enables it without --provider flag."""
        result = _resolve_provider_names(
            provider_names=(),
            external=False,
            provider_config={'pypi': True},
        )
        assert 'pypi' in result

    def test_deduplication(self):
        result = _resolve_provider_names(
            provider_names=('pypi',),
            external=False,
            provider_config={'pypi': True},
        )
        assert result.count('pypi') == 1

    def test_external_plus_explicit(self):
        result = _resolve_provider_names(
            provider_names=('npm',),
            external=True, provider_config={},
        )
        assert '__all__' in result
        assert 'npm' in result

    def test_config_with_multiple_providers(self):
        """Multiple providers enabled in config."""
        result = _resolve_provider_names(
            provider_names=(),
            external=False,
            provider_config={'pypi': True, 'cran': True, 'zenodo': True, 'npm': False},
        )
        assert set(result) == {'pypi', 'cran', 'zenodo'}


class TestPlatformWiring:
    """Test that platform providers are wired into refresh correctly."""

    def test_github_flag_activates_platform(self):
        """--github flag should discover github platform."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.providers.discover_platforms', return_value=[]) as mock_discover:
            runner.invoke(refresh_handler, ['--github'])

        mock_discover.assert_called_once_with(only=['github'])

    def test_provider_github_activates_platform(self):
        """--provider github should discover github platform."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.providers.discover_platforms', return_value=[]) as mock_discover:
            runner.invoke(refresh_handler, ['--provider', 'github'])

        mock_discover.assert_called_once_with(only=['github'])

    def test_external_discovers_all_platforms(self):
        """--external should discover all platforms (no filter)."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.providers.discover_providers', return_value=[]), \
             patch('repoindex.providers.discover_platforms', return_value=[]) as mock_discover:
            runner.invoke(refresh_handler, ['--external'])

        mock_discover.assert_called_once_with()

    def test_no_github_skips_platform(self):
        """--no-github should prevent github platform discovery.

        Even with config default 'github: true', --no-github must exclude github.
        """
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {'github': True}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.providers.discover_platforms', return_value=[]) as mock_discover:
            runner.invoke(refresh_handler, ['--no-github'])

        # If called, must not request github (empty list is OK; None is NOT
        # — None means "all platforms" which would re-include github).
        if mock_discover.called:
            args, kwargs = mock_discover.call_args
            only = kwargs.get('only')
            assert only is not None, "--no-github must not use unfiltered discover_platforms()"
            assert 'github' not in only

    def test_external_plus_no_github_excludes_github(self):
        """--external --no-github must not enrich GitHub (no-github takes priority)."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler
        from unittest.mock import MagicMock as MM

        # Mock a github platform; verify it's filtered out of active_platforms
        mock_github = MM()
        mock_github.platform_id = 'github'

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.providers.discover_platforms', return_value=[mock_github]), \
             patch('repoindex.commands.refresh._process_repo') as mock_process:
            runner.invoke(refresh_handler, ['--external', '--no-github'])

        # If _process_repo was called, check that active_platforms didn't include github
        if mock_process.called:
            kwargs = mock_process.call_args.kwargs
            platforms = kwargs.get('platforms', [])
            platform_ids = [p.platform_id for p in platforms]
            assert 'github' not in platform_ids

    def test_no_flags_no_platforms(self):
        """No flags + no config defaults = no platforms discovered."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.providers.discover_platforms', return_value=[]) as mock_discover:
            runner.invoke(refresh_handler, [])

        # discover_platforms should not be called (no platform names)
        mock_discover.assert_not_called()

    def test_config_default_github_activates_platform(self):
        """Config github: true should discover github platform."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {'github': True}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.providers.discover_platforms', return_value=[]) as mock_discover:
            runner.invoke(refresh_handler, [])

        mock_discover.assert_called_once_with(only=['github'])


class TestUpdateRepoPlatformFields:
    """Test the _update_repo_platform_fields helper."""

    @pytest.fixture(autouse=True)
    def _reset_column_cache(self):
        """Reset the column cache between tests so introspection happens fresh."""
        import repoindex.commands.refresh as refresh_mod
        refresh_mod._REPO_COLUMN_CACHE = None
        yield
        refresh_mod._REPO_COLUMN_CACHE = None

    def _mock_db_with_columns(self, columns):
        """Build a mock db whose PRAGMA table_info returns the given columns."""
        mock_db = MagicMock()
        mock_db.fetchall.return_value = [{'name': c} for c in columns]
        return mock_db

    def test_generates_correct_sql(self):
        """Should produce UPDATE with SET clauses for each field."""
        mock_db = self._mock_db_with_columns(['id', 'github_stars', 'github_forks'])
        _update_repo_platform_fields(mock_db, 42, {
            'github_stars': 100,
            'github_forks': 5,
        })
        # First execute() is PRAGMA, second is UPDATE
        update_call = mock_db.execute.call_args_list[-1]
        sql, params = update_call[0]
        assert 'UPDATE repos SET' in sql
        assert 'github_stars = ?' in sql
        assert 'github_forks = ?' in sql
        assert 'WHERE id = ?' in sql
        # Params order matches dict key iteration (insertion order in 3.7+)
        assert params[-1] == 42  # repo_id is last

    def test_empty_fields_is_noop(self):
        mock_db = MagicMock()
        _update_repo_platform_fields(mock_db, 42, {})
        mock_db.execute.assert_not_called()

    def test_none_fields_is_noop(self):
        mock_db = MagicMock()
        _update_repo_platform_fields(mock_db, 42, None)
        mock_db.execute.assert_not_called()

    def test_drops_unknown_columns(self):
        """Unknown column names should be dropped with a warning, not interpolated."""
        mock_db = self._mock_db_with_columns(['id', 'github_stars'])
        _update_repo_platform_fields(mock_db, 1, {
            'github_stars': 42,
            'nonexistent_column': 'x',
        })
        # PRAGMA + UPDATE (nonexistent dropped)
        update_call = mock_db.execute.call_args_list[-1]
        sql, params = update_call[0]
        assert 'UPDATE repos SET github_stars = ?' in sql
        assert 'nonexistent_column' not in sql

    def test_rejects_sql_injection_identifiers(self):
        """Non-identifier keys (e.g., injection attempts) must not be interpolated."""
        mock_db = self._mock_db_with_columns(['id', 'github_stars'])
        _update_repo_platform_fields(mock_db, 1, {
            'github_stars = 1; DROP TABLE repos; --': 99,
        })
        # Only the PRAGMA should have been executed; no UPDATE because all fields invalid
        calls = mock_db.execute.call_args_list
        assert len(calls) == 1
        assert 'PRAGMA' in calls[0][0][0]

    def test_all_unknown_no_update(self):
        """If every field is unknown, no UPDATE runs (only the PRAGMA)."""
        mock_db = self._mock_db_with_columns(['id', 'github_stars'])
        _update_repo_platform_fields(mock_db, 1, {'unknown_a': 1, 'unknown_b': 2})
        calls = mock_db.execute.call_args_list
        # Only PRAGMA was executed
        assert all('PRAGMA' in call[0][0] for call in calls)

    def test_single_field(self):
        mock_db = self._mock_db_with_columns(['id', 'github_stars'])
        _update_repo_platform_fields(mock_db, 1, {'github_stars': 42})
        update_call = mock_db.execute.call_args_list[-1]
        sql, params = update_call[0]
        assert sql == 'UPDATE repos SET github_stars = ? WHERE id = ?'
        assert params == (42, 1)


class TestProcessRepoWithPlatforms:
    """Test that _process_repo integrates platform providers."""

    def test_platform_enrich_called_for_detected_repo(self):
        """Platform provider's enrich() should be called when detect() returns True."""
        from repoindex.commands.refresh import _process_repo

        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_repo = MagicMock()
        mock_repo.path = '/repos/test'
        mock_repo.name = 'test'

        enriched = MagicMock()
        enriched.remote_url = 'https://github.com/user/test.git'
        enriched.name = 'test'
        enriched.owner = 'user'
        mock_service.get_status.return_value = enriched
        mock_service.config = {}

        stats = {'scanned': 0, 'updated': 0, 'skipped': 0, 'events_added': 0, 'errors': 0}

        mock_platform = MagicMock()
        mock_platform.detect.return_value = True
        mock_platform.enrich.return_value = {'github_stars': 42}

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]), \
             patch('repoindex.commands.refresh._update_repo_platform_fields') as mock_update:
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                platforms=[mock_platform], providers=[],
                config={}, dry_run=False, quiet=True,
            )

        mock_platform.detect.assert_called_once()
        mock_platform.enrich.assert_called_once()
        mock_update.assert_called_once_with(mock_db, 1, {'github_stars': 42})

    def test_platform_not_called_when_detect_false(self):
        """Platform provider's enrich() should NOT be called when detect() returns False."""
        from repoindex.commands.refresh import _process_repo

        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_repo = MagicMock()
        mock_repo.path = '/repos/test'
        mock_repo.name = 'test'

        enriched = MagicMock()
        enriched.remote_url = 'https://gitlab.com/user/test.git'
        enriched.name = 'test'
        enriched.owner = 'user'
        mock_service.get_status.return_value = enriched
        mock_service.config = {}

        stats = {'scanned': 0, 'updated': 0, 'skipped': 0, 'events_added': 0, 'errors': 0}

        mock_platform = MagicMock()
        mock_platform.detect.return_value = False

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]):
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                platforms=[mock_platform], providers=[],
                config={}, dry_run=False, quiet=True,
            )

        mock_platform.detect.assert_called_once()
        mock_platform.enrich.assert_not_called()

    def test_platform_error_is_warning_not_failure(self):
        """Platform provider errors should be warnings, not failures."""
        from repoindex.commands.refresh import _process_repo

        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_repo = MagicMock()
        mock_repo.path = '/repos/test'
        mock_repo.name = 'test'

        enriched = MagicMock()
        enriched.remote_url = 'https://github.com/user/test.git'
        enriched.name = 'test'
        enriched.owner = 'user'
        mock_service.get_status.return_value = enriched
        mock_service.config = {}

        stats = {'scanned': 0, 'updated': 0, 'skipped': 0, 'events_added': 0, 'errors': 0}

        mock_platform = MagicMock()
        mock_platform.name = 'GitHub'
        mock_platform.detect.side_effect = RuntimeError("API timeout")

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]):
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                platforms=[mock_platform], providers=[],
                config={}, dry_run=False, quiet=True,
            )

        # Should still count as updated (platform failure is non-fatal)
        assert stats['updated'] == 1
        assert stats['errors'] == 0

    def test_get_status_called_without_fetch_github(self):
        """service.get_status() should be called without fetch_github parameter."""
        from repoindex.commands.refresh import _process_repo

        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_repo = MagicMock()
        mock_repo.path = '/repos/test'
        mock_repo.name = 'test'

        enriched = MagicMock()
        enriched.remote_url = ''
        enriched.name = 'test'
        mock_service.get_status.return_value = enriched
        mock_service.config = {}

        stats = {'scanned': 0, 'updated': 0, 'skipped': 0, 'events_added': 0, 'errors': 0}

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]):
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                platforms=[], providers=[],
                config={}, dry_run=False, quiet=True,
            )

        # get_status should be called with just repo, no fetch_github
        mock_service.get_status.assert_called_once_with(mock_repo)

    def test_platform_enrich_null_result_skips_update(self):
        """When enrich() returns None, no DB update should happen."""
        from repoindex.commands.refresh import _process_repo

        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_repo = MagicMock()
        mock_repo.path = '/repos/test'
        mock_repo.name = 'test'

        enriched = MagicMock()
        enriched.remote_url = 'https://github.com/user/test.git'
        enriched.name = 'test'
        enriched.owner = 'user'
        mock_service.get_status.return_value = enriched
        mock_service.config = {}

        stats = {'scanned': 0, 'updated': 0, 'skipped': 0, 'events_added': 0, 'errors': 0}

        mock_platform = MagicMock()
        mock_platform.detect.return_value = True
        mock_platform.enrich.return_value = None

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]), \
             patch('repoindex.commands.refresh._update_repo_platform_fields') as mock_update:
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                platforms=[mock_platform], providers=[],
                config={}, dry_run=False, quiet=True,
            )

        mock_update.assert_not_called()
