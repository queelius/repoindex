"""CITATION.cff metadata source for repoindex."""
import json
import logging
from pathlib import Path
from typing import Optional

from . import MetadataSource

logger = logging.getLogger(__name__)


class CitationCffSource(MetadataSource):
    """Parse CITATION.cff files for citation metadata."""

    source_id = "citation_cff"
    name = "CITATION.cff"
    target = "repos"

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        return (Path(repo_path) / 'CITATION.cff').exists()

    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        """Parse CITATION.cff and return citation_* fields."""
        cff_path = Path(repo_path) / 'CITATION.cff'
        if not cff_path.exists():
            return None
        try:
            import yaml
            with open(cff_path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                # File exists but isn't a mapping (list, scalar, etc.) --
                # flag has_citation so callers know the file is present.
                return {'has_citation': 1}
            result = {}
            if data.get('doi'):
                result['citation_doi'] = data['doi']
            if data.get('title'):
                result['citation_title'] = data['title']
            v = data.get('version')
            if v is not None:
                if isinstance(v, float):
                    # YAML coerces unquoted values like "1.10" to float 1.1,
                    # silently losing precision. Warn so users can quote.
                    logger.warning(
                        "CITATION.cff in %s has unquoted float version %r; "
                        "quote it (e.g., version: \"1.10\") to preserve precision",
                        repo_path, v,
                    )
                result['citation_version'] = str(v)
            if data.get('repository-code'):
                result['citation_repository'] = data['repository-code']
            if data.get('license'):
                result['citation_license'] = data['license']
            authors = data.get('authors', [])
            if authors and isinstance(authors, list):
                result['citation_authors'] = json.dumps(authors)
            result['has_citation'] = 1
            return result if result else None
        except Exception:
            return {'has_citation': 1}  # File exists but parse failed


source = CitationCffSource()
