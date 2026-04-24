"""Conda (Anaconda/conda-forge) registry metadata source for repoindex.

Detects conda recipes from meta.yaml and checks the Anaconda API.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from ..domain.repository import PackageMetadata
from . import MetadataSource

logger = logging.getLogger(__name__)


class CondaSource(MetadataSource):
    """Conda-forge / Anaconda registry source."""

    source_id = "conda"
    name = "conda-forge"
    target = "publications"
    batch = False

    def _detect_name(self, repo_path: str) -> Optional[str]:
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

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        return self._detect_name(repo_path) is not None

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

    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        name = self._detect_name(repo_path)
        if not name:
            return None
        metadata = self.check(name, config)
        if metadata is None:
            return None
        return metadata.to_dict()


source = CondaSource()
