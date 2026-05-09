"""Built-in LocalScanner sources.

Each module here exposes a module-level ``source`` attribute that is an
instance of a ``LocalScanner`` subclass. They read files inside the
local repository (no network, no auth) and contribute fields to the
``repos`` table during refresh.
"""
