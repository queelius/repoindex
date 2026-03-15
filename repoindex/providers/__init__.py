"""
Registry provider extension system for repoindex.

Defines the RegistryProvider interface and discovery mechanism.
Built-in providers (pypi, cran, zenodo) are thin wrappers around
existing modules. New providers (npm, cargo, etc.) implement the
interface directly.

User-provided providers can be dropped into ~/.repoindex/providers/*.py,
each exporting a module-level `provider` attribute.
"""

import importlib
import importlib.util
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from ..domain.repository import PackageMetadata

logger = logging.getLogger(__name__)

# Re-export for provider authors
__all__ = [
    'RegistryProvider', 'PackageMetadata', 'discover_providers',
    'PlatformProvider', 'discover_platforms',
]


class RegistryProvider(ABC):
    """
    Abstract base class for package registry providers.

    Each provider can detect whether a repo targets its registry
    and check the registry for publication status.

    Attributes:
        registry: Short identifier (e.g., "pypi", "npm", "cargo")
        name: Human-readable name (e.g., "Python Package Index")
        batch: True if this provider uses batch pre-fetch instead of per-repo API calls
    """
    registry: str = ""
    name: str = ""
    batch: bool = False

    @abstractmethod
    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> Optional[str]:
        """
        Detect whether this repo targets this registry.

        Args:
            repo_path: Filesystem path to the repository
            repo_record: Optional dict of repo metadata from the database

        Returns:
            Package name if detected, None otherwise
        """

    @abstractmethod
    def check(self, package_name: str, config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """
        Check registry for a package.

        Args:
            package_name: Name to look up
            config: Optional configuration dict

        Returns:
            PackageMetadata if found, None otherwise
        """

    def prefetch(self, config: dict) -> None:
        """
        Optional batch pre-fetch hook, called once per refresh.

        Batch providers (batch=True) should override this to fetch
        all records upfront rather than making per-repo API calls.
        """

    def match(self, repo_path: str, repo_record: Optional[dict] = None,
              config: Optional[dict] = None) -> Optional[PackageMetadata]:
        """
        Main entry point: detect then check.

        Non-batch providers use the default detect-then-check flow.
        Batch providers should override this with their matching logic.

        Args:
            repo_path: Filesystem path to the repository
            repo_record: Optional dict of repo metadata
            config: Optional configuration dict

        Returns:
            PackageMetadata if matched and found, None otherwise
        """
        name = self.detect(repo_path, repo_record)
        if name:
            return self.check(name, config)
        return None


class PlatformProvider(ABC):
    """
    Abstract base class for hosting platform providers.

    Platform providers enrich repo-level metadata (stars, topics, forks, etc.)
    from hosting platforms like GitHub, GitLab, Codeberg.

    Unlike RegistryProvider (which creates publication entities in the publications
    table), PlatformProvider enriches the repo entity itself — its fields are
    merged into the repos table with a platform-specific prefix.

    Attributes:
        platform_id: Short identifier (e.g., "github", "gitlab")
        name: Human-readable name (e.g., "GitHub")
        prefix: Column prefix for repos table (e.g., "github" → github_stars)
    """
    platform_id: str = ""
    name: str = ""
    prefix: str = ""

    @abstractmethod
    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        """
        Detect whether this repo is hosted on this platform.

        Args:
            repo_path: Filesystem path to the repository
            repo_record: Optional dict with remote_url, owner, name

        Returns:
            True if this repo has a remote on this platform
        """

    @abstractmethod
    def enrich(self, repo_path: str, repo_record: Optional[dict] = None,
               config: Optional[dict] = None) -> Optional[dict]:
        """
        Fetch platform metadata for this repo.

        Args:
            repo_path: Filesystem path to the repository
            repo_record: Optional dict of repo metadata
            config: Optional configuration dict (auth tokens, etc.)

        Returns:
            Dict of {prefix}_* fields to merge into repos table, or None
        """


# Built-in provider module names (relative to repoindex.providers)
BUILTIN_PROVIDERS = [
    'pypi',
    'cran',
    'zenodo',
    'npm',
    'cargo',
    'conda',
    'docker',
    'rubygems',
    'go',
]


def discover_providers(
    user_dir: Optional[str] = None,
    only: Optional[List[str]] = None,
) -> List[RegistryProvider]:
    """
    Discover and load registry providers.

    Loads built-in providers from repoindex.providers.* and user
    providers from ~/.repoindex/providers/*.py.

    Args:
        user_dir: Override path for user providers (default: ~/.repoindex/providers/)
        only: If set, only load providers whose registry id is in this list

    Returns:
        List of RegistryProvider instances
    """
    providers: List[RegistryProvider] = []

    # Load built-in providers
    for module_name in BUILTIN_PROVIDERS:
        try:
            mod = importlib.import_module(f'.{module_name}', package='repoindex.providers')
            provider = getattr(mod, 'provider', None)
            if provider and isinstance(provider, RegistryProvider):
                if only is None or provider.registry in only:
                    providers.append(provider)
        except ImportError:
            logger.debug(f"Built-in provider module not found: {module_name}")
        except Exception as e:
            logger.warning(f"Failed to load built-in provider '{module_name}': {e}")

    # Load user providers
    if user_dir is None:
        user_dir = os.path.expanduser('~/.repoindex/providers')

    if os.path.isdir(user_dir):
        for filename in sorted(os.listdir(user_dir)):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue

            filepath = os.path.join(user_dir, filename)
            mod_name = filename[:-3]  # strip .py

            try:
                spec = importlib.util.spec_from_file_location(
                    f'repoindex_user_provider_{mod_name}', filepath
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    provider = getattr(mod, 'provider', None)
                    if provider and isinstance(provider, RegistryProvider):
                        if only is None or provider.registry in only:
                            providers.append(provider)
                            logger.info(f"Loaded user provider: {provider.registry} from {filepath}")
            except Exception as e:
                logger.warning(f"Failed to load user provider '{filepath}': {e}")

    return providers


# Built-in platform module names (relative to repoindex.providers)
BUILTIN_PLATFORMS = [
    'github',
]


def discover_platforms(
    user_dir: Optional[str] = None,
    only: Optional[List[str]] = None,
) -> List[PlatformProvider]:
    """
    Discover and load platform providers.

    Loads built-in platforms from repoindex.providers.* and user
    platforms from ~/.repoindex/providers/*.py.

    Args:
        user_dir: Override path for user providers (default: ~/.repoindex/providers/)
        only: If set, only load platforms whose platform_id is in this list

    Returns:
        List of PlatformProvider instances
    """
    platforms: List[PlatformProvider] = []

    # Load built-in platforms
    for module_name in BUILTIN_PLATFORMS:
        try:
            mod = importlib.import_module(f'.{module_name}', package='repoindex.providers')
            platform = getattr(mod, 'platform', None)
            if platform and isinstance(platform, PlatformProvider):
                if only is None or platform.platform_id in only:
                    platforms.append(platform)
        except ImportError:
            logger.debug(f"Built-in platform module not found: {module_name}")
        except Exception as e:
            logger.warning(f"Failed to load built-in platform '{module_name}': {e}")

    # Load user platforms
    if user_dir is None:
        user_dir = os.path.expanduser('~/.repoindex/providers')

    if os.path.isdir(user_dir):
        for filename in sorted(os.listdir(user_dir)):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue

            filepath = os.path.join(user_dir, filename)
            mod_name = filename[:-3]  # strip .py

            try:
                spec = importlib.util.spec_from_file_location(
                    f'repoindex_user_platform_{mod_name}', filepath
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    platform = getattr(mod, 'platform', None)
                    if platform and isinstance(platform, PlatformProvider):
                        if only is None or platform.platform_id in only:
                            platforms.append(platform)
                            logger.info(f"Loaded user platform: {platform.platform_id} from {filepath}")
            except Exception as e:
                logger.warning(f"Failed to load user platform '{filepath}': {e}")

    return platforms
