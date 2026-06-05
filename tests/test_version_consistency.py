"""Tests that all four version sources agree.

Guards against the drift class where pyproject.toml / repoindex.__version__ /
CITATION.cff / codemeta.json fall out of sync (they were stuck at 0.10.1 while
the package shipped 2.0.0).
"""

import json
import re
from pathlib import Path

import yaml

import repoindex
from repoindex.compat import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def _citation_version() -> str:
    with open(REPO_ROOT / "CITATION.cff", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return str(data["version"])


def _codemeta_version() -> str:
    with open(REPO_ROOT / "codemeta.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return str(data["version"])


def test_pyproject_matches_dunder_version():
    assert _pyproject_version() == repoindex.__version__


def test_citation_matches_pyproject():
    assert _citation_version() == _pyproject_version()


def test_codemeta_matches_pyproject():
    assert _codemeta_version() == _pyproject_version()


def test_all_four_versions_agree():
    versions = {
        "pyproject": _pyproject_version(),
        "__version__": repoindex.__version__,
        "CITATION.cff": _citation_version(),
        "codemeta.json": _codemeta_version(),
    }
    assert len(set(versions.values())) == 1, versions


def test_codemeta_release_notes_url_matches_version():
    with open(REPO_ROOT / "codemeta.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    version = data["version"]
    assert data["releaseNotes"].endswith(f"/v{version}")


def test_codemeta_date_modified_is_iso():
    with open(REPO_ROOT / "codemeta.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["dateModified"])


def test_pyproject_drops_pathlib_and_tweepy():
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    deps = data["project"]["dependencies"]
    joined = " ".join(deps)
    assert "pathlib" not in [d.split(">")[0].split("=")[0].strip() for d in deps]
    assert "tweepy" not in [d.split(">")[0].split("=")[0].strip() for d in deps]
    assert "toml" in [d.split(">")[0].split("=")[0].split(";")[0].strip() for d in deps], joined


def test_pyproject_requires_python_310():
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["requires-python"] == ">=3.10"


def test_pyproject_has_per_version_classifiers():
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    classifiers = data["project"]["classifiers"]
    for ver in ("3.10", "3.11", "3.12"):
        assert f"Programming Language :: Python :: {ver}" in classifiers, classifiers


def test_requirements_txt_is_deleted():
    assert not (REPO_ROOT / "requirements.txt").exists(), (
        "requirements.txt must not exist: pyproject extras are the source of truth"
    )


def test_ci_workflow_covers_python_matrix():
    workflow = REPO_ROOT / ".github" / "workflows" / "test.yml"
    assert workflow.exists(), "CI workflow .github/workflows/test.yml is missing"
    with open(workflow, "r", encoding="utf-8") as f:
        ci = yaml.safe_load(f)
    # PyYAML parses the bare `on:` key as boolean True; accept either form.
    triggers = ci.get("on", ci.get(True))
    assert triggers is not None, "workflow has no triggers"
    matrix = ci["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert {"3.10", "3.11", "3.12"} <= set(str(v) for v in matrix), matrix
