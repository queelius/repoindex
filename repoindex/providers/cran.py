"""
CRAN/Bioconductor registry provider for repoindex.

Thin wrapper around repoindex.cran — delegates detection and
API checks to the existing module.
"""

import logging
from typing import Optional

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


class CRANProvider(RegistryProvider):
    """Comprehensive R Archive Network provider."""
    registry = "cran"
    name = "CRAN / Bioconductor"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
        """Detect R package name from DESCRIPTION file."""
        try:
            from ..cran import extract_package_name
            return extract_package_name(repo_path)
        except Exception as e:
            logger.debug(f"CRAN detect failed for {repo_path}: {e}")
            return None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check CRAN and Bioconductor for package."""
        try:
            from ..cran import check_cran_package, check_bioconductor_package

            # Try CRAN first
            info = check_cran_package(package_name)
            if info and info.get('exists'):
                return PackageMetadata(
                    registry='cran',
                    name=package_name,
                    version=info.get('version'),
                    published=True,
                    url=info.get('url'),
                )

            # Fallback to Bioconductor
            info = check_bioconductor_package(package_name)
            if info and info.get('exists'):
                return PackageMetadata(
                    registry='bioconductor',
                    name=package_name,
                    version=info.get('version'),
                    published=True,
                    url=info.get('url'),
                )

            # Package detected locally but not published
            return PackageMetadata(
                registry='cran',
                name=package_name,
                published=False,
            )

        except Exception as e:
            logger.debug(f"CRAN check failed for {package_name}: {e}")
            return None


provider = CRANProvider()
