"""
JSON-LD exporter for repoindex.

Generates schema.org/SoftwareSourceCode objects in a @graph array.
Useful for semantic web / linked data applications.
"""

import json
from typing import IO, List, Optional

from . import Exporter


def _repo_to_jsonld(repo: dict) -> dict:
    """Convert a repo dict to a schema.org SoftwareSourceCode object."""
    obj = {
        "@type": "SoftwareSourceCode",
        "name": repo.get('name', ''),
    }

    url = repo.get('remote_url')
    if url:
        obj["codeRepository"] = url

    desc = repo.get('description') or repo.get('github_description')
    if desc:
        obj["description"] = desc

    lang = repo.get('language')
    if lang:
        obj["programmingLanguage"] = lang

    license_key = repo.get('license_key')
    if license_key:
        # Map common SPDX identifiers to URLs
        spdx_url = f"https://spdx.org/licenses/{license_key}"
        obj["license"] = spdx_url

    doi = repo.get('citation_doi')
    if doi:
        obj["identifier"] = f"https://doi.org/{doi}"

    version = repo.get('citation_version')
    if version:
        obj["version"] = version

    # Authors from citation metadata
    authors_raw = repo.get('citation_authors')
    if authors_raw:
        try:
            authors = json.loads(authors_raw) if isinstance(authors_raw, str) else authors_raw
            if isinstance(authors, list):
                persons = []
                for a in authors:
                    if isinstance(a, dict):
                        person = {"@type": "Person"}
                        name = a.get('name') or ''
                        given = a.get('given-names', '')
                        family = a.get('family-names', '')
                        if given and family:
                            person["givenName"] = given
                            person["familyName"] = family
                            person["name"] = f"{given} {family}"
                        elif name:
                            person["name"] = name
                        orcid = a.get('orcid')
                        if orcid:
                            person["identifier"] = f"https://orcid.org/{orcid}"
                        persons.append(person)
                    elif isinstance(a, str):
                        persons.append({"@type": "Person", "name": a})
                if persons:
                    obj["author"] = persons
        except (json.JSONDecodeError, TypeError):
            pass

    return obj


class JSONLDExporter(Exporter):
    """JSON-LD (schema.org/SoftwareSourceCode) exporter."""
    format_id = "jsonld"
    name = "JSON-LD"
    extension = ".jsonld"

    def export(self, repos: List[dict], output: IO[str],
               config: Optional[dict] = None) -> int:
        graph = []
        for repo in repos:
            graph.append(_repo_to_jsonld(repo))

        doc = {
            "@context": "https://schema.org",
            "@graph": graph,
        }

        json.dump(doc, output, indent=2, ensure_ascii=False)
        output.write('\n')

        return len(graph)


exporter = JSONLDExporter()
