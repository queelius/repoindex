"""
Source type hierarchy for repoindex (introduced in v2.0 / Wave V2.A).

The ``Source`` ABC is the marker base for everything in
``~/.repoindex/sources/**/*.py``. Three concrete subclass roles capture
the three substantively different concepts that previously shared the
flattened ``MetadataSource`` ABC:

- ``LocalScanner`` reads files inside the local repository. No network,
  no auth. Output goes to the ``repos`` table.
- ``GitForge`` (a ``RemoteSource``) hosts git repositories. It exposes
  read metadata via fetch() and a set of optional write capabilities
  (set_topics, set_archived, etc.). Output goes to the ``repos`` table.
- ``Registry`` (a ``RemoteSource``) is a package registry. Output goes
  to the ``publications`` table.

The data destination is now implicit in the subclass; the old
``target: Literal["repos", "publications"]`` discriminator is gone.
The refresh dispatcher uses ``isinstance`` to route fetch() output.

User-provided sources can be dropped into:

- ``~/.repoindex/sources/scanners/*.py``
- ``~/.repoindex/sources/forges/*.py``
- ``~/.repoindex/sources/registries/*.py``

Each user module exports a module-level ``source`` attribute that is an
instance of the right subclass.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    'Source',
    'LocalScanner',
    'RemoteSource',
    'GitForge',
    'Registry',
    'RemoteRepo',
    'RemotePackage',
    'discover_sources',
]


# ---------------------------------------------------------------------------
# Source-extension API value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RemoteRepo:
    """A repository as seen by a GitForge enumerate_user_repos() call.

    Used by the (future) ``ops sync`` command to clone forge-hosted repos
    that aren't yet present locally. The shape is intentionally minimal:
    everything else can be fetched via the forge's normal fetch() once a
    repo lands on disk.
    """

    name: str
    clone_url: str
    default_branch: Optional[str] = None
    is_archived: bool = False
    description: Optional[str] = None


@dataclass(frozen=True)
class RemotePackage:
    """A package as seen by a Registry enumerate_user_packages() call."""

    name: str
    version: Optional[str] = None
    url: Optional[str] = None


# ---------------------------------------------------------------------------
# ABC hierarchy
# ---------------------------------------------------------------------------

class Source(ABC):
    """Marker base for everything in ``~/.repoindex/sources/**/*.py``.

    Subclass one of ``LocalScanner``, ``GitForge``, or ``Registry`` rather
    than ``Source`` directly; the refresh dispatcher routes data using
    ``isinstance`` against those three roles.

    Attributes:
        source_id: Short identifier (e.g., "github", "pypi", "citation_cff").
        name: Human-readable name (e.g., "GitHub", "CITATION.cff").
        batch: Whether the source uses a one-off ``prefetch()`` round-trip
            and matches per-repo in-memory during ``fetch()``. Default
            ``False`` (per-repo network calls). Currently only set by
            Zenodo (an ORCID -> all-records lookup).
    """

    source_id: str = ""
    name: str = ""
    batch: bool = False

    @abstractmethod
    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        """Detect whether this source applies to this repo.

        Args:
            repo_path: Filesystem path to the repository.
            repo_record: Optional dict of repo metadata from the database.

        Returns:
            True if this source can provide metadata for this repo.
        """

    @abstractmethod
    def fetch(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[dict]:
        """Fetch metadata from this source.

        Args:
            repo_path: Filesystem path to the repository.
            repo_record: Optional dict of repo metadata.
            config: Optional configuration dict.

        Returns:
            Dict of metadata fields, or None if nothing available.
            For LocalScanner/GitForge: keys are repos-table column names.
            For Registry: keys are registry/name/version/published/url/etc.
        """

    def prefetch(self, config: dict) -> None:
        """Optional batch pre-fetch hook, called once per refresh.

        Default is a no-op. Override on sources that benefit from a
        single network round-trip across all repos (e.g., Zenodo's
        ORCID lookup).
        """


class LocalScanner(Source):
    """Reads files inside the local repository. No network, no auth.

    Output of fetch() is merged into the ``repos`` table.
    """


class RemoteSource(Source):
    """Network-backed source with auth.

    Subclassed by ``GitForge`` (writes to ``repos``) and ``Registry``
    (writes to ``publications``). Don't subclass ``RemoteSource``
    directly; the refresh dispatcher only knows about the two leaf
    roles.
    """


class GitForge(RemoteSource):
    """Hosts git repositories. Provides API for both metadata and actions.

    Output of fetch() is merged into the ``repos`` table; a forge
    populates fields like ``forge_id``, ``topics``, ``is_archived``, etc.
    (those unified columns land in Wave V2.B; today this is still the
    per-platform ``github_*`` / ``gitea_*`` set.)

    All write capabilities are optional. The default implementations
    raise ``NotImplementedError``. Wave V2.C wires these up on the
    GitHub and Gitea sources and exposes them via ``ops set-*`` commands.
    """

    def enumerate_user_repos(self, config: dict) -> Iterator[RemoteRepo]:
        """List all repos owned by the configured user on this forge.

        Yields RemoteRepo records for the future ``ops sync`` command
        to clone any not-yet-local repositories.
        """
        raise NotImplementedError(
            f"{self.source_id} does not support enumerate_user_repos"
        )

    def set_topics(self, repo_record: dict, topics: list, config: dict) -> None:
        """Set topics on the forge for this repo."""
        raise NotImplementedError(
            f"{self.source_id} does not support set_topics"
        )

    def set_description(self, repo_record: dict, description: str,
                        config: dict) -> None:
        """Set the forge-side description for this repo."""
        raise NotImplementedError(
            f"{self.source_id} does not support set_description"
        )

    def set_archived(self, repo_record: dict, archived: bool,
                     config: dict) -> None:
        """Archive or unarchive the repo on the forge."""
        raise NotImplementedError(
            f"{self.source_id} does not support set_archived"
        )

    def set_visibility(self, repo_record: dict, public: bool,
                       config: dict) -> None:
        """Toggle public/private visibility on the forge."""
        raise NotImplementedError(
            f"{self.source_id} does not support set_visibility"
        )

    def set_default_branch(self, repo_record: dict, branch: str,
                           config: dict) -> None:
        """Change the default branch on the forge."""
        raise NotImplementedError(
            f"{self.source_id} does not support set_default_branch"
        )

    def enable_pages(self, repo_record: dict, branch: str, path: str,
                     config: dict) -> None:
        """Enable Pages-style static-site hosting for this repo."""
        raise NotImplementedError(
            f"{self.source_id} does not support enable_pages"
        )

    def fetch_events(self, repo_record: dict, since: "datetime", config: dict):
        """Yield forge events (release, pull_request, issue) since the cutoff.

        Returns an iterator of domain ``Event`` objects. Default raises
        ``NotImplementedError`` so forges without event support degrade
        gracefully, exactly like the optional ``set_*`` actions.
        """
        raise NotImplementedError(
            f"{self.source_id} does not support fetch_events"
        )

    @staticmethod
    def _parse_event_ts(raw: Optional[str]):
        """Parse an ISO8601 forge timestamp into a naive datetime."""
        from datetime import datetime
        if not raw:
            return datetime.now()
        try:
            return datetime.fromisoformat(
                raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return datetime.now()

    def _item_to_event(self, event_type: str, item: dict,
                       repo_name: str, repo_path: str):
        """Translate a forge API list item into a domain Event.

        This defines the cross-forge event payload contract consumed by
        the events table and display code: releases carry
        ``tag/title/url/author``; pull_requests and issues carry
        ``number/title/state/url/author``. Gitea mirrors GitHub's JSON
        field names, so one mapping serves every forge.
        """
        from ..domain.event import Event
        if event_type == 'release':
            return Event(
                type='release',
                timestamp=self._parse_event_ts(item.get('published_at')),
                repo_name=repo_name, repo_path=repo_path,
                data={'tag': item.get('tag_name') or item.get('name') or 'unknown',
                      'title': item.get('name') or '',
                      'url': item.get('html_url'),
                      'author': (item.get('author') or {}).get('login')})
        return Event(
            type=event_type,
            timestamp=self._parse_event_ts(item.get('created_at')),
            repo_name=repo_name, repo_path=repo_path,
            data={'number': item.get('number'),
                  'title': item.get('title') or '',
                  'state': item.get('state'),
                  'url': item.get('html_url'),
                  'author': (item.get('user') or {}).get('login')})


class Registry(RemoteSource):
    """Package registry. Publishes artifacts; doesn't host source code.

    Output of fetch() is upserted into the ``publications`` table. Set
    ``batch = True`` if the source benefits from a single prefetch()
    call to populate per-repo data via match-in-memory in fetch().
    """

    def enumerate_user_packages(self, config: dict) -> Iterator[RemotePackage]:
        """List all packages owned by the configured user on this registry."""
        raise NotImplementedError(
            f"{self.source_id} does not support enumerate_user_packages"
        )


# ---------------------------------------------------------------------------
# Built-in source loading
# ---------------------------------------------------------------------------

# Built-in source module paths relative to repoindex.sources, grouped by
# subclass role. Order is stable for reproducibility.
_BUILTIN_SOURCE_MODULES = (
    # LocalScanner
    'scanners.citation_cff',
    'scanners.keywords',
    'scanners.local_assets',
    # GitForge
    'forges.gitea',
    'forges.github',
    # Registry
    'registries.pypi',
    'registries.cran',
    'registries.zenodo',
    'registries.npm',
    'registries.cargo',
    'registries.conda',
    'registries.docker',
    'registries.rubygems',
    'registries.go',
)

# Subdirectories scanned for user-provided sources under
# ~/.repoindex/sources/. Each subdir corresponds to one Source role.
_USER_SOURCE_SUBDIRS = ('scanners', 'forges', 'registries')


def _build_builtin_sources() -> List[Source]:
    """Build the list of built-in sources.

    Built-in source failures are bugs, log at WARNING so they aren't hidden.
    """
    sources: List[Source] = []
    for module_name in _BUILTIN_SOURCE_MODULES:
        try:
            mod = importlib.import_module(
                f'.{module_name}', package='repoindex.sources'
            )
            src = getattr(mod, 'source', None)
            if src and isinstance(src, Source):
                sources.append(src)
            else:
                logger.warning(
                    "Built-in source module %s has no Source 'source' attribute",
                    module_name,
                )
        except Exception as e:
            logger.warning("Could not load built-in source %s: %s", module_name, e)
    return sources


# Lazy-initialized cache of built-in sources.
_BUILTIN_SOURCES_CACHE: Optional[List[Source]] = None


def _get_builtin_sources() -> List[Source]:
    """Get built-in sources, building the cache on first call."""
    global _BUILTIN_SOURCES_CACHE
    if _BUILTIN_SOURCES_CACHE is None:
        _BUILTIN_SOURCES_CACHE = _build_builtin_sources()
    return _BUILTIN_SOURCES_CACHE


def _load_sources_from_directory(
    directory: str,
    module_prefix: str,
    attributes: List[str],
) -> List[Source]:
    """Load Source instances from .py files directly in ``directory``.

    Scans .py files (skipping underscore-prefixed), imports each, and
    checks for module-level attributes that are Source instances.

    Args:
        directory: Filesystem path to scan.
        module_prefix: Prefix for generated module names (avoids collisions).
        attributes: Ordered list of attribute names to check on each module.

    Returns:
        List of discovered Source instances.
    """
    sources: List[Source] = []

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
                    if obj and isinstance(obj, Source):
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
) -> List[Source]:
    """Discover and load metadata sources.

    Loads built-in sources from ``_BUILTIN_SOURCE_MODULES`` and user
    sources from the role subdirectories under ``~/.repoindex/sources/``
    (each user module exports a module-level ``source`` attribute).

    Args:
        user_dir: Override path for user sources
            (default: ``~/.repoindex/sources``). The function still
            descends into the role subdirs (scanners/, forges/,
            registries/).
        only: If set, only load sources whose source_id is in this list.

    Returns:
        List of Source instances.
    """
    sources: List[Source] = list(_get_builtin_sources())

    # Load user sources from ~/.repoindex/sources/{scanners,forges,registries}/
    if user_dir is None:
        user_dir = os.path.expanduser('~/.repoindex/sources')

    for subdir in _USER_SOURCE_SUBDIRS:
        sources.extend(
            _load_sources_from_directory(
                os.path.join(user_dir, subdir),
                module_prefix=f'repoindex_user_source_{subdir}',
                attributes=['source'],
            )
        )

    # Apply only filter
    if only is not None:
        only_set = set(only)
        sources = [s for s in sources if s.source_id in only_set]

    return sources
