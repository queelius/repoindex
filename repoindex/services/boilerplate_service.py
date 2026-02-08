"""
Boilerplate file generator service for repoindex.

Generates boilerplate files: LICENSE, codemeta.json, CITATION.cff,
.zenodo.json, mkdocs.yml, deploy-docs.yml, .gitignore,
CODE_OF_CONDUCT.md, and CONTRIBUTING.md for repositories.
Used by the `repoindex ops generate` command group.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from ..citation import parse_citation_file
from ..config import load_config
from ..domain.operation import (
    FileGenerationResult,
    OperationStatus,
    OperationSummary,
)
from ..pypi import extract_project_metadata

logger = logging.getLogger(__name__)


# Common open source licenses with SPDX identifiers
LICENSES = {
    'mit': {
        'spdx': 'MIT',
        'name': 'MIT License',
        'url': 'https://opensource.org/licenses/MIT',
    },
    'apache-2.0': {
        'spdx': 'Apache-2.0',
        'name': 'Apache License 2.0',
        'url': 'https://opensource.org/licenses/Apache-2.0',
    },
    'gpl-3.0': {
        'spdx': 'GPL-3.0',
        'name': 'GNU General Public License v3.0',
        'url': 'https://www.gnu.org/licenses/gpl-3.0.html',
    },
    'bsd-3-clause': {
        'spdx': 'BSD-3-Clause',
        'name': 'BSD 3-Clause License',
        'url': 'https://opensource.org/licenses/BSD-3-Clause',
    },
    'mpl-2.0': {
        'spdx': 'MPL-2.0',
        'name': 'Mozilla Public License 2.0',
        'url': 'https://opensource.org/licenses/MPL-2.0',
    },
}

# Gitignore templates by language
GITIGNORE_TEMPLATES = {
    'python': """# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
*.egg-info/
dist/
build/
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/
""",
    'node': """# Node.js
node_modules/
npm-debug.log*
.env
.env.local
dist/
coverage/
""",
    'rust': """# Rust
/target/
Cargo.lock
""",
    'go': """# Go
/bin/
/pkg/
*.exe
""",
    'cpp': """# C/C++
build/
cmake-build-*/
*.o
*.a
*.so
*.dylib
""",
    'java': """# Java
