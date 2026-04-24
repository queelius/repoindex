"""
Unified metadata source system for repoindex.

MetadataSource is the single ABC for all external metadata enrichment.
Each source detects whether it applies to a repo, then fetches metadata.
The 'target' field determines where the data is stored:
- "repos": merge fields into the repos table (platform enrichment, local file parsing)
- "publications": upsert into the publications table (registry detection)

Sources can be remote (GitHub API, PyPI API) or local (CITATION.cff, pyproject.toml).
User-provided sources can be dropped into ~/.repoindex/sources/*.py,
each exporting a module-level `source` attribute.
"""

import importlib
import importlib.util
import logging
import os
from abc import ABC, abstractmethod
from typing import List, Literal, Optional

logger = logging.getLogger(__name__)

__all__ = [
    'MetadataSource', 'discover_sources',
    'VALID_TARGETS',
]

# Valid values for MetadataSource.target. The discriminator drives where
# fetch() output is merged: "repos" rows (platform enrichment, local file
# parsing) vs "publications" rows (registry detection). Any other value
# would silently no-op in the refresh dispatcher, so discover_sources()
# validates against this set.
VALID_TARGETS = frozenset({"repos", "publications"})

# Built-in source module names (relative to repoindex.sources).
# Order is stable for reproducibility; the first entries emit to 'repos',
# the rest emit to 'publications'.
_BUILTIN_SOURCE_MODULES = (
    # target=repos
    'citation_cff',
    'keywords',
    'local_assets',
    'gitea',
    'github',
    # target=publications
    'pypi',
    'cran',
    'zenodo',
    'npm',
    'cargo',
    'conda',
    'docker',
    'rubygems',
    'go',
)


class MetadataSource(ABC):
    """
    Abstract base class for metadata sources.

    Each source detects whether it applies to a repo and fetches
    metadata as a dict. Sources can be remote (API calls) or local
    (file parsing).

    Attributes:
        source_id: Short identifier (e.g., "github", "pypi", "citation_cff")
        name: Human-readable name (e.g., "GitHub", "CITATION.cff")
        target: Where data goes: "repos" or "publications". Typed as a
            Literal so IDEs and type checkers catch typos; runtime
            validation in discover_sources() enforces the same contract.
        batch: True if this source uses batch pre-fetch (e.g., Zenodo ORCID lookup)
    """
    source_id: str = ""
    name: str = ""
    target: Literal["repos", "publications"] = "repos"
    batch: bool = False

    @abstractmethod
    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        """
        Detect whether this source applies to this repo.

        Args:
            repo_path: Filesystem path to the repository
            repo_record: Optional dict of repo metadata from database

        Returns:
            True if this source can provide metadata for this repo
        """

    @abstractmethod
    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        """
        Fetch metadata from this source.

        Args:
            repo_path: Filesystem path to the repository
            repo_record: Optional dict of repo metadata
            config: Optional configuration dict

        Returns:
            Dict of metadata fields, or None if nothing available.
            For target="repos": keys are column names (github_stars, keywords, etc.)
            For target="publications": keys are registry, name, version, published, url, etc.
        """

    def prefetch(self, config: dict) -> None:
        """Optional batch pre-fetch hook, called once per refresh."""


def _build_builtin_sources() -> List[MetadataSource]:
    """Build the list of built-in sources.

    Built-in source failures are bugs -- log at WARNING so they aren't hidden.
    """
    sources: List[MetadataSource] = []
    for module_name in _BUILTIN_SOURCE_MODULES:
        try:
            mod = importlib.import_module(f'.{module_name}', package='repoindex.sources')
            src = getattr(mod, 'source', None)
            if src and isinstance(src, MetadataSource):
                sources.append(src)
            else:
                logger.warning(
                    "Built-in source module %s has no MetadataSource 'source' attribute",
                    module_name,
                )
        except Exception as e:
            logger.warning("Could not load built-in source %s: %s", module_name, e)
    return sources


# Lazy-initialized cache of built-in sources
_BUILTIN_SOURCES_CACHE: Optional[List[MetadataSource]] = None


def _get_builtin_sources() -> List[MetadataSource]:
    """Get built-in sources, building the cache on first call."""
    global _BUILTIN_SOURCES_CACHE
    if _BUILTIN_SOURCES_CACHE is None:
        _BUILTIN_SOURCES_CACHE = _build_builtin_sources()
    return _BUILTIN_SOURCES_CACHE


def _load_sources_from_directory(
    directory: str,
    module_prefix: str,
    attributes: List[str],
) -> List[MetadataSource]:
    """
    Load MetadataSource instances from Python files in a directory.

    Scans .py files (skipping underscore-prefixed), imports each, and
    checks for module-level attributes that are MetadataSource instances.

    Args:
        directory: Filesystem path to scan
        module_prefix: Prefix for generated module names (avoids collisions)
        attributes: Ordered list of attribute names to check on each module

    Returns:
        List of discovered MetadataSource instances
    """
    sources: List[MetadataSource] = []

    if not os.path.isdir(directory):
        return sources

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith('.py') or filename.startswith('_'):
            continue

        filepath = os.path.join(directory, filename)
        mod_name = filename[:-3]  # strip .py

        try:
            spec = importlib.util.spec_from_file_location(
                f'{module_prefix}_{mod_name}', filepath
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for attr_name in attributes:
                    obj = getattr(mod, attr_name, None)
                    if obj and isinstance(obj, MetadataSource):
                        sources.append(obj)
                        logger.info(
                            "Loaded source: %s from %s", obj.source_id, filepath
                        )
                        break  # one source per module
        except Exception as e:
            logger.warning("Failed to load source from '%s': %s", filepath, e)

    return sources


def discover_sources(
    user_dir: Optional[str] = None,
    only: Optional[List[str]] = None,
) -> List[MetadataSource]:
    """
    Discover and load metadata sources.

    Loads built-in sources from `_BUILTIN_SOURCE_MODULES` and user sources
    from `~/.repoindex/sources/*.py` (each exports a module-level
    `source` attribute).

    Args:
        user_dir: Override path for user sources (default: ~/.repoindex/sources/)
        only: If set, only load sources whose source_id is in this list

    Returns:
        List of MetadataSource instances
    """
    sources: List[MetadataSource] = list(_get_builtin_sources())

    # Load user sources from ~/.repoindex/sources/
    if user_dir is None:
        user_dir = os.path.expanduser('~/.repoindex/sources')

    sources.extend(
        _load_sources_from_directory(
            user_dir,
            module_prefix='repoindex_user_source',
            attributes=['source'],
        )
    )

    # Apply only filter
    if only is not None:
        only_set = set(only)
        sources = [s for s in sources if s.source_id in only_set]

    # Validate source.target against known values. Any source with an unknown
    # target would silently no-op in the refresh dispatcher (neither the
    # 'repos' nor 'publications' branch would fire), so catch typos here and
    # skip the offending source rather than letting a user-provided source
    # with target='repo' vanish into thin air.
    validated: List[MetadataSource] = []
    for s in sources:
        if s.target not in VALID_TARGETS:
            logger.warning(
                "Source %r has invalid target %r (expected one of %s); skipping",
                s.source_id, s.target, sorted(VALID_TARGETS),
            )
            continue
        validated.append(s)

    return validated
