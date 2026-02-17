"""
Tests for config set/get/unset commands and supporting utility functions.
"""
import json
import sys
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from repoindex.config import (
    coerce_value,
    config_get_path,
    config_set_path,
    config_unset_path,
    load_raw_config,
)
from repoindex.commands.config import config_cmd


# ── Utility function tests ─────────────────────────────────────


class TestCoerceValue:
    """Tests for coerce_value()."""

    def test_true(self):
        assert coerce_value("true") is True

    def test_True(self):
        assert coerce_value("True") is True

    def test_TRUE(self):
        assert coerce_value("TRUE") is True

    def test_false(self):
        assert coerce_value("false") is False

    def test_False(self):
        assert coerce_value("False") is False

    def test_int(self):
        assert coerce_value("42") == 42
        assert isinstance(coerce_value("42"), int)

    def test_negative_int(self):
        assert coerce_value("-7") == -7

    def test_zero(self):
        assert coerce_value("0") == 0
        assert isinstance(coerce_value("0"), int)

    def test_float(self):
        assert coerce_value("3.14") == 3.14
        assert isinstance(coerce_value("3.14"), float)

    def test_negative_float(self):
        assert coerce_value("-0.5") == -0.5

    def test_string(self):
        assert coerce_value("hello") == "hello"

    def test_string_with_spaces(self):
        assert coerce_value("hello world") == "hello world"

    def test_empty_string(self):
        assert coerce_value("") == ""

    def test_string_that_looks_numeric_but_isnt(self):
        assert coerce_value("12abc") == "12abc"


class TestConfigGetPath:
    """Tests for config_get_path()."""

    def test_top_level(self):
        config = {"name": "test"}
        value, found = config_get_path(config, "name")
        assert found is True
        assert value == "test"

    def test_nested(self):
        config = {"author": {"name": "Alex", "email": "a@b.com"}}
        value, found = config_get_path(config, "author.name")
        assert found is True
        assert value == "Alex"

    def test_deeply_nested(self):
        config = {"github": {"rate_limit": {"max_retries": 3}}}
        value, found = config_get_path(config, "github.rate_limit.max_retries")
        assert found is True
        assert value == 3

    def test_returns_dict(self):
        config = {"author": {"name": "Alex", "email": "a@b.com"}}
        value, found = config_get_path(config, "author")
        assert found is True
        assert isinstance(value, dict)
        assert value["name"] == "Alex"

    def test_missing_key(self):
        config = {"author": {"name": "Alex"}}
        value, found = config_get_path(config, "author.orcid")
        assert found is False
        assert value is None

    def test_missing_intermediate(self):
        config = {"author": {"name": "Alex"}}
        value, found = config_get_path(config, "github.token")
        assert found is False

    def test_empty_config(self):
        value, found = config_get_path({}, "anything")
        assert found is False

    def test_non_dict_intermediate(self):
        config = {"author": "not a dict"}
        value, found = config_get_path(config, "author.name")
        assert found is False


class TestConfigSetPath:
    """Tests for config_set_path()."""

    def test_set_top_level(self):
        config = {}
        config_set_path(config, "name", "test")
        assert config == {"name": "test"}

    def test_set_nested(self):
        config = {}
        config_set_path(config, "author.name", "Alex")
        assert config == {"author": {"name": "Alex"}}

    def test_set_deeply_nested(self):
        config = {}
        config_set_path(config, "github.rate_limit.max_retries", 5)
        assert config == {"github": {"rate_limit": {"max_retries": 5}}}

    def test_overwrite_existing(self):
        config = {"author": {"name": "Old"}}
        config_set_path(config, "author.name", "New")
        assert config["author"]["name"] == "New"

    def test_preserves_siblings(self):
        config = {"author": {"name": "Alex", "email": "a@b.com"}}
        config_set_path(config, "author.orcid", "0000-1234")
        assert config["author"]["name"] == "Alex"
        assert config["author"]["email"] == "a@b.com"
        assert config["author"]["orcid"] == "0000-1234"

    def test_creates_intermediate_dicts(self):
        config = {"existing": True}
        config_set_path(config, "a.b.c", "deep")
        assert config["a"]["b"]["c"] == "deep"
        assert config["existing"] is True

    def test_overwrites_non_dict_intermediate(self):
        config = {"author": "string_value"}
        config_set_path(config, "author.name", "Alex")
        assert config["author"]["name"] == "Alex"


