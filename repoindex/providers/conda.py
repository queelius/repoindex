"""
Conda (Anaconda/conda-forge) registry provider for repoindex.

Detects conda recipes from meta.yaml and checks the Anaconda API.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


class CondaProvider(RegistryProvider):
    """Conda-forge / Anaconda registry provider."""
    registry = "conda"
    name = "conda-forge"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
        """Detect conda package from recipe/meta.yaml or meta.yaml."""
        candidates = [
            Path(repo_path) / 'recipe' / 'meta.yaml',
            Path(repo_path) / 'meta.yaml',
            Path(repo_path) / 'conda.recipe' / 'meta.yaml',
        ]

        for path in candidates:
            if path.exists():
                try:
                    content = path.read_text()
                    # Look for {% set name = "..." %} or name: ...
                    match = re.search(r'\{%\s*set\s+name\s*=\s*["\']([^"\']+)["\']', content)
                    if match:
                        return match.group(1)
                    # Fallback: YAML name field under package:
                    match = re.search(r'^\s*name:\s*(.+?)$', content, re.MULTILINE)
                    if match:
                        name = match.group(1).strip().strip('"').strip("'")
                        # Skip Jinja template references
                        if not name.startswith('{'):
                            return name
                except Exception as e:
                    logger.debug(f"Conda detect failed for {path}: {e}")
        return None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check Anaconda (conda-forge channel) for package."""
        try:
            url = f"https://api.anaconda.org/package/conda-forge/{package_name}"
            resp = requests.get(url, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                return PackageMetadata(
                    registry='conda',
                    name=package_name,
                    version=data.get('latest_version'),
                    published=True,
                    url=f"https://anaconda.org/conda-forge/{package_name}",
                )
            elif resp.status_code == 404:
                return PackageMetadata(
                    registry='conda',
                    name=package_name,
                    published=False,
                )
        except Exception as e:
            logger.debug(f"Conda check failed for {package_name}: {e}")
        return None


provider = CondaProvider()
