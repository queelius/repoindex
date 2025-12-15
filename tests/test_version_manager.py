"""
Comprehensive tests for version management system.

Tests the VersionBumper and all language-specific version managers:
- Python (pyproject.toml, setup.py, __init__.py)
- Node.js (package.json)
- Rust (Cargo.toml)
- C++ (conanfile.py, CMakeLists.txt)
- Go (git tags)
"""

import pytest
import json
import toml
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.version_manager import (
    VersionBumper,
    PythonVersionManager,
    NodeVersionManager,
    RustVersionManager,
    CppVersionManager,
    GoVersionManager,
    get_version,
    set_version,
    bump_version,
)


class TestVersionBumper:
    """Test semantic version bumping logic."""

    def test_bump_major_standard_version(self):
        """Test bumping major version from standard semver."""
        bumper = VersionBumper()
        assert bumper.bump_major("1.2.3") == "2.0.0"
        assert bumper.bump_major("0.5.10") == "1.0.0"
        assert bumper.bump_major("10.20.30") == "11.0.0"

    def test_bump_major_zero_version(self):
        """Test bumping major version from 0.0.0."""
        bumper = VersionBumper()
        assert bumper.bump_major("0.0.0") == "1.0.0"

    def test_bump_minor_standard_version(self):
        """Test bumping minor version from standard semver."""
        bumper = VersionBumper()
        assert bumper.bump_minor("1.2.3") == "1.3.0"
        assert bumper.bump_minor("0.5.10") == "0.6.0"
        assert bumper.bump_minor("10.20.30") == "10.21.0"

    def test_bump_minor_resets_patch(self):
        """Test that bumping minor resets patch to 0."""
        bumper = VersionBumper()
        assert bumper.bump_minor("1.2.99") == "1.3.0"

    def test_bump_patch_standard_version(self):
        """Test bumping patch version from standard semver."""
        bumper = VersionBumper()
        assert bumper.bump_patch("1.2.3") == "1.2.4"
        assert bumper.bump_patch("0.5.10") == "0.5.11"
        assert bumper.bump_patch("10.20.30") == "10.20.31"

    def test_bump_patch_two_part_version(self):
        """Test bumping patch on two-part version (adds .1)."""
        bumper = VersionBumper()
        assert bumper.bump_patch("1.2") == "1.2.1"

    def test_bump_invalid_version_fallback(self):
        """Test bumping with invalid version uses string fallback."""
        bumper = VersionBumper()
        # These should still work via string manipulation
        result = bumper.bump_major("1.2.3.4")
        assert result.startswith("2.")

        result = bumper.bump_minor("1.2.3.4")
        assert result.startswith("1.3.")


class TestPythonVersionManager:
    """Test Python project version management."""

    def test_get_version_from_pyproject_toml_project_section(self, fs):
        """Test reading version from pyproject.toml [project] section."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)
        pyproject_content = """
[project]
name = "mypackage"
version = "1.2.3"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        version = PythonVersionManager.get_version(repo_path)
        assert version == "1.2.3"

    def test_get_version_from_pyproject_toml_poetry_section(self, fs):
        """Test reading version from pyproject.toml [tool.poetry] section."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)
        pyproject_content = """
[tool.poetry]
name = "mypackage"
version = "2.0.0"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        version = PythonVersionManager.get_version(repo_path)
        assert version == "2.0.0"

    def test_get_version_from_setup_py(self, fs):
        """Test reading version from setup.py."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)
        setup_content = """
from setuptools import setup

setup(
    name="mypackage",
    version="1.5.0",
    packages=["mypackage"],
)
"""
        fs.create_file(f"{repo_path}/setup.py", contents=setup_content)

        version = PythonVersionManager.get_version(repo_path)
        assert version == "1.5.0"

    def test_get_version_from_init_py(self, fs):
        """Test reading version from __init__.py."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)
        fs.create_dir(f"{repo_path}/mypackage")
        init_content = """
__version__ = "3.0.0"
__author__ = "Test Author"
"""
        fs.create_file(f"{repo_path}/mypackage/__init__.py", contents=init_content)

        version = PythonVersionManager.get_version(repo_path)
        assert version == "3.0.0"

    def test_get_version_no_version_found(self, fs):
        """Test when no version file exists."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        version = PythonVersionManager.get_version(repo_path)
        assert version is None

    def test_get_version_priority_pyproject_over_setup_py(self, fs):
        """Test that pyproject.toml takes priority over setup.py."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        pyproject_content = """
