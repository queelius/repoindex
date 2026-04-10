"""Local asset detection metadata source for repoindex."""
from pathlib import Path
from typing import Optional

from . import MetadataSource

# Asset checks: (result_key, candidate_paths)
_ASSET_CHECKS = (
    ('has_codemeta', ('codemeta.json',)),
    ('has_funding', ('.github/FUNDING.yml',)),
    ('has_contributors', ('CONTRIBUTORS', 'CONTRIBUTORS.md', 'AUTHORS', 'AUTHORS.md')),
    ('has_changelog', ('CHANGELOG.md', 'CHANGES.md', 'NEWS.md', 'HISTORY.md',
                        'CHANGELOG', 'CHANGES')),
)


class LocalAssetsSource(MetadataSource):
    """Detect presence of common project asset files."""

    source_id = "local_assets"
    name = "Local Asset Files"
    target = "repos"

    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        # Always applies: every repo can be checked for asset files
        return True

    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        """Detect presence of common project asset files."""
        p = Path(repo_path)
        result = {}

        for key, candidates in _ASSET_CHECKS:
            if any((p / name).exists() for name in candidates):
                result[key] = 1

        return result if result else None


source = LocalAssetsSource()
