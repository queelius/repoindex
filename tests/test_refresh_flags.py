"""
Tests for refresh command external source flags.

Tests the --github, --pypi, --cran, and --external flags,
including config defaults and flag precedence.
"""

import pytest
from unittest.mock import patch, MagicMock

from repoindex.commands.refresh import _resolve_external_flag


class TestResolveExternalFlag:
    """Test the _resolve_external_flag helper function."""

    def test_explicit_true_overrides_all(self):
        """Explicit True flag overrides external and config."""
        assert _resolve_external_flag(True, False, False) is True
        assert _resolve_external_flag(True, True, False) is True
        assert _resolve_external_flag(True, False, True) is True

    def test_explicit_false_overrides_all(self):
        """Explicit False flag overrides external and config."""
        assert _resolve_external_flag(False, True, True) is False
        assert _resolve_external_flag(False, False, True) is False

    def test_external_flag_enables_when_no_explicit(self):
        """--external enables source when no explicit flag given."""
        assert _resolve_external_flag(None, True, False) is True
        assert _resolve_external_flag(None, True, True) is True

    def test_config_default_used_when_no_flags(self):
        """Config default used when no explicit or --external flag."""
        assert _resolve_external_flag(None, False, True) is True
        assert _resolve_external_flag(None, False, False) is False

    def test_priority_explicit_external_config(self):
        """Test priority: explicit > --external > config."""
        # Explicit True wins over everything
        assert _resolve_external_flag(True, False, False) is True

        # Explicit False wins over everything
        assert _resolve_external_flag(False, True, True) is False

        # External wins over config when no explicit
        assert _resolve_external_flag(None, True, False) is True

        # Config used when nothing else
        assert _resolve_external_flag(None, False, True) is True


class TestRefreshHandlerExternalFlags:
    """Test refresh handler with external source flags via CLI help."""

    def test_help_shows_external_flags(self):
        """Help output should show all external source flags."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        result = runner.invoke(refresh_handler, ['--help'])

        assert result.exit_code == 0
        assert '--github / --no-github' in result.output
        assert '--pypi / --no-pypi' in result.output
        assert '--cran / --no-cran' in result.output
        assert '--external' in result.output

    def test_help_explains_external_sources(self):
        """Help should explain external sources are opt-in."""
        from click.testing import CliRunner
        from repoindex.commands.refresh import refresh_handler

        runner = CliRunner()
        result = runner.invoke(refresh_handler, ['--help'])

        assert result.exit_code == 0
        assert 'External sources' in result.output
        assert 'disabled by default' in result.output or 'enabled by default' in result.output
