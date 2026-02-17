"""Tests for the PyPI provider wrapper."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.providers.pypi import PyPIProvider, provider


class TestPyPIProviderAttributes:
    def test_registry(self):
        assert provider.registry == "pypi"

    def test_name(self):
        assert provider.name == "Python Package Index"

    def test_not_batch(self):
        assert provider.batch is False

    def test_is_instance(self):
        assert isinstance(provider, PyPIProvider)


class TestPyPIDetect:
    def test_detect_with_pyproject(self, tmp_path):
        """Detect package name from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text('''
[project]
name = "my-package"
version = "1.0.0"
''')
        p = PyPIProvider()
        assert p.detect(str(tmp_path)) == "my-package"

    def test_detect_no_packaging_files(self, tmp_path):
        """No packaging files → None."""
        p = PyPIProvider()
        assert p.detect(str(tmp_path)) is None

    def test_detect_setup_py(self, tmp_path):
        """Detect from setup.py."""
        (tmp_path / "setup.py").write_text('''
from setuptools import setup
setup(name="legacy-pkg")
''')
        p = PyPIProvider()
        assert p.detect(str(tmp_path)) == "legacy-pkg"


class TestPyPICheck:
    @patch('repoindex.pypi.check_pypi_package')
    def test_check_published(self, mock_check):
        mock_check.return_value = {
            'exists': True,
            'version': '2.0.0',
            'url': 'https://pypi.org/project/my-package/',
            'last_updated': '2025-01-01',
        }
        p = PyPIProvider()
        result = p.check("my-package")
        assert result is not None
        assert result.registry == "pypi"
        assert result.name == "my-package"
        assert result.version == "2.0.0"
        assert result.published is True

    @patch('repoindex.pypi.check_pypi_package')
    def test_check_not_found(self, mock_check):
        mock_check.return_value = {'exists': False}
        p = PyPIProvider()
        result = p.check("nonexistent-pkg")
        assert result is not None
        assert result.published is False

    @patch('repoindex.pypi.check_pypi_package')
    def test_check_api_error(self, mock_check):
        mock_check.return_value = None
        p = PyPIProvider()
        result = p.check("error-pkg")
        assert result is None

    @patch('repoindex.pypi.check_pypi_package')
    def test_check_exception(self, mock_check):
        mock_check.side_effect = Exception("network error")
        p = PyPIProvider()
        result = p.check("broken-pkg")
        assert result is None


class TestPyPIMatch:
    @patch('repoindex.pypi.check_pypi_package')
    def test_match_integration(self, mock_check, tmp_path):
        """Full detect → check flow."""
        (tmp_path / "pyproject.toml").write_text('''
[project]
name = "test-pkg"
''')
        mock_check.return_value = {
            'exists': True,
            'version': '1.0.0',
            'url': 'https://pypi.org/project/test-pkg/',
        }
        p = PyPIProvider()
        result = p.match(str(tmp_path))
        assert result is not None
        assert result.name == "test-pkg"
        assert result.published is True
