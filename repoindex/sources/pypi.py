"""PyPI registry metadata source for repoindex."""

import logging
from typing import Optional

import requests

from ..domain.repository import PackageMetadata
from . import MetadataSource

logger = logging.getLogger(__name__)


def _fetch_downloads(package_name: str) -> Optional[int]:
    """Fetch 30-day download count from PyPI Stats API.

    Returns the last_month download count (NOT lifetime total).
    PyPI does not expose lifetime totals -- pypistats only has recent windows.
    """
    try:
        resp = requests.get(
            f'https://pypistats.org/api/packages/{package_name}/recent',
            timeout=10,
            headers={'User-Agent': 'repoindex (+https://github.com/queelius/repoindex)'},
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get('data', {}).get('last_month')
    except Exception:
        pass
    return None


class PyPISource(MetadataSource):
    """Python Package Index source."""

    source_id = "pypi"
    name = "Python Package Index"
    target = "publications"
    batch = False

    def _detect_name(self, repo_path: str) -> Optional[str]:
        """Detect Python package name from packaging files."""
        try:
            from ..infra.pypi_metadata import find_packaging_files, extract_package_name
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

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        return self._detect_name(repo_path) is not None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check PyPI for package."""
        try:
            from ..infra.pypi_metadata import check_pypi_package
            info = check_pypi_package(package_name)
            if not info:
                return None
            downloads_30d = _fetch_downloads(package_name) if info.get('exists') else None
            return PackageMetadata(
                registry='pypi',
                name=package_name,
                version=info.get('version'),
                published=info.get('exists', False),
                url=info.get('url'),
                downloads_30d=downloads_30d,
                last_updated=info.get('last_updated'),
            )
        except Exception as e:
            logger.debug(f"PyPI check failed for {package_name}: {e}")
            return None

    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        name = self._detect_name(repo_path)
        if not name:
            return None
        metadata = self.check(name, config)
        if metadata is None:
            return None
        return metadata.to_dict()


source = PyPISource()
