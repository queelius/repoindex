"""Tests for local file metadata sources."""
import json
import pytest
from pathlib import Path


class TestCitationCffSource:
    def test_detect_with_file(self, tmp_path):
        from repoindex.sources.citation_cff import source
        (tmp_path / 'CITATION.cff').write_text('title: Test\n')
        assert source.detect(str(tmp_path))

    def test_detect_without_file(self, tmp_path):
        from repoindex.sources.citation_cff import source
        assert not source.detect(str(tmp_path))

    def test_fetch_parses_fields(self, tmp_path):
        from repoindex.sources.citation_cff import source
        (tmp_path / 'CITATION.cff').write_text(
            'title: My Package\n'
            'doi: 10.5281/zenodo.12345\n'
            'version: 1.0.0\n'
            'license: MIT\n'
            'repository-code: https://github.com/user/repo\n'
            'authors:\n'
            '  - given-names: Alice\n'
            '    family-names: Smith\n'
        )
        result = source.fetch(str(tmp_path))
        assert result['citation_title'] == 'My Package'
        assert result['citation_doi'] == '10.5281/zenodo.12345'
        assert result['citation_version'] == '1.0.0'
        assert result['citation_license'] == 'MIT'
        assert result['citation_repository'] == 'https://github.com/user/repo'
        authors = json.loads(result['citation_authors'])
        assert authors[0]['given-names'] == 'Alice'
        assert result['has_citation'] == 1

    def test_fetch_missing_file(self, tmp_path):
        from repoindex.sources.citation_cff import source
        result = source.fetch(str(tmp_path))
        assert result is None

    def test_fetch_minimal_file(self, tmp_path):
        from repoindex.sources.citation_cff import source
        (tmp_path / 'CITATION.cff').write_text('title: Minimal\n')
        result = source.fetch(str(tmp_path))
        assert result['citation_title'] == 'Minimal'
        assert result['has_citation'] == 1
        assert 'citation_doi' not in result

    def test_fetch_corrupt_yaml(self, tmp_path):
        from repoindex.sources.citation_cff import source
        (tmp_path / 'CITATION.cff').write_text('{not: [valid yaml')
        result = source.fetch(str(tmp_path))
        # File exists but parse failed -- should still flag has_citation
        assert result['has_citation'] == 1

    def test_fetch_non_dict_yaml(self, tmp_path):
        from repoindex.sources.citation_cff import source
        (tmp_path / 'CITATION.cff').write_text('- just\n- a\n- list\n')
        result = source.fetch(str(tmp_path))
        # yaml.safe_load returns a list, not dict -- file exists but
        # unparseable as expected, consistent with exception path
        assert result == {'has_citation': 1}

    def test_fetch_non_dict_scalar(self, tmp_path):
        """Scalar YAML (e.g., just a string) should also flag has_citation."""
        from repoindex.sources.citation_cff import source
        (tmp_path / 'CITATION.cff').write_text('just a string\n')
        result = source.fetch(str(tmp_path))
        assert result == {'has_citation': 1}

    def test_fetch_float_version_warns(self, tmp_path, caplog):
        """Float version (unquoted 1.10 -> 1.1) should log a warning."""
        import logging
        from repoindex.sources.citation_cff import source
        # YAML will parse 1.10 as float 1.1, losing precision
        (tmp_path / 'CITATION.cff').write_text('title: T\nversion: 1.10\n')
        with caplog.at_level(logging.WARNING):
            result = source.fetch(str(tmp_path))
        assert result['citation_version'] == '1.1'  # precision lost
        # Warning should have been emitted
        assert any(
            'CITATION.cff' in rec.message and 'version' in rec.message.lower()
            for rec in caplog.records
        )

    def test_fetch_quoted_version_no_warn(self, tmp_path, caplog):
        """Quoted version string should not emit a warning."""
        import logging
        from repoindex.sources.citation_cff import source
        (tmp_path / 'CITATION.cff').write_text('title: T\nversion: "1.10"\n')
        with caplog.at_level(logging.WARNING):
            result = source.fetch(str(tmp_path))
        assert result['citation_version'] == '1.10'  # precision preserved
        # No warning expected
        assert not any(
            'version' in rec.message.lower() and 'precision' in rec.message.lower()
            for rec in caplog.records
        )

    def test_fetch_version_coerced_to_string(self, tmp_path):
        from repoindex.sources.citation_cff import source
        (tmp_path / 'CITATION.cff').write_text('title: T\nversion: 2\n')
        result = source.fetch(str(tmp_path))
        assert result['citation_version'] == '2'
        assert isinstance(result['citation_version'], str)

    def test_source_attributes(self):
        from repoindex.sources.citation_cff import source
        assert source.source_id == 'citation_cff'
        assert source.name == 'CITATION.cff'
        assert source.target == 'repos'
        assert source.batch is False

    def test_discovered_by_discover_sources(self):
        from repoindex.sources import discover_sources
        sources = discover_sources()
        ids = [s.source_id for s in sources]
        assert 'citation_cff' in ids


