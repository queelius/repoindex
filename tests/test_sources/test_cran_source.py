"""Tests for the CRAN metadata source."""

from unittest.mock import patch, MagicMock

import pytest

from repoindex.sources.registries.cran import CRANSource, _parse_description, source


# ---------------------------------------------------------------------------
# Source attributes
# ---------------------------------------------------------------------------

class TestCRANSourceAttributes:
    def test_source_id(self):
        assert source.source_id == "cran"

    def test_name(self):
        assert "CRAN" in source.name

    def test_is_registry_instance(self):
        from repoindex.sources import Registry
        assert isinstance(source, Registry)

    def test_not_batch(self):
        assert source.batch is False


# ---------------------------------------------------------------------------
# detect() / _detect_name()
# ---------------------------------------------------------------------------

class TestCRANDetect:
    def test_detect_r_package(self, tmp_path):
        """Detect R package from DESCRIPTION file."""
        (tmp_path / "DESCRIPTION").write_text(
            "Package: myRpkg\nVersion: 0.1.0\nTitle: Test\n"
        )
        s = CRANSource()
        assert s.detect(str(tmp_path)) is True
        assert s._detect_name(str(tmp_path)) == "myRpkg"

    def test_detect_no_description(self, tmp_path):
        """No DESCRIPTION -> False."""
        s = CRANSource()
        assert s.detect(str(tmp_path)) is False

    def test_detect_non_r_description(self, tmp_path):
        """DESCRIPTION without Package field -> False."""
        (tmp_path / "DESCRIPTION").write_text("Title: Just a document\n")
        s = CRANSource()
        assert s.detect(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# check() -- crandb JSON API
# ---------------------------------------------------------------------------

class TestCRANCheck:
    @patch('repoindex.sources.registries.cran.requests.get')
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

        s = CRANSource()
        result = s.check("myRpkg")

        assert result is not None
        assert result.registry == "cran"
        assert result.published is True
        assert result.version == "1.2.0"
        assert result.name == "myRpkg"
        assert "cran.r-project.org" in result.url
        # Only one call needed (CRAN hit, no Bioconductor fallback)
        assert mock_get.call_count == 1
        assert 'crandb.r-pkg.org/myRpkg' in mock_get.call_args[0][0]

    @patch('repoindex.sources.registries.cran.requests.get')
    def test_check_published_on_bioconductor(self, mock_get):
        """crandb 404, Bioconductor 200 -> Bioconductor metadata."""
        cran_resp = MagicMock()
        cran_resp.status_code = 404

        bioc_resp = MagicMock()
        bioc_resp.status_code = 200

        mock_get.side_effect = [cran_resp, bioc_resp]

        s = CRANSource()
        result = s.check("myBiocPkg")

        assert result is not None
        assert result.registry == "bioconductor"
        assert result.published is True
        assert result.name == "myBiocPkg"
        assert "bioconductor.org" in result.url
        assert mock_get.call_count == 2

    @patch('repoindex.sources.registries.cran.requests.get')
    def test_check_not_published(self, mock_get):
        """Both APIs return 404 -> PackageMetadata(published=False).

        A locally-detected R package that isn't on CRAN or Bioconductor
        should still produce a record (so 'repos I wrote but haven't
        published' queries work).
        """
        resp_404 = MagicMock()
        resp_404.status_code = 404
        mock_get.return_value = resp_404

        s = CRANSource()
        result = s.check("unpublished-pkg")

        assert result is not None
        assert result.published is False
        assert result.registry == 'cran'
        assert result.name == 'unpublished-pkg'

    @patch('repoindex.sources.registries.cran.requests.get')
    def test_check_cran_exception_falls_through_to_bioc(self, mock_get):
        """Network error on crandb -> still tries Bioconductor."""
        bioc_resp = MagicMock()
        bioc_resp.status_code = 200

        mock_get.side_effect = [Exception("timeout"), bioc_resp]

        s = CRANSource()
        result = s.check("myBiocPkg")

        assert result is not None
        assert result.registry == "bioconductor"

    @patch('repoindex.sources.registries.cran.requests.get')
    def test_check_both_exception(self, mock_get):
        """Both APIs raise -> still returns unpublished record (not None)."""
        mock_get.side_effect = Exception("fail")

        s = CRANSource()
        result = s.check("error-pkg")

        assert result is not None
        assert result.published is False

    @patch('repoindex.sources.registries.cran.requests.get')
    def test_check_version_none_when_missing(self, mock_get):
        """crandb JSON missing Version key -> version=None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'Package': 'bare'}
        mock_get.return_value = mock_resp

        s = CRANSource()
        result = s.check("bare")

        assert result is not None
        assert result.version is None
        assert result.published is True


# ---------------------------------------------------------------------------
# fetch() (integration)
# ---------------------------------------------------------------------------

class TestCRANFetch:
    @patch('repoindex.sources.registries.cran.requests.get')
    def test_fetch_integration(self, mock_get, tmp_path):
        (tmp_path / "DESCRIPTION").write_text(
            "Package: testpkg\nVersion: 1.0.0\n"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'Package': 'testpkg', 'Version': '1.0.0'}
        mock_get.return_value = mock_resp

        s = CRANSource()
        result = s.fetch(str(tmp_path))
        assert result is not None
        assert result['name'] == 'testpkg'
        assert result['published'] is True

    def test_fetch_returns_none_without_detection(self, tmp_path):
        s = CRANSource()
        assert s.fetch(str(tmp_path)) is None


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
