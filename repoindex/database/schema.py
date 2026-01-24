"""
Database schema for repoindex.

This module defines the SQLite schema and handles migrations.
The schema is designed to:
- Store repository metadata efficiently
- Support fast queries with proper indexing
- Enable cross-domain queries (repos + events + tags)
- Track historical snapshots for trending analysis
"""

import sqlite3
from typing import List, Tuple

# Current schema version - increment when schema changes
# v1: Initial schema
# v2: Renamed GitHub fields with github_ prefix for explicit provenance
# v3: Added citation detection (has_citation, citation_file)
# v4: Added citation metadata parsing (citation_doi, citation_title, etc.)
CURRENT_VERSION = 4

# Schema definition as SQL statements
SCHEMA_V1 = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS _schema_info (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- Core repositories table
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT UNIQUE NOT NULL,

    -- Git info
    branch TEXT,
    remote_url TEXT,
    is_clean BOOLEAN DEFAULT 1,
    ahead INTEGER DEFAULT 0,
    behind INTEGER DEFAULT 0,
    has_upstream BOOLEAN DEFAULT 0,
    uncommitted_changes BOOLEAN DEFAULT 0,
    untracked_files INTEGER DEFAULT 0,

    -- Owner (derived from remote_url)
    owner TEXT,

    -- Metadata
    language TEXT,
    languages TEXT,  -- JSON array of all languages
    description TEXT,
    readme_content TEXT,  -- For full-text search

    -- License info
    license_key TEXT,
    license_name TEXT,
    license_file TEXT,

    -- GitHub metadata (nullable, fetched via --enrich-github)
    -- All fields prefixed with github_ for explicit provenance
    github_owner TEXT,
    github_name TEXT,
    github_description TEXT,
    github_stars INTEGER DEFAULT 0,
    github_forks INTEGER DEFAULT 0,
    github_watchers INTEGER DEFAULT 0,
    github_open_issues INTEGER DEFAULT 0,
    github_is_fork BOOLEAN DEFAULT 0,
    github_is_private BOOLEAN DEFAULT 0,
    github_is_archived BOOLEAN DEFAULT 0,
    github_has_issues BOOLEAN DEFAULT 1,
    github_has_wiki BOOLEAN DEFAULT 1,
    github_has_pages BOOLEAN DEFAULT 0,
    github_pages_url TEXT,
    github_topics TEXT,  -- JSON array

    -- Flags (computed)
    has_readme BOOLEAN DEFAULT 0,
    has_license BOOLEAN DEFAULT 0,
    has_ci BOOLEAN DEFAULT 0,

    -- Citation detection (local files: CITATION.cff, .zenodo.json, CITATION.bib)
    has_citation BOOLEAN DEFAULT 0,
    citation_file TEXT,

    -- Citation metadata (parsed from CITATION.cff, .zenodo.json)
    citation_doi TEXT,           -- DOI identifier (e.g., "10.5281/zenodo.1234567")
    citation_title TEXT,         -- Software title from citation file
    citation_authors TEXT,       -- JSON array of author objects
    citation_version TEXT,       -- Version from citation file
    citation_repository TEXT,    -- Repository URL from citation file
    citation_license TEXT,       -- License from citation file

    -- GitHub timestamps (nullable, fetched via --enrich-github)
    github_created_at TIMESTAMP,
    github_updated_at TIMESTAMP,
    github_pushed_at TIMESTAMP,

    -- Local scan timestamp
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- For smart refresh (mtime of .git/index)
    git_index_mtime REAL
);

-- Tags table (user-assigned and implicit)
CREATE TABLE IF NOT EXISTS tags (
    repo_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    source TEXT DEFAULT 'user',  -- 'user', 'implicit', 'github'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (repo_id, tag),
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
);

-- Events table (git activity, releases, etc.)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    event_id TEXT UNIQUE,  -- Stable ID for deduplication
    type TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    ref TEXT,  -- Branch/tag name
    message TEXT,
    author TEXT,
    metadata TEXT,  -- JSON for type-specific data
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
);