target/
*.class
*.jar
.gradle/
""",
}


@dataclass
class AuthorInfo:
    """Author information for citations."""
    name: str
    given_names: Optional[str] = None
    family_names: Optional[str] = None
    email: Optional[str] = None
    orcid: Optional[str] = None
    affiliation: Optional[str] = None

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> Optional['AuthorInfo']:
        """Create AuthorInfo from config author section."""
        author_config = config.get('author', {})
        name = author_config.get('name', '')

        if not name:
            return None

        # Parse name into given/family names
        given_names = None
        family_names = None
        if ' ' in name:
            parts = name.rsplit(' ', 1)
            given_names = parts[0]
            family_names = parts[1]

        return cls(
            name=name,
            given_names=given_names,
            family_names=family_names,
            email=author_config.get('email'),
            orcid=author_config.get('orcid'),
            affiliation=author_config.get('affiliation'),
        )

    def to_codemeta_dict(self) -> Dict[str, Any]:
        """Convert to codemeta.json Person format."""
        result: Dict[str, Any] = {
            '@type': 'Person',
            'name': self.name,
        }
        if self.given_names:
            result['givenName'] = self.given_names
        if self.family_names:
            result['familyName'] = self.family_names
        if self.email:
            result['email'] = self.email
        if self.orcid:
            orcid = self.orcid
            if not orcid.startswith('https://'):
                orcid = f'https://orcid.org/{orcid}'
            result['@id'] = orcid
        if self.affiliation:
            result['affiliation'] = {
                '@type': 'Organization',
                'name': self.affiliation,
            }
        return result

    def to_cff_dict(self) -> Dict[str, Any]:
        """Convert to CITATION.cff author format."""
        result: Dict[str, Any] = {}
        if self.family_names:
            result['family-names'] = self.family_names
        if self.given_names:
            result['given-names'] = self.given_names
        if self.email:
            result['email'] = self.email
        if self.orcid:
            orcid = self.orcid
            if not orcid.startswith('https://'):
                orcid = f'https://orcid.org/{orcid}'
            result['orcid'] = orcid
        if self.affiliation:
            result['affiliation'] = self.affiliation
        return result

    def to_zenodo_dict(self) -> Dict[str, Any]:
        """Convert to .zenodo.json creator format."""
        # Zenodo expects "Family, Given" format for name
        if self.family_names and self.given_names:
            name = f'{self.family_names}, {self.given_names}'
        else:
            name = self.name
        result: Dict[str, Any] = {'name': name}
        if self.orcid:
            orcid = self.orcid
            if orcid.startswith('https://orcid.org/'):
                orcid = orcid[len('https://orcid.org/'):]
            result['orcid'] = orcid
        if self.affiliation:
            result['affiliation'] = self.affiliation
        return result


@dataclass
class GenerationOptions:
    """Options for file generation."""
    dry_run: bool = False
    force: bool = False  # Overwrite existing files
    author: Optional[AuthorInfo] = None
    license: Optional[str] = None  # SPDX identifier


class BoilerplateService:
    """
    Service for generating boilerplate files.

    Generates LICENSE, codemeta.json, .gitignore, CODE_OF_CONDUCT.md,
    and CONTRIBUTING.md files based on repository metadata and configuration.

    Example:
        service = BoilerplateService()
        options = GenerationOptions(dry_run=True)

        for progress in service.generate_license(repos, options, 'mit'):
            print(progress)

        result = service.last_result
        print(f"Generated {result.successful} files")
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize BoilerplateService.

        Args:
            config: Configuration dict (loads default if None)
        """
        self.config = config or load_config()
        self.last_result: Optional[OperationSummary] = None
        self._version = self._get_version()

    def _get_version(self) -> str:
        """Get repoindex version."""
        try:
            from .. import __version__
            return __version__
        except ImportError:
            return "unknown"

    def _generate_files(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions,
        operation_name: str,
        filename: str,
        file_type: str,
        display_name: str,
        content_fn,
    ) -> Generator[str, None, OperationSummary]:
        """
        Common generator for all boilerplate file generation.

        Args:
            repos: List of repository dicts (from query)
            options: Generation options
            operation_name: Name for the OperationSummary (e.g., "generate_codemeta")
            filename: Target filename (e.g., "codemeta.json", "LICENSE")
            file_type: Type label for FileGenerationResult (e.g., "codemeta", "license")
            display_name: Human-readable name for progress messages (e.g., "codemeta.json")
            content_fn: Callable(repo_dict, repo_name) -> str that generates file content

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        result = OperationSummary(operation=operation_name, dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to process"
            return result

        for repo in repos:
            path = repo.get('path', '')
            name = repo.get('name', path)

            if not path:
                continue

            repo_path = Path(path)
            target_file = repo_path / filename

            if target_file.exists() and not options.force:
                yield f"Skipping {name} ({filename} exists, use --force to overwrite)"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="File exists",
                    file_type=file_type,
                )
                result.add_detail(detail)
                continue

            try:
                content = content_fn(repo, name)

                if options.dry_run:
                    yield f"Would generate {display_name} for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.DRY_RUN,
                        action="would_generate",
                        file_path=str(target_file),
                        file_type=file_type,
                    )
                else:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_text(content)
                    yield f"Generated {display_name} for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="generated",
                        file_path=str(target_file),
                        file_type=file_type,
                        overwritten=options.force,
                    )

                result.add_detail(detail)

            except Exception as e:
                logger.error(f"Failed to generate {display_name} for {name}: {e}")
                yield f"Error generating {display_name} for {name}: {e}"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.FAILED,
                    action="generation_failed",
                    error=str(e),
                    file_type=file_type,
                )
                result.add_detail(detail)

        return result

    def generate_codemeta(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate codemeta.json files for repositories.

        Args:
            repos: List of repository dicts (from query)
            options: Generation options

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        author = options.author or AuthorInfo.from_config(self.config)

        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_codemeta",
            filename="codemeta.json",
            file_type="codemeta",
            display_name="codemeta.json",
            content_fn=lambda repo, name: self._generate_codemeta_content(repo, author, options.license),
        ))

    def _generate_codemeta_content(
        self,
        repo: Dict[str, Any],
        author: Optional[AuthorInfo],
        license_id: Optional[str]
    ) -> str:
        """Generate codemeta.json content."""
        name = repo.get('name', 'Unknown')
        description = repo.get('description') or repo.get('github_description', '')
        remote_url = repo.get('remote_url', '')
        version = repo.get('version') or repo.get('pypi_version', '')
        language = repo.get('language', '')
        repo_license = license_id or repo.get('license') or repo.get('license_key', '')

        codemeta: Dict[str, Any] = {
            '@context': 'https://doi.org/10.5063/schema/codemeta-2.0',
            '@type': 'SoftwareSourceCode',
            'name': name,
        }

        if description:
            codemeta['description'] = description

        if author:
            codemeta['author'] = [author.to_codemeta_dict()]

        if remote_url:
            display_url = remote_url
            if display_url.startswith('git@github.com:'):
                display_url = display_url.replace('git@github.com:', 'https://github.com/')
            if display_url.endswith('.git'):
                display_url = display_url[:-4]
            codemeta['codeRepository'] = display_url

        if version:
            codemeta['version'] = version

        if language:
            codemeta['programmingLanguage'] = language

        if repo_license:
            license_url = f'https://spdx.org/licenses/{repo_license}'
            codemeta['license'] = license_url

        codemeta['dateModified'] = date.today().isoformat()

        return json.dumps(codemeta, indent=2) + '\n'

    # ========================================================================
    # CITATION.cff generation
    # ========================================================================

    def generate_citation_cff(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate CITATION.cff files for repositories.

        Args:
            repos: List of repository dicts (from query)
            options: Generation options

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        author = options.author or AuthorInfo.from_config(self.config)

        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_citation_cff",
            filename="CITATION.cff",
            file_type="citation_cff",
            display_name="CITATION.cff",
            content_fn=lambda repo, name: self._generate_citation_cff_content(repo, author),
        ))

    def _normalize_remote_url(self, remote_url: str) -> str:
        """Normalize git remote URL to HTTPS format."""
        url = remote_url
        if url.startswith('git@github.com:'):
            url = url.replace('git@github.com:', 'https://github.com/')
        if url.endswith('.git'):
            url = url[:-4]
        return url

    def _generate_citation_cff_content(
        self,
        repo: Dict[str, Any],
        author: Optional[AuthorInfo],
    ) -> str:
        """Generate CITATION.cff content (CFF 1.2.0 format).

        Reads pyproject.toml for enriched metadata. Preserves existing DOI
        if regenerating with --force.
        """
        try:
            import yaml
        except ImportError as err:
            raise ImportError("PyYAML is required for CITATION.cff generation: pip install pyyaml") from err

        repo_path = repo.get('path', '')
        name = repo.get('name', 'Unknown')

        # Read pyproject.toml for richer metadata
        proj = extract_project_metadata(repo_path) if repo_path else {}
        proj_name = proj.get('name') or name
        version = proj.get('version') or repo.get('version') or repo.get('pypi_version', '')
        description = proj.get('description') or repo.get('description') or repo.get('github_description', '')
        license_id = proj.get('license') or repo.get('license') or repo.get('license_key', '')
        keywords = proj.get('keywords', [])
        remote_url = repo.get('remote_url', '')
        homepage = proj.get('homepage', '')

        # Preserve existing DOI if file exists
        existing_doi = None
        if repo_path:
            existing = parse_citation_file(repo_path, 'CITATION.cff')
            if existing and existing.get('doi'):
                existing_doi = existing['doi']

        # Build CFF structure
        cff: Dict[str, Any] = {
            'cff-version': '1.2.0',
            'message': 'If you use this software, please cite it as below.',
            'type': 'software',
            'title': proj_name,
        }

        if version:
            cff['version'] = version

        if description:
            cff['abstract'] = description

        if license_id:
            cff['license'] = license_id

        cff['date-released'] = date.today().isoformat()

        if remote_url:
            cff['repository-code'] = self._normalize_remote_url(remote_url)

        if homepage:
            cff['url'] = homepage

        if keywords:
            cff['keywords'] = keywords

        if author:
            cff['authors'] = [author.to_cff_dict()]

        if existing_doi:
            cff['identifiers'] = [{'type': 'doi', 'value': existing_doi}]

        return yaml.dump(cff, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # ========================================================================
    # .zenodo.json generation
    # ========================================================================

    def generate_zenodo_json(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate .zenodo.json files for repositories.

        Args:
            repos: List of repository dicts (from query)
            options: Generation options

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        author = options.author or AuthorInfo.from_config(self.config)

        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_zenodo_json",
            filename=".zenodo.json",
            file_type="zenodo_json",
            display_name=".zenodo.json",
            content_fn=lambda repo, name: self._generate_zenodo_json_content(repo, author),
        ))

    def _generate_zenodo_json_content(
        self,
        repo: Dict[str, Any],
        author: Optional[AuthorInfo],
    ) -> str:
        """Generate .zenodo.json content.

        Reads pyproject.toml for enriched metadata. Preserves existing DOI
        if regenerating with --force.
        """
        repo_path = repo.get('path', '')
        name = repo.get('name', 'Unknown')

        # Read pyproject.toml for richer metadata
        proj = extract_project_metadata(repo_path) if repo_path else {}
        proj_name = proj.get('name') or name
        description = proj.get('description') or repo.get('description') or repo.get('github_description', '')
        version = proj.get('version') or repo.get('version') or repo.get('pypi_version', '')
        license_id = proj.get('license') or repo.get('license') or repo.get('license_key', '')
        keywords = proj.get('keywords', [])
        remote_url = repo.get('remote_url', '')

        # Preserve existing DOI if file exists
        existing_doi = None
        if repo_path:
            existing = parse_citation_file(repo_path, '.zenodo.json')
            if existing and existing.get('doi'):
                existing_doi = existing['doi']

        # Build Zenodo metadata
        title = f'{proj_name}: {description}' if description else proj_name
        # Zenodo title should be concise
        if len(title) > 200:
            title = proj_name

        zenodo: Dict[str, Any] = {
            'title': title,
            'upload_type': 'software',
        }

        if description:
            zenodo['description'] = description

        if version:
            zenodo['version'] = version

        if license_id:
            zenodo['license'] = {'id': license_id}

        if keywords:
            zenodo['keywords'] = keywords

        if author:
            zenodo['creators'] = [author.to_zenodo_dict()]

        if remote_url:
            zenodo['related_identifiers'] = [{
                'identifier': self._normalize_remote_url(remote_url),
                'relation': 'isSupplementTo',
                'scheme': 'url',
            }]

        if existing_doi:
            zenodo['doi'] = existing_doi

        return json.dumps(zenodo, indent=2) + '\n'

    # ========================================================================
    # mkdocs.yml generation
    # ========================================================================

    def generate_mkdocs(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate mkdocs.yml files for repositories.

        Scaffolds mkdocs.yml with Material theme, standard extensions,
        and nav from docs/ if it exists.

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_mkdocs",
            filename="mkdocs.yml",
            file_type="mkdocs",
            display_name="mkdocs.yml",
            content_fn=lambda repo, name: self._generate_mkdocs_content(repo),
        ))

    def _generate_mkdocs_content(self, repo: Dict[str, Any]) -> str:
        """Generate mkdocs.yml content with Material theme."""
        try:
            import yaml
        except ImportError as err:
            raise ImportError("PyYAML is required for mkdocs.yml generation: pip install pyyaml") from err

        repo_path = repo.get('path', '')
        name = repo.get('name', 'Unknown')
        description = repo.get('description') or repo.get('github_description', '')
        remote_url = repo.get('remote_url', '')

        proj = extract_project_metadata(repo_path) if repo_path else {}
        site_name = proj.get('name') or name

        repo_url = ''
        if remote_url:
            repo_url = self._normalize_remote_url(remote_url)

        mkdocs: Dict[str, Any] = {
            'site_name': site_name,
        }

        if description:
            mkdocs['site_description'] = description

        if repo_url:
            mkdocs['repo_url'] = repo_url
            mkdocs['repo_name'] = name

        mkdocs['theme'] = {
            'name': 'material',
            'palette': [
                {
                    'scheme': 'default',
                    'primary': 'indigo',
                    'accent': 'indigo',
                    'toggle': {
                        'icon': 'material/brightness-7',
                        'name': 'Switch to dark mode',
                    },
                },
                {
                    'scheme': 'slate',
                    'primary': 'indigo',
                    'accent': 'indigo',
                    'toggle': {
                        'icon': 'material/brightness-4',
                        'name': 'Switch to light mode',
                    },
                },
            ],
        }

        mkdocs['markdown_extensions'] = [
            'pymdownx.highlight',
            'pymdownx.superfences',
            'pymdownx.tabbed',
            'admonition',
            'pymdownx.details',
            'toc',
        ]

        # Build nav from docs/ if it exists
        nav = [{'Home': 'index.md'}]
        docs_dir = Path(repo_path) / 'docs' if repo_path else None
        if docs_dir and docs_dir.exists():
            for md_file in sorted(docs_dir.glob('*.md')):
                if md_file.name != 'index.md':
                    title = md_file.stem.replace('-', ' ').replace('_', ' ').title()
                    nav.append({title: md_file.name})

        mkdocs['nav'] = nav

        return yaml.dump(mkdocs, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # ========================================================================
    # GitHub Pages workflow generation
    # ========================================================================

    def generate_gh_pages_workflow(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate .github/workflows/deploy-docs.yml for repositories.

        Scaffolds a GitHub Actions workflow for deploying MkDocs to GitHub Pages.

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_gh_pages",
            filename=".github/workflows/deploy-docs.yml",
            file_type="gh_pages_workflow",
            display_name="deploy-docs.yml",
            content_fn=lambda repo, name: self._generate_gh_pages_content(),
        ))

    def _generate_gh_pages_content(self) -> str:
        """Generate GitHub Actions workflow for MkDocs deployment."""
        return """name: Deploy docs

on:
  push:
    branches: [main, master]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.x'
      - run: pip install mkdocs-material
      - run: mkdocs build
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - id: deployment
        uses: actions/deploy-pages@v4
"""

    def generate_license(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions,
        license_type: str = 'mit'
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate LICENSE files for repositories.

        Args:
            repos: List of repository dicts (from query)
            options: Generation options
            license_type: License type (mit, apache-2.0, gpl-3.0, etc.)

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        license_key = license_type.lower()
        if license_key not in LICENSES:
            result = OperationSummary(operation="generate_license", dry_run=options.dry_run)
            self.last_result = result
            yield f"Unknown license type: {license_type}"
            yield f"Supported: {', '.join(LICENSES.keys())}"
            return result

        author = options.author or AuthorInfo.from_config(self.config)
        author_name = author.name if author else "Author"

        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_license",
            filename="LICENSE",
            file_type="license",
            display_name=f"LICENSE ({license_type})",
            content_fn=lambda repo, name: self._generate_license_content(license_key, author_name),
        ))

    def _generate_license_content(self, license_type: str, author_name: str) -> str:
        """Generate license file content."""
        year = date.today().year

        if license_type == 'mit':
            return f"""MIT License

Copyright (c) {year} {author_name}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
        elif license_type == 'apache-2.0':
            return f"""                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   Copyright {year} {author_name}

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
        elif license_type == 'gpl-3.0':
            return f"""GNU GENERAL PUBLIC LICENSE
Version 3, 29 June 2007

Copyright (C) {year} {author_name}

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
        elif license_type == 'bsd-3-clause':
            return f"""BSD 3-Clause License

