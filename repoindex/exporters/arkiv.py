"""
Arkiv exporter for repoindex.

Exports repository and event data as arkiv universal records (JSONL).

Repos become inode/directory records with metadata.
Events become text/plain records (commit/tag messages) with fragment URIs.

See: arkiv SPEC.md for the universal record format.
"""

import json
import sqlite3
from collections import Counter
from typing import IO, List, Optional

from . import Exporter
from ..database.connection import Database
from ..database.events import get_events


def _repo_to_arkiv(repo: dict) -> dict:
    """Convert a repo dict to an arkiv record."""
    path = repo.get('path', '')
    record = {
        'mimetype': 'inode/directory',
        'uri': f'file://{path}',
        'metadata': {},
    }
    scanned_at = repo.get('scanned_at')
    if scanned_at is not None:
        record['timestamp'] = scanned_at

    # Core identity
    meta = record['metadata']
    for key in ('name', 'description', 'language', 'branch', 'remote_url',
                'owner', 'license_key'):
        val = repo.get(key)
        if val is not None and val != '':
            meta[key] = val

    # Languages array
    langs = repo.get('languages')
    if langs:
        try:
            parsed = json.loads(langs) if isinstance(langs, str) else langs
            if isinstance(parsed, list) and parsed:
                meta['languages'] = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Git status
    if repo.get('is_clean') is not None:
        meta['is_clean'] = bool(repo['is_clean'])

    # File presence flags
    for flag in ('has_readme', 'has_license', 'has_ci', 'has_citation'):
        val = repo.get(flag)
        if val is not None:
            meta[flag] = bool(val)

    # README content
    readme = repo.get('readme_content')
    if readme:
        meta['readme'] = readme

    # Tags (from joined data if available)
    tags = repo.get('tags')
    if tags:
        try:
            parsed = json.loads(tags) if isinstance(tags, str) else tags
            if isinstance(parsed, list) and parsed:
                meta['tags'] = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Citation metadata
    citation = {}
    for key in ('citation_doi', 'citation_title', 'citation_version',
                'citation_repository', 'citation_license'):
        val = repo.get(key)
        if val is not None and val != '':
            citation[key.replace('citation_', '')] = val
    authors = repo.get('citation_authors')
    if authors:
        try:
            parsed = json.loads(authors) if isinstance(authors, str) else authors
            if isinstance(parsed, list):
                citation['authors'] = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if citation:
        meta['citation'] = citation

    # GitHub metadata (nested for provenance)
    github = {}
    github_fields = {
        'github_stars': 'stars', 'github_forks': 'forks',
        'github_watchers': 'watchers', 'github_open_issues': 'open_issues',
        'github_is_fork': 'is_fork', 'github_is_private': 'is_private',
        'github_is_archived': 'is_archived',
        'github_description': 'description',
        'github_created_at': 'created_at', 'github_updated_at': 'updated_at',
    }
    for db_key, arkiv_key in github_fields.items():
        val = repo.get(db_key)
        if val is not None and val != '':
            github[arkiv_key] = val
    topics = repo.get('github_topics')
    if topics:
        try:
            parsed = json.loads(topics) if isinstance(topics, str) else topics
            if isinstance(parsed, list) and parsed:
                github['topics'] = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if github:
        meta['github'] = github

    return record


def _event_to_arkiv(event: dict) -> dict:
    """Convert an event dict to an arkiv record."""
    repo_path = event.get('repo_path', '')
    ref = event.get('ref', '')
    message = event.get('message')

    # Fragment identifies the specific object within the repo
    fragment = ref if ref else ''
    uri = f'file://{repo_path}'
    if fragment:
        uri = f'{uri}#{fragment}'

    record = {
        'uri': uri,
        'metadata': {
            'type': event.get('type'),
            'repo': event.get('repo_name'),
        },
    }

    timestamp = event.get('timestamp')
    if timestamp is not None:
        record['timestamp'] = timestamp

    # Has a message -> text/plain content
    if message:
        record['mimetype'] = 'text/plain'
        record['content'] = message

    # Additional metadata
    meta = record['metadata']
    if ref:
        meta['ref'] = ref
    author = event.get('author')
    if author:
        meta['author'] = author
    branch = event.get('data', {}).get('branch')
    if branch:
        meta['branch'] = branch

    return record


