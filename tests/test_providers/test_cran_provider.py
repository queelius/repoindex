"""Tests for the CRAN provider wrapper."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.providers.cran import CRANProvider, _parse_description, provider


# ---------------------------------------------------------------------------
# Provider attributes
# ---------------------------------------------------------------------------

class TestCRANProviderAttributes:
    def test_registry(self):
        assert provider.registry == "cran"

    def test_name(self):
        assert "CRAN" in provider.name

    def test_not_batch(self):
        assert provider.batch is False


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

class TestCRANDetect:
    def test_detect_r_package(self, tmp_path):
        """Detect R package from DESCRIPTION file."""
        (tmp_path / "DESCRIPTION").write_text(
            "Package: myRpkg\nVersion: 0.1.0\nTitle: Test\n"
        )
        p = CRANProvider()
        assert p.detect(str(tmp_path)) == "myRpkg"

    def test_detect_no_description(self, tmp_path):
        """No DESCRIPTION -> None."""
        p = CRANProvider()
        assert p.detect(str(tmp_path)) is None

    def test_detect_non_r_description(self, tmp_path):
        """DESCRIPTION without Package field -> None."""
        (tmp_path / "DESCRIPTION").write_text("Title: Just a document\n")
        p = CRANProvider()
        assert p.detect(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# check() — crandb JSON API
# ---------------------------------------------------------------------------

class TestCRANCheck:
    @patch('repoindex.providers.cran.requests.get')
    def test_check_published_on_cran(self, mock_get):
        """crandb returns 200 with JSON -> CRAN metadata."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'Package': 'myRpkg',
            'Version': '1.2.0',
            'Title': 'My R Package',
        }
        mock_get.return_value = mock_resp

        p = CRANProvider()
        result = p.check("myRpkg")

        assert result is not None
        assert result.registry == "cran"
        assert result.published is True
        assert result.version == "1.2.0"
        assert result.name == "myRpkg"
        assert "cran.r-project.org" in result.url
        # Only one call needed (CRAN hit, no Bioconductor fallback)
        assert mock_get.call_count == 1
        assert 'crandb.r-pkg.org/myRpkg' in mock_get.call_args[0][0]

    @patch('repoindex.providers.cran.requests.get')
    def test_check_published_on_bioconductor(self, mock_get):
        """crandb 404, Bioconductor 200 -> Bioconductor metadata."""
        cran_resp = MagicMock()
        cran_resp.status_code = 404

        bioc_resp = MagicMock()
        bioc_resp.status_code = 200

        mock_get.side_effect = [cran_resp, bioc_resp]

        p = CRANProvider()
        result = p.check("myBiocPkg")

        assert result is not None
        assert result.registry == "bioconductor"
        assert result.published is True
        assert result.name == "myBiocPkg"
        assert "bioconductor.org" in result.url
        assert mock_get.call_count == 2

    @patch('repoindex.providers.cran.requests.get')
    def test_check_not_published(self, mock_get):
        """Both APIs return 404 -> None."""
        resp_404 = MagicMock()
        resp_404.status_code = 404
        mock_get.return_value = resp_404

        p = CRANProvider()
        result = p.check("unpublished-pkg")

        assert result is None

    @patch('repoindex.providers.cran.requests.get')
    def test_check_cran_exception_falls_through_to_bioc(self, mock_get):
        """Network error on crandb -> still tries Bioconductor."""
        bioc_resp = MagicMock()
        bioc_resp.status_code = 200

        mock_get.side_effect = [Exception("timeout"), bioc_resp]

        p = CRANProvider()
        result = p.check("myBiocPkg")

        assert result is not None
        assert result.registry == "bioconductor"

    @patch('repoindex.providers.cran.requests.get')
    def test_check_both_exception(self, mock_get):
        """Both APIs raise -> None."""
        mock_get.side_effect = Exception("fail")

        p = CRANProvider()
        result = p.check("error-pkg")

        assert result is None

    @patch('repoindex.providers.cran.requests.get')
    def test_check_version_none_when_missing(self, mock_get):
        """crandb JSON missing Version key -> version=None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'Package': 'bare'}
        mock_get.return_value = mock_resp

        p = CRANProvider()
        result = p.check("bare")

        assert result is not None
        assert result.version is None
        assert result.published is True


# ---------------------------------------------------------------------------
# _parse_description()
# ---------------------------------------------------------------------------

class TestParseDescription:
    def test_basic_fields(self, tmp_path):
        """Parse all standard fields."""
        desc = tmp_path / "DESCRIPTION"
        desc.write_text(
            "Package: testpkg\n"
            "Title: My Test Package\n"
            "Version: 1.0.0\n"
            "Author: Jane Doe\n"
            "Maintainer: Jane Doe <jane@example.com>\n"
            "URL: https://example.com/testpkg\n"
            "BugReports: https://example.com/testpkg/issues\n"
            "Description: A package for testing.\n"
            "License: MIT + file LICENSE\n"
        )
        result = _parse_description(str(desc))

        assert result['package'] == 'testpkg'
        assert result['title'] == 'My Test Package'
        assert result['version'] == '1.0.0'
        assert result['author'] == 'Jane Doe'
        assert result['maintainer'] == 'Jane Doe <jane@example.com>'
        assert result['url'] == 'https://example.com/testpkg'
        assert result['bugreports'] == 'https://example.com/testpkg/issues'
        assert result['description'] == 'A package for testing.'
        assert result['license'] == 'MIT + file LICENSE'

    def test_multiline_values(self, tmp_path):
        """Continuation lines (leading whitespace) are joined."""
        desc = tmp_path / "DESCRIPTION"
        desc.write_text(
            "Package: mypkg\n"
            "Version: 0.2.0\n"
            "Description: This is a long description\n"
            "    that spans multiple lines\n"
            "    and keeps going.\n"
            "License: GPL-3\n"
        )
        result = _parse_description(str(desc))

        assert result['description'] == (
            "This is a long description that spans multiple lines and keeps going."
        )
        assert result['license'] == 'GPL-3'

    def test_missing_fields(self, tmp_path):
        """Fields not present in file are None."""
        desc = tmp_path / "DESCRIPTION"
        desc.write_text("Package: minimal\nVersion: 0.0.1\n")
        result = _parse_description(str(desc))

        assert result['package'] == 'minimal'
        assert result['version'] == '0.0.1'
        assert result['title'] is None
        assert result['author'] is None
        assert result['maintainer'] is None
        assert result['url'] is None
        assert result['bugreports'] is None
        assert result['description'] is None
        assert result['license'] is None

    def test_empty_file(self, tmp_path):
        """Empty DESCRIPTION file -> all None."""
        desc = tmp_path / "DESCRIPTION"
        desc.write_text("")
        result = _parse_description(str(desc))

        assert result['package'] is None
        assert result['version'] is None

    def test_nonexistent_file(self, tmp_path):
        """Non-existent path -> all None."""
        result = _parse_description(str(tmp_path / "nope"))

        assert result['package'] is None

    def test_authors_at_r_fallback(self, tmp_path):
        """Authors@R used when Author is absent."""
        desc = tmp_path / "DESCRIPTION"
        desc.write_text(
            "Package: fancy\n"
            "Version: 1.0.0\n"
            'Authors@R: person("Jane", "Doe", role = c("aut", "cre"))\n'
        )
        result = _parse_description(str(desc))

        assert result['author'] is not None
        assert 'Jane' in result['author']

    def test_author_preferred_over_authors_at_r(self, tmp_path):
        """Author field takes precedence over Authors@R."""
        desc = tmp_path / "DESCRIPTION"
        desc.write_text(
            "Package: both\n"
            "Version: 1.0.0\n"
            "Author: Plain Author\n"
            'Authors@R: person("Other", "Person")\n'
        )
        result = _parse_description(str(desc))

        # Author appears first in DCF, so it wins
        assert result['author'] == 'Plain Author'