Copyright (c) {year}, {author_name}
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
        elif license_type == 'mpl-2.0':
            return f"""Mozilla Public License Version 2.0

Copyright (c) {year} {author_name}

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""
        else:
            return f"# License\n\nCopyright (c) {year} {author_name}\n"

    def generate_gitignore(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions,
        language: str = 'python'
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate .gitignore files for repositories.

        Args:
            repos: List of repository dicts (from query)
            options: Generation options
            language: Language template (python, node, rust, go, cpp, java)

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        lang_key = language.lower()
        if lang_key not in GITIGNORE_TEMPLATES:
            result = OperationSummary(operation="generate_gitignore", dry_run=options.dry_run)
            self.last_result = result
            yield f"Unknown language: {language}"
            yield f"Supported: {', '.join(GITIGNORE_TEMPLATES.keys())}"
            return result

        template = GITIGNORE_TEMPLATES[lang_key]

        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_gitignore",
            filename=".gitignore",
            file_type="gitignore",
            display_name=f".gitignore ({language})",
            content_fn=lambda repo, name: template,
        ))

    def generate_code_of_conduct(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate CODE_OF_CONDUCT.md files for repositories.

        Uses Contributor Covenant v2.1.

        Args:
            repos: List of repository dicts (from query)
            options: Generation options

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        author = options.author or AuthorInfo.from_config(self.config)
        contact_email = (author.email or "maintainer@example.com") if author else "maintainer@example.com"

        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_code_of_conduct",
            filename="CODE_OF_CONDUCT.md",
            file_type="code_of_conduct",
            display_name="CODE_OF_CONDUCT.md",
            content_fn=lambda repo, name: self._generate_code_of_conduct_content(contact_email),
        ))

    def _generate_code_of_conduct_content(self, contact_email: str) -> str:
        """Generate CODE_OF_CONDUCT.md content (Contributor Covenant v2.1)."""
        return f"""# Contributor Covenant Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our
