"""Tests for source integration with the refresh command."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.commands.refresh import (
    _resolve_active_sources,
    _update_repo_platform_fields,
    _LOCAL_SOURCE_IDS,
)
from repoindex.sources import MetadataSource


_SENTINEL = object()

def _make_source(source_id, target="repos", batch=False,
                 detect_val=True, fetch_val=_SENTINEL):
    """Helper to create a mock MetadataSource."""
    src = MagicMock(spec=MetadataSource)
    src.source_id = source_id
    src.name = source_id.title()
    src.target = target
    src.batch = batch
    src.detect = MagicMock(return_value=detect_val)
    src.fetch = MagicMock(return_value={'test': True} if fetch_val is _SENTINEL else fetch_val)
    return src


class TestResolveActiveSources:
    """Test the unified source resolution logic."""

    def _resolve(self, source_names=(), provider_names=(), github=None,
                 external=False, config=None):
        if config is None:
            config = {'refresh': {'external_sources': {}, 'providers': {}}}
        return _resolve_active_sources(
            source_names=source_names,
            provider_names=provider_names,
            github=github,
            external=external,
            config=config,
        )

    def test_default_returns_local_sources_only(self):
        """No flags = local sources only."""
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = [
                _make_source('citation_cff'),
                _make_source('keywords'),
            ]
            result = self._resolve()
            # discover_sources called with only=local source IDs
            call_kwargs = mock_discover.call_args
            only = call_kwargs[1].get('only') or call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get('only')
            assert set(only) == _LOCAL_SOURCE_IDS

    def test_source_github_activates_github(self):
        """--source github should request github + local sources."""
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = [_make_source('github')]
            self._resolve(source_names=('github',))
            call_kwargs = mock_discover.call_args
            only = call_kwargs[1].get('only') if call_kwargs[1] else None
            assert only is not None
            assert 'github' in only

    def test_provider_flag_activates_source(self):
        """Deprecated --provider flag should work like --source."""
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = [_make_source('pypi', target='publications')]
            self._resolve(provider_names=('pypi',))
            call_kwargs = mock_discover.call_args
            only = call_kwargs[1].get('only') if call_kwargs[1] else None
            assert only is not None
            assert 'pypi' in only

    def test_github_flag_activates_source(self):
        """--github flag should include github in requested sources."""
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = [_make_source('github')]
            self._resolve(github=True)
            call_kwargs = mock_discover.call_args
            only = call_kwargs[1].get('only') if call_kwargs[1] else None
            assert only is not None
            assert 'github' in only

    def test_no_github_excludes_github(self):
        """--no-github should exclude github even from --external."""
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            github_src = _make_source('github')
            pypi_src = _make_source('pypi', target='publications')
            mock_discover.return_value = [github_src, pypi_src]
            result = self._resolve(github=False, external=True)
            source_ids = [s.source_id for s in result]
            assert 'github' not in source_ids
            assert 'pypi' in source_ids

    def test_external_activates_all_sources(self):
        """--external should return all sources."""
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            all_sources = [
                _make_source('citation_cff'),
                _make_source('github'),
                _make_source('pypi', target='publications'),
            ]
            mock_discover.return_value = all_sources
            result = self._resolve(external=True)
            # discover_sources() called without only= filter
            call_kwargs = mock_discover.call_args
            assert call_kwargs == ((), {}) or call_kwargs[1].get('only') is None

    def test_config_default_github_activates(self):
        """Config github: true should include github."""
        config = {'refresh': {'external_sources': {'github': True}, 'providers': {}}}
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = [_make_source('github')]
            self._resolve(config=config)
            call_kwargs = mock_discover.call_args
            only = call_kwargs[1].get('only') if call_kwargs[1] else None
            assert only is not None
            assert 'github' in only

    def test_config_provider_defaults(self):
        """Config providers: pypi: true should include pypi."""
        config = {'refresh': {'external_sources': {}, 'providers': {'pypi': True}}}
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = [_make_source('pypi', target='publications')]
            self._resolve(config=config)
            call_kwargs = mock_discover.call_args
            only = call_kwargs[1].get('only') if call_kwargs[1] else None
            assert only is not None
            assert 'pypi' in only

    def test_local_sources_always_included(self):
        """Local sources should always be requested unless --external."""
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = []
            self._resolve(source_names=('github',))
            call_kwargs = mock_discover.call_args
            only = call_kwargs[1].get('only') if call_kwargs[1] else None
            assert only is not None
            for local_id in _LOCAL_SOURCE_IDS:
                assert local_id in only

    def test_no_github_with_config_default(self):
        """--no-github overrides config default github: true."""
        config = {'refresh': {'external_sources': {'github': True}, 'providers': {}}}
        with patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = [_make_source('citation_cff')]
            result = self._resolve(github=False, config=config)
            call_kwargs = mock_discover.call_args
            only = call_kwargs[1].get('only') if call_kwargs[1] else None
            if only is not None:
                assert 'github' not in only


class TestSourceWiring:
    """Test that source system is wired into refresh correctly via CLI."""

    def test_source_flag_activates_source(self):
        """--source github should activate github source."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = []
            runner.invoke(refresh_handler, ['--source', 'github'])

        call_kwargs = mock_discover.call_args
        only = call_kwargs[1].get('only') if call_kwargs[1] else None
        assert only is not None
        assert 'github' in only

    def test_github_flag_activates_source(self):
        """--github flag should discover github source."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = []
            runner.invoke(refresh_handler, ['--github'])

        call_kwargs = mock_discover.call_args
        only = call_kwargs[1].get('only') if call_kwargs[1] else None
        assert only is not None
        assert 'github' in only

    def test_provider_flag_backward_compat(self):
        """--provider pypi should work (deprecated but functional)."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = []
            runner.invoke(refresh_handler, ['--provider', 'pypi'])

        call_kwargs = mock_discover.call_args
        only = call_kwargs[1].get('only') if call_kwargs[1] else None
        assert only is not None
        assert 'pypi' in only

    def test_external_discovers_all_sources(self):
        """--external should discover all sources (no filter)."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = []
            runner.invoke(refresh_handler, ['--external'])

        # discover_sources() called without only= filter
        mock_discover.assert_called_once_with()

    def test_no_github_excludes_github_from_external(self):
        """--external --no-github must not include GitHub."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        mock_github = _make_source('github')
        mock_pypi = _make_source('pypi', target='publications')

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.commands.refresh.discover_sources', return_value=[mock_github, mock_pypi]), \
             patch('repoindex.commands.refresh._process_repo') as mock_process:
            runner.invoke(refresh_handler, ['--external', '--no-github'])

        # If _process_repo was called, check that sources didn't include github
        if mock_process.called:
            kwargs = mock_process.call_args.kwargs
            sources = kwargs.get('sources', [])
            source_ids = [s.source_id for s in sources]
            assert 'github' not in source_ids

    def test_no_flags_defaults_to_local_sources(self):
        """No flags = local sources only."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = []
            runner.invoke(refresh_handler, [])

        call_kwargs = mock_discover.call_args
        only = call_kwargs[1].get('only') if call_kwargs[1] else None
        assert only is not None
        assert set(only) == _LOCAL_SOURCE_IDS

    def test_config_default_github_activates_source(self):
        """Config github: true should activate github source."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        with patch('repoindex.commands.refresh.load_config', return_value={
            'repository_directories': [],
            'refresh': {'external_sources': {'github': True}, 'providers': {}},
        }), \
             patch('repoindex.commands.refresh.get_repository_directories', return_value=[]), \
             patch('repoindex.commands.refresh.discover_sources') as mock_discover:
            mock_discover.return_value = []
            runner.invoke(refresh_handler, [])

        call_kwargs = mock_discover.call_args
        only = call_kwargs[1].get('only') if call_kwargs[1] else None
        assert only is not None
        assert 'github' in only


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


