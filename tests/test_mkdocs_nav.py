"""Guard tests for mkdocs nav consistency.

Asserts every nav target file exists under docs/ and that the dead
`catalog-query.md` / `render.md` entries are gone while `export.md` is present.
A standalone unit test cannot exercise `mkdocs build --strict` portably, so this
validates the same invariant strict mode enforces (no nav reference to a missing
page) directly against mkdocs.yml.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"


def _nav_targets(nav):
    """Yield every leaf doc path referenced in a mkdocs nav structure."""
    if isinstance(nav, str):
        yield nav
    elif isinstance(nav, list):
        for item in nav:
            yield from _nav_targets(item)
    elif isinstance(nav, dict):
        for value in nav.values():
            yield from _nav_targets(value)


def _load_nav():
    text = (PROJECT_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    # mkdocs.yml uses no custom python tags in this project, so safe_load works.
    data = yaml.safe_load(text)
    return list(_nav_targets(data.get("nav", [])))


def test_every_nav_target_exists():
    for target in _load_nav():
        assert (DOCS_DIR / target).is_file(), f"nav target missing: {target}"


def test_dead_nav_entries_removed():
    targets = _load_nav()
    assert "catalog-query.md" not in targets
    assert "render.md" not in targets


def test_export_doc_is_in_nav():
    assert "export.md" in _load_nav()
