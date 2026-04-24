"""RubyGems registry metadata source for repoindex.

Detects Ruby gems from .gemspec files and checks rubygems.org.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from ..domain.repository import PackageMetadata
from . import MetadataSource

logger = logging.getLogger(__name__)


class RubyGemsSource(MetadataSource):
    """RubyGems.org registry source."""

    source_id = "rubygems"
    name = "RubyGems"
    target = "publications"
    batch = False

    def _detect_name(self, repo_path: str) -> Optional[str]:
        """Detect gem name from .gemspec file."""
        repo = Path(repo_path)

        # Look for *.gemspec files
        gemspecs = list(repo.glob('*.gemspec'))
        if not gemspecs:
            return None

        # Try to extract name from first gemspec
        try:
            content = gemspecs[0].read_text()
            # Match: spec.name = "gem-name" or s.name = 'gem-name'
            match = re.search(r'\.name\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)
        except Exception as e:
            logger.debug(f"RubyGems detect failed for {repo_path}: {e}")

        # Fallback: gemspec filename without extension
        return gemspecs[0].stem

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        return self._detect_name(repo_path) is not None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check RubyGems.org for gem."""
        try:
            url = f"https://rubygems.org/api/v1/gems/{package_name}.json"
            resp = requests.get(url, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                return PackageMetadata(
                    registry='rubygems',
                    name=package_name,
                    version=data.get('version'),
                    published=True,
                    url=f"https://rubygems.org/gems/{package_name}",
                    downloads=data.get('downloads'),
                )
            elif resp.status_code == 404:
                return PackageMetadata(
                    registry='rubygems',
                    name=package_name,
                    published=False,
                )
        except Exception as e:
            logger.debug(f"RubyGems check failed for {package_name}: {e}")
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


source = RubyGemsSource()
