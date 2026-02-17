"""
RubyGems registry provider for repoindex.

Detects Ruby gems from .gemspec files and checks rubygems.org.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


class RubyGemsProvider(RegistryProvider):
    """RubyGems.org registry provider."""
    registry = "rubygems"
    name = "RubyGems"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
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


provider = RubyGemsProvider()
