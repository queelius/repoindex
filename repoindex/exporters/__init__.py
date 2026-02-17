"""
Exporter extension system for repoindex.

Defines the Exporter interface for rendering repository data to
various output formats (BibTeX, CSV, Markdown, OPML, JSON-LD, etc.).

User-provided exporters can be placed in ~/.repoindex/exporters/*.py,
each exporting a module-level `exporter` attribute.
"""

import importlib
import importlib.util
import logging
import os
from abc import ABC, abstractmethod
from typing import IO, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ['Exporter', 'discover_exporters']


class Exporter(ABC):
    """
    Abstract base class for format exporters.

    Each exporter renders a list of repository dicts to a specific
    output format, writing to a file-like stream.

    Attributes:
        format_id: CLI identifier (e.g., "bibtex", "csv")
        name: Human-readable name (e.g., "BibTeX Citations")
        extension: Default file extension (e.g., ".bib")
    """
    format_id: str = ""
    name: str = ""
    extension: str = ""

    @abstractmethod
    def export(self, repos: List[dict], output: IO[str],
               config: Optional[dict] = None) -> int:
        """
        Write repos to output stream.

        Args:
            repos: List of repository dicts (from database rows)
            output: Writable text stream (stdout or file)
            config: Optional configuration dict

        Returns:
            Number of records rendered
        """


# Built-in exporter module names
BUILTIN_EXPORTERS = [
    'bibtex',
    'csv_exporter',
    'markdown',
    'opml',
    'jsonld',
    'arkiv',
]


def discover_exporters(
    user_dir: Optional[str] = None,
    only: Optional[List[str]] = None,
) -> Dict[str, Exporter]:
    """
    Discover and load format exporters.

    Args:
        user_dir: Override path for user exporters (default: ~/.repoindex/exporters/)
        only: If set, only load exporters whose format_id is in this list

    Returns:
        Dict mapping format_id to Exporter instance
    """
    exporters: Dict[str, Exporter] = {}

    # Load built-in exporters
    for module_name in BUILTIN_EXPORTERS:
        try:
            mod = importlib.import_module(f'.{module_name}', package='repoindex.exporters')
            exp = getattr(mod, 'exporter', None)
            if exp and isinstance(exp, Exporter):
                if only is None or exp.format_id in only:
                    exporters[exp.format_id] = exp
        except ImportError:
            logger.debug(f"Built-in exporter module not found: {module_name}")
        except Exception as e:
            logger.warning(f"Failed to load built-in exporter '{module_name}': {e}")

    # Load user exporters
    if user_dir is None:
        user_dir = os.path.expanduser('~/.repoindex/exporters')

    if os.path.isdir(user_dir):
        for filename in sorted(os.listdir(user_dir)):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue

            filepath = os.path.join(user_dir, filename)
            mod_name = filename[:-3]

            try:
                spec = importlib.util.spec_from_file_location(
                    f'repoindex_user_exporter_{mod_name}', filepath
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    exp = getattr(mod, 'exporter', None)
                    if exp and isinstance(exp, Exporter):
                        if only is None or exp.format_id in only:
                            exporters[exp.format_id] = exp
                            logger.info(f"Loaded user exporter: {exp.format_id} from {filepath}")
            except Exception as e:
                logger.warning(f"Failed to load user exporter '{filepath}': {e}")

    return exporters
