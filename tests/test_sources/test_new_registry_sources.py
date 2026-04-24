"""Tests for the npm, cargo, conda, docker, rubygems, and go metadata sources."""

import json
from unittest.mock import patch, MagicMock

import pytest

from repoindex.sources.npm import NpmSource
from repoindex.sources.cargo import CargoSource
from repoindex.sources.conda import CondaSource
from repoindex.sources.docker import DockerSource
from repoindex.sources.rubygems import RubyGemsSource
from repoindex.sources.go import GoSource, _encode_module_path


# ============================================================================
# npm
# ============================================================================

class TestNpmDetect:
    def test_detect_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "@scope/my-lib",
            "version": "1.0.0",
        }))
        s = NpmSource()
        assert s.detect(str(tmp_path)) is True
        assert s._detect_name(str(tmp_path)) == "@scope/my-lib"

    def test_detect_private_package(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "private-app",
            "private": True,
        }))
        s = NpmSource()
        assert s.detect(str(tmp_path)) is False

    def test_detect_no_package_json(self, tmp_path):
        s = NpmSource()
        assert s.detect(str(tmp_path)) is False

    def test_detect_invalid_json(self, tmp_path):
        (tmp_path / "package.json").write_text("not json")
        s = NpmSource()
        assert s.detect(str(tmp_path)) is False

    def test_detect_missing_name(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"version": "1.0.0"}))
        s = NpmSource()
        assert s.detect(str(tmp_path)) is False


