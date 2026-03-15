"""
CRAN/Bioconductor registry provider for repoindex.

Detects R packages via DESCRIPTION files and checks publication
status using the crandb JSON API (CRAN) and Bioconductor JSON API.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import requests

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


def _parse_description(desc_path: str) -> Dict[str, Optional[str]]:
    """Parse an R DESCRIPTION file (DCF format) into a dict.

    DCF format uses ``Key: Value`` lines with continuation lines
    that start with whitespace.  All values are stripped strings;
    keys not present in the file map to ``None``.

    Returns dict with keys: package, title, version, author,
    maintainer, url, bugreports, description, license.
    """
    _FIELDS = {
        'Package': 'package',
        'Title': 'title',
        'Version': 'version',
        'Author': 'author',
        'Authors@R': 'author',  # fallback
        'Maintainer': 'maintainer',
        'URL': 'url',
        'BugReports': 'bugreports',
        'Description': 'description',
        'License': 'license',
    }

    raw: Dict[str, str] = {}
    try:
        text = Path(desc_path).read_text(encoding='utf-8')
    except Exception:
        return {v: None for v in set(_FIELDS.values())}

    current_field: Optional[str] = None
    current_value: list = []

    for line in text.split('\n'):
        if line and not line[0].isspace():
            # Save previous field
            if current_field is not None:
                raw[current_field] = ' '.join(current_value).strip()
            # Parse new field
            if ':' in line:
                field, _, value = line.partition(':')
                current_field = field.strip()
                current_value = [value.strip()]
            else:
                current_field = None
                current_value = []
        elif current_field is not None and line.strip():
            current_value.append(line.strip())

    # Save last field
    if current_field is not None:
        raw[current_field] = ' '.join(current_value).strip()

    # Map DCF keys to our normalized keys
    result: Dict[str, Optional[str]] = {v: None for v in set(_FIELDS.values())}
    for dcf_key, norm_key in _FIELDS.items():
        if dcf_key in raw and result[norm_key] is None:
            result[norm_key] = raw[dcf_key] or None
    return result


class CRANProvider(RegistryProvider):
    """Comprehensive R Archive Network provider."""
    registry = "cran"
    name = "CRAN / Bioconductor"
    batch = False

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
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

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Check CRAN (via crandb JSON API) and Bioconductor for package."""
        # Try CRAN via crandb (JSON API)
        try:
            resp = requests.get(
                f'https://crandb.r-pkg.org/{package_name}', timeout=10,
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
                timeout=10,
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

        return None


provider = CRANProvider()
