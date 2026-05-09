"""Built-in GitForge sources.

Each module here exposes a module-level ``source`` attribute that is an
instance of a ``GitForge`` subclass. Forges host git repositories and
expose APIs for both metadata reads (fetch()) and write actions
(set_topics, set_archived, etc.). Output of fetch() goes to the
``repos`` table.
"""