class TestNpmCheck:
    @patch('repoindex.sources.npm.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"dist-tags": {"latest": "2.0.0"}},
        )
        s = NpmSource()
        result = s.check("my-lib")
        assert result.published is True
        assert result.version == "2.0.0"
        assert result.registry == "npm"

    @patch('repoindex.sources.npm.requests.get')
    def test_check_not_found(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        s = NpmSource()
        result = s.check("nonexistent")
        assert result.published is False

    @patch('repoindex.sources.npm.requests.get')
    def test_check_network_error(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        s = NpmSource()
        assert s.check("broken") is None


class TestNpmSourceAttributes:
    def test_attributes(self):
        s = NpmSource()
        assert s.source_id == "npm"
        assert s.target == "publications"
        assert s.batch is False


# ============================================================================
# Cargo
# ============================================================================

class TestCargoDetect:
    def test_detect_cargo_toml(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('''
[package]
name = "my-crate"
version = "0.1.0"
edition = "2021"
''')
        s = CargoSource()
        assert s._detect_name(str(tmp_path)) == "my-crate"

    def test_detect_no_cargo_toml(self, tmp_path):
        s = CargoSource()
        assert s.detect(str(tmp_path)) is False

    def test_detect_workspace_without_name(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('''
[workspace]
members = ["crate-a", "crate-b"]
''')
        s = CargoSource()
        assert s.detect(str(tmp_path)) is False


class TestCargoCheck:
    @patch('repoindex.sources.cargo.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"crate": {"max_version": "0.5.0", "downloads": 1000}},
        )
        s = CargoSource()
        result = s.check("my-crate")
        assert result.published is True
        assert result.version == "0.5.0"
        assert result.downloads == 1000

    @patch('repoindex.sources.cargo.requests.get')
    def test_check_with_user_agent(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        s = CargoSource()
        s.check("test")
        # Verify User-Agent was set
        call_kwargs = mock_get.call_args
        assert 'repoindex' in call_kwargs.kwargs.get('headers', {}).get('User-Agent', '')


class TestCargoSourceAttributes:
    def test_attributes(self):
        s = CargoSource()
        assert s.source_id == "cargo"
        assert s.target == "publications"


# ============================================================================
# Conda
# ============================================================================

class TestCondaDetect:
    def test_detect_recipe_meta_yaml(self, tmp_path):
        recipe = tmp_path / "recipe"
        recipe.mkdir()
        (recipe / "meta.yaml").write_text('''
{% set name = "my-conda-pkg" %}
{% set version = "1.0.0" %}

package:
  name: {{ name }}
  version: {{ version }}
''')
        s = CondaSource()
        assert s._detect_name(str(tmp_path)) == "my-conda-pkg"

    def test_detect_root_meta_yaml(self, tmp_path):
        (tmp_path / "meta.yaml").write_text('''
package:
  name: simple-pkg
  version: 0.1
''')
        s = CondaSource()
        assert s._detect_name(str(tmp_path)) == "simple-pkg"

    def test_detect_no_meta_yaml(self, tmp_path):
        s = CondaSource()
        assert s.detect(str(tmp_path)) is False


class TestCondaCheck:
    @patch('repoindex.sources.conda.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"latest_version": "2.3.0"},
        )
        s = CondaSource()
        result = s.check("my-conda-pkg")
        assert result.published is True
        assert result.version == "2.3.0"
        assert result.registry == "conda"


class TestCondaSourceAttributes:
    def test_attributes(self):
        s = CondaSource()
        assert s.source_id == "conda"
        assert s.target == "publications"


# ============================================================================
# Docker
# ============================================================================

class TestDockerDetect:
    def test_detect_dockerfile(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
        s = DockerSource()
        result = s._detect_name(str(tmp_path), repo_record={'owner': 'myuser'})
        assert result == "myuser/{}".format(tmp_path.name)

    def test_detect_dockerfile_without_owner(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        s = DockerSource()
        result = s._detect_name(str(tmp_path))
        assert result == tmp_path.name

    def test_detect_no_dockerfile(self, tmp_path):
        s = DockerSource()
        assert s.detect(str(tmp_path)) is False


class TestDockerCheck:
    @patch('repoindex.sources.docker.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"pull_count": 5000, "last_updated": "2025-01-01T00:00:00Z"},
        )
        s = DockerSource()
        result = s.check("myuser/myapp")
        assert result.published is True
        assert result.downloads == 5000

    @patch('repoindex.sources.docker.requests.get')
    def test_check_library_image(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        s = DockerSource()
        result = s.check("myapp")  # No slash = library image
        assert result.published is False


class TestDockerSourceAttributes:
    def test_attributes(self):
        s = DockerSource()
        assert s.source_id == "docker"
        assert s.target == "publications"


# ============================================================================
# RubyGems
# ============================================================================

class TestRubyGemsDetect:
    def test_detect_gemspec(self, tmp_path):
        (tmp_path / "my-gem.gemspec").write_text('''
Gem::Specification.new do |s|
  s.name = "my-gem"
  s.version = "1.0.0"
end
''')
        s = RubyGemsSource()
        assert s._detect_name(str(tmp_path)) == "my-gem"

    def test_detect_gemspec_single_quotes(self, tmp_path):
        (tmp_path / "test.gemspec").write_text("spec.name = 'quoted-gem'")
        s = RubyGemsSource()
        assert s._detect_name(str(tmp_path)) == "quoted-gem"

    def test_detect_no_gemspec(self, tmp_path):
        s = RubyGemsSource()
        assert s.detect(str(tmp_path)) is False

    def test_detect_fallback_to_filename(self, tmp_path):
        (tmp_path / "fallback.gemspec").write_text("# empty gemspec\n")
        s = RubyGemsSource()
        assert s._detect_name(str(tmp_path)) == "fallback"


class TestRubyGemsCheck:
    @patch('repoindex.sources.rubygems.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"version": "3.0.0", "downloads": 50000},
        )
        s = RubyGemsSource()
        result = s.check("my-gem")
        assert result.published is True
        assert result.version == "3.0.0"
        assert result.downloads == 50000


class TestRubyGemsSourceAttributes:
    def test_attributes(self):
        s = RubyGemsSource()
        assert s.source_id == "rubygems"
        assert s.target == "publications"


# ============================================================================
# Go
# ============================================================================

class TestGoModulePathEncoding:
    def test_lowercase_unchanged(self):
        assert _encode_module_path("github.com/user/repo") == "github.com/user/repo"

    def test_uppercase_encoded(self):
        assert _encode_module_path("github.com/Azure/go-sdk") == "github.com/!azure/go-sdk"

    def test_multiple_uppercase(self):
        assert _encode_module_path("GitHub.com") == "!git!hub.com"


class TestGoDetect:
    def test_detect_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module github.com/user/mymod\n\ngo 1.21\n")
        s = GoSource()
        assert s._detect_name(str(tmp_path)) == "github.com/user/mymod"

    def test_detect_no_go_mod(self, tmp_path):
        s = GoSource()
        assert s.detect(str(tmp_path)) is False


class TestGoCheck:
    @patch('repoindex.sources.go.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"Version": "v1.5.0"},
        )
        s = GoSource()
        result = s.check("github.com/user/mymod")
        assert result.published is True
        assert result.version == "v1.5.0"
        assert result.registry == "go"
        # Verify the URL was encoded for the proxy
        called_url = mock_get.call_args[0][0]
        assert "proxy.golang.org" in called_url

    @patch('repoindex.sources.go.requests.get')
    def test_check_not_found(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        s = GoSource()
        result = s.check("github.com/user/nonexistent")
        assert result.published is False

    @patch('repoindex.sources.go.requests.get')
    def test_check_gone(self, mock_get):
        """410 Gone is also a valid "not published" response."""
        mock_get.return_value = MagicMock(status_code=410)
        s = GoSource()
        result = s.check("github.com/user/retracted")
        assert result.published is False


class TestGoSourceAttributes:
    def test_attributes(self):
        s = GoSource()
        assert s.source_id == "go"
        assert s.target == "publications"


# ============================================================================
# fetch() integration smoke tests (make sure the fetch method produces dicts)
# ============================================================================

class TestFetchIntegration:
    @patch('repoindex.sources.npm.requests.get')
    def test_npm_fetch(self, mock_get, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "my-lib"}))
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"dist-tags": {"latest": "1.0.0"}},
        )
        s = NpmSource()
        result = s.fetch(str(tmp_path))
        assert result is not None
        assert result['registry'] == 'npm'
        assert result['name'] == 'my-lib'
        assert result['version'] == '1.0.0'

    def test_npm_fetch_no_detect(self, tmp_path):
        s = NpmSource()
        assert s.fetch(str(tmp_path)) is None

    @patch('repoindex.sources.cargo.requests.get')
    def test_cargo_fetch(self, mock_get, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "my-crate"\n')
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"crate": {"max_version": "0.1.0"}},
        )
        s = CargoSource()
        result = s.fetch(str(tmp_path))
        assert result is not None
        assert result['registry'] == 'cargo'

    @patch('repoindex.sources.go.requests.get')
    def test_go_fetch(self, mock_get, tmp_path):
        (tmp_path / "go.mod").write_text("module github.com/user/mod\n")
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"Version": "v1.0.0"},
        )
        s = GoSource()
        result = s.fetch(str(tmp_path))
        assert result is not None
        assert result['registry'] == 'go'
