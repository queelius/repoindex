"""Guard tests: removed-command breadcrumbs and bad marketplace refs must stay gone.

These assert against the real on-disk source/docs so that the v2.x trust-repair
fixes (removing `repoindex query` / `repoindex init` onboarding hints and the
nonexistent `claude-code-marketplace`) cannot silently regress.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def test_config_init_footer_has_no_removed_query_command():
    text = _read("repoindex/commands/config.py")
    assert "repoindex query" not in text


def test_status_footer_has_no_removed_query_command():
    text = _read("repoindex/commands/status.py")
    assert "repoindex query" not in text


def test_refresh_hint_has_no_removed_init_command():
    text = _read("repoindex/commands/refresh.py")
    assert "repoindex init" not in text


def test_readme_has_no_bad_marketplace_ref():
    text = _read("README.md")
    assert "claude-code-marketplace" not in text
    assert "queelius/claude-anvil" in text


def test_docs_index_has_no_bad_marketplace_ref():
    text = _read("docs/index.md")
    assert "claude-code-marketplace" not in text
    assert "queelius/claude-anvil" in text