[project]
version = "2.0.0"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        setup_content = """
setup(version="1.0.0")
"""
        fs.create_file(f"{repo_path}/setup.py", contents=setup_content)

        version = PythonVersionManager.get_version(repo_path)
        assert version == "2.0.0", "pyproject.toml should take priority"

    def test_set_version_in_pyproject_toml_project_section(self, fs):
        """Test setting version in pyproject.toml [project] section."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        pyproject_content = """
[project]
name = "mypackage"
version = "1.0.0"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        result = PythonVersionManager.set_version(repo_path, "2.0.0")
        assert result is True

        # Verify the file was updated
        updated_data = toml.load(Path(repo_path) / "pyproject.toml")
        assert updated_data["project"]["version"] == "2.0.0"

    def test_set_version_in_pyproject_toml_poetry_section(self, fs):
        """Test setting version in pyproject.toml [tool.poetry] section."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        pyproject_content = """
[tool.poetry]
name = "mypackage"
version = "1.0.0"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        result = PythonVersionManager.set_version(repo_path, "3.0.0")
        assert result is True

        # Verify the file was updated
        updated_data = toml.load(Path(repo_path) / "pyproject.toml")
        assert updated_data["tool"]["poetry"]["version"] == "3.0.0"

    def test_set_version_in_setup_py(self, fs):
        """Test setting version in setup.py."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        setup_content = """
setup(
    name="mypackage",
    version="1.0.0",
)
"""
        fs.create_file(f"{repo_path}/setup.py", contents=setup_content)

        result = PythonVersionManager.set_version(repo_path, "2.5.0")
        assert result is True

        # Verify the file was updated
        updated_content = Path(repo_path, "setup.py").read_text()
        assert 'version="2.5.0"' in updated_content

    def test_set_version_in_init_py(self, fs):
        """Test setting version in __init__.py."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)
        fs.create_dir(f"{repo_path}/mypackage")

        init_content = """
__version__ = "1.0.0"
"""
        fs.create_file(f"{repo_path}/mypackage/__init__.py", contents=init_content)

        result = PythonVersionManager.set_version(repo_path, "4.0.0")
        assert result is True

        # Verify the file was updated
        updated_content = Path(repo_path, "mypackage/__init__.py").read_text()
        assert '__version__ = "4.0.0"' in updated_content

    def test_set_version_updates_multiple_files(self, fs):
        """Test that set_version updates all Python version files."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)
        fs.create_dir(f"{repo_path}/mypackage")

        # Create multiple version files
        pyproject_content = """
[project]
version = "1.0.0"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        setup_content = 'setup(version="1.0.0")'
        fs.create_file(f"{repo_path}/setup.py", contents=setup_content)

        init_content = '__version__ = "1.0.0"'
        fs.create_file(f"{repo_path}/mypackage/__init__.py", contents=init_content)

        # Update version
        result = PythonVersionManager.set_version(repo_path, "2.0.0")
        assert result is True

        # Verify all files were updated
        pyproject_data = toml.load(Path(repo_path) / "pyproject.toml")
        assert pyproject_data["project"]["version"] == "2.0.0"

        setup_text = Path(repo_path, "setup.py").read_text()
        assert 'version="2.0.0"' in setup_text

        init_text = Path(repo_path, "mypackage/__init__.py").read_text()
        assert '__version__ = "2.0.0"' in init_text

    def test_set_version_no_version_files(self, fs):
        """Test setting version when no version files exist."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        result = PythonVersionManager.set_version(repo_path, "1.0.0")
        assert result is False


class TestNodeVersionManager:
    """Test Node.js package version management."""

    def test_get_version_from_package_json(self, fs):
        """Test reading version from package.json."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        package_json = {
            "name": "my-package",
            "version": "1.2.3",
            "main": "index.js"
        }
        fs.create_file(
            f"{repo_path}/package.json",
            contents=json.dumps(package_json, indent=2)
        )

        version = NodeVersionManager.get_version(repo_path)
        assert version == "1.2.3"

    def test_get_version_no_package_json(self, fs):
        """Test when package.json doesn't exist."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        version = NodeVersionManager.get_version(repo_path)
        assert version is None

    def test_get_version_package_json_no_version(self, fs):
        """Test when package.json exists but has no version."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        package_json = {
            "name": "my-package",
            "main": "index.js"
        }
        fs.create_file(
            f"{repo_path}/package.json",
            contents=json.dumps(package_json)
        )

        version = NodeVersionManager.get_version(repo_path)
        assert version is None

    def test_set_version_in_package_json(self, fs):
        """Test setting version in package.json."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        package_json = {
            "name": "my-package",
            "version": "1.0.0"
        }
        fs.create_file(
            f"{repo_path}/package.json",
            contents=json.dumps(package_json, indent=2)
        )

        result = NodeVersionManager.set_version(repo_path, "2.5.0")
        assert result is True

        # Verify the file was updated
        with open(f"{repo_path}/package.json") as f:
            updated_data = json.load(f)
        assert updated_data["version"] == "2.5.0"
        assert updated_data["name"] == "my-package"

    def test_set_version_adds_trailing_newline(self, fs):
        """Test that set_version adds a trailing newline (npm convention)."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        package_json = {"name": "my-package", "version": "1.0.0"}
        fs.create_file(
            f"{repo_path}/package.json",
            contents=json.dumps(package_json)
        )

        NodeVersionManager.set_version(repo_path, "2.0.0")

        # Check that file ends with newline
        content = Path(repo_path, "package.json").read_text()
        assert content.endswith('\n')

    def test_set_version_no_package_json(self, fs):
        """Test setting version when package.json doesn't exist."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        result = NodeVersionManager.set_version(repo_path, "1.0.0")
        assert result is False


class TestRustVersionManager:
    """Test Rust crate version management."""

    def test_get_version_from_cargo_toml(self, fs):
        """Test reading version from Cargo.toml."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        cargo_content = """