def _publication_to_arkiv(pub: dict) -> dict:
    """Convert a publication row (joined with repo name/path) to an arkiv record."""
    url = pub.get('url')
    repo_path = pub.get('repo_path', '')
    uri = url if url else f'file://{repo_path}'

    record = {
        'mimetype': 'application/json',
        'uri': uri,
        'metadata': {},
    }

    # Only include timestamp if present — prefer last_published, fall back to scanned_at
    ts = pub.get('last_published') or pub.get('scanned_at')
    if ts:
        record['timestamp'] = ts

    meta = record['metadata']
    for key in ('registry', 'package_name'):
        val = pub.get(key)
        if val is not None:
            meta[key] = val

    version = pub.get('current_version')
    if version is not None:
        meta['version'] = version

    if pub.get('published') is not None:
        meta['published'] = bool(pub['published'])

    repo_name = pub.get('repo_name')
    if repo_name:
        meta['repo'] = repo_name

    for key in ('doi', 'downloads_total', 'downloads_30d', 'last_published'):
        val = pub.get(key)
        if val is not None and val != '':
            meta[key] = val

    return record


def _walk_metadata(obj: dict, prefix: str, stats: dict) -> None:
    """Walk a metadata dict recursively, accumulating per-key statistics.

    For each leaf key, tracks type occurrences, count, distinct values, and
    an example. Dict values are recursed into (no entry for the parent key).
    """
    for k, v in obj.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _walk_metadata(v, full_key, stats)
            continue
        if full_key not in stats:
            stats[full_key] = {
                'types': Counter(),
                'count': 0,
                'values': set(),
                'example': None,
            }
        entry = stats[full_key]
        entry['count'] += 1
        # bool must be checked before int/float (bool is subclass of int)
        if isinstance(v, bool):
            entry['types']['boolean'] += 1
        elif isinstance(v, (int, float)):
            entry['types']['number'] += 1
        elif isinstance(v, list):
            entry['types']['array'] += 1
        else:
            entry['types']['string'] += 1
        # Track distinct values for cardinality decisions
        try:
            hashable = tuple(v) if isinstance(v, list) else v
            entry['values'].add(hashable)
        except TypeError:
            pass
        if entry['example'] is None:
            entry['example'] = v


def _discover_schema(records: list) -> dict:
    """Discover schema from a list of arkiv records.

    Returns dict of key_path -> {type, count, values|example}.
    - type: most common type across all occurrences
    - count: number of records containing this key
    - values: sorted distinct values if cardinality <= 20
    - example: one sample value if cardinality > 20
    """
    stats: dict = {}
    for record in records:
        meta = record.get('metadata')
        if meta:
            _walk_metadata(meta, '', stats)

    schema = {}
    for key, entry in sorted(stats.items()):
        most_common_type = entry['types'].most_common(1)[0][0]
        info: dict = {
            'type': most_common_type,
            'count': entry['count'],
        }
        distinct = entry['values']
        if len(distinct) <= 20:
            # Unpack tuples back to lists for array-type values
            restored = []
            for v in distinct:
                restored.append(list(v) if isinstance(v, tuple) else v)
            info['values'] = sorted(restored, key=lambda x: str(x))
        else:
            info['example'] = entry['example']
        schema[key] = info
    return schema


