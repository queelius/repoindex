"""Python-version / dependency compatibility shims for repoindex.

Centralizes the ``tomllib`` (stdlib, 3.11+) vs ``tomli`` (backport) dance
so callers can just ``from repoindex.compat import tomllib`` without
repeating the try/except at every use site.
"""

try:
    import tomllib
except ImportError:  # Python 3.8-3.10
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = ['tomllib']
