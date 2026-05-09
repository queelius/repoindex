"""CRAN/Bioconductor registry metadata source for repoindex.

Detects R packages via DESCRIPTION files and checks publication
status using the crandb JSON API (CRAN) and Bioconductor JSON API.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import requests

from ...domain.repository import PackageMetadata
from .. import Registry

logger = logging.getLogger(__name__)


def _parse_description(desc_path: str) -> Dict[str, Optional[str]]:
    """Extract the Package name from an R DESCRIPTION file (DCF format).

    Returns a dict with the 'package' key, or {'package': None} on failure.
    The parser handles the DCF format's ``Key: Value`` line structure.
    """
    try:
        text = Path(desc_path).read_text(encoding='utf-8')
    except Exception:
        return {'package': None}

    for line in text.splitlines():
        if line.startswith('Package:'):
            value = line.split(':', 1)[1].strip()
            return {'package': value or None}
    return {'package': None}


class CRANSource(Registry):
    """Comprehensive R Archive Network source."""

    source_id = "cran"
    name = "CRAN / Bioconductor"
    batch = False

    def _detect_name(self, repo_path: str) -> Optional[str]:
        """Detect R package name from DESCRIPTION file."""
        desc_path = Path(repo_path) / 'DESCRIPTION'
        if not desc_path.exists():
            return None
        try:
            fields = _parse_description(str(desc_path))
            return fields.get('package')
        except Exception as e:
            logger.debug(f"CRAN detect failed for {repo_path}: {e}")
            return None

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        return self._detect_name(repo_path) is not None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check CRAN (via crandb JSON API) and Bioconductor for package."""
        headers = {'User-Agent': 'repoindex (+https://github.com/queelius/repoindex)'}

        # Try CRAN via crandb (JSON API)
        try:
            resp = requests.get(
                f'https://crandb.r-pkg.org/{package_name}', timeout=10, headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return PackageMetadata(
                    registry='cran',
                    name=package_name,
                    version=data.get('Version'),
                    published=True,
                    url=f'https://cran.r-project.org/package={package_name}',
                )
        except Exception:
            pass

        # Fallback: try Bioconductor
        try:
            resp = requests.get(
                f'https://bioconductor.org/packages/json/3.20/bioc/{package_name}',
                timeout=10, headers=headers,
            )
            if resp.status_code == 200:
                return PackageMetadata(
                    registry='bioconductor',
                    name=package_name,
                    published=True,
                    url=f'https://bioconductor.org/packages/{package_name}',
                )
        except Exception:
            pass

        # Detected locally but not published to any known registry
        return PackageMetadata(
            registry='cran',
            name=package_name,
            published=False,
            url=None,
        )

    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        name = self._detect_name(repo_path)
        if not name:
            return None
        metadata = self.check(name, config)
        if metadata is None:
            return None
        return metadata.to_dict()


source = CRANSource()
