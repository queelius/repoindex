"""Tests for local metadata extraction during refresh."""
import json
import pytest
from pathlib import Path


class TestKeywordExtraction:
    def test_pyproject_keywords(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nkeywords = ["cli", "git"]\n'
        )
        assert _extract_keywords(tmp_path) == ["cli", "git"]

    def test_package_json_keywords(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "package.json").write_text(json.dumps(
            {"name": "pkg", "keywords": ["nodejs", "api"]}
        ))
        assert _extract_keywords(tmp_path) == ["nodejs", "api"]

    def test_cargo_toml_keywords(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "pkg"\nkeywords = ["cli", "rust"]\n'
        )
        assert _extract_keywords(tmp_path) == ["cli", "rust"]

    def test_no_project_files(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        assert _extract_keywords(tmp_path) is None

    def test_pyproject_no_keywords(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "pkg"\n')
        assert _extract_keywords(tmp_path) is None

    def test_priority_pyproject_over_package_json(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nkeywords = ["python"]\n'
        )
        (tmp_path / "package.json").write_text(json.dumps(
            {"name": "pkg", "keywords": ["node"]}
        ))
        assert _extract_keywords(tmp_path) == ["python"]

    def test_priority_pyproject_over_cargo(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nkeywords = ["python"]\n'
        )
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "pkg"\nkeywords = ["rust"]\n'
        )
        assert _extract_keywords(tmp_path) == ["python"]

    def test_priority_cargo_over_package_json(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "pkg"\nkeywords = ["rust"]\n'
        )
        (tmp_path / "package.json").write_text(json.dumps(
            {"name": "pkg", "keywords": ["node"]}
        ))
        assert _extract_keywords(tmp_path) == ["rust"]

    def test_corrupt_toml_skipped(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text("not valid toml {{{")
        assert _extract_keywords(tmp_path) is None

    def test_corrupt_json_skipped(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "package.json").write_text("not valid json {{{")
        assert _extract_keywords(tmp_path) is None

    def test_empty_keywords_returns_none(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nkeywords = []\n'
        )
        assert _extract_keywords(tmp_path) is None

    def test_fallthrough_to_package_json_when_pyproject_has_no_keywords(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "pkg"\n')
        (tmp_path / "package.json").write_text(json.dumps(
            {"name": "pkg", "keywords": ["node"]}
        ))
        assert _extract_keywords(tmp_path) == ["node"]

    def test_fallthrough_corrupt_pyproject_to_cargo(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text("bad {{{")
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "pkg"\nkeywords = ["rust"]\n'
        )
        assert _extract_keywords(tmp_path) == ["rust"]

    def test_string_path_accepted(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nkeywords = ["cli"]\n'
        )
        assert _extract_keywords(str(tmp_path)) == ["cli"]

    def test_keywords_not_a_list_ignored(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pkg"\nkeywords = "not-a-list"\n'
        )
        assert _extract_keywords(tmp_path) is None


class TestLocalAssetDetection:
    def test_codemeta_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "codemeta.json").write_text("{}")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_codemeta'] is True

    def test_funding_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "FUNDING.yml").write_text("github: user")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_funding'] is True

    def test_contributors_md_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "CONTRIBUTORS.md").write_text("# Contributors")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_contributors'] is True

    def test_authors_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "AUTHORS").write_text("Alex Towell")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_contributors'] is True

    def test_changelog_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "CHANGELOG.md").write_text("# Changes")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_changelog'] is True

    def test_news_md_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "NEWS.md").write_text("# News")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_changelog'] is True

    def test_no_assets(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        assets = _detect_local_assets(tmp_path)
        assert not any(assets.values())

    def test_all_assets(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "codemeta.json").write_text("{}")
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "FUNDING.yml").write_text("github: user")
        (tmp_path / "AUTHORS.md").write_text("Authors")
        (tmp_path / "CHANGES.md").write_text("Changes")
        assets = _detect_local_assets(tmp_path)
        assert all(assets.values())

    def test_contributors_plain_file(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "CONTRIBUTORS").write_text("Alice\nBob")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_contributors'] is True

    def test_authors_md_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "AUTHORS.md").write_text("# Authors")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_contributors'] is True

    def test_changes_md_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "CHANGES.md").write_text("# Changes")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_changelog'] is True

    def test_history_md_detected(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "HISTORY.md").write_text("# History")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_changelog'] is True

    def test_changelog_plain_file(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "CHANGELOG").write_text("v1.0 - Initial release")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_changelog'] is True

    def test_changes_plain_file(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "CHANGES").write_text("v1.0 - Initial release")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_changelog'] is True

    def test_string_path_accepted(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        (tmp_path / "codemeta.json").write_text("{}")
        assets = _detect_local_assets(str(tmp_path))
        assert assets['has_codemeta'] is True

    def test_returns_exactly_four_keys(self, tmp_path):
        from repoindex.services.repository_service import _detect_local_assets
        assets = _detect_local_assets(tmp_path)
        assert set(assets.keys()) == {'has_codemeta', 'has_funding', 'has_contributors', 'has_changelog'}
