"""
Unit tests for ghops.cran module - R package detection and CRAN integration
"""
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.cran import (
    find_r_package_files,
    parse_description_file,
    extract_package_name,
    extract_package_version,
    extract_package_info,
    check_cran_package,
    check_bioconductor_package,
    detect_r_package,
    is_r_package_outdated,
    is_r_package,
)


class TestFindRPackageFiles(unittest.TestCase):
    """Test R package file detection."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_find_description_file(self):
        """Find DESCRIPTION file in repo."""
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text("Package: testpkg\nVersion: 1.0.0")

        files = find_r_package_files(self.temp_dir)

        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith('DESCRIPTION'))

    def test_find_both_files(self):
        """Find both DESCRIPTION and NAMESPACE files."""
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text("Package: testpkg\nVersion: 1.0.0")
        ns_path = Path(self.temp_dir) / "NAMESPACE"
        ns_path.write_text("export(my_func)")

        files = find_r_package_files(self.temp_dir)

        self.assertEqual(len(files), 2)

    def test_no_r_package_files(self):
        """Return empty list when no R package files found."""
        files = find_r_package_files(self.temp_dir)

        self.assertEqual(len(files), 0)


class TestParseDescriptionFile(unittest.TestCase):
    """Test DESCRIPTION file parsing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_parse_simple_description(self):
        """Parse simple DESCRIPTION file."""
        content = """Package: testpkg
Version: 1.0.0
Title: Test Package
Description: A test package for testing.
Author: Test Author
Maintainer: Test Maintainer <test@example.com>
License: MIT
"""
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        result = parse_description_file(str(desc_path))

        self.assertEqual(result['Package'], 'testpkg')
        self.assertEqual(result['Version'], '1.0.0')
        self.assertEqual(result['Title'], 'Test Package')
        self.assertEqual(result['License'], 'MIT')

    def test_parse_multiline_description(self):
        """Parse DESCRIPTION with multiline field."""
        content = """Package: testpkg
Version: 1.0.0
Description: This is a long description
    that continues on multiple lines
    and has more content here.
License: GPL-3
"""
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        result = parse_description_file(str(desc_path))

        self.assertIn('long description', result['Description'])
        self.assertIn('multiple lines', result['Description'])

    def test_parse_with_depends(self):
        """Parse DESCRIPTION with Depends field."""
        content = """Package: testpkg
Version: 1.0.0
Depends: R (>= 3.5.0), dplyr, ggplot2
Imports: httr, jsonlite
Suggests: testthat
"""
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        result = parse_description_file(str(desc_path))

        self.assertIn('R (>= 3.5.0)', result['Depends'])
        self.assertIn('httr', result['Imports'])

    def test_parse_nonexistent_file(self):
        """Return empty dict for nonexistent file."""
        result = parse_description_file("/nonexistent/DESCRIPTION")

        self.assertEqual(result, {})


class TestExtractPackageName(unittest.TestCase):
    """Test package name extraction."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_extract_name(self):
        """Extract package name from DESCRIPTION."""
        content = "Package: myRpackage\nVersion: 2.0.0"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        name = extract_package_name(self.temp_dir)

        self.assertEqual(name, 'myRpackage')

    def test_no_description_file(self):
        """Return None when no DESCRIPTION file."""
        name = extract_package_name(self.temp_dir)

        self.assertIsNone(name)


class TestExtractPackageVersion(unittest.TestCase):
    """Test package version extraction."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_extract_version(self):
        """Extract version from DESCRIPTION."""
        content = "Package: testpkg\nVersion: 1.2.3"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        version = extract_package_version(self.temp_dir)

        self.assertEqual(version, '1.2.3')

    def test_extract_version_with_dash(self):
        """Extract version with dash notation (R convention)."""
        content = "Package: testpkg\nVersion: 1.2-3"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        version = extract_package_version(self.temp_dir)

        self.assertEqual(version, '1.2-3')


class TestExtractPackageInfo(unittest.TestCase):
    """Test full package info extraction."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_extract_full_info(self):
        """Extract all package information."""
        content = """Package: analytics
