"""Tests for the PyPI provider wrapper."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.providers.pypi import PyPIProvider, provider, _fetch_downloads


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


class TestFetchDownloads:
    def test_returns_monthly_downloads(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'data': {'last_day': 100, 'last_week': 700, 'last_month': 3000}
        }
        with patch('repoindex.providers.pypi.requests.get', return_value=mock_resp):
            result = _fetch_downloads('repoindex')
        assert result == 3000

    def test_returns_none_on_404(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch('repoindex.providers.pypi.requests.get', return_value=mock_resp):
            result = _fetch_downloads('nonexistent')
        assert result is None

    def test_returns_none_on_error(self):
        with patch('repoindex.providers.pypi.requests.get', side_effect=Exception("timeout")):
            result = _fetch_downloads('anything')
        assert result is None

    def test_returns_none_on_missing_data_key(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        with patch('repoindex.providers.pypi.requests.get', return_value=mock_resp):
            result = _fetch_downloads('some-pkg')
        assert result is None

    def test_returns_none_on_missing_last_month(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'data': {'last_day': 100}}
        with patch('repoindex.providers.pypi.requests.get', return_value=mock_resp):
            result = _fetch_downloads('some-pkg')
        assert result is None

    def test_calls_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'data': {'last_month': 500}}
        with patch('repoindex.providers.pypi.requests.get', return_value=mock_resp) as mock_get:
            _fetch_downloads('my-package')
        call_args = mock_get.call_args
        assert call_args[0][0] == 'https://pypistats.org/api/packages/my-package/recent'
        assert call_args[1]['timeout'] == 10
        assert 'User-Agent' in call_args[1].get('headers', {})


class TestPyPICheck:
    @patch('repoindex.providers.pypi._fetch_downloads', return_value=4200)
    @patch('repoindex.pypi.check_pypi_package')
    def test_check_published(self, mock_check, mock_downloads):
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
        assert result.downloads_30d == 4200
        assert result.downloads is None  # lifetime total not available from PyPI
        mock_downloads.assert_called_once_with("my-package")

    @patch('repoindex.providers.pypi._fetch_downloads')
    @patch('repoindex.pypi.check_pypi_package')
    def test_check_not_found(self, mock_check, mock_downloads):
        mock_check.return_value = {'exists': False}
        p = PyPIProvider()
        result = p.check("nonexistent-pkg")
        assert result is not None
        assert result.published is False
        assert result.downloads is None
        mock_downloads.assert_not_called()

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

    @patch('repoindex.providers.pypi._fetch_downloads', return_value=None)
    @patch('repoindex.pypi.check_pypi_package')
    def test_check_published_downloads_unavailable(self, mock_check, mock_downloads):
        """Published package but pypistats returns None."""
        mock_check.return_value = {
            'exists': True,
            'version': '1.0.0',
            'url': 'https://pypi.org/project/pkg/',
        }
        p = PyPIProvider()
        result = p.check("pkg")
        assert result is not None
        assert result.published is True
        assert result.downloads_30d is None
        assert result.downloads is None


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