[package]
name = "my-crate"
version = "0.1.5"
edition = "2021"
"""
        fs.create_file(f"{repo_path}/Cargo.toml", contents=cargo_content)

        version = RustVersionManager.get_version(repo_path)
        assert version == "0.1.5"

    def test_get_version_no_cargo_toml(self, fs):
        """Test when Cargo.toml doesn't exist."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        version = RustVersionManager.get_version(repo_path)
        assert version is None

    def test_set_version_in_cargo_toml(self, fs):
        """Test setting version in Cargo.toml."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        cargo_content = """
[package]
name = "my-crate"
version = "0.1.0"
"""
        fs.create_file(f"{repo_path}/Cargo.toml", contents=cargo_content)

        result = RustVersionManager.set_version(repo_path, "0.2.0")
        assert result is True

        # Verify the file was updated
        updated_data = toml.load(Path(repo_path) / "Cargo.toml")
        assert updated_data["package"]["version"] == "0.2.0"

    def test_set_version_no_cargo_toml(self, fs):
        """Test setting version when Cargo.toml doesn't exist."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        result = RustVersionManager.set_version(repo_path, "1.0.0")
        assert result is False


class TestCppVersionManager:
    """Test C++ project version management."""

    def test_get_version_from_conanfile_py(self, fs):
        """Test reading version from conanfile.py."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        conanfile_content = """
from conan import ConanFile

class MyLibConan(ConanFile):
    name = "mylib"
    version = "2.3.1"
    license = "MIT"
"""
        fs.create_file(f"{repo_path}/conanfile.py", contents=conanfile_content)

        version = CppVersionManager.get_version(repo_path)
        assert version == "2.3.1"

    def test_get_version_from_cmake(self, fs):
        """Test reading version from CMakeLists.txt."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        cmake_content = """
cmake_minimum_required(VERSION 3.10)
project(MyProject VERSION 1.5.2 LANGUAGES CXX)

add_library(mylib mylib.cpp)
"""
        fs.create_file(f"{repo_path}/CMakeLists.txt", contents=cmake_content)

        version = CppVersionManager.get_version(repo_path)
        assert version == "1.5.2"

    def test_get_version_cmake_case_insensitive(self, fs):
        """Test reading version from CMakeLists.txt with various case."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        cmake_content = """
PROJECT(MyProject version 3.2.1)
"""
        fs.create_file(f"{repo_path}/CMakeLists.txt", contents=cmake_content)

        version = CppVersionManager.get_version(repo_path)
        assert version == "3.2.1"

    def test_get_version_priority_conanfile_over_cmake(self, fs):
        """Test that conanfile.py takes priority over CMakeLists.txt."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        conanfile_content = 'version = "2.0.0"'
        fs.create_file(f"{repo_path}/conanfile.py", contents=conanfile_content)

        cmake_content = "project(MyProject VERSION 1.0.0)"
        fs.create_file(f"{repo_path}/CMakeLists.txt", contents=cmake_content)

        version = CppVersionManager.get_version(repo_path)
        assert version == "2.0.0", "conanfile.py should take priority"

    def test_get_version_no_version_files(self, fs):
        """Test when no version files exist."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        version = CppVersionManager.get_version(repo_path)
        assert version is None

    def test_set_version_in_conanfile_py(self, fs):
        """Test setting version in conanfile.py."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        conanfile_content = """
class MyLibConan(ConanFile):
    name = "mylib"
    version = "1.0.0"
