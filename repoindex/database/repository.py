"""
Repository database operations for repoindex.

Provides CRUD operations for repositories, mapping between
domain objects and database records.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Generator

from ..domain.repository import Repository, GitStatus, GitHubMetadata, LicenseInfo
from ..citation import parse_citation_file
from .connection import Database


def upsert_repo(db: Database, repo: Repository) -> int:
    """
    Insert or update a repository.

    Args:
        db: Database connection
        repo: Repository domain object

    Returns:
        Row ID of the inserted/updated repository
    """
    # Convert domain object to database record
    record = _repo_to_record(repo)

    # Check if exists
    db.execute("SELECT id FROM repos WHERE path = ?", (repo.path,))
    existing = db.fetchone()

    if existing:
        # Update existing
        repo_id = existing['id']
        _update_repo(db, repo_id, record)
    else:
        # Insert new
        repo_id = _insert_repo(db, record)

    # Handle tags
    if repo.tags:
        _sync_tags(db, repo_id, repo.tags, source='user')

    return repo_id


def _repo_to_record(repo: Repository) -> Dict[str, Any]:
    """Convert Repository domain object to database record."""
    record: Dict[str, Any] = {
        'name': repo.name,
        'path': repo.path,
        'remote_url': repo.remote_url,
        'owner': repo.owner,
        'language': repo.language,
        'languages': json.dumps(list(repo.languages)) if repo.languages else None,
        'scanned_at': datetime.now().isoformat(),
    }

    # Git status
    if repo.status:
        record.update({
            'branch': repo.status.branch,
            'is_clean': repo.status.clean,
            'ahead': repo.status.ahead,
            'behind': repo.status.behind,
            'has_upstream': repo.status.has_upstream,
            'uncommitted_changes': repo.status.uncommitted_changes,
            'untracked_files': repo.status.untracked_files,
        })

    # License
    if repo.license:
        record.update({
            'license_key': repo.license.key,
            'license_name': repo.license.name,
            'license_file': repo.license.file,
            'has_license': True,
        })

    # GitHub metadata (all fields prefixed with github_ for explicit provenance)
    if repo.github:
        record.update({
            'github_owner': repo.github.owner,
            'github_name': repo.github.name,
            'github_description': repo.github.description,
            'description': repo.github.description,  # Also set main description
            'github_stars': repo.github.stars,
            'github_forks': repo.github.forks,
            'github_watchers': repo.github.watchers,
            'github_open_issues': repo.github.open_issues_count,
            'github_is_fork': repo.github.is_fork,
            'github_is_private': repo.github.is_private,
            'github_is_archived': repo.github.is_archived,
            'github_has_issues': repo.github.has_issues,
            'github_has_wiki': repo.github.has_wiki,
            'github_has_pages': repo.github.has_pages,
            'github_pages_url': repo.github.pages_url,
            'github_topics': json.dumps(list(repo.github.topics)) if repo.github.topics else None,
            'github_created_at': repo.github.created_at,
            'github_updated_at': repo.github.updated_at,
            'github_pushed_at': repo.github.pushed_at,
        })

    # Git index mtime for smart refresh
    git_index = Path(repo.path) / '.git' / 'index'
    if git_index.exists():
        record['git_index_mtime'] = git_index.stat().st_mtime

    # Check for common files
    repo_path = Path(repo.path)
    record['has_readme'] = any(
        (repo_path / f).exists()
        for f in ['README.md', 'README.rst', 'README.txt', 'README']
    )
    record['has_ci'] = any([
        (repo_path / '.github' / 'workflows').exists(),
        (repo_path / '.gitlab-ci.yml').exists(),
        (repo_path / '.travis.yml').exists(),
        (repo_path / 'Jenkinsfile').exists(),
    ])

    # Check for citation files (CITATION.cff, .zenodo.json, CITATION.bib, CITATION)
    citation_files = ['CITATION.cff', '.zenodo.json', 'CITATION.bib', 'CITATION']
    record['has_citation'] = False
    record['citation_file'] = None
    for citation_file in citation_files:
        if (repo_path / citation_file).exists():
            record['has_citation'] = True
            record['citation_file'] = citation_file
            break

    # Parse citation metadata if file found
    if record['has_citation'] and record['citation_file']:
        citation_data = parse_citation_file(str(repo_path), record['citation_file'])
        if citation_data:
            record['citation_doi'] = citation_data.get('doi')
            record['citation_title'] = citation_data.get('title')
            authors = citation_data.get('authors', [])
            record['citation_authors'] = json.dumps(authors) if authors else None
            record['citation_version'] = citation_data.get('version')
            record['citation_repository'] = citation_data.get('repository')
            record['citation_license'] = citation_data.get('license')

    return record


def _insert_repo(db: Database, record: Dict[str, Any]) -> int:
    """Insert a new repository record."""
    columns = list(record.keys())
    placeholders = ', '.join(['?' for _ in columns])
    column_names = ', '.join(columns)

    sql = f"INSERT INTO repos ({column_names}) VALUES ({placeholders})"
    db.execute(sql, tuple(record.values()))
    return db.lastrowid or 0


def _update_repo(db: Database, repo_id: int, record: Dict[str, Any]) -> None:
    """Update an existing repository record."""
    set_clause = ', '.join([f"{k} = ?" for k in record.keys()])
    sql = f"UPDATE repos SET {set_clause} WHERE id = ?"
    db.execute(sql, tuple(record.values()) + (repo_id,))


def _sync_tags(db: Database, repo_id: int, tags: frozenset, source: str = 'user') -> None:
    """Sync tags for a repository."""
    # Get current tags for this source
    db.execute(
        "SELECT tag FROM tags WHERE repo_id = ? AND source = ?",
        (repo_id, source)
    )
    current = {row['tag'] for row in db.fetchall()}

    # Tags to add
    to_add = tags - current
    for tag in to_add:
        db.execute(
            "INSERT OR IGNORE INTO tags (repo_id, tag, source) VALUES (?, ?, ?)",
            (repo_id, tag, source)
        )

    # Tags to remove
    to_remove = current - tags
    for tag in to_remove:
        db.execute(
            "DELETE FROM tags WHERE repo_id = ? AND tag = ? AND source = ?",
            (repo_id, tag, source)
        )


def get_repo_by_path(db: Database, path: str) -> Optional[Dict[str, Any]]:
    """Get repository by path."""
    db.execute("SELECT * FROM repos WHERE path = ?", (path,))
    row = db.fetchone()
    return dict(row) if row else None


def get_repo_by_name(db: Database, name: str) -> Optional[Dict[str, Any]]:
    """Get repository by name (may return first match if multiple)."""
    db.execute("SELECT * FROM repos WHERE name = ?", (name,))
    row = db.fetchone()
    return dict(row) if row else None


def get_repo_by_id(db: Database, repo_id: int) -> Optional[Dict[str, Any]]:
    """Get repository by ID."""
    db.execute("SELECT * FROM repos WHERE id = ?", (repo_id,))
    row = db.fetchone()
    return dict(row) if row else None


def get_all_repos(db: Database) -> Generator[Dict[str, Any], None, None]:
    """Get all repositories as dictionaries."""
    db.execute("SELECT * FROM repos ORDER BY name")
    for row in db.fetchall():
        yield dict(row)


def get_repos_with_tags(db: Database) -> Generator[Dict[str, Any], None, None]:
    """Get all repositories with their tags included."""
    db.execute("""
        SELECT r.*, GROUP_CONCAT(t.tag) as tags_csv
        FROM repos r
        LEFT JOIN tags t ON t.repo_id = r.id
        GROUP BY r.id
        ORDER BY r.name
    """)
    for row in db.fetchall():
        record = dict(row)
        # Parse tags
        tags_csv = record.pop('tags_csv', None)
        record['tags'] = tags_csv.split(',') if tags_csv else []
        yield record


def delete_repo(db: Database, repo_id: int) -> bool:
    """Delete a repository by ID."""
    db.execute("DELETE FROM repos WHERE id = ?", (repo_id,))
    return db.rowcount > 0


def delete_repo_by_path(db: Database, path: str) -> bool:
    """Delete a repository by path."""
    db.execute("DELETE FROM repos WHERE path = ?", (path,))
    return db.rowcount > 0


def needs_refresh(db: Database, path: str) -> bool:
    """
    Check if a repository needs to be refreshed.

    Compares stored git_index_mtime with current mtime.

    Args:
        db: Database connection
        path: Repository path

    Returns:
        True if repo needs refresh, False if up-to-date
    """
    db.execute(
        "SELECT git_index_mtime FROM repos WHERE path = ?",
        (path,)
    )
    row = db.fetchone()

    if not row:
        return True  # Not in database, needs initial scan

    stored_mtime = row['git_index_mtime']
    if stored_mtime is None:
        return True

    git_index = Path(path) / '.git' / 'index'
    if not git_index.exists():
        return True

    current_mtime = git_index.stat().st_mtime
    return current_mtime > stored_mtime


def get_stale_repos(db: Database) -> Generator[str, None, None]:
    """
    Get paths of repositories that need refresh.

    Yields:
        Paths to repositories needing refresh
    """
    db.execute("SELECT path, git_index_mtime FROM repos")
    for row in db.fetchall():
        if needs_refresh(db, row['path']):
            yield row['path']


def cleanup_missing_repos(db: Database) -> int:
    """
    Remove repos from database that no longer exist on disk.

    Returns:
        Number of repos removed
    """
    db.execute("SELECT id, path FROM repos")
    removed = 0

    for row in db.fetchall():
        if not Path(row['path']).exists():
            delete_repo(db, row['id'])
            removed += 1

    return removed


def get_repo_count(db: Database) -> int:
    """Get total number of repositories."""
    db.execute("SELECT COUNT(*) FROM repos")
    row = db.fetchone()
    return row[0] if row else 0


def search_repos(db: Database, query: str) -> Generator[Dict[str, Any], None, None]:
    """
    Full-text search for repositories.

    Args:
        db: Database connection
        query: Search query

    Yields:
        Matching repository records
    """
    db.execute("""
        SELECT r.*
        FROM repos r
        JOIN repos_fts fts ON fts.rowid = r.id
        WHERE repos_fts MATCH ?
        ORDER BY rank
    """, (query,))

    for row in db.fetchall():
        yield dict(row)


def get_repos_by_language(
    db: Database,
    language: str
) -> Generator[Dict[str, Any], None, None]:
    """Get repositories by primary language."""
    db.execute(
        "SELECT * FROM repos WHERE language = ? ORDER BY github_stars DESC",
        (language,)
    )
    for row in db.fetchall():
        yield dict(row)


def get_repos_by_tag(
    db: Database,
    tag_pattern: str
) -> Generator[Dict[str, Any], None, None]:
    """
    Get repositories matching a tag pattern.

    Args:
        db: Database connection
        tag_pattern: Tag pattern (supports % wildcards for LIKE)

    Yields:
        Matching repository records
    """
    if '%' in tag_pattern or '*' in tag_pattern:
        # Pattern matching
        pattern = tag_pattern.replace('*', '%')
        db.execute("""
            SELECT DISTINCT r.*
            FROM repos r
            JOIN tags t ON t.repo_id = r.id
            WHERE t.tag LIKE ?
            ORDER BY r.name
        """, (pattern,))
    else:
        # Exact match
        db.execute("""
            SELECT r.*
            FROM repos r
            JOIN tags t ON t.repo_id = r.id
            WHERE t.tag = ?
            ORDER BY r.name
        """, (tag_pattern,))

    for row in db.fetchall():
        yield dict(row)


def record_to_domain(record: Dict[str, Any]) -> Repository:
    """
    Convert a database record to a Repository domain object.

    Args:
        record: Database row as dictionary

    Returns:
        Repository domain object
    """
    # Parse status
    status = GitStatus(
        branch=record.get('branch', 'main'),
        clean=bool(record.get('is_clean', True)),
        ahead=record.get('ahead', 0),
        behind=record.get('behind', 0),
        has_upstream=bool(record.get('has_upstream', False)),
        uncommitted_changes=bool(record.get('uncommitted_changes', False)),
        untracked_files=record.get('untracked_files', 0),
    )

    # Parse license
    license_info = None
    if record.get('license_key'):
        license_info = LicenseInfo(
            key=record['license_key'],
            name=record.get('license_name'),
            file=record.get('license_file'),
        )

    # Parse GitHub metadata (all fields use github_ prefix)
    github = None
    if record.get('github_owner'):
        topics: tuple[Any, ...] = ()
        if record.get('github_topics'):
            try:
                topics = tuple(json.loads(record['github_topics']))
            except (json.JSONDecodeError, TypeError):
                pass

        github = GitHubMetadata(
            owner=record['github_owner'],
            name=record.get('github_name', record['name']),
            description=record.get('github_description'),
            stars=record.get('github_stars', 0),
            forks=record.get('github_forks', 0),
            watchers=record.get('github_watchers', 0),
            is_fork=bool(record.get('github_is_fork', False)),
            is_private=bool(record.get('github_is_private', False)),
            is_archived=bool(record.get('github_is_archived', False)),
            topics=topics,
            has_issues=bool(record.get('github_has_issues', True)),
            has_wiki=bool(record.get('github_has_wiki', True)),
            has_pages=bool(record.get('github_has_pages', False)),
            pages_url=record.get('github_pages_url'),
            open_issues_count=record.get('github_open_issues', 0),
            created_at=record.get('github_created_at'),
            updated_at=record.get('github_updated_at'),
            pushed_at=record.get('github_pushed_at'),
        )

    # Parse languages
    languages = ()
    if record.get('languages'):
        try:
            languages = tuple(json.loads(record['languages']))
        except (json.JSONDecodeError, TypeError):
            pass

    # Parse tags (if included in record)
    tags: frozenset[str] = frozenset()
    if 'tags' in record and record['tags']:
        if isinstance(record['tags'], str):
            tags = frozenset(record['tags'].split(','))
        elif isinstance(record['tags'], (list, set, frozenset)):
            tags = frozenset(record['tags'])

    return Repository(
        path=record['path'],
        name=record['name'],
        status=status,
        remote_url=record.get('remote_url'),
        owner=record.get('owner'),
        language=record.get('language'),
        languages=languages,
        license=license_info,
        tags=tags,
        github=github,
        last_updated=record.get('github_updated_at'),
    )
