"""
Tests for refresh command external source flags.

Tests the --github, --source, --provider, and --external flags,
including config defaults and flag precedence.
"""

import pytest
from unittest.mock import patch, MagicMock

from repoindex.commands.refresh import _resolve_active_sources, _LOCAL_SOURCE_IDS
from repoindex.sources import MetadataSource


def _make_source(source_id, target="repos"):
    """Helper to create a mock MetadataSource."""
    src = MagicMock(spec=MetadataSource)
    src.source_id = source_id
    src.name = source_id.title()
    src.target = target
    src.batch = False
    return src


class TestResolveActiveSources:
    """Test the _resolve_active_sources helper function."""

    def _resolve(self, **kwargs):
        defaults = {
            'source_names': (),
            'provider_names': (),
            'github': None,
            'external': False,
            'config': {'refresh': {'external_sources': {}, 'providers': {}}},
        }
        defaults.update(kwargs)
        return _resolve_active_sources(**defaults)

    def test_github_true_includes_github(self):
        """--github includes github in requested sources."""
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            mock.return_value = [_make_source('github')]
            self._resolve(github=True)
            only = mock.call_args[1].get('only')
            assert 'github' in only

    def test_github_false_excludes_github_from_external(self):
        """--no-github excludes github even with --external."""
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            github_src = _make_source('github')
            pypi_src = _make_source('pypi', target='publications')
            mock.return_value = [github_src, pypi_src]
            result = self._resolve(github=False, external=True)
            ids = [s.source_id for s in result]
            assert 'github' not in ids

    def test_external_gets_all_sources(self):
        """--external discovers all sources."""
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            mock.return_value = []
            self._resolve(external=True)
            # Called without only= filter
            mock.assert_called_once_with()

    def test_config_default_github_enables(self):
        """Config github: true should include github."""
        config = {'refresh': {'external_sources': {'github': True}, 'providers': {}}}
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            mock.return_value = []
            self._resolve(config=config)
            only = mock.call_args[1].get('only')
            assert 'github' in only

    def test_config_default_no_override_explicit_false(self):
        """--no-github overrides config default."""
        config = {'refresh': {'external_sources': {'github': True}, 'providers': {}}}
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            mock.return_value = []
            self._resolve(github=False, config=config)
            only = mock.call_args[1].get('only')
            if only is not None:
                assert 'github' not in only

    def test_no_flags_returns_local_sources(self):
        """No flags = local sources only."""
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            mock.return_value = []
            self._resolve()
            only = mock.call_args[1].get('only')
            assert set(only) == _LOCAL_SOURCE_IDS

    def test_priority_explicit_over_external_over_config(self):
        """Test priority: explicit --no-github > --external > config."""
        # --no-github + --external: github excluded
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            mock.return_value = [_make_source('github'), _make_source('pypi')]
            result = self._resolve(github=False, external=True)
            ids = [s.source_id for s in result]
            assert 'github' not in ids

        # --external alone: github included
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            mock.return_value = [_make_source('github'), _make_source('pypi')]
            result = self._resolve(external=True)
            ids = [s.source_id for s in result]
            assert 'github' in ids

    def test_source_and_provider_flags_merged(self):
        """--source and --provider flags are merged."""
        with patch('repoindex.commands.refresh.discover_sources') as mock:
            mock.return_value = []
            self._resolve(source_names=('github',), provider_names=('pypi',))
            only = mock.call_args[1].get('only')
            assert 'github' in only
            assert 'pypi' in only


class TestRefreshHandlerExternalFlags:
    """Test refresh handler CLI flags."""

    def test_help_shows_source_and_github_flags(self):
        """Help output should show --source, --github, and --external flags."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        result = runner.invoke(refresh_handler, ['--help'])

        assert result.exit_code == 0
        assert '--github / --no-github' in result.output
        assert '--source' in result.output or '-s' in result.output
        assert '--external' in result.output

    def test_help_does_not_show_legacy_flags(self):
        """Help output should NOT show removed --pypi/--cran/--zenodo flags."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        result = runner.invoke(refresh_handler, ['--help'])

        assert result.exit_code == 0
        assert '--pypi' not in result.output
        assert '--cran' not in result.output
        assert '--zenodo / --no-zenodo' not in result.output

    def test_help_does_not_show_deprecated_provider_option(self):
        """--provider is hidden (deprecated) so should not appear in Options section."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        result = runner.invoke(refresh_handler, ['--help'])

        assert result.exit_code == 0
        # --provider is hidden, should not appear as an option
        # (it may appear in the description text, but not in the Options listing)
        options_section = result.output.split('Options:')[1] if 'Options:' in result.output else ''
        assert '-p, --provider' not in options_section
