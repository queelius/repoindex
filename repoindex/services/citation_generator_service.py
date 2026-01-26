"""
Citation generator service for repoindex.

Generates CITATION.cff, codemeta.json, and LICENSE files for repositories.
Used by the `repoindex ops generate` command group.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Any, Generator, List, Optional

from ..config import load_config
from ..domain.operation import (
    OperationStatus,
    OperationSummary,
    FileGenerationResult,
)

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

    def to_cff_dict(self) -> Dict[str, Any]:
        """Convert to CFF author format."""
        result = {}
        # CFF supports both structured names (given-names/family-names)
        # and simple name for entities or when structured isn't available
        if self.family_names:
            result['family-names'] = self.family_names
        if self.given_names:
            result['given-names'] = self.given_names
        # If no structured names, use 'name' field as fallback
        if not self.family_names and not self.given_names and self.name:
            result['name'] = self.name
        if self.email:
            result['email'] = self.email
        if self.orcid:
            # CFF expects full ORCID URL
            orcid = self.orcid
            if not orcid.startswith('https://'):
                orcid = f'https://orcid.org/{orcid}'
            result['orcid'] = orcid
        if self.affiliation:
            result['affiliation'] = self.affiliation
        return result

    def to_codemeta_dict(self) -> Dict[str, Any]:
        """Convert to codemeta.json Person format."""
        result = {
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


@dataclass
class GenerationOptions:
    """Options for file generation."""
    dry_run: bool = False
    force: bool = False  # Overwrite existing files
    author: Optional[AuthorInfo] = None
    license: Optional[str] = None  # SPDX identifier


class CitationGeneratorService:
    """
    Service for generating citation and metadata files.

    Generates CITATION.cff, codemeta.json, and LICENSE files
    based on repository metadata and configuration.

    Example:
        service = CitationGeneratorService()
        options = GenerationOptions(dry_run=True)

        for progress in service.generate_citation(repos, options):
            print(progress)

        result = service.last_result
        print(f"Generated {result.successful} files")
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize CitationGeneratorService.

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

    def generate_citation(
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
        result = OperationSummary(operation="generate_citation", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to process"
            return result

        # Get author from options or config
        author = options.author or AuthorInfo.from_config(self.config)

        for repo in repos:
            path = repo.get('path', '')
            name = repo.get('name', path)

            if not path:
                continue

            repo_path = Path(path)
            citation_file = repo_path / 'CITATION.cff'

            # Check if file exists
            if citation_file.exists() and not options.force:
                yield f"Skipping {name} (CITATION.cff exists, use --force to overwrite)"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="File exists",
                    file_type="citation",
                )
                result.add_detail(detail)
                continue

            # Generate content
            try:
                content = self._generate_cff_content(repo, author, options.license)

                if options.dry_run:
                    yield f"Would generate CITATION.cff for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.DRY_RUN,
                        action="would_generate",
                        file_path=str(citation_file),
                        file_type="citation",
                    )
                else:
                    citation_file.write_text(content)
                    yield f"Generated CITATION.cff for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="generated",
                        file_path=str(citation_file),
                        file_type="citation",
                        overwritten=citation_file.exists(),
                    )

                result.add_detail(detail)

            except Exception as e:
                logger.error(f"Failed to generate citation for {name}: {e}")
                yield f"Error generating CITATION.cff for {name}: {e}"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.FAILED,
                    action="generation_failed",
                    error=str(e),
                    file_type="citation",
                )
                result.add_detail(detail)

        return result

    def _generate_cff_content(
        self,
        repo: Dict[str, Any],
        author: Optional[AuthorInfo],
        license_id: Optional[str]
    ) -> str:
        """Generate CITATION.cff content."""
        name = repo.get('name', 'Unknown')
        description = repo.get('description') or repo.get('github_description', '')
        remote_url = repo.get('remote_url', '')
        version = repo.get('version') or repo.get('pypi_version', '')

        # Detect license from repo or use provided
        repo_license = license_id or repo.get('license') or repo.get('license_key', '')

        lines = [
            'cff-version: 1.2.0',
            f'title: "{name}"',
            'type: software',
        ]

        if description:
            # Escape quotes in description
            desc_escaped = description.replace('"', '\\"')
            lines.append('message: "If you use this software, please cite it as below."')
            lines.append(f'abstract: "{desc_escaped}"')

        # Authors section
        lines.append('authors:')
        if author:
            author_dict = author.to_cff_dict()
            first = True
            for key, value in author_dict.items():
                prefix = '  - ' if first else '    '
                lines.append(f'{prefix}{key}: "{value}"')
                first = False
        else:
            lines.append('  - name: "Author Name"')

        # Repository URL
        if remote_url:
            # Convert SSH to HTTPS for display
            display_url = remote_url
            if display_url.startswith('git@github.com:'):
                display_url = display_url.replace('git@github.com:', 'https://github.com/')
            if display_url.endswith('.git'):
                display_url = display_url[:-4]
            lines.append(f'repository-code: "{display_url}"')

        # License
        if repo_license:
            license_upper = repo_license.upper()
            # Map common names to SPDX
            spdx_map = {
                'MIT': 'MIT',
                'APACHE-2.0': 'Apache-2.0',
                'GPL-3.0': 'GPL-3.0-only',
                'BSD-3-CLAUSE': 'BSD-3-Clause',
                'MPL-2.0': 'MPL-2.0',
            }
            spdx = spdx_map.get(license_upper, repo_license)
            lines.append(f'license: {spdx}')

        # Version
        if version:
            lines.append(f'version: "{version}"')

        # Date
        lines.append(f'date-released: "{date.today().isoformat()}"')

        return '\n'.join(lines) + '\n'

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
        result = OperationSummary(operation="generate_codemeta", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to process"
            return result

        author = options.author or AuthorInfo.from_config(self.config)

        for repo in repos:
            path = repo.get('path', '')
            name = repo.get('name', path)

            if not path:
                continue

            repo_path = Path(path)
            codemeta_file = repo_path / 'codemeta.json'

            if codemeta_file.exists() and not options.force:
                yield f"Skipping {name} (codemeta.json exists, use --force to overwrite)"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="File exists",
                    file_type="codemeta",
                )
                result.add_detail(detail)
                continue

            try:
                content = self._generate_codemeta_content(repo, author, options.license)

                if options.dry_run:
                    yield f"Would generate codemeta.json for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.DRY_RUN,
                        action="would_generate",
                        file_path=str(codemeta_file),
                        file_type="codemeta",
                    )
                else:
                    codemeta_file.write_text(content)
                    yield f"Generated codemeta.json for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="generated",
                        file_path=str(codemeta_file),
                        file_type="codemeta",
                        overwritten=codemeta_file.exists(),
                    )

                result.add_detail(detail)

            except Exception as e:
                logger.error(f"Failed to generate codemeta for {name}: {e}")
                yield f"Error generating codemeta.json for {name}: {e}"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.FAILED,
                    action="generation_failed",
                    error=str(e),
                    file_type="codemeta",
                )
                result.add_detail(detail)

        return result

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
        result = OperationSummary(operation="generate_license", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to process"
            return result

        license_key = license_type.lower()
        if license_key not in LICENSES:
            yield f"Unknown license type: {license_type}"
            yield f"Supported: {', '.join(LICENSES.keys())}"
            return result

        author = options.author or AuthorInfo.from_config(self.config)
        author_name = author.name if author else "Author"

        for repo in repos:
            path = repo.get('path', '')
            name = repo.get('name', path)

            if not path:
                continue

            repo_path = Path(path)
            license_file = repo_path / 'LICENSE'

            if license_file.exists() and not options.force:
                yield f"Skipping {name} (LICENSE exists, use --force to overwrite)"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="File exists",
                    file_type="license",
                )
                result.add_detail(detail)
                continue

            try:
                content = self._generate_license_content(license_key, author_name)

                if options.dry_run:
                    yield f"Would generate LICENSE ({license_type}) for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.DRY_RUN,
                        action="would_generate",
                        file_path=str(license_file),
                        file_type="license",
                    )
                else:
                    license_file.write_text(content)
                    yield f"Generated LICENSE ({license_type}) for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="generated",
                        file_path=str(license_file),
                        file_type="license",
                        overwritten=license_file.exists(),
                    )

                result.add_detail(detail)

            except Exception as e:
                logger.error(f"Failed to generate license for {name}: {e}")
                yield f"Error generating LICENSE for {name}: {e}"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.FAILED,
                    action="generation_failed",
                    error=str(e),
                    file_type="license",
                )
                result.add_detail(detail)

        return result

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
