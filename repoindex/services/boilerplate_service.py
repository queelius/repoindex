"""
Boilerplate file generator service for repoindex.

Generates boilerplate files: LICENSE, codemeta.json, .gitignore,
CODE_OF_CONDUCT.md, and CONTRIBUTING.md for repositories.
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
        result = OperationSummary(operation="generate_gitignore", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to process"
            return result

        lang_key = language.lower()
        if lang_key not in GITIGNORE_TEMPLATES:
            yield f"Unknown language: {language}"
            yield f"Supported: {', '.join(GITIGNORE_TEMPLATES.keys())}"
            return result

        template = GITIGNORE_TEMPLATES[lang_key]

        for repo in repos:
            path = repo.get('path', '')
            name = repo.get('name', path)

            if not path:
                continue

            repo_path = Path(path)
            gitignore_file = repo_path / '.gitignore'

            if gitignore_file.exists() and not options.force:
                yield f"Skipping {name} (.gitignore exists, use --force to overwrite)"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="File exists",
                    file_type="gitignore",
                )
                result.add_detail(detail)
                continue

            try:
                if options.dry_run:
                    yield f"Would generate .gitignore ({language}) for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.DRY_RUN,
                        action="would_generate",
                        file_path=str(gitignore_file),
                        file_type="gitignore",
                    )
                else:
                    gitignore_file.write_text(template)
                    yield f"Generated .gitignore ({language}) for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="generated",
                        file_path=str(gitignore_file),
                        file_type="gitignore",
                        overwritten=gitignore_file.exists(),
                    )

                result.add_detail(detail)

            except Exception as e:
                logger.error(f"Failed to generate .gitignore for {name}: {e}")
                yield f"Error generating .gitignore for {name}: {e}"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.FAILED,
                    action="generation_failed",
                    error=str(e),
                    file_type="gitignore",
                )
                result.add_detail(detail)

        return result

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
        result = OperationSummary(operation="generate_code_of_conduct", dry_run=options.dry_run)
        self.last_result = result

        if not repos:
            yield "No repositories to process"
            return result

        author = options.author or AuthorInfo.from_config(self.config)
        contact_email = author.email if author else "maintainer@example.com"

        for repo in repos:
            path = repo.get('path', '')
            name = repo.get('name', path)

            if not path:
                continue

            repo_path = Path(path)
            coc_file = repo_path / 'CODE_OF_CONDUCT.md'

            if coc_file.exists() and not options.force:
                yield f"Skipping {name} (CODE_OF_CONDUCT.md exists, use --force to overwrite)"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="File exists",
                    file_type="code_of_conduct",
                )
                result.add_detail(detail)
                continue

            try:
                content = self._generate_code_of_conduct_content(contact_email)

                if options.dry_run:
                    yield f"Would generate CODE_OF_CONDUCT.md for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.DRY_RUN,
                        action="would_generate",
                        file_path=str(coc_file),
                        file_type="code_of_conduct",
                    )
                else:
                    coc_file.write_text(content)
                    yield f"Generated CODE_OF_CONDUCT.md for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="generated",
                        file_path=str(coc_file),
                        file_type="code_of_conduct",
                        overwritten=coc_file.exists(),
                    )

                result.add_detail(detail)

            except Exception as e:
                logger.error(f"Failed to generate CODE_OF_CONDUCT.md for {name}: {e}")
                yield f"Error generating CODE_OF_CONDUCT.md for {name}: {e}"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.FAILED,
                    action="generation_failed",
                    error=str(e),
                    file_type="code_of_conduct",
                )
                result.add_detail(detail)

        return result

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
        result = OperationSummary(operation="generate_contributing", dry_run=options.dry_run)
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
            contributing_file = repo_path / 'CONTRIBUTING.md'

            if contributing_file.exists() and not options.force:
                yield f"Skipping {name} (CONTRIBUTING.md exists, use --force to overwrite)"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.SKIPPED,
                    action="skipped",
                    message="File exists",
                    file_type="contributing",
                )
                result.add_detail(detail)
                continue

            try:
                content = self._generate_contributing_content(name)

                if options.dry_run:
                    yield f"Would generate CONTRIBUTING.md for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.DRY_RUN,
                        action="would_generate",
                        file_path=str(contributing_file),
                        file_type="contributing",
                    )
                else:
                    contributing_file.write_text(content)
                    yield f"Generated CONTRIBUTING.md for {name}"
                    detail = FileGenerationResult(
                        repo_path=path,
                        repo_name=name,
                        status=OperationStatus.SUCCESS,
                        action="generated",
                        file_path=str(contributing_file),
                        file_type="contributing",
                        overwritten=contributing_file.exists(),
                    )

                result.add_detail(detail)

            except Exception as e:
                logger.error(f"Failed to generate CONTRIBUTING.md for {name}: {e}")
                yield f"Error generating CONTRIBUTING.md for {name}: {e}"
                detail = FileGenerationResult(
                    repo_path=path,
                    repo_name=name,
                    status=OperationStatus.FAILED,
                    action="generation_failed",
                    error=str(e),
                    file_type="contributing",
                )
                result.add_detail(detail)

        return result

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