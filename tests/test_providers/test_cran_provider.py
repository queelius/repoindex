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
        """Both APIs return 404 -> PackageMetadata(published=False).

        A locally-detected R package that isn't on CRAN or Bioconductor
        should still produce a record (so 'repos I wrote but haven't
        published' queries work).
        """
        resp_404 = MagicMock()
        resp_404.status_code = 404
        mock_get.return_value = resp_404

        p = CRANProvider()
        result = p.check("unpublished-pkg")

        assert result is not None
        assert result.published is False
        assert result.registry == 'cran'
        assert result.name == 'unpublished-pkg'

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
        """Both APIs raise -> still returns unpublished record (not None)."""
        mock_get.side_effect = Exception("fail")

        p = CRANProvider()
        result = p.check("error-pkg")

        assert result is not None
        assert result.published is False

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
    """Tests for the simplified DESCRIPTION parser.

    Only the Package field is currently consumed (used by detect()).
    If richer fields are needed later, add them back with tests.
    """

    def test_basic_package(self, tmp_path):
        desc = tmp_path / "DESCRIPTION"
        desc.write_text("Package: testpkg\nVersion: 1.0.0\n")
        result = _parse_description(str(desc))
        assert result['package'] == 'testpkg'

    def test_package_not_on_first_line(self, tmp_path):
        desc = tmp_path / "DESCRIPTION"
        desc.write_text("Title: Some Package\nPackage: mypkg\nVersion: 2.0\n")
        result = _parse_description(str(desc))
        assert result['package'] == 'mypkg'

    def test_empty_file(self, tmp_path):
        desc = tmp_path / "DESCRIPTION"
        desc.write_text("")
        result = _parse_description(str(desc))
        assert result['package'] is None

    def test_no_package_field(self, tmp_path):
        desc = tmp_path / "DESCRIPTION"
        desc.write_text("Title: Only a title\nVersion: 1.0\n")
        result = _parse_description(str(desc))
        assert result['package'] is None

    def test_nonexistent_file(self, tmp_path):
        result = _parse_description(str(tmp_path / "nope"))
        assert result['package'] is None

    def test_package_with_surrounding_whitespace(self, tmp_path):
        desc = tmp_path / "DESCRIPTION"
        desc.write_text("Package:   spaced-pkg  \n")
        result = _parse_description(str(desc))
        assert result['package'] == 'spaced-pkg'
