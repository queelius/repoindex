"""Tests for provider integration with the refresh command."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.commands.refresh import _resolve_provider_names


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
