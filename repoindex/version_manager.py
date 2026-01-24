"""
Version management utilities for different package types.

Handles version bumping and setting for:
- Python (PEP 440): pyproject.toml, setup.py, __version__
- Node.js (semver): package.json
- Rust (semver): Cargo.toml
- Ruby (semver): gemspec, VERSION file
- C++ (varies): conanfile.py, CMakeLists.txt
- Go (semver): git tags
"""

import re
import toml
import json
from pathlib import Path
from typing import Optional, Tuple
from packaging.version import Version, InvalidVersion


class VersionBumper:
    """Bump semantic versions."""

    @staticmethod
    def bump_major(version_str: str) -> str:
        """Bump major version (X.0.0)."""
        try:
            v = Version(version_str)
            return f"{v.major + 1}.0.0"
        except InvalidVersion:
            # Fallback to string manipulation
            parts = version_str.split('.')
            parts[0] = str(int(parts[0]) + 1)
            parts[1:] = ['0'] * (len(parts) - 1)
            return '.'.join(parts)

    @staticmethod
    def bump_minor(version_str: str) -> str:
        """Bump minor version (x.Y.0)."""
        try:
            v = Version(version_str)
            return f"{v.major}.{v.minor + 1}.0"
        except InvalidVersion:
            parts = version_str.split('.')
            if len(parts) >= 2:
                parts[1] = str(int(parts[1]) + 1)
                parts[2:] = ['0'] * (len(parts) - 2)
            return '.'.join(parts)

    @staticmethod
    def bump_patch(version_str: str) -> str:
        """Bump patch version (x.y.Z)."""
        try:
            v = Version(version_str)
            return f"{v.major}.{v.minor}.{v.micro + 1}"
        except InvalidVersion:
            parts = version_str.split('.')
            if len(parts) >= 3:
                parts[2] = str(int(parts[2]) + 1)
            elif len(parts) == 2:
                parts.append('1')
            return '.'.join(parts)


class PythonVersionManager:
    """Manage Python package versions."""

    @staticmethod
    def get_version(repo_path: str) -> Optional[str]:
        """Get current version from Python project."""
        repo = Path(repo_path)

        # Try pyproject.toml first
        pyproject = repo / "pyproject.toml"
        if pyproject.exists():
            try:
                data = toml.load(pyproject)
                if 'project' in data and 'version' in data['project']:
                    return data['project']['version']
                if 'tool' in data and 'poetry' in data['tool'] and 'version' in data['tool']['poetry']:
                    return data['tool']['poetry']['version']
            except Exception:
                pass

        # Try setup.py
        setup_py = repo / "setup.py"
        if setup_py.exists():
            content = setup_py.read_text()
            match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)

        # Try __init__.py
        for init_file in repo.glob("*/__init__.py"):
            content = init_file.read_text()
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)

        return None

    @staticmethod
    def set_version(repo_path: str, new_version: str) -> bool:
        """Set version in Python project files."""
        repo = Path(repo_path)
        updated = False

        # Update pyproject.toml
        pyproject = repo / "pyproject.toml"
        if pyproject.exists():
            try:
                data = toml.load(pyproject)
                if 'project' in data and 'version' in data['project']:
                    data['project']['version'] = new_version
                    with open(pyproject, 'w') as f:
                        toml.dump(data, f)
                    updated = True
                elif 'tool' in data and 'poetry' in data['tool'] and 'version' in data['tool']['poetry']:
                    data['tool']['poetry']['version'] = new_version
                    with open(pyproject, 'w') as f:
                        toml.dump(data, f)
                    updated = True
            except Exception:
                pass

        # Update setup.py
        setup_py = repo / "setup.py"
        if setup_py.exists():
            content = setup_py.read_text()
            new_content = re.sub(
                r'(version\s*=\s*["\'])([^"\']+)(["\'])',
                rf'\g<1>{new_version}\g<3>',
                content
            )
            if new_content != content:
                setup_py.write_text(new_content)
                updated = True

        # Update __init__.py
        for init_file in repo.glob("*/__init__.py"):
            content = init_file.read_text()
            new_content = re.sub(
                r'(__version__\s*=\s*["\'])([^"\']+)(["\'])',
                rf'\g<1>{new_version}\g<3>',
                content
            )
            if new_content != content:
                init_file.write_text(new_content)
                updated = True

        return updated


class NodeVersionManager:
    """Manage Node.js package versions."""

    @staticmethod
    def get_version(repo_path: str) -> Optional[str]:
        """Get current version from package.json."""
        package_json = Path(repo_path) / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                return data.get('version')
            except (json.JSONDecodeError, OSError):
                pass
        return None

    @staticmethod
    def set_version(repo_path: str, new_version: str) -> bool:
        """Set version in package.json."""
        package_json = Path(repo_path) / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                data['version'] = new_version
                with open(package_json, 'w') as f:
                    json.dump(data, f, indent=2)
                    f.write('\n')  # Add trailing newline
                return True
            except (json.JSONDecodeError, OSError):
                pass
        return False


