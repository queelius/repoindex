"""Keywords metadata source for repoindex."""
import json
from pathlib import Path
from typing import Optional

from . import MetadataSource

# Files checked for keywords, in priority order
_KEYWORD_FILES = ('pyproject.toml', 'Cargo.toml', 'package.json')


class KeywordsSource(MetadataSource):
    """Extract keywords from project metadata files (pyproject.toml, Cargo.toml, package.json)."""

    source_id = "keywords"
    name = "Project Keywords"
    target = "repos"

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        p = Path(repo_path)
        return any((p / f).exists() for f in _KEYWORD_FILES)

    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        """Extract keywords from project metadata files.

        Priority: pyproject.toml > Cargo.toml > package.json
        """
        p = Path(repo_path)

        # pyproject.toml
        if (p / 'pyproject.toml').exists():
            kw = self._extract_toml_keywords(
                p / 'pyproject.toml', ('project', 'keywords'))
            if kw is not None:
                return kw

        # Cargo.toml
        if (p / 'Cargo.toml').exists():
            kw = self._extract_toml_keywords(
                p / 'Cargo.toml', ('package', 'keywords'))
            if kw is not None:
                return kw

        # package.json
        if (p / 'package.json').exists():
            try:
                with open(p / 'package.json') as f:
                    data = json.load(f)
                kw = data.get('keywords')
                if kw and isinstance(kw, list):
                    return {'keywords': json.dumps(kw)}
            except Exception:
                pass

        return None

    @staticmethod
    def _extract_toml_keywords(path: Path, key_path: tuple) -> Optional[dict]:
        """Extract keywords from a TOML file at the given nested key path."""
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore[no-redef]
            with open(path, 'rb') as f:
                data = tomllib.load(f)
            node = data
            for key in key_path:
                node = node.get(key, {})
            if node and isinstance(node, list):
                return {'keywords': json.dumps(node)}
        except Exception:
            pass
        return None


source = KeywordsSource()
