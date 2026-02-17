"""Tests for new registry providers (npm, cargo, conda, docker, rubygems, go)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from repoindex.providers.npm import NpmProvider
from repoindex.providers.cargo import CargoProvider
from repoindex.providers.conda import CondaProvider
from repoindex.providers.docker import DockerProvider
from repoindex.providers.rubygems import RubyGemsProvider
from repoindex.providers.go import GoProvider, _encode_module_path


# ============================================================================
# npm
# ============================================================================

class TestNpmDetect:
    def test_detect_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "@scope/my-lib",
            "version": "1.0.0",
        }))
        p = NpmProvider()
        assert p.detect(str(tmp_path)) == "@scope/my-lib"

    def test_detect_private_package(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "private-app",
            "private": True,
        }))
        p = NpmProvider()
        assert p.detect(str(tmp_path)) is None

    def test_detect_no_package_json(self, tmp_path):
        p = NpmProvider()
        assert p.detect(str(tmp_path)) is None

    def test_detect_invalid_json(self, tmp_path):
        (tmp_path / "package.json").write_text("not json")
        p = NpmProvider()
        assert p.detect(str(tmp_path)) is None

    def test_detect_missing_name(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"version": "1.0.0"}))
        p = NpmProvider()
        assert p.detect(str(tmp_path)) is None


class TestNpmCheck:
    @patch('repoindex.providers.npm.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"dist-tags": {"latest": "2.0.0"}},
        )
        p = NpmProvider()
        result = p.check("my-lib")
        assert result.published is True
        assert result.version == "2.0.0"
        assert result.registry == "npm"

    @patch('repoindex.providers.npm.requests.get')
    def test_check_not_found(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        p = NpmProvider()
        result = p.check("nonexistent")
        assert result.published is False

    @patch('repoindex.providers.npm.requests.get')
    def test_check_network_error(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        p = NpmProvider()
        assert p.check("broken") is None


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
        p = CargoProvider()
        assert p.detect(str(tmp_path)) == "my-crate"

    def test_detect_no_cargo_toml(self, tmp_path):
        p = CargoProvider()
        assert p.detect(str(tmp_path)) is None

    def test_detect_workspace_without_name(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('''
[workspace]
members = ["crate-a", "crate-b"]
''')
        p = CargoProvider()
        assert p.detect(str(tmp_path)) is None


class TestCargoCheck:
    @patch('repoindex.providers.cargo.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"crate": {"max_version": "0.5.0", "downloads": 1000}},
        )
        p = CargoProvider()
        result = p.check("my-crate")
        assert result.published is True
        assert result.version == "0.5.0"
        assert result.downloads == 1000

    @patch('repoindex.providers.cargo.requests.get')
    def test_check_with_user_agent(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        p = CargoProvider()
        p.check("test")
        # Verify User-Agent was set
        call_kwargs = mock_get.call_args
        assert 'repoindex' in call_kwargs.kwargs.get('headers', {}).get('User-Agent', '')


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
        p = CondaProvider()
        assert p.detect(str(tmp_path)) == "my-conda-pkg"

    def test_detect_root_meta_yaml(self, tmp_path):
        (tmp_path / "meta.yaml").write_text('''
package:
  name: simple-pkg
  version: 0.1
''')
        p = CondaProvider()
        assert p.detect(str(tmp_path)) == "simple-pkg"

    def test_detect_no_meta_yaml(self, tmp_path):
        p = CondaProvider()
        assert p.detect(str(tmp_path)) is None


class TestCondaCheck:
    @patch('repoindex.providers.conda.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"latest_version": "2.3.0"},
        )
        p = CondaProvider()
        result = p.check("my-conda-pkg")
        assert result.published is True
        assert result.version == "2.3.0"
        assert result.registry == "conda"


# ============================================================================
# Docker
# ============================================================================

class TestDockerDetect:
    def test_detect_dockerfile(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
        p = DockerProvider()
        result = p.detect(str(tmp_path), repo_record={'owner': 'myuser'})
        assert result == "myuser/{}".format(tmp_path.name)

    def test_detect_dockerfile_without_owner(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        p = DockerProvider()
        result = p.detect(str(tmp_path))
        assert result == tmp_path.name

    def test_detect_no_dockerfile(self, tmp_path):
        p = DockerProvider()
        assert p.detect(str(tmp_path)) is None


class TestDockerCheck:
    @patch('repoindex.providers.docker.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"pull_count": 5000, "last_updated": "2025-01-01T00:00:00Z"},
        )
        p = DockerProvider()
        result = p.check("myuser/myapp")
        assert result.published is True
        assert result.downloads == 5000

    @patch('repoindex.providers.docker.requests.get')
    def test_check_library_image(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        p = DockerProvider()
        result = p.check("myapp")  # No slash = library image
        assert result.published is False


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
        p = RubyGemsProvider()
        assert p.detect(str(tmp_path)) == "my-gem"

    def test_detect_gemspec_single_quotes(self, tmp_path):
        (tmp_path / "test.gemspec").write_text("spec.name = 'quoted-gem'")
        p = RubyGemsProvider()
        assert p.detect(str(tmp_path)) == "quoted-gem"

    def test_detect_no_gemspec(self, tmp_path):
        p = RubyGemsProvider()
        assert p.detect(str(tmp_path)) is None

    def test_detect_fallback_to_filename(self, tmp_path):
        (tmp_path / "fallback.gemspec").write_text("# empty gemspec\n")
        p = RubyGemsProvider()
        assert p.detect(str(tmp_path)) == "fallback"


class TestRubyGemsCheck:
    @patch('repoindex.providers.rubygems.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"version": "3.0.0", "downloads": 50000},
        )
        p = RubyGemsProvider()
        result = p.check("my-gem")
        assert result.published is True
        assert result.version == "3.0.0"
        assert result.downloads == 50000


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
        p = GoProvider()
        assert p.detect(str(tmp_path)) == "github.com/user/mymod"

    def test_detect_no_go_mod(self, tmp_path):
        p = GoProvider()
        assert p.detect(str(tmp_path)) is None


class TestGoCheck:
    @patch('repoindex.providers.go.requests.get')
    def test_check_published(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"Version": "v1.5.0"},
        )
        p = GoProvider()
        result = p.check("github.com/user/mymod")
        assert result.published is True
        assert result.version == "v1.5.0"
        assert result.registry == "go"
        # Verify the URL was encoded for the proxy
        called_url = mock_get.call_args[0][0]
        assert "proxy.golang.org" in called_url

    @patch('repoindex.providers.go.requests.get')
    def test_check_not_found(self, mock_get):
        mock_get.return_value = MagicMock(status_code=404)
        p = GoProvider()
        result = p.check("github.com/user/nonexistent")
        assert result.published is False

    @patch('repoindex.providers.go.requests.get')
    def test_check_gone(self, mock_get):
        """410 Gone is also a valid "not published" response."""
        mock_get.return_value = MagicMock(status_code=410)
        p = GoProvider()
        result = p.check("github.com/user/retracted")
        assert result.published is False
