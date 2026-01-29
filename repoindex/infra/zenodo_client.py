"""
Zenodo API client infrastructure for repoindex.

Provides access to the Zenodo public API for DOI enrichment:
- Batch-fetch records by ORCID (single API call for all author records)
- Extract concept DOIs (version-independent, always resolve to latest)
- Extract GitHub URLs from related_identifiers for repo matching

Public API — no authentication needed for open-access records.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests

logger = logging.getLogger(__name__)

# Zenodo public API base URL
ZENODO_API_BASE = "https://zenodo.org/api/records"

# Default page size for API queries
DEFAULT_PAGE_SIZE = 25


@dataclass
class ZenodoRecord:
    """A Zenodo deposit record."""
    doi: str                            # e.g., "10.5281/zenodo.18345659"
    concept_doi: Optional[str] = None   # Version-independent DOI
    title: str = ""
    version: Optional[str] = None
    url: str = ""                       # e.g., "https://zenodo.org/records/18345659"
    github_url: Optional[str] = None    # From related_identifiers

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> Optional['ZenodoRecord']:
        """
        Create from a Zenodo API response record.

        Args:
            data: Single record from Zenodo API search results

        Returns:
            ZenodoRecord or None if essential fields are missing
        """
        doi = data.get('doi')
        if not doi:
            return None

        # Extract concept DOI (version-independent)
        concept_doi = data.get('conceptdoi')

        # Extract metadata
        metadata = data.get('metadata', {})
        title = metadata.get('title', '')
        version = metadata.get('version')

        # Build Zenodo URL from record ID
        record_id = data.get('id')
        url = f"https://zenodo.org/records/{record_id}" if record_id else ''

        # Extract GitHub URL from related_identifiers
        github_url = _extract_github_url(metadata.get('related_identifiers', []))

        return cls(
            doi=doi,
            concept_doi=concept_doi,
            title=title,
            version=version,
            url=url,
            github_url=github_url,
        )


def _extract_github_url(related_identifiers: List[Dict[str, Any]]) -> Optional[str]:
    """
    Extract a GitHub repository URL from Zenodo related_identifiers.

    Zenodo records linked to GitHub often have a related_identifier like:
        {"identifier": "https://github.com/owner/repo/tree/v1.0",
         "relation": "isSupplementTo",
         "scheme": "url"}

    Args:
        related_identifiers: List of related identifier objects

    Returns:
        Normalized GitHub URL (https://github.com/owner/repo) or None
    """
    for rel in related_identifiers:
        identifier = rel.get('identifier', '')
        if 'github.com' in identifier:
            return _normalize_github_url(identifier)
    return None


def _normalize_github_url(url: str) -> str:
    """
    Normalize a GitHub URL to https://github.com/owner/repo format.

    Handles:
        https://github.com/owner/repo/tree/v1.0 → https://github.com/owner/repo
        https://github.com/owner/repo.git → https://github.com/owner/repo
        git@github.com:owner/repo.git → https://github.com/owner/repo
    """
    # Convert SSH to HTTPS
    url = re.sub(r'^git@github\.com:', 'https://github.com/', url)

    # Remove .git suffix
    url = re.sub(r'\.git$', '', url)

    # Extract just owner/repo from path
    match = re.match(r'(https?://github\.com/[^/]+/[^/]+)', url)
    if match:
        return match.group(1).lower()

    return url.lower()


class ZenodoClient:
    """
    Client for the Zenodo public REST API.

    Uses batch-fetch strategy: a single ORCID query returns all
    the author's records. No per-repo API calls needed.
    """

    def __init__(self, timeout: int = 30):
        """
        Initialize ZenodoClient.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
        })

    def search_by_orcid(self, orcid: str) -> List[ZenodoRecord]:
        """
        Search Zenodo for all records by an ORCID author.

        Uses the Zenodo search API with creators.orcid query.
        Paginates automatically if there are more results than page size.

        Args:
            orcid: ORCID identifier (e.g., "0000-0001-6443-9897")

        Returns:
            List of ZenodoRecord objects
        """
        records = []
        page = 1

        while True:
            params = {
                'q': f'creators.orcid:{orcid}',
                'size': DEFAULT_PAGE_SIZE,
                'page': page,
                'sort': '-mostrecent',
            }

            try:
                response = self.session.get(
                    ZENODO_API_BASE,
                    params=params,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                logger.warning(f"Zenodo API request failed: {e}")
                break
            except ValueError as e:
                logger.warning(f"Zenodo API returned invalid JSON: {e}")
                break

            hits = data.get('hits', {}).get('hits', [])
            if not hits:
                break

            for hit in hits:
                record = ZenodoRecord.from_api_response(hit)
                if record:
                    records.append(record)

            # Check if there are more pages
            total = data.get('hits', {}).get('total', 0)
            if page * DEFAULT_PAGE_SIZE >= total:
                break

            page += 1

        logger.info(f"Zenodo: found {len(records)} records for ORCID {orcid}")
        return records
