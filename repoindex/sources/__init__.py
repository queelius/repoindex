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
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ['MetadataSource', 'discover_sources']


class MetadataSource(ABC):
    """
    Abstract base class for metadata sources.

    Each source detects whether it applies to a repo and fetches
    metadata as a dict. Sources can be remote (API calls) or local
    (file parsing).

    Attributes:
        source_id: Short identifier (e.g., "github", "pypi", "citation_cff")
        name: Human-readable name (e.g., "GitHub", "CITATION.cff")
        target: Where data goes: "repos" or "publications"
        batch: True if this source uses batch pre-fetch (e.g., Zenodo ORCID lookup)
    """
    source_id: str = ""
    name: str = ""
    target: str = "repos"
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


BUILTIN_SOURCES: List[MetadataSource] = [
    # These will be populated as providers are migrated (Task 2)
    # For now, empty - sources are discovered from providers via compatibility layer
]


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

    Loads built-in sources from BUILTIN_SOURCES and user sources
    from ~/.repoindex/sources/*.py (each exports a module-level `source` attribute).

    Also loads from ~/.repoindex/providers/*.py for backward compatibility
    (old provider/platform attributes are adapted if they're not MetadataSource instances).

    Args:
        user_dir: Override path for user sources (default: ~/.repoindex/sources/)
        only: If set, only load sources whose source_id is in this list

    Returns:
        List of MetadataSource instances
    """
    sources: List[MetadataSource] = list(BUILTIN_SOURCES)

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

    # Backward compatibility: also scan ~/.repoindex/providers/ for MetadataSource instances
    # (old modules may export `source`, `provider`, or `platform` attributes that
    # are MetadataSource instances if they've been migrated)
    providers_dir = os.path.expanduser('~/.repoindex/providers')
    if user_dir != providers_dir:
        sources.extend(
            _load_sources_from_directory(
                providers_dir,
                module_prefix='repoindex_user_provider_compat',
                attributes=['source', 'provider', 'platform'],
            )
        )

    # Apply only filter
    if only is not None:
        only_set = set(only)
        sources = [s for s in sources if s.source_id in only_set]

    return sources
