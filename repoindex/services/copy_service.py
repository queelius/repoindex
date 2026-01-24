"""
Copy service for repoindex.

Copies repositories to a destination directory with filtering support.
Useful for backups, redundancy, and organizing repos.
"""

import logging
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Generator, List, Optional

from ..config import load_config

logger = logging.getLogger(__name__)


class CollisionStrategy(Enum):
    """Strategy for handling name collisions when copying."""
    RENAME = "rename"      # Append -1, -2, etc.
    SKIP = "skip"          # Skip duplicate, report in results
    OVERWRITE = "overwrite"  # Replace existing


@dataclass
class CopyOptions:
    """Options for copy operation."""
    destination: Path
    exclude_git: bool = False
    preserve_structure: bool = False
    collision_strategy: CollisionStrategy = CollisionStrategy.RENAME
    dry_run: bool = False


@dataclass
class CopyResult:
    """Result of copy operation."""
    repos_copied: int = 0
    repos_skipped: int = 0
    bytes_copied: int = 0
    errors: List[str] = field(default_factory=list)
    details: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class CopyService:
    """
    Service for copying repositories to a destination.

    Supports filtering via query, collision handling, and structure preservation.

    Example:
        service = CopyService()
        options = CopyOptions(destination=Path("/tmp/backup"))

        for progress in service.copy(repos, options):
            print(progress)  # "Copying repo-name..."

        result = service.last_result
        print(f"Copied {result.repos_copied} repos")
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize CopyService.

        Args:
            config: Configuration dict (loads default if None)
        """
        self.config = config or load_config()
        self.last_result: Optional[CopyResult] = None

    def copy(
        self,
        repos: List[Dict[str, Any]],
        options: CopyOptions
    ) -> Generator[str, None, CopyResult]:
        """
        Copy repositories to destination.

        Yields progress messages, returns CopyResult.

        Args:
            repos: List of repository dicts (from query)
            options: Copy options

        Yields:
            Progress messages

        Returns:
            CopyResult with stats and any errors
        """
        result = CopyResult()
        self.last_result = result

        if not repos:
            yield "No repositories to copy"
            return result

        # Prepare output directory
        dest_dir = options.destination
        if not options.dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        # Track used names for collision detection
        used_names: Dict[str, int] = {}

        for repo in repos:
            repo_path = Path(repo.get('path', ''))
            repo_name = repo.get('name', repo_path.name)

            if not repo_path.exists():
                result.errors.append(f"Repository not found: {repo_path}")
                continue

            yield f"Copying {repo_name}..."

            try:
                # Determine destination path
                if options.preserve_structure:
                    # Keep parent directory structure
                    # e.g., ~/github/beta/repo -> backup/github/beta/repo
                    relative_path = self._get_relative_path(repo_path)
                    target_path = dest_dir / relative_path
                else:
                    # Flat structure
                    target_name = self._resolve_collision(
                        repo_name, dest_dir, used_names, options.collision_strategy
                    )
                    if target_name is None:
                        # Skip this repo
                        result.repos_skipped += 1
                        result.details.append({
                            'path': str(repo_path),
                            'name': repo_name,
                            'status': 'skipped',
                            'reason': 'collision'
                        })
                        continue
                    target_path = dest_dir / target_name

                # Actually copy if not dry run
                if not options.dry_run:
                    bytes_copied = self._copy_repo(
                        repo_path, target_path, options.exclude_git
                    )
                    result.bytes_copied += bytes_copied
                else:
                    bytes_copied = self._estimate_size(repo_path, options.exclude_git)
                    result.bytes_copied += bytes_copied

                result.repos_copied += 1
                result.details.append({
                    'path': str(repo_path),
                    'name': repo_name,
                    'target': str(target_path),
                    'status': 'copied',
                    'bytes': bytes_copied
                })

            except Exception as e:
                logger.error(f"Failed to copy {repo_name}: {e}")
                result.errors.append(f"{repo_name}: {str(e)}")
                result.details.append({
                    'path': str(repo_path),
                    'name': repo_name,
                    'status': 'error',
                    'error': str(e)
                })

        return result

    def _get_relative_path(self, repo_path: Path) -> Path:
        """Get relative path from home directory."""
        try:
            return repo_path.relative_to(Path.home())
        except ValueError:
            # Not under home, use the last 2 directory components
            parts = repo_path.parts
            if len(parts) >= 2:
                return Path(*parts[-2:])
            return Path(repo_path.name)

    def _resolve_collision(
        self,
        name: str,
        dest_dir: Path,
        used_names: Dict[str, int],
        strategy: CollisionStrategy
    ) -> Optional[str]:
        """
        Resolve name collision based on strategy.

        Returns:
            Resolved name, or None if should skip
        """
        target_path = dest_dir / name

        # Check if name is already used in this batch
        if name in used_names:
            if strategy == CollisionStrategy.SKIP:
                return None
            elif strategy == CollisionStrategy.RENAME:
                counter = used_names[name]
                while True:
                    counter += 1
                    new_name = f"{name}-{counter}"
                    if new_name not in used_names and not (dest_dir / new_name).exists():
                        used_names[name] = counter
                        used_names[new_name] = 0
                        return new_name
            else:  # OVERWRITE
                return name

        # Check if already exists on disk
        if target_path.exists():
            if strategy == CollisionStrategy.SKIP:
                return None
            elif strategy == CollisionStrategy.RENAME:
                counter = 0
                while True:
                    counter += 1
                    new_name = f"{name}-{counter}"
                    if not (dest_dir / new_name).exists():
                        used_names[new_name] = 0
                        return new_name
            else:  # OVERWRITE
                used_names[name] = 0
                return name

        used_names[name] = 0
        return name

    def _copy_repo(
        self,
        source: Path,
        dest: Path,
        exclude_git: bool
    ) -> int:
        """
        Copy a repository directory.

        Returns:
            Bytes copied
        """
        bytes_copied = 0

        def ignore_patterns(directory: str, files: List[str]) -> List[str]:
            """Return files to ignore during copy."""
            if exclude_git and '.git' in files:
                return ['.git']
            return []

        # Create parent directories
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing if present (for overwrite)
        if dest.exists():
            shutil.rmtree(dest)

        # Copy with ignore function
        shutil.copytree(
            source,
            dest,
            ignore=ignore_patterns if exclude_git else None,
            dirs_exist_ok=False
        )

        # Calculate bytes copied
        bytes_copied = self._get_dir_size(dest)
        return bytes_copied

    def _estimate_size(self, path: Path, exclude_git: bool) -> int:
        """Estimate size of directory (for dry run)."""
        return self._get_dir_size(path, exclude_git)

    def _get_dir_size(self, path: Path, exclude_git: bool = False) -> int:
        """Get total size of a directory in bytes."""
        total = 0
        try:
            for entry in path.rglob('*'):
                if exclude_git and '.git' in entry.parts:
                    continue
                if entry.is_file():
                    try:
                        total += entry.stat().st_size
                    except (OSError, IOError):
                        pass
        except (OSError, IOError):
            pass
        return total
