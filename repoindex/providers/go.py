"""
Go module proxy registry provider for repoindex.

Detects Go modules from go.mod and checks the Go module proxy.
Handles Go's module path encoding (uppercase → !lowercase).
"""

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


def _encode_module_path(path: str) -> str:
    """
    Encode a Go module path for the proxy API.

    Go proxy uses a case-encoding where uppercase letters
    are replaced with !lowercase (e.g., "GitHub" → "!git!hub").
    """
    result = []
    for ch in path:
        if ch.isupper():
            result.append('!')
            result.append(ch.lower())
        else:
            result.append(ch)
    return ''.join(result)


class GoProvider(RegistryProvider):
    """Go module proxy provider."""
    registry = "go"
    name = "Go Module Proxy"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
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


provider = GoProvider()
