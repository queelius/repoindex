"""
Zenodo registry provider for repoindex.

Batch provider — fetches all records by ORCID in a single API call
during prefetch(), then matches repos locally in match().
"""

import logging
from typing import Dict, List, Optional

from . import RegistryProvider, PackageMetadata

logger = logging.getLogger(__name__)


class ZenodoProvider(RegistryProvider):
    """Zenodo DOI archive provider (batch-fetch via ORCID)."""
    registry = "zenodo"
    name = "Zenodo"
    batch = True

    def __init__(self):
        self._records: list = []

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
        """Not used for batch providers — match() handles everything."""
        return None

    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Not used for batch providers — match() handles everything."""
        return None

    def prefetch(self, config: dict) -> None:
        """Batch-fetch all Zenodo records by ORCID."""
        orcid = config.get('author', {}).get('orcid', '')
        if not orcid:
            logger.debug("Zenodo: no author.orcid configured, skipping")
            return

        try:
            from ..infra.zenodo_client import ZenodoClient
            client = ZenodoClient()
            self._records = client.search_by_orcid(orcid)
            logger.info(f"Zenodo: prefetched {len(self._records)} records for ORCID {orcid}")
        except Exception as e:
            logger.warning(f"Zenodo prefetch failed: {e}")
            self._records = []

    def match(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """Match repo to a pre-fetched Zenodo record."""
        if not self._records:
            return None

        from ..infra.zenodo_client import _normalize_github_url
        from pathlib import Path

        # Strategy 1: Match via GitHub URL from repo_record
        remote_url = None
        if repo_record:
            remote_url = repo_record.get('remote_url')
        if not remote_url:
            # Try to read from git config
            try:
                from ..infra import GitClient
                git = GitClient()
                remote_url = git.remote_url(repo_path)
            except Exception:
                pass

        if remote_url:
            normalized = _normalize_github_url(remote_url)
            for record in self._records:
                if record.github_url and record.github_url == normalized:
                    return self._to_metadata(record)

        # Strategy 2: Case-insensitive name/title match
        repo_name = Path(repo_path).name.lower()
        for record in self._records:
            if record.title and repo_name == record.title.lower():
                return self._to_metadata(record)

        return None

    @staticmethod
    def _to_metadata(record) -> PackageMetadata:
        """Convert a ZenodoRecord to PackageMetadata."""
        return PackageMetadata(
            registry='zenodo',
            name=record.title or '',
            version=record.version,
            published=True,
            url=record.url,
            doi=record.concept_doi or record.doi,
        )


provider = ZenodoProvider()
