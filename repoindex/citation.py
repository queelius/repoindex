"""
Citation file parsing for repoindex.

Parses CITATION.cff (YAML) and .zenodo.json (JSON) to extract metadata
such as DOI, title, authors, version, repository URL, and license.

CITATION.cff spec: https://citation-file-format.github.io/
Zenodo metadata: https://developers.zenodo.org/
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def parse_citation_file(repo_path: str, citation_file: str) -> Optional[Dict[str, Any]]:
    """
    Parse a citation file and extract metadata.

    Args:
        repo_path: Path to the repository
        citation_file: Name of the citation file (e.g., "CITATION.cff")

    Returns:
        Dictionary with extracted metadata:
        - doi: DOI identifier
        - title: Software title
        - authors: List of author dicts with name, orcid, affiliation
        - version: Version string
        - repository: Repository URL
        - license: License identifier

        Returns None if parsing fails or file doesn't exist.
    """
    filepath = Path(repo_path) / citation_file

    if not filepath.exists():
        return None

    try:
        if citation_file == 'CITATION.cff':
            return _parse_citation_cff(filepath)
        elif citation_file == '.zenodo.json':
            return _parse_zenodo_json(filepath)
        elif citation_file == 'CITATION.bib':
            # BibTeX parsing deferred to future enhancement
            # Would require a BibTeX parser library
            logger.debug(f"BibTeX parsing not implemented: {filepath}")
            return None
        else:
            return None
    except Exception as e:
        logger.debug(f"Failed to parse {citation_file} in {repo_path}: {e}")
        return None


def _parse_citation_cff(filepath: Path) -> Optional[Dict[str, Any]]:
    """
    Parse CITATION.cff (YAML format).

    CFF 1.2.0 spec: https://citation-file-format.github.io/

    Example CITATION.cff:
        cff-version: 1.2.0
        title: "Project Name"
        authors:
          - family-names: "Smith"
            given-names: "John"
            orcid: "https://orcid.org/0000-0000-0000-0000"
        identifiers:
          - type: doi
            value: "10.5281/zenodo.1234567"
        repository-code: "https://github.com/user/repo"
        license: MIT
        version: "1.0.0"
    """
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed, cannot parse CITATION.cff")
        return None

    try:
        content = filepath.read_text(encoding='utf-8', errors='replace')
        data = yaml.safe_load(content)

        if not isinstance(data, dict):
            return None

        result = {
            'doi': None,
            'title': data.get('title'),
            'authors': _parse_cff_authors(data.get('authors', [])),
            'version': data.get('version'),
            'repository': data.get('repository-code'),
            'license': data.get('license'),
        }

        # Extract DOI from identifiers array (CFF 1.2.0 format)
        identifiers = data.get('identifiers', [])
        for ident in identifiers:
            if isinstance(ident, dict) and ident.get('type') == 'doi':
                result['doi'] = ident.get('value')
                break

        # Fallback: check for doi field directly (older format)
        if not result['doi'] and 'doi' in data:
            result['doi'] = data['doi']

        return result

    except yaml.YAMLError as e:
        logger.debug(f"YAML parse error in {filepath}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Error parsing CITATION.cff: {e}")
        return None


def _parse_cff_authors(authors: List[Any]) -> List[Dict[str, Any]]:
    """
    Parse CFF authors list.

    CFF format supports:
    - family-names + given-names (person)
    - name (entity like "Research Group")
    - Optional: orcid, affiliation, email

    Returns simplified author objects with name and optional metadata.
    """
    result = []

    for author in authors:
        if not isinstance(author, dict):
            continue

        author_obj = {}

        # Build name from parts (person)
        family = author.get('family-names', '')
        given = author.get('given-names', '')

        if family or given:
            name_parts = []
            if given:
                name_parts.append(given)
            if family:
                name_parts.append(family)
            author_obj['name'] = ' '.join(name_parts)
        elif author.get('name'):
            # Entity name (research group, organization)
            author_obj['name'] = author['name']

        # Optional metadata
        if author.get('orcid'):
            author_obj['orcid'] = author['orcid']

        if author.get('affiliation'):
            author_obj['affiliation'] = author['affiliation']

        if author.get('email'):
            author_obj['email'] = author['email']

        if author_obj.get('name'):
            result.append(author_obj)

    return result


def _parse_zenodo_json(filepath: Path) -> Optional[Dict[str, Any]]:
    """
    Parse .zenodo.json format.

    Zenodo deposit metadata format for automatic DOI minting.

    Example .zenodo.json:
        {
            "doi": "10.5281/zenodo.7654321",
            "title": "Project Name",
            "creators": [
                {"name": "Smith, John", "orcid": "0000-0000-0000-0000"}
            ],
            "version": "2.0.0",
            "license": {"id": "MIT"}
        }
    """
    try:
        content = filepath.read_text(encoding='utf-8', errors='replace')
        data = json.loads(content)

        if not isinstance(data, dict):
            return None

        # Extract repository from related_identifiers if present
        repository = None
        related = data.get('related_identifiers', [])
        for rel in related:
            if isinstance(rel, dict) and rel.get('relation') in ('isSupplementTo', 'isPartOf'):
                repository = rel.get('identifier')
                break

        result = {
            'doi': data.get('doi'),
            'title': data.get('title'),
            'authors': _parse_zenodo_authors(data.get('creators', [])),
            'version': data.get('version'),
            'repository': repository,
            'license': _parse_zenodo_license(data.get('license')),
        }

        return result

    except json.JSONDecodeError as e:
        logger.debug(f"JSON parse error in {filepath}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Error parsing .zenodo.json: {e}")
        return None


def _parse_zenodo_authors(creators: List[Any]) -> List[Dict[str, Any]]:
    """
    Parse Zenodo creators list.

    Zenodo format:
        {"name": "Last, First", "orcid": "...", "affiliation": "..."}
    """
    result = []

    for creator in creators:
        if not isinstance(creator, dict):
            continue

        author_obj = {}

        if creator.get('name'):
            author_obj['name'] = creator['name']

        if creator.get('orcid'):
            author_obj['orcid'] = creator['orcid']

        if creator.get('affiliation'):
            author_obj['affiliation'] = creator['affiliation']

        if author_obj.get('name'):
            result.append(author_obj)

    return result


def _parse_zenodo_license(license_data: Any) -> Optional[str]:
    """
    Parse Zenodo license field.

    Can be either:
    - String: "MIT"
    - Object: {"id": "MIT"}
    """
    if isinstance(license_data, dict):
        return license_data.get('id')
    elif isinstance(license_data, str):
        return license_data
    return None
