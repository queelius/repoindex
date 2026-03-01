"""
Arkiv exporter for repoindex.

Exports repository and event data as arkiv universal records (JSONL).

Repos become inode/directory records with metadata.
Events become text/plain records (commit/tag messages) with fragment URIs.

See: arkiv SPEC.md for the universal record format.
"""

import json
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
        'content': None,
        'timestamp': repo.get('scanned_at'),
        'metadata': {},
    }

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
        'timestamp': event.get('timestamp'),
        'metadata': {
            'type': event.get('type'),
            'repo': event.get('repo_name'),
        },
    }

    # Has a message -> text/plain content
    if message:
        record['mimetype'] = 'text/plain'
        record['content'] = message
    else:
        record['mimetype'] = None
        record['content'] = None

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


def _collect_meta_keys(d: dict, prefix: str = '') -> list:
    """Collect all keys from a nested dict for schema discovery."""
    keys = []
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        keys.append(full_key)
        if isinstance(v, dict):
            keys.extend(_collect_meta_keys(v, full_key))
    return keys


def export_archive(
    output_dir,
    repos: list,
    events: list,
    version: str = None,
) -> dict:
    """Write full arkiv archive to output_dir.

    Creates: repos.jsonl, events.jsonl, README.md, schema.yaml.
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
    repo_count = 0
    repo_keys = set()
    with open(output_dir / "repos.jsonl", "w", encoding="utf-8") as f:
        for repo in repos:
            record = _repo_to_arkiv(repo)
            f.write(json.dumps(record, default=str) + "\n")
            repo_count += 1
            if record.get('metadata'):
                repo_keys.update(_collect_meta_keys(record['metadata']))

    # events.jsonl
    event_count = 0
    event_keys = set()
    with open(output_dir / "events.jsonl", "w", encoding="utf-8") as f:
        for event in events:
            record = _event_to_arkiv(event)
            f.write(json.dumps(record, default=str) + "\n")
            event_count += 1
            if record.get('metadata'):
                event_keys.update(_collect_meta_keys(record['metadata']))

    # README.md
    now = datetime.now().strftime("%Y-%m-%d")
    frontmatter = {
        'name': 'repoindex export',
        'description': 'Git repository metadata from repoindex',
        'datetime': now,
        'generator': f'repoindex v{version}',
        'contents': [
            {'path': 'repos.jsonl', 'description': 'Repository metadata (inode/directory records)'},
            {'path': 'events.jsonl', 'description': 'Git events (text/plain records)'},
        ],
    }
    with open(output_dir / "README.md", "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(frontmatter, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        f.write("---\n\n")
        f.write(
            "# repoindex Export\n\n"
            "This archive contains git repository metadata exported from repoindex.\n\n"
            "## Collections\n\n"
            f"- **repos.jsonl** - {repo_count} repository records\n"
            f"- **events.jsonl** - {event_count} event records\n"
        )

    # schema.yaml
    schema = {}
    if repo_keys:
        schema['repos'] = {
            'record_count': repo_count,
            'metadata_keys': {k: {'type': 'string'} for k in sorted(repo_keys)},
        }
    if event_keys:
        schema['events'] = {
            'record_count': event_count,
            'metadata_keys': {k: {'type': 'string'} for k in sorted(event_keys)},
        }
    with open(output_dir / "schema.yaml", "w", encoding="utf-8") as f:
        yaml.dump(schema, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return {'repos': repo_count, 'events': event_count}


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
                    # Get repo IDs for the filtered repos
                    repo_paths = {r.get('path') for r in repos}
                    for event in get_events(db):
                        if event.get('repo_path') in repo_paths:
                            record = _event_to_arkiv(event)
                            output.write(json.dumps(record, default=str) + '\n')
                            count += 1
            except Exception:
                # If DB access fails, just export repos without events
                pass

        return count


exporter = ArkivExporter()
