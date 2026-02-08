"""
Tests for newly added boilerplate generators and extract_project_metadata.

Tests cover:
- extract_project_metadata() from pypi.py
- BoilerplateService.generate_citation_cff()
- BoilerplateService.generate_zenodo_json()
- BoilerplateService.generate_mkdocs()
- BoilerplateService.generate_gh_pages_workflow()
"""

import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

from repoindex.pypi import extract_project_metadata
from repoindex.services.boilerplate_service import (
    AuthorInfo,
    BoilerplateService,
    GenerationOptions,
)
from repoindex.domain.operation import OperationStatus


# ============================================================================
# extract_project_metadata Tests
# ============================================================================

class TestExtractProjectMetadata:
    """Test pypi.extract_project_metadata()."""

    def test_full_pyproject(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('''
[project]
name = "my-package"
version = "1.2.3"
description = "A great package"
license = "MIT"
keywords = ["python", "cli", "tools"]
authors = [
    {name = "Jane Doe", email = "jane@example.com"},
]

[project.urls]
Homepage = "https://example.com"
Repository = "https://github.com/user/repo"
''')
        result = extract_project_metadata(str(tmp_path))
        assert result['name'] == 'my-package'
        assert result['version'] == '1.2.3'
        assert result['description'] == 'A great package'
        assert result['license'] == 'MIT'
        assert result['keywords'] == ['python', 'cli', 'tools']
        assert len(result['authors']) == 1
        assert result['authors'][0]['name'] == 'Jane Doe'
        assert result['homepage'] == 'https://example.com'
        assert result['repository'] == 'https://github.com/user/repo'

    def test_no_pyproject(self, tmp_path):
        result = extract_project_metadata(str(tmp_path))
        assert result['name'] == ''
        assert result['keywords'] == []

    def test_empty_project_section(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[build-system]\nrequires = ["hatchling"]\n')
        result = extract_project_metadata(str(tmp_path))
        assert result['name'] == ''

    def test_license_as_table(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('''
[project]
name = "pkg"
license = {text = "Apache-2.0"}
''')
        result = extract_project_metadata(str(tmp_path))
        assert result['license'] == 'Apache-2.0'

    def test_license_as_file_ref(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('''
[project]
name = "pkg"
license = {file = "LICENSE"}
''')
        result = extract_project_metadata(str(tmp_path))
        assert result['license'] == 'LICENSE'

    def test_source_code_url(self, tmp_path):
        """The 'Source Code' key is a common URL key."""
        (tmp_path / 'pyproject.toml').write_text('''
[project]
name = "pkg"

[project.urls]
"Source Code" = "https://github.com/user/pkg"
''')
        result = extract_project_metadata(str(tmp_path))
        assert result['repository'] == 'https://github.com/user/pkg'

    def test_malformed_toml(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('this is not valid toml [[[')
        result = extract_project_metadata(str(tmp_path))
        # Should return defaults, not crash
        assert result['name'] == ''

    def test_minimal_project(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "tiny"\n')
        result = extract_project_metadata(str(tmp_path))
        assert result['name'] == 'tiny'
        assert result['version'] == ''
        assert result['keywords'] == []
        assert result['authors'] == []


# ============================================================================
# CITATION.cff Generation Tests
# ============================================================================

class TestGenerateCitationCff:
    """Test BoilerplateService.generate_citation_cff()."""

    def _make_service(self, config=None):
        return BoilerplateService(config=config or {})

    def _make_repo(self, tmp_path, name='myproject', **overrides):
        base = {
            'name': name,
            'path': str(tmp_path),
            'remote_url': 'https://github.com/user/myproject.git',
            'description': 'A test project',
            'license_key': 'MIT',
        }
        base.update(overrides)
        return base

    def test_generates_valid_yaml(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "myproject"\nversion = "0.1.0"\n')
        repo = self._make_repo(tmp_path)
        service = self._make_service()
        author = AuthorInfo(name='Jane Doe', given_names='Jane', family_names='Doe')
        options = GenerationOptions(dry_run=True, author=author)

        messages = list(service.generate_citation_cff([repo], options))
        result = service.last_result
        assert result.total == 1
        assert result.details[0].status == OperationStatus.DRY_RUN

    def test_writes_file(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "myproject"\nversion = "0.1.0"\n')
        repo = self._make_repo(tmp_path)
        service = self._make_service()
        author = AuthorInfo(name='Jane Doe', given_names='Jane', family_names='Doe')
        options = GenerationOptions(dry_run=False, author=author)

        messages = list(service.generate_citation_cff([repo], options))
        result = service.last_result
        assert result.successful == 1

        cff_path = tmp_path / 'CITATION.cff'
        assert cff_path.exists()
        content = yaml.safe_load(cff_path.read_text())
        assert content['cff-version'] == '1.2.0'
        assert content['title'] == 'myproject'
        assert 'authors' in content

    def test_preserves_doi(self, tmp_path):
        """When regenerating with --force, preserves existing DOI."""
        # Create existing CITATION.cff with DOI
        existing = {
            'cff-version': '1.2.0',
            'title': 'myproject',
            'identifiers': [{'type': 'doi', 'value': '10.5281/zenodo.123456'}],
        }
        (tmp_path / 'CITATION.cff').write_text(yaml.dump(existing))

        repo = self._make_repo(tmp_path)
        service = self._make_service()
        options = GenerationOptions(dry_run=False, force=True)

        messages = list(service.generate_citation_cff([repo], options))
        result = service.last_result
        assert result.successful == 1

        content = yaml.safe_load((tmp_path / 'CITATION.cff').read_text())
        assert content.get('identifiers', [{}])[0].get('value') == '10.5281/zenodo.123456'

    def test_skips_existing(self, tmp_path):
        """Without --force, skips repos with existing CITATION.cff."""
        (tmp_path / 'CITATION.cff').write_text('existing content')
        repo = self._make_repo(tmp_path)
        service = self._make_service()
        options = GenerationOptions(dry_run=False, force=False)

        messages = list(service.generate_citation_cff([repo], options))
        result = service.last_result
        assert result.skipped == 1

    def test_includes_keywords(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text(
            '[project]\nname = "myproject"\nkeywords = ["ml", "python"]\n'
        )
        repo = self._make_repo(tmp_path)
        service = self._make_service()
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_citation_cff([repo], options))
        content = yaml.safe_load((tmp_path / 'CITATION.cff').read_text())
        assert content['keywords'] == ['ml', 'python']


# ============================================================================
# .zenodo.json Generation Tests
# ============================================================================

class TestGenerateZenodoJson:
    """Test BoilerplateService.generate_zenodo_json()."""

    def _make_repo(self, tmp_path, name='myproject', **overrides):
        base = {
            'name': name,
            'path': str(tmp_path),
            'remote_url': 'https://github.com/user/myproject.git',
            'description': 'A test project',
            'license_key': 'MIT',
        }
        base.update(overrides)
        return base

    def test_generates_valid_json(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text(
            '[project]\nname = "myproject"\nversion = "1.0.0"\ndescription = "Cool project"\n'
        )
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        author = AuthorInfo(name='Jane Doe', given_names='Jane', family_names='Doe')
        options = GenerationOptions(dry_run=False, author=author)

        messages = list(service.generate_zenodo_json([repo], options))
        result = service.last_result
        assert result.successful == 1

        zenodo_path = tmp_path / '.zenodo.json'
        assert zenodo_path.exists()
        content = json.loads(zenodo_path.read_text())
        assert content['upload_type'] == 'software'
        assert 'creators' in content

    def test_preserves_doi(self, tmp_path):
        """Preserves existing DOI when regenerating with --force."""
        existing = json.dumps({'doi': '10.5281/zenodo.789'})
        (tmp_path / '.zenodo.json').write_text(existing)

        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False, force=True)

        messages = list(service.generate_zenodo_json([repo], options))
        content = json.loads((tmp_path / '.zenodo.json').read_text())
        assert content.get('doi') == '10.5281/zenodo.789'

    def test_includes_related_identifiers(self, tmp_path):
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_zenodo_json([repo], options))
        content = json.loads((tmp_path / '.zenodo.json').read_text())
        assert 'related_identifiers' in content
        assert content['related_identifiers'][0]['relation'] == 'isSupplementTo'

    def test_title_from_name_and_description(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text(
            '[project]\nname = "myproject"\ndescription = "A thing"\n'
        )
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_zenodo_json([repo], options))
        content = json.loads((tmp_path / '.zenodo.json').read_text())
        assert content['title'] == 'myproject: A thing'

    def test_skips_existing(self, tmp_path):
        (tmp_path / '.zenodo.json').write_text('{}')
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False, force=False)

        messages = list(service.generate_zenodo_json([repo], options))
        result = service.last_result
        assert result.skipped == 1


# ============================================================================
# mkdocs.yml Generation Tests
# ============================================================================

class TestGenerateMkdocs:
    """Test BoilerplateService.generate_mkdocs()."""

    def _make_repo(self, tmp_path, name='myproject', **overrides):
        base = {
            'name': name,
            'path': str(tmp_path),
            'remote_url': 'https://github.com/user/myproject.git',
            'description': 'A test project',
        }
        base.update(overrides)
        return base

    def test_generates_valid_yaml(self, tmp_path):
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_mkdocs([repo], options))
        result = service.last_result
        assert result.successful == 1

        mkdocs_path = tmp_path / 'mkdocs.yml'
        assert mkdocs_path.exists()
        content = yaml.safe_load(mkdocs_path.read_text())
        assert content['site_name'] == 'myproject'
        assert content['theme']['name'] == 'material'

    def test_includes_repo_url(self, tmp_path):
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_mkdocs([repo], options))
        content = yaml.safe_load((tmp_path / 'mkdocs.yml').read_text())
        assert 'repo_url' in content
        # Should normalize to HTTPS
        assert content['repo_url'].startswith('https://')

    def test_uses_pyproject_name(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "fancy-name"\n')
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_mkdocs([repo], options))
        content = yaml.safe_load((tmp_path / 'mkdocs.yml').read_text())
        assert content['site_name'] == 'fancy-name'

    def test_nav_from_docs(self, tmp_path):
        """Nav should auto-detect docs/*.md files."""
        docs_dir = tmp_path / 'docs'
        docs_dir.mkdir()
        (docs_dir / 'index.md').write_text('# Home\n')
        (docs_dir / 'getting-started.md').write_text('# Getting Started\n')
        (docs_dir / 'api-reference.md').write_text('# API\n')

        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_mkdocs([repo], options))
        content = yaml.safe_load((tmp_path / 'mkdocs.yml').read_text())
        nav = content['nav']
        assert nav[0] == {'Home': 'index.md'}
        # Other md files should be in nav (not index.md)
        nav_files = [list(entry.values())[0] for entry in nav]
        assert 'api-reference.md' in nav_files
        assert 'getting-started.md' in nav_files

    def test_has_material_extensions(self, tmp_path):
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_mkdocs([repo], options))
        content = yaml.safe_load((tmp_path / 'mkdocs.yml').read_text())
        exts = content['markdown_extensions']
        assert 'pymdownx.highlight' in exts
        assert 'pymdownx.superfences' in exts

    def test_skips_existing(self, tmp_path):
        (tmp_path / 'mkdocs.yml').write_text('site_name: existing\n')
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False, force=False)

        messages = list(service.generate_mkdocs([repo], options))
        result = service.last_result
        assert result.skipped == 1


# ============================================================================
# GitHub Pages Workflow Tests
# ============================================================================

class TestGenerateGhPages:
    """Test BoilerplateService.generate_gh_pages_workflow()."""

    def _make_repo(self, tmp_path, name='myproject'):
        return {
            'name': name,
            'path': str(tmp_path),
            'remote_url': 'https://github.com/user/myproject.git',
        }

    def test_generates_workflow(self, tmp_path):
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_gh_pages_workflow([repo], options))
        result = service.last_result
        assert result.successful == 1

        workflow_path = tmp_path / '.github' / 'workflows' / 'deploy-docs.yml'
        assert workflow_path.exists()
        content = workflow_path.read_text()
        assert 'mkdocs build' in content
        assert 'deploy-pages' in content

    def test_creates_directories(self, tmp_path):
        """Should create .github/workflows/ directories if they don't exist."""
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_gh_pages_workflow([repo], options))
        assert (tmp_path / '.github' / 'workflows').is_dir()

    def test_dry_run(self, tmp_path):
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=True)

        messages = list(service.generate_gh_pages_workflow([repo], options))
        result = service.last_result
        assert result.total == 1
        assert result.details[0].status == OperationStatus.DRY_RUN
        # File should NOT be created in dry-run
        assert not (tmp_path / '.github' / 'workflows' / 'deploy-docs.yml').exists()

    def test_skips_existing(self, tmp_path):
        workflow_dir = tmp_path / '.github' / 'workflows'
        workflow_dir.mkdir(parents=True)
        (workflow_dir / 'deploy-docs.yml').write_text('existing workflow')

        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False, force=False)

        messages = list(service.generate_gh_pages_workflow([repo], options))
        result = service.last_result
        assert result.skipped == 1

    def test_workflow_content(self, tmp_path):
        """Verify workflow has correct triggers and steps."""
        repo = self._make_repo(tmp_path)
        service = BoilerplateService(config={})
        options = GenerationOptions(dry_run=False)

        messages = list(service.generate_gh_pages_workflow([repo], options))
        content = (tmp_path / '.github' / 'workflows' / 'deploy-docs.yml').read_text()
        # Should trigger on push to main/master
        assert 'main' in content
        assert 'master' in content
        # Should install mkdocs-material
        assert 'mkdocs-material' in content