-- Publications table (PyPI, npm, CRAN, etc.)
CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    registry TEXT NOT NULL,  -- 'pypi', 'npm', 'cran', 'cargo', 'docker'
    package_name TEXT NOT NULL,
    current_version TEXT,
    published BOOLEAN DEFAULT 0,
    url TEXT,
    downloads_total INTEGER,
    downloads_30d INTEGER,
    last_published TIMESTAMP,
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (repo_id, registry),
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
);

-- Scan errors (track failed repos during refresh)
CREATE TABLE IF NOT EXISTS scan_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    error_type TEXT NOT NULL,  -- 'permission', 'corrupt', 'not_git', 'git_error'
    error_message TEXT,
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_repos_name ON repos(name);
CREATE INDEX IF NOT EXISTS idx_repos_language ON repos(language);
CREATE INDEX IF NOT EXISTS idx_repos_owner ON repos(owner);
CREATE INDEX IF NOT EXISTS idx_repos_github_updated ON repos(github_updated_at);
CREATE INDEX IF NOT EXISTS idx_repos_github_stars ON repos(github_stars);
CREATE INDEX IF NOT EXISTS idx_repos_scanned ON repos(scanned_at);
CREATE INDEX IF NOT EXISTS idx_repos_citation_doi ON repos(citation_doi);

CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
CREATE INDEX IF NOT EXISTS idx_tags_source ON tags(source);