def _bundle_sqlite(output_dir, collections, schemas, readme_frontmatter, readme_body=''):
    """Create arkiv-format SQLite database from record collections.

    Args:
        output_dir: Path to archive directory
        collections: dict of {name: [records]} — already-converted arkiv records
        schemas: dict of {name: {metadata_keys: {...}}} — discovered schemas
        readme_frontmatter: dict of README.md frontmatter
        readme_body: str of README.md markdown body
    """
    db_path = output_dir / "archive.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            CREATE TABLE records (
                id INTEGER PRIMARY KEY,
                collection TEXT,
                mimetype TEXT,
                uri TEXT,
                content TEXT,
                timestamp TEXT,
                metadata JSON
            );
            CREATE TABLE _schema (
                collection TEXT,
                key_path TEXT,
                type TEXT,
                count INTEGER,
                sample_values TEXT,
                description TEXT
            );
            CREATE TABLE _metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE INDEX idx_records_collection ON records(collection);
            CREATE INDEX idx_records_mimetype ON records(mimetype);
            CREATE INDEX idx_records_timestamp ON records(timestamp);
        """)

        # Insert records
        for collection_name, records in collections.items():
            for record in records:
                conn.execute(
                    "INSERT INTO records (collection, mimetype, uri, content, timestamp, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        collection_name,
                        record.get('mimetype'),
                        record.get('uri'),
                        record.get('content'),
                        record.get('timestamp'),
                        json.dumps(record.get('metadata', {})),
                    ),
                )

        # Insert schema
        for collection_name, schema_data in schemas.items():
            for key_path, entry in schema_data.get('metadata_keys', {}).items():
                sample = json.dumps(entry.get('values', entry.get('example')))
                conn.execute(
                    "INSERT INTO _schema (collection, key_path, type, count, sample_values) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (collection_name, key_path, entry.get('type'), entry.get('count'), sample),
                )

        # Insert metadata
        conn.execute(
            "INSERT INTO _metadata (key, value) VALUES (?, ?)",
            ('readme_frontmatter', json.dumps(readme_frontmatter)),
        )
        conn.execute(
            "INSERT INTO _metadata (key, value) VALUES (?, ?)",
            ('readme_body', readme_body),
        )

        conn.commit()
    finally:
        conn.close()


def export_archive(
    output_dir,
    repos: list,
    events: list,
    publications: list = None,
    version: str = None,
) -> dict:
    """Write full arkiv archive to output_dir.

    Creates: repos.jsonl, events.jsonl, publications.jsonl, README.md, schema.yaml.
    Returns dict with counts.
    """
    import yaml
    from datetime import datetime
    from pathlib import Path

    if version is None:
        from repoindex import __version__
        version = __version__

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # repos.jsonl
    repo_records = []
    with open(output_dir / "repos.jsonl", "w", encoding="utf-8") as f:
        for repo in repos:
            record = _repo_to_arkiv(repo)
            f.write(json.dumps(record, default=str) + "\n")
            repo_records.append(record)

    # events.jsonl
    event_records = []
    with open(output_dir / "events.jsonl", "w", encoding="utf-8") as f:
        for event in events:
            record = _event_to_arkiv(event)
            f.write(json.dumps(record, default=str) + "\n")
            event_records.append(record)

    # publications.jsonl
    pub_records = []
    if publications:
        with open(output_dir / "publications.jsonl", "w", encoding="utf-8") as f:
            for pub in publications:
                record = _publication_to_arkiv(pub)
                f.write(json.dumps(record, default=str) + "\n")
                pub_records.append(record)

    # README.md
    now = datetime.now().strftime("%Y-%m-%d")
    contents = [
        {'path': 'repos.jsonl', 'description': 'Repository metadata (inode/directory records)'},
        {'path': 'events.jsonl', 'description': 'Git events (text/plain records)'},
    ]
    if pub_records:
        contents.append({'path': 'publications.jsonl', 'description': 'Package registry publications (application/json records)'})
    contents.append({'path': 'archive.db', 'description': 'SQLite derived database (queryable, regenerable from JSONL)'})
    frontmatter = {
        'name': 'repoindex export',
        'description': 'Git repository metadata from repoindex',
        'datetime': now,
        'generator': f'repoindex v{version}',
        'contents': contents,
    }
    with open(output_dir / "README.md", "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(frontmatter, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        f.write("---\n\n")
        readme_body = (
            "# repoindex Export\n\n"
            "This archive contains git repository metadata exported from repoindex.\n\n"
            "## Collections\n\n"
            f"- **repos.jsonl** - {len(repo_records)} repository records\n"
            f"- **events.jsonl** - {len(event_records)} event records\n"
        )
        if pub_records:
            readme_body += f"- **publications.jsonl** - {len(pub_records)} publication records\n"
        f.write(readme_body)

    # schema.yaml
    schema = {}
    if repo_records:
        schema['repos'] = {
            'record_count': len(repo_records),
            'metadata_keys': _discover_schema(repo_records),
        }
    if event_records:
        schema['events'] = {
            'record_count': len(event_records),
            'metadata_keys': _discover_schema(event_records),
        }
    if pub_records:
        schema['publications'] = {
            'record_count': len(pub_records),
            'metadata_keys': _discover_schema(pub_records),
        }
    with open(output_dir / "schema.yaml", "w", encoding="utf-8") as f:
        yaml.dump(schema, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Bundle SQLite derived database
    collections = {'repos': repo_records, 'events': event_records}
    if pub_records:
        collections['publications'] = pub_records
    _bundle_sqlite(output_dir, collections, schema, frontmatter, readme_body=readme_body)

    return {'repos': len(repo_records), 'events': len(event_records), 'publications': len(pub_records)}


class ArkivExporter(Exporter):
    """Arkiv universal record format exporter."""
    format_id = "arkiv"
    name = "Arkiv Universal Records"
    extension = ".jsonl"

    def export(self, repos: List[dict], output: IO[str],
               config: Optional[dict] = None) -> int:
        """
        Export repos (and optionally events) as arkiv JSONL records.

        Repos are always exported. Events are exported if a database
        connection can be established from config.
        """
        count = 0

        # Export repos
        for repo in repos:
            record = _repo_to_arkiv(repo)
            output.write(json.dumps(record, default=str) + '\n')
            count += 1

        # Export events if we can access the database
        if config is not None:
            try:
                with Database(config=config, read_only=True) as db:
                    for repo in repos:
                        repo_id = repo.get('id')
                        if repo_id is not None:
                            for event in get_events(db, repo_id=repo_id):
                                record = _event_to_arkiv(event)
                                output.write(json.dumps(record, default=str) + '\n')
                                count += 1
            except Exception:
                # If DB access fails, just export repos without events
                pass

        return count


exporter = ArkivExporter()
