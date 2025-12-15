"""
File store infrastructure for repoindex.

Provides JSON/YAML file persistence with:
- Atomic writes (write to temp, then rename)
- Pretty formatting for human readability
- Thread-safe operations
- Automatic parent directory creation
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class FileStore:
    """
    JSON file persistence with atomic writes.

    Example:
        store = FileStore(Path("~/.repoindex/metadata.json"))
        store.set("repo:/path/to/repo", {"name": "myrepo", ...})
        data = store.get("repo:/path/to/repo")
    """

    def __init__(self, path: Path, auto_create: bool = True):
        """
        Initialize FileStore.

        Args:
            path: Path to JSON file
            auto_create: Create file and parent directories if they don't exist
        """
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.Lock()
        self._cache: Optional[Dict[str, Any]] = None

        if auto_create:
            self._ensure_exists()

    def _ensure_exists(self) -> None:
        """Create file and parent directories if needed."""
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            self._write_atomic({})

    def _write_atomic(self, data: Dict[str, Any]) -> None:
        """Write data atomically using temp file and rename."""
        # Write to temp file in same directory
        fd, temp_path = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp"
        )

        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write('\n')  # Trailing newline

            # Atomic rename
            os.replace(temp_path, self.path)

        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def read(self) -> Dict[str, Any]:
        """
        Read entire store.

        Returns:
            Dictionary with all stored data
        """
        with self._lock:
            if self._cache is not None:
                return self._cache.copy()

            try:
                if self.path.exists():
                    with open(self.path, 'r') as f:
                        self._cache = json.load(f)
                        return self._cache.copy()
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error reading {self.path}: {e}")

            self._cache = {}
            return {}

    def write(self, data: Dict[str, Any]) -> None:
        """
        Write entire store.

        Args:
            data: Dictionary to write
        """
        with self._lock:
            self._write_atomic(data)
            self._cache = data.copy()

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get single value.

        Args:
            key: Key to retrieve
            default: Default value if not found

        Returns:
            Value or default
        """
        data = self.read()
        return data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set single value.

        Args:
            key: Key to set
            value: Value to store
        """
        with self._lock:
            data = self.read()
            data[key] = value
            self._write_atomic(data)
            self._cache = data

    def delete(self, key: str) -> bool:
        """
        Delete a key.

        Args:
            key: Key to delete

        Returns:
            True if key was deleted, False if not found
        """
        with self._lock:
            data = self.read()
            if key in data:
                del data[key]
                self._write_atomic(data)
                self._cache = data
                return True
            return False

    def has(self, key: str) -> bool:
        """Check if key exists."""
        return key in self.read()

    def keys(self) -> list:
        """Get all keys."""
        return list(self.read().keys())

    def values(self) -> list:
        """Get all values."""
        return list(self.read().values())

    def items(self):
        """Get all key-value pairs."""
        return self.read().items()

    def clear(self) -> None:
        """Clear all data."""
        self.write({})

    def invalidate_cache(self) -> None:
        """Invalidate in-memory cache, forcing next read from disk."""
        with self._lock:
            self._cache = None

    def update(self, updates: Dict[str, Any]) -> None:
        """
        Update multiple keys.

        Args:
            updates: Dictionary of key-value pairs to update
        """
        with self._lock:
            data = self.read()
            data.update(updates)
            self._write_atomic(data)
            self._cache = data

    def __len__(self) -> int:
        return len(self.read())

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __getitem__(self, key: str) -> Any:
        data = self.read()
        return data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        if not self.delete(key):
            raise KeyError(key)
