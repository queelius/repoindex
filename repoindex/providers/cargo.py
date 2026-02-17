"""
Cargo (crates.io) registry provider for repoindex.

Detects Rust packages from Cargo.toml and checks crates.io.
Note: crates.io API requires a User-Agent header.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import requests

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


class CargoProvider(RegistryProvider):
    """Cargo (crates.io) registry provider."""
    registry = "cargo"
    name = "crates.io"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
        """Detect Rust crate name from Cargo.toml."""
        cargo_path = Path(repo_path) / 'Cargo.toml'
        if not cargo_path.exists():
            return None

        try:
            content = cargo_path.read_text()
            # Parse [package] section for name
            in_package = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped == '[package]':
                    in_package = True
                    continue
                if in_package and stripped.startswith('['):
                    break
                if in_package:
                    match = re.match(r'name\s*=\s*"([^"]+)"', stripped)
                    if match:
                        return match.group(1)
        except Exception as e:
            logger.debug(f"Cargo detect failed for {repo_path}: {e}")
        return None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check crates.io for package."""
        try:
            url = f"https://crates.io/api/v1/crates/{package_name}"
            headers = {'User-Agent': 'repoindex (https://github.com/queelius/repoindex)'}
            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                crate = data.get('crate', {})
                return PackageMetadata(
                    registry='cargo',
                    name=package_name,
                    version=crate.get('max_version'),
                    published=True,
                    url=f"https://crates.io/crates/{package_name}",
                    downloads=crate.get('downloads'),
                )
            elif resp.status_code == 404:
                return PackageMetadata(
                    registry='cargo',
                    name=package_name,
                    published=False,
                )
        except Exception as e:
            logger.debug(f"Cargo check failed for {package_name}: {e}")
        return None


provider = CargoProvider()
