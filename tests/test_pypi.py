"""
Unit tests for ghops.pypi module
"""
import unittest
import tempfile
import os
import shutil
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.pypi import (
    detect_pypi_package,
    check_pypi_package,
    is_package_outdated,
    extract_package_name,
    find_packaging_files
)


class TestDetectPypiPackage(unittest.TestCase):
    """Test PyPI package detection functionality"""
    
    def setUp(self):
        """Set up test directory"""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test directory"""
        shutil.rmtree(self.temp_dir)
    
    def test_detect_pyproject_toml(self):
        """Test package detection from pyproject.toml"""
        pyproject_content = """
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "test-package"
version = "1.0.0"
description = "A test package"
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        self.assertEqual(result['package_name'], 'test-package')
    
    def test_detect_setup_py(self):
        """Test package detection from setup.py"""
        setup_content = """
from setuptools import setup

setup(
    name="test-package",
    version="1.0.0",
    description="A test package"
)
"""
        setup_path = Path(self.temp_dir) / "setup.py"
        setup_path.write_text(setup_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        self.assertEqual(result['package_name'], 'test-package')
    
    def test_detect_setup_cfg(self):
        """Test package detection from setup.cfg"""
        setup_cfg_content = """
[metadata]
name = test-package
version = 1.0.0
description = A test package
"""
        setup_cfg_path = Path(self.temp_dir) / "setup.cfg"
        setup_cfg_path.write_text(setup_cfg_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        self.assertEqual(result['package_name'], 'test-package')
    
    def test_no_packaging_files(self):
        """Test when no packaging files are found"""
        result = detect_pypi_package(self.temp_dir)
        
        self.assertFalse(result['has_packaging_files'])
        self.assertIsNone(result['package_name'])
        self.assertFalse(result['is_published'])
        self.assertIsNone(result['pypi_info'])
    
    @patch('repoindex.pypi.check_pypi_package')
    def test_published_package(self, mock_check_pypi):
        """Test detection of published package"""
        # Setup package file
        pyproject_content = """
[project]
name = "published-package"
version = "1.0.0"
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        # Mock PyPI response
        mock_check_pypi.return_value = {
            'exists': True,
            'version': '1.0.0',
            'url': 'https://pypi.org/project/published-package/'
        }
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        self.assertEqual(result['package_name'], 'published-package')
        self.assertTrue(result['is_published'])
        self.assertIsNotNone(result['pypi_info'])
    
    def test_detect_pyproject_toml_setuptools_format(self):
        """Test package detection from pyproject.toml with setuptools format"""
        pyproject_content = """
[tool.setuptools]
name = "setuptools-package"
version = "1.0.0"
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        self.assertEqual(result['package_name'], 'setuptools-package')
    
    def test_detect_pyproject_toml_build_system_format(self):
        """Test package detection from pyproject.toml with build-system format"""
        pyproject_content = """
[build-system]
name = "build-system-package"
requires = ["setuptools"]
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        self.assertEqual(result['package_name'], 'build-system-package')
    
    def test_detect_pyproject_toml_invalid_format(self):
        """Test package detection from invalid pyproject.toml"""
        pyproject_content = """
[invalid toml format
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        # When file parsing fails, package_name should be None
        self.assertIsNone(result['package_name'])
    
    def test_detect_setup_py_invalid_syntax(self):
        """Test package detection from setup.py with invalid syntax"""
        setup_content = """
setup(
    name="syntax-error-package"
    version="1.0.0"  # Missing comma
    description="Test package"
)
"""
        setup_path = Path(self.temp_dir) / "setup.py"
        setup_path.write_text(setup_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        # The regex extraction should still work even with syntax errors
        self.assertEqual(result['package_name'], 'syntax-error-package')
    
    def test_detect_setup_py_no_name(self):
        """Test package detection from setup.py without name"""
        setup_content = """
from setuptools import setup

setup(
    version="1.0.0",
    description="Test package without name"
)
"""
        setup_path = Path(self.temp_dir) / "setup.py"
        setup_path.write_text(setup_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        # When no name is found in setup.py, package_name should be None
        self.assertIsNone(result['package_name'])
    
    def test_detect_setup_cfg_invalid_format(self):
        """Test package detection from invalid setup.cfg"""
        setup_cfg_content = """
[metadata
name = invalid-cfg-package
"""
        setup_cfg_path = Path(self.temp_dir) / "setup.cfg"
        setup_cfg_path.write_text(setup_cfg_content)
        
        result = detect_pypi_package(self.temp_dir)
        
        self.assertTrue(result['has_packaging_files'])
        # When file parsing fails, package_name should be None
        self.assertIsNone(result['package_name'])


class TestCheckPypiPackage(unittest.TestCase):
    """Test PyPI API interaction"""
    
    @patch('repoindex.pypi.requests.get')
    def test_check_package_success(self, mock_get):
        """Test successful PyPI API call"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'info': {
                'version': '2.1.0',
                'summary': 'A test package',
                'author': 'Test Author',
                'home_page': 'https://example.com',
                'download_url': ''
            },
            'urls': [{'upload_time': '2023-01-01T00:00:00'}]
        }
        mock_get.return_value = mock_response
        
        result = check_pypi_package('test-package')
        
        self.assertIsNotNone(result)
        self.assertTrue(result['exists'])
        self.assertEqual(result['version'], '2.1.0')
        self.assertIn('url', result)
    
    @patch('repoindex.pypi.requests.get')
    def test_check_package_not_found(self, mock_get):
        """Test PyPI API call for non-existent package"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        result = check_pypi_package('non-existent-package')
        
        self.assertIsNotNone(result)
        self.assertFalse(result['exists'])
    
    @patch('repoindex.pypi.requests.get')
    def test_check_package_network_error(self, mock_get):
        """Test PyPI API call with network error"""
        mock_get.side_effect = Exception("Network error")
        
        result = check_pypi_package('test-package')
        
        self.assertIsNone(result)


class TestFindPackagingFiles(unittest.TestCase):
    """Test packaging file detection"""
    
    def setUp(self):
        """Set up test directory"""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test directory"""
        shutil.rmtree(self.temp_dir)
    
    def test_find_pyproject_toml(self):
        """Test finding pyproject.toml"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text("[project]\nname = 'test'")
        
        files = find_packaging_files(self.temp_dir)
        
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith('pyproject.toml'))
    
    def test_find_setup_py(self):
        """Test finding setup.py"""
        setup_path = Path(self.temp_dir) / "setup.py"
        setup_path.write_text("from setuptools import setup\nsetup(name='test')")
        
        files = find_packaging_files(self.temp_dir)
        
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith('setup.py'))
    
    def test_find_multiple_files(self):
        """Test finding multiple packaging files"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text("[project]\nname = 'test'")
        
        setup_path = Path(self.temp_dir) / "setup.py"
        setup_path.write_text("from setuptools import setup\nsetup(name='test')")
        
        files = find_packaging_files(self.temp_dir)
        
        self.assertEqual(len(files), 2)
    
    def test_find_no_files(self):
        """Test when no packaging files exist"""
        files = find_packaging_files(self.temp_dir)
        
        self.assertEqual(len(files), 0)


class TestExtractPackageName(unittest.TestCase):
    """Test package name extraction"""
    
    def setUp(self):
        """Set up test directory"""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test directory"""
        shutil.rmtree(self.temp_dir)
    
    def test_extract_from_pyproject_toml(self):
        """Test extracting package name from pyproject.toml"""
        pyproject_content = """
[project]
name = "test-package"
version = "1.0.0"
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        name = extract_package_name(str(pyproject_path))
        
        self.assertEqual(name, 'test-package')
    
    def test_extract_from_setup_py(self):
        """Test extracting package name from setup.py"""
        setup_content = """
from setuptools import setup

setup(
    name="test-package",
    version="1.0.0"
)
"""
        setup_path = Path(self.temp_dir) / "setup.py"
        setup_path.write_text(setup_content)
        
        name = extract_package_name(str(setup_path))
        
        self.assertEqual(name, 'test-package')
    
    def test_extract_from_setup_cfg(self):
        """Test extracting package name from setup.cfg"""
        setup_cfg_content = """
[metadata]
name = test-package
version = 1.0.0
"""
        setup_cfg_path = Path(self.temp_dir) / "setup.cfg"
        setup_cfg_path.write_text(setup_cfg_content)
        
        name = extract_package_name(str(setup_cfg_path))
        
        self.assertEqual(name, 'test-package')


class TestIsPackageOutdated(unittest.TestCase):
    """Test package outdated detection"""
    
    def setUp(self):
        """Set up test directory"""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test directory"""
        shutil.rmtree(self.temp_dir)
    
    @patch('repoindex.pypi.check_pypi_package')
    @patch('repoindex.pypi.get_local_package_version')
    def test_package_is_outdated(self, mock_get_local, mock_check_pypi):
        """Test detection of outdated package"""
        # Mock local version
        mock_get_local.return_value = '1.0.0'
        
        # Mock PyPI response with newer version
        mock_check_pypi.return_value = {
            'exists': True,
            'version': '2.0.0',
            'url': 'https://pypi.org/project/test-package/'
        }
        
        result = is_package_outdated(self.temp_dir, 'test-package', '2.0.0')
        
        self.assertTrue(result)
    
    @patch('repoindex.pypi.check_pypi_package')
    @patch('repoindex.pypi.get_local_package_version')
    def test_package_is_current(self, mock_get_local, mock_check_pypi):
        """Test detection of current package"""
        # Mock local version
        mock_get_local.return_value = '2.0.0'
        
        # Mock PyPI response with same version
        mock_check_pypi.return_value = {
            'exists': True,
            'version': '2.0.0',
            'url': 'https://pypi.org/project/test-package/'
        }
        
        result = is_package_outdated(self.temp_dir, 'test-package', '2.0.0')
        
        self.assertFalse(result)
    
    @patch('repoindex.pypi.check_pypi_package')
    def test_package_not_on_pypi(self, mock_check_pypi):
        """Test when package is not available on PyPI"""
        mock_check_pypi.return_value = {'exists': False}
        
        result = is_package_outdated(self.temp_dir, 'non-existent-package', '1.0.0')
        
        self.assertFalse(result)


class TestGetLocalPackageVersion(unittest.TestCase):
    """Test local package version detection"""
    
    def setUp(self):
        """Set up test directory"""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test directory"""
        shutil.rmtree(self.temp_dir)
    
    def test_get_version_from_pyproject_toml_project(self):
        """Test version extraction from pyproject.toml [project] section"""
        pyproject_content = """
[project]
name = "test-package"
version = "1.2.3"
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        from repoindex.pypi import get_local_package_version
        version = get_local_package_version(self.temp_dir, "test-package")
        
        self.assertEqual(version, "1.2.3")
    
    def test_get_version_from_pyproject_toml_setuptools(self):
        """Test version extraction from pyproject.toml [tool.setuptools] section"""
        pyproject_content = """
[tool.setuptools]
name = "test-package"
version = "2.1.0"
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        from repoindex.pypi import get_local_package_version
        version = get_local_package_version(self.temp_dir, "test-package")
        
        self.assertEqual(version, "2.1.0")
    
    def test_get_version_from_setup_py(self):
        """Test version extraction from setup.py"""
        setup_content = """
from setuptools import setup

setup(
    name="test-package",
    version="3.0.1",
    description="Test package"
)
"""
        setup_path = Path(self.temp_dir) / "setup.py"
        setup_path.write_text(setup_content)
        
        from repoindex.pypi import get_local_package_version
        version = get_local_package_version(self.temp_dir, "test-package")
        
        self.assertEqual(version, "3.0.1")
    
    def test_get_version_no_packaging_files(self):
        """Test version extraction when no packaging files exist"""
        from repoindex.pypi import get_local_package_version
        version = get_local_package_version(self.temp_dir, "test-package")
        
        self.assertIsNone(version)
    
    def test_get_version_invalid_file_format(self):
        """Test version extraction from invalid file format"""
        pyproject_content = """
[invalid toml format
"""
        pyproject_path = Path(self.temp_dir) / "pyproject.toml"
        pyproject_path.write_text(pyproject_content)
        
        from repoindex.pypi import get_local_package_version
        version = get_local_package_version(self.temp_dir, "test-package")
        
        self.assertIsNone(version)


class TestPackageVersionComparison(unittest.TestCase):
    """Test package version comparison functionality"""
    
    def setUp(self):
        """Set up test directory"""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test directory"""
        shutil.rmtree(self.temp_dir)
    
    @patch('repoindex.pypi.get_local_package_version')
    def test_package_is_outdated_local_older(self, mock_get_local):
        """Test package is outdated when local version is older"""
        mock_get_local.return_value = "1.0.0"
        
        from repoindex.pypi import is_package_outdated
        result = is_package_outdated(self.temp_dir, "test-package", "2.0.0")
        
        self.assertTrue(result)
    
    @patch('repoindex.pypi.get_local_package_version')
    def test_package_is_current_same_version(self, mock_get_local):
        """Test package is current when versions match"""
        mock_get_local.return_value = "1.0.0"
        
        from repoindex.pypi import is_package_outdated
        result = is_package_outdated(self.temp_dir, "test-package", "1.0.0")
        
        self.assertFalse(result)
    
    @patch('repoindex.pypi.get_local_package_version')
    def test_package_is_current_local_newer(self, mock_get_local):
        """Test package is current when local version is newer"""
        mock_get_local.return_value = "2.0.0"
        
        from repoindex.pypi import is_package_outdated
        result = is_package_outdated(self.temp_dir, "test-package", "1.0.0")
        
        self.assertFalse(result)
    
    @patch('repoindex.pypi.get_local_package_version')
    def test_package_no_local_version(self, mock_get_local):
        """Test when local version cannot be determined"""
        mock_get_local.return_value = None
        
        from repoindex.pypi import is_package_outdated
        result = is_package_outdated(self.temp_dir, "test-package", "1.0.0")
        
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
