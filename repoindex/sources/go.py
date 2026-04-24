"""Go module proxy metadata source for repoindex.

Detects Go modules from go.mod and checks the Go module proxy.
Handles Go's module path encoding (uppercase -> !lowercase).
"""

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from ..domain.repository import PackageMetadata
from . import MetadataSource

logger = logging.getLogger(__name__)


def _encode_module_path(path: str) -> str:
    """Encode a Go module path for the proxy API.

    Go proxy uses a case-encoding where uppercase letters
    are replaced with !lowercase (e.g., "GitHub" -> "!git!hub").
    """
    result = []
    for ch in path:
        if ch.isupper():
            result.append('!')
            result.append(ch.lower())
        else:
            result.append(ch)
    return ''.join(result)


class GoSource(MetadataSource):
    """Go module proxy source."""

    source_id = "go"
    name = "Go Module Proxy"
    target = "publications"
    batch = False

    def _detect_name(self, repo_path: str) -> Optional[str]:
        """Detect Go module path from go.mod."""
        gomod_path = Path(repo_path) / 'go.mod'
        if not gomod_path.exists():
            return None

        try:
            content = gomod_path.read_text()
            # First line is typically "module github.com/owner/repo"
            match = re.match(r'module\s+(\S+)', content)
            if match:
                return match.group(1)
        except Exception as e:
            logger.debug(f"Go detect failed for {repo_path}: {e}")
        return None

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        return self._detect_name(repo_path) is not None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check Go module proxy for module."""
        try:
            encoded = _encode_module_path(package_name)
            url = f"https://proxy.golang.org/{encoded}/@latest"
            resp = requests.get(url, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                return PackageMetadata(
                    registry='go',
                    name=package_name,
                    version=data.get('Version'),
                    published=True,
                    url=f"https://pkg.go.dev/{package_name}",
                )
            elif resp.status_code in (404, 410):
                return PackageMetadata(
                    registry='go',
                    name=package_name,
                    published=False,
                )
        except Exception as e:
            logger.debug(f"Go check failed for {package_name}: {e}")
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


source = GoSource()