community a harassment-free experience for everyone.

## Our Standards

Examples of behavior that contributes to a positive environment:

* Using welcoming and inclusive language
* Being respectful of differing viewpoints and experiences
* Gracefully accepting constructive criticism
* Focusing on what is best for the community

Examples of unacceptable behavior:

* Trolling, insulting or derogatory comments
* Public or private harassment
* Publishing others' private information without permission
* Other conduct which could reasonably be considered inappropriate

## Enforcement Responsibilities

Community leaders are responsible for clarifying and enforcing our standards
of acceptable behavior.

## Scope

This Code of Conduct applies within all community spaces, and also applies
when an individual is officially representing the community in public spaces.

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the community leaders responsible for enforcement at
{contact_email}.

## Attribution

This Code of Conduct is adapted from the [Contributor Covenant][homepage],
version 2.1.

[homepage]: https://www.contributor-covenant.org
"""

    def generate_contributing(
        self,
        repos: List[Dict[str, Any]],
        options: GenerationOptions
    ) -> Generator[str, None, OperationSummary]:
        """
        Generate CONTRIBUTING.md files for repositories.

        Args:
            repos: List of repository dicts (from query)
            options: Generation options

        Yields:
            Progress messages

        Returns:
            OperationSummary with results
        """
        return (yield from self._generate_files(
            repos, options,
            operation_name="generate_contributing",
            filename="CONTRIBUTING.md",
            file_type="contributing",
            display_name="CONTRIBUTING.md",
            content_fn=lambda repo, name: self._generate_contributing_content(name),
        ))

    def _generate_contributing_content(self, project_name: str) -> str:
        """Generate CONTRIBUTING.md content."""
        return f"""# Contributing to {project_name}

Thank you for your interest in contributing to {project_name}!

## How to Contribute

### Reporting Issues

- Check if the issue already exists
- Include steps to reproduce the problem
- Include expected vs actual behavior

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Write or update tests as needed
5. Ensure tests pass
6. Commit your changes (`git commit -m 'Add your feature'`)
7. Push to your branch (`git push origin feature/your-feature`)
8. Open a Pull Request

### Code Style

- Follow the existing code style
- Add tests for new functionality
- Update documentation as needed

### Development Setup

```bash
git clone <repository-url>
cd {project_name}
# Follow project-specific setup instructions in README
```

## Questions?

Open an issue for any questions about contributing.
"""