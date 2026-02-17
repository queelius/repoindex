"""Tests for the CRAN provider wrapper."""

from unittest.mock import patch

import pytest

from repoindex.providers.cran import CRANProvider, provider


class TestCRANProviderAttributes:
    def test_registry(self):
        assert provider.registry == "cran"

    def test_name(self):
        assert "CRAN" in provider.name

    def test_not_batch(self):
        assert provider.batch is False


class TestCRANDetect:
    def test_detect_r_package(self, tmp_path):
        """Detect R package from DESCRIPTION file."""
        (tmp_path / "DESCRIPTION").write_text(
            "Package: myRpkg\nVersion: 0.1.0\nTitle: Test\n"
        )
        p = CRANProvider()
        assert p.detect(str(tmp_path)) == "myRpkg"

    def test_detect_no_description(self, tmp_path):
        """No DESCRIPTION → None."""
        p = CRANProvider()
        assert p.detect(str(tmp_path)) is None

    def test_detect_non_r_description(self, tmp_path):
        """DESCRIPTION without Package field → None."""
        (tmp_path / "DESCRIPTION").write_text("Title: Just a document\n")
        p = CRANProvider()
        assert p.detect(str(tmp_path)) is None


class TestCRANCheck:
    @patch('repoindex.cran.check_bioconductor_package')
    @patch('repoindex.cran.check_cran_package')
    def test_check_published_on_cran(self, mock_cran, mock_bioc):
        mock_cran.return_value = {
            'exists': True,
            'version': '1.2.0',
            'url': 'https://cran.r-project.org/package=myRpkg',
        }
        p = CRANProvider()
        result = p.check("myRpkg")
        assert result is not None
        assert result.registry == "cran"
        assert result.published is True
        assert result.version == "1.2.0"
        mock_bioc.assert_not_called()

    @patch('repoindex.cran.check_bioconductor_package')
    @patch('repoindex.cran.check_cran_package')
    def test_check_published_on_bioconductor(self, mock_cran, mock_bioc):
        mock_cran.return_value = {'exists': False}
        mock_bioc.return_value = {
            'exists': True,
            'version': '3.0',
            'url': 'https://bioconductor.org/packages/myBiocPkg',
        }
        p = CRANProvider()
        result = p.check("myBiocPkg")
        assert result is not None
        assert result.registry == "bioconductor"
        assert result.published is True

    @patch('repoindex.cran.check_bioconductor_package')
    @patch('repoindex.cran.check_cran_package')
    def test_check_not_published(self, mock_cran, mock_bioc):
        mock_cran.return_value = {'exists': False}
        mock_bioc.return_value = {'exists': False}
        p = CRANProvider()
        result = p.check("unpublished-pkg")
        assert result is not None
        assert result.published is False

    @patch('repoindex.cran.check_bioconductor_package')
    @patch('repoindex.cran.check_cran_package')
    def test_check_exception(self, mock_cran, mock_bioc):
        mock_cran.side_effect = Exception("fail")
        p = CRANProvider()
        result = p.check("error-pkg")
        assert result is None
