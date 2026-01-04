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
CURRENT_VERSION = 1

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

    -- GitHub metadata (nullable, fetched on demand)
    github_owner TEXT,
    github_name TEXT,
    github_description TEXT,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    watchers INTEGER DEFAULT 0,
    open_issues INTEGER DEFAULT 0,
    is_fork BOOLEAN DEFAULT 0,
    is_private BOOLEAN DEFAULT 0,
    is_archived BOOLEAN DEFAULT 0,
    has_issues BOOLEAN DEFAULT 1,
    has_wiki BOOLEAN DEFAULT 1,
    has_pages BOOLEAN DEFAULT 0,
    pages_url TEXT,
    topics TEXT,  -- JSON array

    -- Flags (computed)
    has_readme BOOLEAN DEFAULT 0,
    has_license BOOLEAN DEFAULT 0,
    has_ci BOOLEAN DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    pushed_at TIMESTAMP,
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

-- Dependencies table (extracted from package manifests)
CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    package_name TEXT NOT NULL,
    package_registry TEXT,  -- 'pypi', 'npm', etc.
    version_spec TEXT,
    dep_type TEXT DEFAULT 'runtime',  -- 'runtime', 'dev', 'optional'
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
);

-- Historical snapshots (for trending analysis)
CREATE TABLE IF NOT EXISTS repo_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    captured_at DATE NOT NULL,
    stars INTEGER,
    forks INTEGER,
    open_issues INTEGER,
    UNIQUE (repo_id, captured_at),
    FOREIGN KEY (repo_id) REFERENCES repos(id) ON DELETE CASCADE
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_repos_name ON repos(name);
CREATE INDEX IF NOT EXISTS idx_repos_language ON repos(language);
CREATE INDEX IF NOT EXISTS idx_repos_owner ON repos(owner);
CREATE INDEX IF NOT EXISTS idx_repos_updated ON repos(updated_at);
CREATE INDEX IF NOT EXISTS idx_repos_stars ON repos(stars);
CREATE INDEX IF NOT EXISTS idx_repos_scanned ON repos(scanned_at);

CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
CREATE INDEX IF NOT EXISTS idx_tags_source ON tags(source);

CREATE INDEX IF NOT EXISTS idx_events_repo ON events(repo_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_repo_type_ts ON events(repo_id, type, timestamp);

CREATE INDEX IF NOT EXISTS idx_publications_registry ON publications(registry);
CREATE INDEX IF NOT EXISTS idx_publications_package ON publications(package_name);

CREATE INDEX IF NOT EXISTS idx_dependencies_package ON dependencies(package_name);
CREATE INDEX IF NOT EXISTS idx_dependencies_repo ON dependencies(repo_id);

CREATE INDEX IF NOT EXISTS idx_snapshots_repo ON repo_snapshots(repo_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON repo_snapshots(captured_at);

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
    r.stars,
    r.forks,
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
    """Apply schema to database."""
    # For now, just apply V1
    # Future versions would have migration logic here
    if version >= 1:
        conn.executescript(SCHEMA_V1)
        conn.execute(
            "INSERT OR REPLACE INTO _schema_info (version, description) VALUES (?, ?)",
            (1, "Initial schema with repos, events, tags, publications, dependencies")
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