class TestKeywordsSource:
    def test_detect_pyproject(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n')
        assert source.detect(str(tmp_path))

    def test_detect_cargo(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'Cargo.toml').write_text('[package]\nname = "x"\n')
        assert source.detect(str(tmp_path))

    def test_detect_package_json(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'package.json').write_text('{"name": "x"}')
        assert source.detect(str(tmp_path))

    def test_detect_nothing(self, tmp_path):
        from repoindex.sources.keywords import source
        assert not source.detect(str(tmp_path))

    def test_fetch_pyproject_keywords(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'pyproject.toml').write_text(
            '[project]\nname = "pkg"\nkeywords = ["cli", "git"]\n'
        )
        result = source.fetch(str(tmp_path))
        assert json.loads(result['keywords']) == ['cli', 'git']

    def test_fetch_cargo_keywords(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'Cargo.toml').write_text(
            '[package]\nname = "pkg"\nkeywords = ["rust", "wasm"]\n'
        )
        result = source.fetch(str(tmp_path))
        assert json.loads(result['keywords']) == ['rust', 'wasm']

    def test_fetch_package_json_keywords(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'package.json').write_text(
            '{"name": "pkg", "keywords": ["js", "node"]}'
        )
        result = source.fetch(str(tmp_path))
        assert json.loads(result['keywords']) == ['js', 'node']

    def test_fetch_pyproject_priority_over_cargo(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'pyproject.toml').write_text(
            '[project]\nname = "pkg"\nkeywords = ["python"]\n'
        )
        (tmp_path / 'Cargo.toml').write_text(
            '[package]\nname = "pkg"\nkeywords = ["rust"]\n'
        )
        result = source.fetch(str(tmp_path))
        assert json.loads(result['keywords']) == ['python']

    def test_fetch_no_keywords_in_pyproject(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "pkg"\n')
        result = source.fetch(str(tmp_path))
        assert result is None

    def test_fetch_no_files(self, tmp_path):
        from repoindex.sources.keywords import source
        result = source.fetch(str(tmp_path))
        assert result is None

    def test_fetch_empty_keywords_list(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'pyproject.toml').write_text(
            '[project]\nname = "pkg"\nkeywords = []\n'
        )
        result = source.fetch(str(tmp_path))
        assert result is None

    def test_fetch_corrupt_toml(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'pyproject.toml').write_text('this is not valid toml [[[')
        result = source.fetch(str(tmp_path))
        assert result is None

    def test_fetch_corrupt_json(self, tmp_path):
        from repoindex.sources.keywords import source
        (tmp_path / 'package.json').write_text('{bad json')
        result = source.fetch(str(tmp_path))
        assert result is None

    def test_source_attributes(self):
        from repoindex.sources.keywords import source
        assert source.source_id == 'keywords'
        assert source.name == 'Project Keywords'
        assert source.target == 'repos'

    def test_discovered_by_discover_sources(self):
        from repoindex.sources import discover_sources
        sources = discover_sources()
        ids = [s.source_id for s in sources]
        assert 'keywords' in ids


class TestLocalAssetsSource:
    def test_detect_always_true(self, tmp_path):
        from repoindex.sources.local_assets import source
        assert source.detect(str(tmp_path))

    def test_fetch_codemeta(self, tmp_path):
        from repoindex.sources.local_assets import source
        (tmp_path / 'codemeta.json').write_text('{}')
        result = source.fetch(str(tmp_path))
        assert result['has_codemeta'] == 1

    def test_fetch_funding(self, tmp_path):
        from repoindex.sources.local_assets import source
        (tmp_path / '.github').mkdir()
        (tmp_path / '.github' / 'FUNDING.yml').write_text('github: user')
        result = source.fetch(str(tmp_path))
        assert result['has_funding'] == 1

    def test_fetch_contributors(self, tmp_path):
        from repoindex.sources.local_assets import source
        (tmp_path / 'CONTRIBUTORS').write_text('Alice\n')
        result = source.fetch(str(tmp_path))
        assert result['has_contributors'] == 1

    def test_fetch_contributors_md(self, tmp_path):
        from repoindex.sources.local_assets import source
        (tmp_path / 'AUTHORS.md').write_text('# Authors\n')
        result = source.fetch(str(tmp_path))
        assert result['has_contributors'] == 1

    def test_fetch_changelog(self, tmp_path):
        from repoindex.sources.local_assets import source
        (tmp_path / 'CHANGELOG.md').write_text('# Changes')
        result = source.fetch(str(tmp_path))
        assert result['has_changelog'] == 1

    def test_fetch_changes_variant(self, tmp_path):
        from repoindex.sources.local_assets import source
        (tmp_path / 'CHANGES').write_text('changes')
        result = source.fetch(str(tmp_path))
        assert result['has_changelog'] == 1

    def test_fetch_news_variant(self, tmp_path):
        from repoindex.sources.local_assets import source
        (tmp_path / 'NEWS.md').write_text('news')
        result = source.fetch(str(tmp_path))
        assert result['has_changelog'] == 1

    def test_fetch_nothing(self, tmp_path):
        from repoindex.sources.local_assets import source
        result = source.fetch(str(tmp_path))
        assert result is None

    def test_fetch_all_assets(self, tmp_path):
        from repoindex.sources.local_assets import source
        (tmp_path / 'codemeta.json').write_text('{}')
        (tmp_path / '.github').mkdir()
        (tmp_path / '.github' / 'FUNDING.yml').write_text('github: user')
        (tmp_path / 'AUTHORS.md').write_text('# Authors')
        (tmp_path / 'CHANGES.md').write_text('# Changes')
        result = source.fetch(str(tmp_path))
        assert result['has_codemeta'] == 1
        assert result['has_funding'] == 1
        assert result['has_contributors'] == 1
        assert result['has_changelog'] == 1

    def test_source_attributes(self):
        from repoindex.sources.local_assets import source
        assert source.source_id == 'local_assets'
        assert source.name == 'Local Asset Files'
        assert source.target == 'repos'

    def test_discovered_by_discover_sources(self):
        from repoindex.sources import discover_sources
        sources = discover_sources()
        ids = [s.source_id for s in sources]
        assert 'local_assets' in ids