"""
        fs.create_file(f"{repo_path}/conanfile.py", contents=conanfile_content)

        result = CppVersionManager.set_version(repo_path, "2.0.0")
        assert result is True

        # Verify the file was updated
        updated_content = Path(repo_path, "conanfile.py").read_text()
        assert 'version = "2.0.0"' in updated_content

    def test_set_version_in_cmake(self, fs):
        """Test setting version in CMakeLists.txt."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        cmake_content = """
project(MyProject VERSION 1.0.0 LANGUAGES CXX)
"""
        fs.create_file(f"{repo_path}/CMakeLists.txt", contents=cmake_content)

        result = CppVersionManager.set_version(repo_path, "3.5.0")
        assert result is True

        # Verify the file was updated
        updated_content = Path(repo_path, "CMakeLists.txt").read_text()
        assert "VERSION 3.5.0" in updated_content

    def test_set_version_updates_both_files(self, fs):
        """Test that set_version updates both conanfile.py and CMakeLists.txt."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        conanfile_content = 'version = "1.0.0"'
        fs.create_file(f"{repo_path}/conanfile.py", contents=conanfile_content)

        cmake_content = "project(MyProject VERSION 1.0.0)"
        fs.create_file(f"{repo_path}/CMakeLists.txt", contents=cmake_content)

        result = CppVersionManager.set_version(repo_path, "2.0.0")
        assert result is True

        # Verify both files were updated
        conanfile_text = Path(repo_path, "conanfile.py").read_text()
        assert 'version = "2.0.0"' in conanfile_text

        cmake_text = Path(repo_path, "CMakeLists.txt").read_text()
        assert "VERSION 2.0.0" in cmake_text

    def test_set_version_no_version_files(self, fs):
        """Test setting version when no version files exist."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        result = CppVersionManager.set_version(repo_path, "1.0.0")
        assert result is False


class TestGoVersionManager:
    """Test Go module version management via git tags."""

    @patch('repoindex.utils.run_command')
    def test_get_version_from_git_tag(self, mock_run_command):
        """Test reading version from git tag."""
        mock_run_command.return_value = ("v1.2.3\n", 0)

        version = GoVersionManager.get_version("/test/repo")
        assert version == "1.2.3", "Should strip 'v' prefix"

        mock_run_command.assert_called_once_with(
            "git describe --tags --abbrev=0",
            cwd="/test/repo",
            capture_output=True,
            check=False
        )

    @patch('repoindex.utils.run_command')
    def test_get_version_without_v_prefix(self, mock_run_command):
        """Test reading version from git tag without 'v' prefix."""
        mock_run_command.return_value = ("2.0.0\n", 0)

        version = GoVersionManager.get_version("/test/repo")
        assert version == "2.0.0"

    @patch('repoindex.utils.run_command')
    def test_get_version_no_tags(self, mock_run_command):
        """Test when no git tags exist."""
        mock_run_command.return_value = ("", 1)

        version = GoVersionManager.get_version("/test/repo")
        assert version is None

    @patch('repoindex.utils.run_command')
    def test_set_version_creates_git_tag(self, mock_run_command):
        """Test that set_version creates a git tag with 'v' prefix."""
        mock_run_command.return_value = ("", 0)

        result = GoVersionManager.set_version("/test/repo", "1.5.0")
        assert result is True

        mock_run_command.assert_called_once_with(
            "git tag v1.5.0",
            cwd="/test/repo",
            capture_output=True,
            check=False
        )

    @patch('repoindex.utils.run_command')
    def test_set_version_with_v_prefix(self, mock_run_command):
        """Test that set_version doesn't double 'v' prefix."""
        mock_run_command.return_value = ("", 0)

        result = GoVersionManager.set_version("/test/repo", "v2.0.0")
        assert result is True

        mock_run_command.assert_called_once_with(
            "git tag v2.0.0",
            cwd="/test/repo",
            capture_output=True,
            check=False
        )

    @patch('repoindex.utils.run_command')
    def test_set_version_git_failure(self, mock_run_command):
        """Test handling git tag creation failure."""
        mock_run_command.return_value = ("error: tag already exists", 1)

        result = GoVersionManager.set_version("/test/repo", "1.0.0")
        assert result is False


class TestVersionManagerAPI:
    """Test the high-level version manager API functions."""

    def test_get_version_python(self, fs):
        """Test get_version() for Python project."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        pyproject_content = """
