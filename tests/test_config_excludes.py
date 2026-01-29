"""
Tests for repoindex config excludes CLI commands.
"""
import json
import os
import tempfile
import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from repoindex.commands.config import config_cmd


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path):
    """Create a temporary config directory with a config file."""
    config_path = tmp_path / "config.yaml"
    config_data = {
        "repository_directories": ["~/github/**"],
        "exclude_directories": [],
        "repository_tags": {},
    }
    with open(config_path, "w") as f:
        yaml.safe_dump(config_data, f)
    return tmp_path, config_path


@pytest.fixture
def config_env(config_dir, monkeypatch):
    """Set REPOINDEX_CONFIG to the temp config path."""
    tmp_path, config_path = config_dir
    monkeypatch.setenv("REPOINDEX_CONFIG", str(config_path))
    return config_path


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


class TestExcludesAdd:
    """Tests for 'config excludes add' command."""

    def test_add_new_path(self, runner, config_env):
        result = runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        assert result.exit_code == 0
        assert "Added exclude directory" in result.output

        config = _load_yaml(config_env)
        assert "~/github/archived" in config["exclude_directories"]

    def test_add_duplicate_path(self, runner, config_env):
        # Add once
        runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        # Add again
        result = runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        assert result.exit_code == 0
        assert "already in exclude list" in result.output

        config = _load_yaml(config_env)
        assert config["exclude_directories"].count("~/github/archived") == 1

    def test_add_multiple_paths(self, runner, config_env):
        runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        runner.invoke(config_cmd, ["excludes", "add", "~/github/forks"])

        config = _load_yaml(config_env)
        assert len(config["exclude_directories"]) == 2
        assert "~/github/archived" in config["exclude_directories"]
        assert "~/github/forks" in config["exclude_directories"]


class TestExcludesRemove:
    """Tests for 'config excludes remove' command."""

    def test_remove_existing_path(self, runner, config_env):
        # Add first
        runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        # Remove
        result = runner.invoke(config_cmd, ["excludes", "remove", "~/github/archived"])
        assert result.exit_code == 0
        assert "Removed exclude directory" in result.output

        config = _load_yaml(config_env)
        assert "~/github/archived" not in config["exclude_directories"]

    def test_remove_nonexistent_path(self, runner, config_env):
        # Add one path so the list is non-empty
        runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        # Try to remove a different path
        result = runner.invoke(config_cmd, ["excludes", "remove", "~/github/nope"])
        assert result.exit_code == 0
        assert "not found in exclude list" in result.output

    def test_remove_from_empty_list(self, runner, config_env):
        result = runner.invoke(config_cmd, ["excludes", "remove", "~/github/nope"])
        assert result.exit_code == 0
        assert "No exclude directories configured" in result.output


class TestExcludesList:
    """Tests for 'config excludes list' command."""

    def test_list_empty(self, runner, config_env):
        result = runner.invoke(config_cmd, ["excludes", "list"])
        assert result.exit_code == 0
        assert "No exclude directories configured" in result.output

    def test_list_with_entries(self, runner, config_env):
        runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        runner.invoke(config_cmd, ["excludes", "add", "~/github/forks"])

        result = runner.invoke(config_cmd, ["excludes", "list"])
        assert result.exit_code == 0
        assert "~/github/archived" in result.output
        assert "~/github/forks" in result.output

    def test_list_json_empty(self, runner, config_env):
        result = runner.invoke(config_cmd, ["excludes", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert data == {"exclude_directories": []}

    def test_list_json_with_entries(self, runner, config_env):
        runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        runner.invoke(config_cmd, ["excludes", "add", "~/github/forks"])

        result = runner.invoke(config_cmd, ["excludes", "list", "--json"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 2

        entry0 = json.loads(lines[0])
        assert entry0["index"] == 0
        assert entry0["path"] == "~/github/archived"

        entry1 = json.loads(lines[1])
        assert entry1["index"] == 1
        assert entry1["path"] == "~/github/forks"


class TestExcludesClear:
    """Tests for 'config excludes clear' command."""

    def test_clear_empty(self, runner, config_env):
        result = runner.invoke(config_cmd, ["excludes", "clear"])
        assert result.exit_code == 0
        assert "No exclude directories configured" in result.output

    def test_clear_with_yes(self, runner, config_env):
        runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])
        runner.invoke(config_cmd, ["excludes", "add", "~/github/forks"])

        result = runner.invoke(config_cmd, ["excludes", "clear", "--yes"])
        assert result.exit_code == 0
        assert "Cleared all exclude directories" in result.output

        config = _load_yaml(config_env)
        assert config["exclude_directories"] == []

    def test_clear_cancelled(self, runner, config_env):
        runner.invoke(config_cmd, ["excludes", "add", "~/github/archived"])

        # Simulate 'n' input for confirmation
        result = runner.invoke(config_cmd, ["excludes", "clear"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.output

        config = _load_yaml(config_env)
        assert len(config["exclude_directories"]) == 1