Version: 3.1.0
Title: Advanced Analytics Tools
Description: A suite of advanced analytics tools.
Author: John Doe
Maintainer: John Doe <john@example.com>
License: Apache License 2.0
URL: https://github.com/johndoe/analytics
BugReports: https://github.com/johndoe/analytics/issues
Depends: R (>= 4.0)
Imports: dplyr, tidyr
Suggests: testthat, knitr
"""
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        info = extract_package_info(self.temp_dir)

        self.assertEqual(info['name'], 'analytics')
        self.assertEqual(info['version'], '3.1.0')
        self.assertEqual(info['title'], 'Advanced Analytics Tools')
        self.assertEqual(info['license'], 'Apache License 2.0')
        self.assertIn('dplyr', info['imports'])


class TestCheckCranPackage(unittest.TestCase):
    """Test CRAN API interaction."""

    @patch('repoindex.cran.requests.get')
    def test_package_exists(self, mock_get):
        """Check existing CRAN package."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '<td>Version:</td>\n<td>1.4.0</td>'
        mock_get.return_value = mock_response

        result = check_cran_package('dplyr')

        self.assertIsNotNone(result)
        self.assertTrue(result['exists'])
        self.assertEqual(result['version'], '1.4.0')
        self.assertEqual(result['registry'], 'cran')

    @patch('repoindex.cran.requests.get')
    def test_package_not_found(self, mock_get):
        """Check non-existent CRAN package."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = check_cran_package('nonexistent-package')

        self.assertIsNotNone(result)
        self.assertFalse(result['exists'])

    @patch('repoindex.cran.requests.get')
    def test_network_error(self, mock_get):
        """Handle network error gracefully."""
        mock_get.side_effect = Exception("Network error")

        result = check_cran_package('dplyr')

        self.assertIsNone(result)


class TestCheckBioconductorPackage(unittest.TestCase):
    """Test Bioconductor API interaction."""

    @patch('repoindex.cran.requests.get')
    def test_package_exists(self, mock_get):
        """Check existing Bioconductor package."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = 'Version: 3.14.0'
        mock_get.return_value = mock_response

        result = check_bioconductor_package('GenomicRanges')

        self.assertIsNotNone(result)
        self.assertTrue(result['exists'])
        self.assertEqual(result['registry'], 'bioconductor')

    @patch('repoindex.cran.requests.get')
    def test_package_not_found(self, mock_get):
        """Check non-existent Bioconductor package."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = check_bioconductor_package('nonexistent')

        self.assertIsNotNone(result)
        self.assertFalse(result['exists'])


class TestDetectRPackage(unittest.TestCase):
    """Test R package detection."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_detect_valid_r_package(self):
        """Detect valid R package."""
        content = """Package: mypackage
Version: 1.0.0
Title: My Package
Description: A description.
"""
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)
        ns_path = Path(self.temp_dir) / "NAMESPACE"
        ns_path.write_text("export(my_func)")

        result = detect_r_package(self.temp_dir)

        self.assertTrue(result['has_packaging_files'])
        self.assertEqual(result['package_name'], 'mypackage')
        self.assertEqual(result['local_version'], '1.0.0')
        self.assertEqual(result['type'], 'r')

    def test_detect_no_r_package(self):
        """Return empty result for non-R repo."""
        result = detect_r_package(self.temp_dir)

        self.assertFalse(result['has_packaging_files'])
        self.assertIsNone(result['package_name'])
        self.assertFalse(result['is_published'])

    @patch('repoindex.cran.check_cran_package')
    def test_detect_published_package(self, mock_check_cran):
        """Detect published CRAN package."""
        content = """Package: published
Version: 1.0.0
"""
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        mock_check_cran.return_value = {
            'exists': True,
            'version': '1.0.0',
            'registry': 'cran'
        }

        result = detect_r_package(self.temp_dir)

        self.assertTrue(result['is_published'])
        self.assertEqual(result['registry'], 'cran')


class TestIsRPackageOutdated(unittest.TestCase):
    """Test R package version comparison."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_local_older(self):
        """Local version is older than registry."""
        content = "Package: test\nVersion: 1.0.0"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        result = is_r_package_outdated(self.temp_dir, 'test', '2.0.0')

        self.assertTrue(result)

    def test_local_same(self):
        """Local version same as registry."""
        content = "Package: test\nVersion: 1.0.0"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        result = is_r_package_outdated(self.temp_dir, 'test', '1.0.0')

        self.assertFalse(result)

    def test_local_newer(self):
        """Local version newer than registry."""
        content = "Package: test\nVersion: 2.0.0"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        result = is_r_package_outdated(self.temp_dir, 'test', '1.0.0')

        self.assertFalse(result)

    def test_dash_version_format(self):
        """Handle R's dash version format (1.2-3)."""
        content = "Package: test\nVersion: 1.0-1"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        result = is_r_package_outdated(self.temp_dir, 'test', '1.0-2')

        self.assertTrue(result)

    def test_no_local_version(self):
        """Return False when no local version found."""
        result = is_r_package_outdated(self.temp_dir, 'test', '1.0.0')

        self.assertFalse(result)


class TestIsRPackage(unittest.TestCase):
    """Test R package validation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_valid_r_package(self):
        """Valid R package with Package and Version."""
        content = "Package: testpkg\nVersion: 1.0.0"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        self.assertTrue(is_r_package(self.temp_dir))

    def test_missing_package_field(self):
        """Invalid - missing Package field."""
        content = "Version: 1.0.0\nTitle: Test"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        self.assertFalse(is_r_package(self.temp_dir))

    def test_missing_version_field(self):
        """Invalid - missing Version field."""
        content = "Package: test\nTitle: Test"
        desc_path = Path(self.temp_dir) / "DESCRIPTION"
        desc_path.write_text(content)

        self.assertFalse(is_r_package(self.temp_dir))

    def test_no_description_file(self):
        """Not an R package without DESCRIPTION file."""
        self.assertFalse(is_r_package(self.temp_dir))


if __name__ == '__main__':
    unittest.main()
