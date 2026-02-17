"""
npm registry provider for repoindex.

Detects Node.js packages from package.json and checks the npm registry.
Skips packages marked as private.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import requests

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


class NpmProvider(RegistryProvider):
    """npm (Node.js) registry provider."""
    registry = "npm"
    name = "npm Registry"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
        """Detect npm package from package.json."""
        pkg_path = Path(repo_path) / 'package.json'
        if not pkg_path.exists():
            return None

        try:
            with open(pkg_path) as f:
                data = json.load(f)

            # Skip private packages
            if data.get('private', False):
                return None

            name = data.get('name')
            if name and isinstance(name, str):
                return name
        except Exception as e:
            logger.debug(f"npm detect failed for {repo_path}: {e}")
        return None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check npm registry for package."""
        try:
            url = f"https://registry.npmjs.org/{package_name}"
            resp = requests.get(url, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                latest = data.get('dist-tags', {}).get('latest')
                return PackageMetadata(
                    registry='npm',
                    name=package_name,
                    version=latest,
                    published=True,
                    url=f"https://www.npmjs.com/package/{package_name}",
                )
            elif resp.status_code == 404:
                return PackageMetadata(
                    registry='npm',
                    name=package_name,
                    published=False,
                )
        except Exception as e:
            logger.debug(f"npm check failed for {package_name}: {e}")
        return None


provider = NpmProvider()
