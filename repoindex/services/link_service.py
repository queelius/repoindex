"""
Link service for repoindex.

Creates and manages symlink trees organized by metadata (tags, language, etc.).
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Generator, List, Optional, Set

from ..config import load_config

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = '.repoindex-links.json'


class OrganizeBy(Enum):
    """Methods for organizing symlink trees."""
    TAG = "tag"
    LANGUAGE = "language"
    CREATED_YEAR = "created-year"
    MODIFIED_YEAR = "modified-year"
    OWNER = "owner"


@dataclass
class LinkTreeOptions:
    """Options for symlink tree creation."""
    destination: Path
    organize_by: OrganizeBy
    max_depth: int = 10
    collision_strategy: str = "rename"
    dry_run: bool = False


@dataclass
class LinkTreeResult:
    """Result of symlink tree operation."""
    links_created: int = 0
    links_updated: int = 0
    links_skipped: int = 0
    dirs_created: int = 0
    errors: List[str] = field(default_factory=list)
    details: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class RefreshResult:
    """Result of refresh/status operation."""
    total_links: int = 0
    valid_links: int = 0
    broken_links: int = 0
    removed_links: int = 0
    errors: List[str] = field(default_factory=list)
    broken_paths: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class LinkService:
    """
    Service for creating and managing symlink trees.

    Creates hierarchical symlink structures organized by metadata.
    Repos can appear in multiple locations (e.g., multiple tags).

    Example:
        service = LinkService()
        options = LinkTreeOptions(
            destination=Path("/tmp/links"),
            organize_by=OrganizeBy.TAG
        )

        for progress in service.create_tree(repos, options):
            print(progress)  # "Creating links for repo-name..."

        result = service.last_result
        print(f"Created {result.links_created} links")
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize LinkService.

        Args:
            config: Configuration dict (loads default if None)
        """
        self.config = config or load_config()
        self.last_result: Optional[LinkTreeResult] = None
        self.last_refresh_result: Optional[RefreshResult] = None
        self._version = self._get_version()

    def _get_version(self) -> str:
        """Get repoindex version."""
        try:
            from .. import __version__
            return __version__
        except ImportError:
            return "unknown"

    def create_tree(
        self,
        repos: List[Dict[str, Any]],
        options: LinkTreeOptions
    ) -> Generator[str, None, LinkTreeResult]:
        """
        Create symlink tree organized by metadata.

        Yields progress messages, returns LinkTreeResult.

        Args:
            repos: List of repository dicts (from query)
            options: Link tree options

        Yields:
            Progress messages

        Returns:
            LinkTreeResult with stats and any errors
        """
        result = LinkTreeResult()
        self.last_result = result

        if not repos:
            yield "No repositories to link"
            return result

        dest_dir = options.destination

        # Create destination directory
        if not options.dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            result.dirs_created += 1

        # Track used link paths for collision detection
        used_paths: Set[str] = set()

        for repo in repos:
            repo_path = Path(repo.get('path', ''))
            repo_name = repo.get('name', repo_path.name)

            if not repo_path.exists():
                result.errors.append(f"Repository not found: {repo_path}")
                continue

            yield f"Creating links for {repo_name}..."

            try:
                # Get target paths based on organization method
                target_paths = self._get_target_paths(repo, options)

                for rel_path in target_paths:
                    link_path = dest_dir / rel_path / repo_name

                    # Handle collision
                    final_link_path = self._resolve_link_collision(
                        link_path, used_paths, options.collision_strategy
                    )

                    if final_link_path is None:
                        result.links_skipped += 1
                        continue

                    used_paths.add(str(final_link_path))

                    if not options.dry_run:
                        # Create parent directories
                        final_link_path.parent.mkdir(parents=True, exist_ok=True)

                        # Create or update symlink
                        if final_link_path.is_symlink():
                            if final_link_path.resolve() != repo_path:
                                final_link_path.unlink()
                                final_link_path.symlink_to(repo_path)
                                result.links_updated += 1
                            else:
                                # Already correct
                                pass
                        elif final_link_path.exists():
                            result.errors.append(
                                f"Path exists and is not a symlink: {final_link_path}"
                            )
                            continue
                        else:
                            final_link_path.symlink_to(repo_path)
                            result.links_created += 1

                        result.details.append({
                            'repo': repo_name,
                            'path': str(repo_path),
                            'link': str(final_link_path),
                            'relative_path': str(rel_path),
                            'status': 'created'
                        })
                    else:
                        result.links_created += 1
                        result.details.append({
                            'repo': repo_name,
                            'path': str(repo_path),
                            'link': str(final_link_path),
                            'relative_path': str(rel_path),
                            'status': 'would_create'
                        })

            except Exception as e:
                logger.error(f"Failed to create links for {repo_name}: {e}")
                result.errors.append(f"{repo_name}: {str(e)}")

        # Write manifest
        if not options.dry_run:
            self._write_manifest(dest_dir, repos, options, result)

        return result

    def _get_target_paths(
        self,
        repo: Dict[str, Any],
        options: LinkTreeOptions
    ) -> List[Path]:
        """
        Get target directory paths based on organization method.

        Returns list of relative paths (a repo can appear in multiple places).
        """
        organize_by = options.organize_by
        paths = []

        if organize_by == OrganizeBy.TAG:
            tags = repo.get('tags', [])
            if not tags:
                paths.append(Path('untagged'))
            else:
                for tag in tags:
                    tag_path = self._parse_tag_path(tag)
                    if tag_path:
                        paths.append(tag_path)

        elif organize_by == OrganizeBy.LANGUAGE:
            language = repo.get('language') or 'Unknown'
            paths.append(Path(self._safe_dirname(language)))

        elif organize_by == OrganizeBy.CREATED_YEAR:
            # Use first commit date if available
            created_at = repo.get('created_at') or repo.get('github_created_at')
            if created_at:
                year = str(created_at)[:4]
                paths.append(Path(year))
            else:
                paths.append(Path('unknown'))

        elif organize_by == OrganizeBy.MODIFIED_YEAR:
            # Use last commit date if available
            updated_at = repo.get('updated_at') or repo.get('github_pushed_at')
            if updated_at:
                year = str(updated_at)[:4]
                paths.append(Path(year))
            else:
                paths.append(Path('unknown'))

        elif organize_by == OrganizeBy.OWNER:
            # Extract owner from remote URL or use directory
            remote_url = repo.get('remote_url', '')
            owner = self._extract_owner(remote_url)
            if owner:
                paths.append(Path(self._safe_dirname(owner)))
            else:
                # Fall back to parent directory name
                parent = Path(repo.get('path', '')).parent.name
                paths.append(Path(self._safe_dirname(parent or 'unknown')))

        # Limit depth
        limited_paths = []
        for p in paths:
            parts = list(p.parts)[:options.max_depth]
            if parts:
                limited_paths.append(Path(*parts))
            else:
                limited_paths.append(Path('.'))

        return limited_paths if limited_paths else [Path('.')]

    def _parse_tag_path(self, tag: str) -> Optional[Path]:
        """
        Parse a tag into a hierarchical path.

        Examples:
            "topic:ml/research" -> Path("topic/ml/research")
            "alex/beta" -> Path("alex/beta")
            "simple" -> Path("simple")
        """
        if not tag:
            return None

        parts = []

        if ':' in tag:
            key, value = tag.split(':', 1)
            parts.append(self._safe_dirname(key))
            if value:
                if '/' in value:
                    parts.extend(self._safe_dirname(p) for p in value.split('/') if p)
                else:
                    parts.append(self._safe_dirname(value))
        elif '/' in tag:
            parts = [self._safe_dirname(p) for p in tag.split('/') if p]
        else:
            parts = [self._safe_dirname(tag)]

        return Path(*parts) if parts else None

    def _extract_owner(self, remote_url: str) -> Optional[str]:
        """Extract owner from git remote URL."""
        import re

        if not remote_url:
            return None

        # GitHub/GitLab style URLs
        match = re.search(r'[:/]([^/]+)/[^/]+(?:\.git)?$', remote_url)
        if match:
            return match.group(1)

        return None

    def _safe_dirname(self, name: str) -> str:
        """Convert a name to a safe directory name."""
        safe = name.replace('/', '_').replace('\\', '_').replace(':', '_')
        safe = safe.replace('<', '_').replace('>', '_').replace('"', '_')
        safe = safe.replace('|', '_').replace('?', '_').replace('*', '_')
        safe = safe.strip('.')  # Remove leading/trailing dots
        return safe or 'unnamed'

    def _resolve_link_collision(
        self,
        link_path: Path,
        used_paths: Set[str],
        strategy: str
    ) -> Optional[Path]:
        """
        Resolve link path collision.

        Returns final path or None if should skip.
        """
        if str(link_path) not in used_paths and not link_path.exists():
            return link_path

        if strategy == "skip":
            return None

        # Rename strategy
        counter = 0
        while True:
            counter += 1
            new_path = link_path.parent / f"{link_path.name}-{counter}"
            if str(new_path) not in used_paths and not new_path.exists():
                return new_path
            if counter > 1000:
                return None  # Give up after too many attempts

    def _write_manifest(
        self,
        dest_dir: Path,
        repos: List[Dict[str, Any]],
        options: LinkTreeOptions,
        result: LinkTreeResult
    ) -> None:
        """Write manifest file for the link tree."""
        manifest = {
            "created_at": datetime.now().isoformat(),
            "organize_by": options.organize_by.value,
            "repos_count": len(repos),
            "links_created": result.links_created,
            "repoindex_version": self._version,
        }

        manifest_path = dest_dir / MANIFEST_FILENAME
        manifest_path.write_text(json.dumps(manifest, indent=2))

    def refresh_tree(
        self,
        tree_path: Path,
        prune: bool = False,
        dry_run: bool = False
    ) -> Generator[str, None, RefreshResult]:
        """
        Refresh an existing link tree.

        Checks for broken symlinks and optionally removes them.

        Args:
            tree_path: Path to the link tree root
            prune: Whether to remove broken links
            dry_run: Whether to just report without making changes

        Yields:
            Progress messages

        Returns:
            RefreshResult with stats
        """
        result = RefreshResult()
        self.last_refresh_result = result

        if not tree_path.exists():
            result.errors.append(f"Tree path does not exist: {tree_path}")
            yield f"Error: {result.errors[-1]}"
            return result

        yield f"Scanning {tree_path}..."

        # Find all symlinks
        for path in tree_path.rglob('*'):
            if path.is_symlink():
                result.total_links += 1
                target = path.resolve()

                if target.exists():
                    result.valid_links += 1
                else:
                    result.broken_links += 1
                    result.broken_paths.append(str(path))

                    if prune:
                        yield f"Removing broken link: {path.name}"
                        if not dry_run:
                            path.unlink()
                            result.removed_links += 1

        return result

    def get_tree_status(
        self,
        tree_path: Path
    ) -> Generator[str, None, RefreshResult]:
        """
        Get status of an existing link tree (non-modifying).

        Args:
            tree_path: Path to the link tree root

        Yields:
            Progress messages

        Returns:
            RefreshResult with stats
        """
        return self.refresh_tree(tree_path, prune=False, dry_run=True)