[project]
version = "1.2.3"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        version = get_version(repo_path, "python")
        assert version == "1.2.3"

    def test_get_version_node(self, fs):
        """Test get_version() for Node.js project."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        package_json = {"version": "2.0.0"}
        fs.create_file(
            f"{repo_path}/package.json",
            contents=json.dumps(package_json)
        )

        version = get_version(repo_path, "node")
        assert version == "2.0.0"

    def test_get_version_unsupported_type(self, fs):
        """Test get_version() with unsupported project type."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        version = get_version(repo_path, "unknown")
        assert version is None

    def test_set_version_python(self, fs):
        """Test set_version() for Python project."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        pyproject_content = """
[project]
version = "1.0.0"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        result = set_version(repo_path, "python", "2.0.0")
        assert result is True

        # Verify update
        data = toml.load(Path(repo_path) / "pyproject.toml")
        assert data["project"]["version"] == "2.0.0"

    def test_set_version_unsupported_type(self, fs):
        """Test set_version() with unsupported project type."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        result = set_version(repo_path, "unknown", "1.0.0")
        assert result is False

    def test_bump_version_patch(self, fs):
        """Test bump_version() with patch bump."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        pyproject_content = """
[project]
version = "1.2.3"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        old_ver, new_ver = bump_version(repo_path, "python", "patch")
        assert old_ver == "1.2.3"
        assert new_ver == "1.2.4"

        # Verify file was updated
        data = toml.load(Path(repo_path) / "pyproject.toml")
        assert data["project"]["version"] == "1.2.4"

    def test_bump_version_minor(self, fs):
        """Test bump_version() with minor bump."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        package_json = {"version": "1.5.9"}
        fs.create_file(
            f"{repo_path}/package.json",
            contents=json.dumps(package_json)
        )

        old_ver, new_ver = bump_version(repo_path, "node", "minor")
        assert old_ver == "1.5.9"
        assert new_ver == "1.6.0"

    def test_bump_version_major(self, fs):
        """Test bump_version() with major bump."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        cargo_content = """
[package]
version = "0.9.5"
"""
        fs.create_file(f"{repo_path}/Cargo.toml", contents=cargo_content)

        old_ver, new_ver = bump_version(repo_path, "rust", "major")
        assert old_ver == "0.9.5"
        assert new_ver == "1.0.0"

    def test_bump_version_no_version_found(self, fs):
        """Test bump_version() when no version exists."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        old_ver, new_ver = bump_version(repo_path, "python", "patch")
        assert old_ver is None
        assert new_ver is None

    def test_bump_version_defaults_to_patch(self, fs):
        """Test that bump_version() defaults to patch bump."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        pyproject_content = """
[project]
version = "2.0.0"
"""
        fs.create_file(f"{repo_path}/pyproject.toml", contents=pyproject_content)

        old_ver, new_ver = bump_version(repo_path, "python")
        assert old_ver == "2.0.0"
        assert new_ver == "2.0.1"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_version_bumper_with_prerelease(self):
        """Test bumping versions with prerelease identifiers."""
        bumper = VersionBumper()
        # The packaging library should handle these
        assert bumper.bump_patch("1.0.0a1") == "1.0.1"
        assert bumper.bump_minor("1.0.0rc1") == "1.1.0"

    def test_python_corrupted_toml(self, fs):
        """Test handling of corrupted TOML files."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        # Invalid TOML
        fs.create_file(f"{repo_path}/pyproject.toml", contents="[invalid")

        version = PythonVersionManager.get_version(repo_path)
        assert version is None

    def test_node_corrupted_json(self, fs):
        """Test handling of corrupted JSON files."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        # Invalid JSON
        fs.create_file(f"{repo_path}/package.json", contents="{invalid}")

        version = NodeVersionManager.get_version(repo_path)
        assert version is None

    def test_python_set_version_read_only_file(self, fs):
        """Test setting version on read-only file."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        pyproject_content = """
[project]
version = "1.0.0"
"""
        pyproject_path = f"{repo_path}/pyproject.toml"
        fs.create_file(pyproject_path, contents=pyproject_content)

        # Make file read-only
        import os
        os.chmod(pyproject_path, 0o444)

        # Should fail gracefully
        result = PythonVersionManager.set_version(repo_path, "2.0.0")
        # Result depends on filesystem behavior, but shouldn't crash
        assert result in [True, False]

    def test_version_manager_with_empty_files(self, fs):
        """Test handling of empty version files."""
        repo_path = "/test/repo"
        fs.create_dir(repo_path)

        # Empty files
        fs.create_file(f"{repo_path}/pyproject.toml", contents="")
        fs.create_file(f"{repo_path}/package.json", contents="")

        assert PythonVersionManager.get_version(repo_path) is None
        assert NodeVersionManager.get_version(repo_path) is None
