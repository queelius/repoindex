"""
PyPI registry provider for repoindex.

Thin wrapper around repoindex.pypi — delegates detection and
API checks to the existing module.
"""

import logging
from typing import Optional

import requests

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


def _fetch_downloads(package_name: str) -> Optional[int]:
    """Fetch recent download stats from PyPI Stats API."""
    try:
        resp = requests.get(
            f'https://pypistats.org/api/packages/{package_name}/recent',
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get('data', {}).get('last_month')
    except Exception:
        pass
    return None


class PyPIProvider(RegistryProvider):
    """Python Package Index provider."""
    registry = "pypi"
    name = "Python Package Index"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
        """Detect Python package name from packaging files."""
        try:
            from ..pypi import find_packaging_files, extract_package_name
            packaging_files = find_packaging_files(repo_path)
            if not packaging_files:
                return None
            for file_path in packaging_files:
                name = extract_package_name(file_path)
                if name:
                    return name
        except Exception as e:
            logger.debug(f"PyPI detect failed for {repo_path}: {e}")
        return None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check PyPI for package."""
        try:
            from ..pypi import check_pypi_package
            info = check_pypi_package(package_name)
            if not info:
                return None
            downloads = _fetch_downloads(package_name) if info.get('exists') else None
            return PackageMetadata(
                registry='pypi',
                name=package_name,
                version=info.get('version'),
                published=info.get('exists', False),
                url=info.get('url'),
                downloads=downloads,
                last_updated=info.get('last_updated'),
            )
        except Exception as e:
            logger.debug(f"PyPI check failed for {package_name}: {e}")
            return None


provider = PyPIProvider()