class RustVersionManager:
    """Manage Rust crate versions."""

    @staticmethod
    def get_version(repo_path: str) -> Optional[str]:
        """Get current version from Cargo.toml."""
        cargo_toml = Path(repo_path) / "Cargo.toml"
        if cargo_toml.exists():
            try:
                data = toml.load(cargo_toml)
                return data.get('package', {}).get('version')
            except Exception:
                pass
        return None

    @staticmethod
    def set_version(repo_path: str, new_version: str) -> bool:
        """Set version in Cargo.toml."""
        cargo_toml = Path(repo_path) / "Cargo.toml"
        if cargo_toml.exists():
            try:
                data = toml.load(cargo_toml)
                if 'package' in data:
                    data['package']['version'] = new_version
                    with open(cargo_toml, 'w') as f:
                        toml.dump(data, f)
                    return True
            except Exception:
                pass
        return False


class CppVersionManager:
    """Manage C++ project versions."""

    @staticmethod
    def get_version(repo_path: str) -> Optional[str]:
        """Get current version from conanfile.py or CMakeLists.txt."""
        repo = Path(repo_path)

        # Try conanfile.py
        conanfile = repo / "conanfile.py"
        if conanfile.exists():
            content = conanfile.read_text()
            match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)

        # Try CMakeLists.txt
        cmake = repo / "CMakeLists.txt"
        if cmake.exists():
            content = cmake.read_text()
            # Look for project(NAME VERSION x.y.z)
            match = re.search(r'project\s*\([^)]*VERSION\s+([0-9.]+)', content, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    @staticmethod
    def set_version(repo_path: str, new_version: str) -> bool:
        """Set version in C++ project files."""
        repo = Path(repo_path)
        updated = False

        # Update conanfile.py
        conanfile = repo / "conanfile.py"
        if conanfile.exists():
            content = conanfile.read_text()
            new_content = re.sub(
                r'(version\s*=\s*["\'])([^"\']+)(["\'])',
                rf'\g<1>{new_version}\g<3>',
                content
            )
            if new_content != content:
                conanfile.write_text(new_content)
                updated = True

        # Update CMakeLists.txt
        cmake = repo / "CMakeLists.txt"
        if cmake.exists():
            content = cmake.read_text()
            new_content = re.sub(
                r'(project\s*\([^)]*VERSION\s+)([0-9.]+)',
                rf'\g<1>{new_version}',
                content,
                flags=re.IGNORECASE
            )
            if new_content != content:
                cmake.write_text(new_content)
                updated = True

        return updated


class GoVersionManager:
    """Manage Go module versions via git tags."""

    @staticmethod
    def get_version(repo_path: str) -> Optional[str]:
        """Get current version from latest git tag."""
        from .utils import run_command
        output, returncode = run_command(
            "git describe --tags --abbrev=0",
            cwd=repo_path,
            capture_output=True,
            check=False
        )
        if returncode == 0 and output:
            # Strip 'v' prefix if present
            version = output.strip()
            return version[1:] if version.startswith('v') else version
        return None

    @staticmethod
    def set_version(repo_path: str, new_version: str) -> bool:
        """Set version by creating a git tag."""
        from .utils import run_command
        # Go versions are prefixed with 'v'
        tag = f"v{new_version}" if not new_version.startswith('v') else new_version
        output, returncode = run_command(
            f"git tag {tag}",
            cwd=repo_path,
            capture_output=True,
            check=False
        )
        return returncode == 0


# Version manager registry
VERSION_MANAGERS = {
    'python': PythonVersionManager,
    'node': NodeVersionManager,
    'rust': RustVersionManager,
    'cpp': CppVersionManager,
    'go': GoVersionManager,
}


def get_version(repo_path: str, project_type: str) -> Optional[str]:
    """Get current version for a project type."""
    manager = VERSION_MANAGERS.get(project_type)
    if manager:
        return manager.get_version(repo_path)
    return None


def set_version(repo_path: str, project_type: str, new_version: str) -> bool:
    """Set version for a project type."""
    manager = VERSION_MANAGERS.get(project_type)
    if manager:
        return manager.set_version(repo_path, new_version)
    return False


def bump_version(repo_path: str, project_type: str, bump_type: str = 'patch') -> Tuple[Optional[str], Optional[str]]:
    """Bump version for a project type.

    Args:
        repo_path: Path to repository
        project_type: Type of project (python, node, rust, cpp, go)
        bump_type: Type of bump (major, minor, patch)

    Returns:
        Tuple of (old_version, new_version) or (None, None) if failed
    """
    current_version = get_version(repo_path, project_type)
    if not current_version:
        return None, None

    # Bump version
    bumper = VersionBumper()
    if bump_type == 'major':
        new_version = bumper.bump_major(current_version)
    elif bump_type == 'minor':
        new_version = bumper.bump_minor(current_version)
    else:  # patch
        new_version = bumper.bump_patch(current_version)

    # Set new version
    if set_version(repo_path, project_type, new_version):
        return current_version, new_version

    return None, None