class TestProcessRepoWithSources:
    """Test that _process_repo integrates sources correctly."""

    def test_repos_target_source_updates_fields(self):
        """Source with target='repos' should update repo fields via _update_repo_platform_fields."""
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

        mock_source = _make_source('github', target='repos')
        mock_source.detect.return_value = True
        mock_source.fetch.return_value = {'github_stars': 42}

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]), \
             patch('repoindex.commands.refresh._update_repo_platform_fields') as mock_update:
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                sources=[mock_source],
                config={}, dry_run=False, quiet=True,
            )

        mock_update.assert_called_once_with(mock_db, 1, {'github_stars': 42})

    def test_publications_target_source_upserts_publication(self):
        """Source with target='publications' should upsert a publication record."""
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

        mock_source = _make_source('pypi', target='publications')
        mock_source.detect.return_value = True
        mock_source.fetch.return_value = {
            'registry': 'pypi', 'name': 'test-pkg',
            'version': '1.0.0', 'published': True,
        }

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]), \
             patch('repoindex.database.repository._upsert_publication') as mock_upsert:
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                sources=[mock_source],
                config={}, dry_run=False, quiet=True,
            )

        mock_upsert.assert_called_once()
        pkg = mock_upsert.call_args[0][2]
        assert pkg.registry == 'pypi'
        assert pkg.name == 'test-pkg'
        assert pkg.version == '1.0.0'
        assert pkg.published is True

    def test_source_not_called_when_detect_false(self):
        """Source's fetch() should NOT be called when detect() returns False."""
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

        mock_source = _make_source('github', detect_val=False)

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]):
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                sources=[mock_source],
                config={}, dry_run=False, quiet=True,
            )

        mock_source.fetch.assert_not_called()

    def test_source_error_is_warning_not_failure(self):
        """Source errors should be warnings, not failures."""
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

        mock_source = _make_source('github')
        mock_source.detect.side_effect = RuntimeError("API timeout")

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]):
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                sources=[mock_source],
                config={}, dry_run=False, quiet=True,
            )

        # Should still count as updated (source failure is non-fatal)
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
                sources=[],
                config={}, dry_run=False, quiet=True,
            )

        # get_status should be called with just repo, no fetch_github
        mock_service.get_status.assert_called_once_with(mock_repo)

    def test_source_fetch_null_result_skips_update(self):
        """When fetch() returns None, no DB update should happen."""
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

        mock_source = _make_source('github', detect_val=True)
        mock_source.fetch.return_value = None

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]), \
             patch('repoindex.commands.refresh._update_repo_platform_fields') as mock_update:
            _process_repo(
                mock_db, mock_service, mock_repo, stats,
                full=True, since=MagicMock(),
                sources=[mock_source],
                config={}, dry_run=False, quiet=True,
            )

        mock_update.assert_not_called()

    def test_unknown_target_logs_warning_and_skips(self, caplog):
        """A source whose target is neither 'repos' nor 'publications' should
        log a warning and skip, not silently drop the fetched data.

        discover_sources() already filters bad targets, but this defensive
        else-arm catches the case where a source mutates self.target after
        discovery, or is constructed and passed directly (bypassing discovery).
        """
        import logging
        from repoindex.commands.refresh import _process_repo

        mock_db = MagicMock()
        mock_service = MagicMock()
        mock_repo = MagicMock()
        mock_repo.path = '/repos/test'
        mock_repo.name = 'test'

        enriched = MagicMock()
        enriched.remote_url = 'https://example.com/user/test.git'
        enriched.name = 'test'
        enriched.owner = 'user'
        mock_service.get_status.return_value = enriched
        mock_service.config = {}

        stats = {'scanned': 0, 'updated': 0, 'skipped': 0, 'events_added': 0, 'errors': 0}

        # A source with a bogus target — bypasses the discover_sources()
        # validation because we pass it directly.
        mock_source = _make_source('weird', target='somewhere_else')
        mock_source.detect.return_value = True
        mock_source.fetch.return_value = {'arbitrary': 'data'}

        with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
             patch('repoindex.commands.refresh.upsert_repo', return_value=1), \
             patch('repoindex.commands.refresh.clear_scan_error_for_path'), \
             patch('repoindex.commands.refresh.scan_events', return_value=[]), \
             patch('repoindex.commands.refresh._update_repo_platform_fields') as mock_update, \
             patch('repoindex.database.repository._upsert_publication') as mock_upsert:
            with caplog.at_level(logging.WARNING, logger='repoindex.commands.refresh'):
                _process_repo(
                    mock_db, mock_service, mock_repo, stats,
                    full=True, since=MagicMock(),
                    sources=[mock_source],
                    config={}, dry_run=False, quiet=True,
                )

        # Neither dispatch branch should fire
        mock_update.assert_not_called()
        mock_upsert.assert_not_called()
        # Warning surfaced with the source id and its bogus target
        messages = ' '.join(r.message for r in caplog.records)
        assert 'weird' in messages
        assert 'somewhere_else' in messages
        # Stats still reflect a successful update (source failure is non-fatal)
        assert stats['updated'] == 1
        assert stats['errors'] == 0