CREATE INDEX IF NOT EXISTS idx_events_repo ON events(repo_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_repo_type_ts ON events(repo_id, type, timestamp);

CREATE INDEX IF NOT EXISTS idx_publications_registry ON publications(registry);
CREATE INDEX IF NOT EXISTS idx_publications_package ON publications(package_name);

CREATE INDEX IF NOT EXISTS idx_scan_errors_path ON scan_errors(path);

-- Full-text search on repos (name, description, readme)
CREATE VIRTUAL TABLE IF NOT EXISTS repos_fts USING fts5(
    name,
    description,
    readme_content,
    content='repos',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS repos_fts_insert AFTER INSERT ON repos BEGIN
    INSERT INTO repos_fts(rowid, name, description, readme_content)
    VALUES (NEW.id, NEW.name, NEW.description, NEW.readme_content);
END;

CREATE TRIGGER IF NOT EXISTS repos_fts_delete AFTER DELETE ON repos BEGIN
    INSERT INTO repos_fts(repos_fts, rowid, name, description, readme_content)
    VALUES ('delete', OLD.id, OLD.name, OLD.description, OLD.readme_content);
END;

CREATE TRIGGER IF NOT EXISTS repos_fts_update AFTER UPDATE ON repos BEGIN
    INSERT INTO repos_fts(repos_fts, rowid, name, description, readme_content)
    VALUES ('delete', OLD.id, OLD.name, OLD.description, OLD.readme_content);
    INSERT INTO repos_fts(rowid, name, description, readme_content)
    VALUES (NEW.id, NEW.name, NEW.description, NEW.readme_content);
END;

-- Computed views for common queries

-- Active repos (committed to in last 30 days)
CREATE VIEW IF NOT EXISTS v_active_repos AS
SELECT DISTINCT r.*
FROM repos r
WHERE EXISTS (
    SELECT 1 FROM events e
    WHERE e.repo_id = r.id
    AND e.type = 'commit'
    AND e.timestamp > datetime('now', '-30 days')
);

-- Stale repos (no commits in 180 days)
CREATE VIEW IF NOT EXISTS v_stale_repos AS
SELECT r.*
FROM repos r
WHERE NOT EXISTS (
    SELECT 1 FROM events e
    WHERE e.repo_id = r.id
    AND e.type = 'commit'
    AND e.timestamp > datetime('now', '-180 days')
);

-- Repo stats view (aggregated metrics)
CREATE VIEW IF NOT EXISTS v_repo_stats AS
SELECT
    r.id as repo_id,
    r.name,
    r.language,
    r.github_stars,
    r.github_forks,
    COALESCE(commits_30d.cnt, 0) as commits_30d,
    COALESCE(commits_90d.cnt, 0) as commits_90d,
    COALESCE(tags_90d.cnt, 0) as tags_90d,
    MAX(CASE WHEN e.type = 'commit' THEN e.timestamp END) as last_commit,
    MAX(CASE WHEN e.type = 'git_tag' THEN e.timestamp END) as last_tag,
    CASE
        WHEN MAX(CASE WHEN e.type = 'commit' THEN e.timestamp END) > datetime('now', '-30 days') THEN 'active'
        WHEN MAX(CASE WHEN e.type = 'commit' THEN e.timestamp END) > datetime('now', '-180 days') THEN 'maintained'
        ELSE 'stale'
    END as activity_status
FROM repos r
LEFT JOIN events e ON e.repo_id = r.id
LEFT JOIN (
    SELECT repo_id, COUNT(*) as cnt
    FROM events
    WHERE type = 'commit' AND timestamp > datetime('now', '-30 days')
    GROUP BY repo_id
) commits_30d ON commits_30d.repo_id = r.id
LEFT JOIN (
    SELECT repo_id, COUNT(*) as cnt
    FROM events
    WHERE type = 'commit' AND timestamp > datetime('now', '-90 days')
    GROUP BY repo_id
) commits_90d ON commits_90d.repo_id = r.id
LEFT JOIN (
    SELECT repo_id, COUNT(*) as cnt
    FROM events
    WHERE type = 'git_tag' AND timestamp > datetime('now', '-90 days')
    GROUP BY repo_id
) tags_90d ON tags_90d.repo_id = r.id
GROUP BY r.id;
"""


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Get current schema version from database."""
    try:
        cursor = conn.execute(
            "SELECT MAX(version) FROM _schema_info"
        )
        result = cursor.fetchone()
        return result[0] if result[0] is not None else 0
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return 0


def apply_schema(conn: sqlite3.Connection, version: int = CURRENT_VERSION) -> None:
    """
    Apply schema to database.

    Since repoindex is a cache that can be rebuilt from the filesystem,
    we simply drop and recreate if the schema version doesn't match.
    The database is ephemeral - the ground truth is in local git repos.
    """
    current = get_schema_version(conn)

    # If schema version mismatch, drop everything and recreate
    # No complex migration needed - this is just a cache
    if current != 0 and current < CURRENT_VERSION:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Schema version {current} -> {CURRENT_VERSION}, rebuilding cache")

        # Drop all tables (cascade will handle FKs)
        conn.executescript("""
            DROP TABLE IF EXISTS repos_fts;
            DROP TABLE IF EXISTS tags;
            DROP TABLE IF EXISTS events;
            DROP TABLE IF EXISTS publications;
            DROP TABLE IF EXISTS scan_errors;
            DROP TABLE IF EXISTS repos;
            DROP TABLE IF EXISTS _schema_info;
        """)

    # Apply current schema
    conn.executescript(SCHEMA_V1)
    conn.execute(
        "INSERT OR REPLACE INTO _schema_info (version, description) VALUES (?, ?)",
        (CURRENT_VERSION, "v0.10.0: Added citation metadata parsing (citation_doi, citation_title, etc.)")
    )

    conn.commit()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure database has current schema, migrating if necessary."""
    current = get_schema_version(conn)

    if current < CURRENT_VERSION:
        apply_schema(conn, CURRENT_VERSION)


def get_migrations() -> List[Tuple[int, str, str]]:
    """
    Get list of migrations.

    Returns:
        List of (version, description, sql) tuples
    """
    # For now, just the initial schema
    # Future migrations would be added here
    return [
        (1, "Initial schema", SCHEMA_V1),
    ]
