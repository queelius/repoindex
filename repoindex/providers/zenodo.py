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
        """Match repo to a pre-fetched Zenodo record.

        Three matching strategies (in priority order):
        1. GitHub URL from related_identifiers (most precise)
        2. Exact title match (title == repo dirname)
        3. Title-starts-with match (title starts with "dirname:" or "dirname ")
        """
        if not self._records:
            return None

        from ..infra.zenodo_client import _normalize_github_url
        from pathlib import Path

        repo_name = Path(repo_path).name.lower()

        # Strategy 1: Match via GitHub URL from related_identifiers
        remote_url = None
        if repo_record:
            remote_url = repo_record.get('remote_url')
        if not remote_url:
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

        # Strategy 2: Exact title match (e.g., title="repoindex", dir="repoindex")
        for record in self._records:
            if record.title and repo_name == record.title.lower().strip():
                return self._to_metadata(record)

        # Strategy 3: Title starts with repo name followed by colon or space
        # Handles "algebraic.mle: Algebraic Maximum Likelihood Estimators"
        # matching directory "algebraic.mle"
        for record in self._records:
            if not record.title:
                continue
            title_lower = record.title.lower().strip()
            if title_lower.startswith(repo_name + ':') or title_lower.startswith(repo_name + ' '):
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
