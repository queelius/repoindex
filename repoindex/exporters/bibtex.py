"""
BibTeX exporter for repoindex.

Generates @software{} entries suitable for academic citations.
Uses citation metadata (DOI, authors, title) when available,
falls back to repo metadata.
"""

import json
import re
from typing import IO, List, Optional

from . import Exporter


def _make_bibtex_key(repo: dict) -> str:
    """Generate a BibTeX citation key from repo metadata."""
    name = repo.get('name', 'unknown')
    # Sanitize: only alphanumeric and underscores
    key = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    return key


def _escape_bibtex(text: str) -> str:
    """Escape special BibTeX characters."""
    if not text:
        return ''
    # Use placeholders for commands that contain braces, to avoid
    # those braces being re-escaped by the brace escaping step.
    _BACKSLASH = '\x00BACKSLASH\x00'
    _TILDE = '\x00TILDE\x00'
    text = text.replace('\\', _BACKSLASH)
    text = text.replace('~', _TILDE)
    for char in ('&', '%', '#', '_', '$', '{', '}'):
        if char == '{':
            text = text.replace(char, '\\{')
        elif char == '}':
            text = text.replace(char, '\\}')
        else:
            text = text.replace(char, f'\\{char}')
    text = text.replace(_BACKSLASH, '\\textbackslash{}')
    text = text.replace(_TILDE, '\\textasciitilde{}')
    return text


def _format_authors(authors_json: Optional[str]) -> Optional[str]:
    """Format citation_authors JSON into BibTeX author string."""
    if not authors_json:
        return None
    try:
        authors = json.loads(authors_json) if isinstance(authors_json, str) else authors_json
        if not isinstance(authors, list):
            return None
        names = []
        for a in authors:
            if isinstance(a, dict):
                name = a.get('name') or a.get('family-names', '')
                given = a.get('given-names', '')
                if given and name:
                    names.append(f"{name}, {given}")
                elif name:
                    names.append(name)
            elif isinstance(a, str):
                names.append(a)
        return ' and '.join(names) if names else None
    except (json.JSONDecodeError, TypeError):
        return None


class BibTeXExporter(Exporter):
    """BibTeX @software{} citation exporter."""
    format_id = "bibtex"
    name = "BibTeX Citations"
    extension = ".bib"

    def export(self, repos: List[dict], output: IO[str],
               config: Optional[dict] = None) -> int:
        count = 0
        for repo in repos:
            key = _make_bibtex_key(repo)

            # Title: prefer citation_title, fallback to name
            title = repo.get('citation_title') or repo.get('name', '')

            # Author: prefer citation_authors, fallback to owner
            author = _format_authors(repo.get('citation_authors'))
            if not author:
                author = repo.get('owner') or repo.get('github_owner') or ''

            # Version
            version = repo.get('citation_version') or repo.get('current_version') or ''

            # URL
            url = repo.get('citation_repository') or repo.get('remote_url') or ''

            # DOI
            doi = repo.get('citation_doi') or ''

            output.write(f"@software{{{key},\n")
            output.write(f"  title = {{{_escape_bibtex(title)}}},\n")
            if author:
                output.write(f"  author = {{{_escape_bibtex(author)}}},\n")
            if version:
                output.write(f"  version = {{{version}}},\n")
            if url:
                output.write(f"  url = {{{url}}},\n")
            if doi:
                output.write(f"  doi = {{{doi}}},\n")

            lang = repo.get('language') or ''
            if lang:
                output.write(f"  note = {{Primary language: {lang}}},\n")

            license_key = repo.get('license_key') or ''
            if license_key:
                output.write(f"  license = {{{license_key}}},\n")

            output.write("}\n\n")
            count += 1

        return count


exporter = BibTeXExporter()
