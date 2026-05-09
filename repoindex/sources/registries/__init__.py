"""Built-in Registry sources.

Each module here exposes a module-level ``source`` attribute that is an
instance of a ``Registry`` subclass. Registries publish packaged
artifacts (PyPI wheels, CRAN tarballs, npm tarballs, etc.) and
contribute rows to the ``publications`` table during refresh.
"""
