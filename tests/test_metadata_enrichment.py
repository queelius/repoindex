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