class TestConfigUnsetPath:
    """Tests for config_unset_path()."""

    def test_unset_existing(self):
        config = {"author": {"name": "Alex", "email": "a@b.com"}}
        result = config_unset_path(config, "author.name")
        assert result is True
        assert "name" not in config["author"]
        assert config["author"]["email"] == "a@b.com"

    def test_unset_top_level(self):
        config = {"name": "test", "other": "val"}
        result = config_unset_path(config, "name")
        assert result is True
        assert "name" not in config

    def test_unset_nonexistent(self):
        config = {"author": {"name": "Alex"}}
        result = config_unset_path(config, "author.orcid")
        assert result is False

    def test_unset_missing_intermediate(self):
        config = {"author": {"name": "Alex"}}
        result = config_unset_path(config, "github.token")
        assert result is False

    def test_unset_from_empty(self):
        result = config_unset_path({}, "anything")
        assert result is False


class TestLoadRawConfig:
    """Tests for load_raw_config()."""

    def test_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        # Must override HOME so get_config_path() doesn't find real config
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("REPOINDEX_CONFIG", raising=False)
        config = load_raw_config()
        assert config == {}

    def test_reads_yaml_without_defaults(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        raw = {"repository_directories": ["~/github/**"]}
        with open(config_path, "w") as f:
            yaml.safe_dump(raw, f)
        monkeypatch.setenv("REPOINDEX_CONFIG", str(config_path))

        config = load_raw_config()
        assert config == raw
        # Should NOT have default keys like "author", "github", etc.
        assert "author" not in config
        assert "github" not in config


# ── CLI integration tests ──────────────────────────────────────


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    """Create a temp config with minimal content and set REPOINDEX_CONFIG."""
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.safe_dump({"repository_directories": ["~/github/**"]}, f)
    monkeypatch.setenv("REPOINDEX_CONFIG", str(config_path))
    return config_path


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


class TestConfigSetCLI:
    """Tests for 'config set' CLI command."""

    def test_set_string(self, runner, config_env):
        result = runner.invoke(config_cmd, ["set", "author.name", "Alex Towell"])
        assert result.exit_code == 0
        assert "author.name" in result.output

        config = _load_yaml(config_env)
        assert config["author"]["name"] == "Alex Towell"

    def test_set_bool(self, runner, config_env):
        result = runner.invoke(config_cmd, ["set", "refresh.providers.pypi", "true"])
        assert result.exit_code == 0

        config = _load_yaml(config_env)
        assert config["refresh"]["providers"]["pypi"] is True

    def test_set_int(self, runner, config_env):
        result = runner.invoke(config_cmd, ["set", "github.rate_limit.max_retries", "5"])
        assert result.exit_code == 0

        config = _load_yaml(config_env)
        assert config["github"]["rate_limit"]["max_retries"] == 5

    def test_set_does_not_bloat_with_defaults(self, runner, config_env):
        """Setting one key should not persist all defaults."""
        runner.invoke(config_cmd, ["set", "author.name", "Test"])

        config = _load_yaml(config_env)
        # Should have repository_directories (original) and author.name (new)
        # Should NOT have all the default keys
        assert "repository_tags" not in config
        assert config.get("author", {}).get("name") == "Test"

    def test_set_preserves_existing(self, runner, config_env):
        """Setting a new key should preserve existing keys."""
        runner.invoke(config_cmd, ["set", "author.name", "Alex"])

        config = _load_yaml(config_env)
        assert config["repository_directories"] == ["~/github/**"]
        assert config["author"]["name"] == "Alex"


class TestConfigGetCLI:
    """Tests for 'config get' CLI command."""

    def test_get_scalar(self, runner, config_env):
        # First set a value
        runner.invoke(config_cmd, ["set", "author.name", "Alex"])

        result = runner.invoke(config_cmd, ["get", "author.name"])
        assert result.exit_code == 0
        assert result.output.strip() == "Alex"

    def test_get_dict(self, runner, config_env):
        runner.invoke(config_cmd, ["set", "author.name", "Alex"])
        runner.invoke(config_cmd, ["set", "author.email", "a@b.com"])

        result = runner.invoke(config_cmd, ["get", "author"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "Alex"
        assert data["email"] == "a@b.com"

    def test_get_default_value(self, runner, config_env):
        """Get should show effective (default-merged) value even if not in file."""
        result = runner.invoke(config_cmd, ["get", "github.rate_limit.max_retries"])
        assert result.exit_code == 0
        assert result.output.strip() == "3"  # default value

    def test_get_missing_key(self, runner, config_env):
        result = runner.invoke(config_cmd, ["get", "nonexistent.key"])
        assert result.exit_code == 1
        assert "Key not found" in result.output

    def test_get_bool_value(self, runner, config_env):
        runner.invoke(config_cmd, ["set", "refresh.providers.pypi", "true"])
        result = runner.invoke(config_cmd, ["get", "refresh.providers.pypi"])
        assert result.exit_code == 0
        assert result.output.strip() == "True"

    def test_get_int_value(self, runner, config_env):
        runner.invoke(config_cmd, ["set", "github.rate_limit.max_retries", "10"])
        result = runner.invoke(config_cmd, ["get", "github.rate_limit.max_retries"])
        assert result.exit_code == 0
        assert result.output.strip() == "10"


class TestConfigUnsetCLI:
    """Tests for 'config unset' CLI command."""

    def test_unset_existing(self, runner, config_env):
        # First set a value
        runner.invoke(config_cmd, ["set", "author.name", "Alex"])
        # Then unset it
        result = runner.invoke(config_cmd, ["unset", "author.name"])
        assert result.exit_code == 0
        assert "Removed" in result.output

        config = _load_yaml(config_env)
        assert "name" not in config.get("author", {})

    def test_unset_nonexistent(self, runner, config_env):
        result = runner.invoke(config_cmd, ["unset", "nonexistent.key"])
        assert result.exit_code == 1
        assert "Key not found" in result.output

    def test_unset_preserves_siblings(self, runner, config_env):
        runner.invoke(config_cmd, ["set", "author.name", "Alex"])
        runner.invoke(config_cmd, ["set", "author.email", "a@b.com"])
        runner.invoke(config_cmd, ["unset", "author.name"])

        config = _load_yaml(config_env)
        assert "name" not in config["author"]
        assert config["author"]["email"] == "a@b.com"


class TestConfigShowCLI:
    """Tests for 'config show' CLI command."""

    def test_show_default_yaml(self, runner, config_env):
        result = runner.invoke(config_cmd, ["show"])
        assert result.exit_code == 0
        # Should be valid YAML
        data = yaml.safe_load(result.output)
        assert "repository_directories" in data

    def test_show_json(self, runner, config_env):
        result = runner.invoke(config_cmd, ["show", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "repository_directories" in data

    def test_show_path(self, runner, config_env):
        result = runner.invoke(config_cmd, ["show", "--path"])
        assert result.exit_code == 0
        # Should be a plain path string, not JSON
        output = result.output.strip()
        assert not output.startswith("{")
        assert output.endswith(".yaml")


class TestConfigInitCLI:
    """Tests for 'config init' CLI command."""

    def test_init_writes_yaml(self, runner, tmp_path, monkeypatch):
        # Override HOME so get_config_path() writes to tmp dir
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("REPOINDEX_CONFIG", raising=False)
        config_path = tmp_path / ".repoindex" / "config.yaml"

        # Create a directory with a git repo so detection works
        repo = tmp_path / "myrepo" / ".git"
        repo.mkdir(parents=True)

        result = runner.invoke(
            config_cmd,
            ["init", "-y", "-d", str(tmp_path)],
        )
        assert result.exit_code == 0

        # Verify it's valid YAML (not JSON)
        content = config_path.read_text()
        data = yaml.safe_load(content)
        assert "repository_directories" in data
        # Should not be JSON (no opening brace)
        assert not content.strip().startswith("{")
