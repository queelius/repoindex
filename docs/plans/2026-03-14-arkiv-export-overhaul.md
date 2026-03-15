# Arkiv Export Overhaul

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make repoindex's arkiv export fully compliant with the arkiv SPEC.md — proper schema discovery, publications collection, null-field omission, and bundled SQLite database.

**Architecture:** The arkiv exporter (`repoindex/exporters/arkiv.py`) handles record conversion and archive generation. Schema discovery gets a real implementation that infers types, counts values, and follows the spec. Publications become a new JSONL collection. The archive bundles a derived SQLite database in arkiv format. The stream exporter gets the same repo_id filtering fix that archive mode already has.

**Tech Stack:** Python stdlib (`json`, `sqlite3`, `collections.Counter`), `pyyaml`

**Reference:** arkiv SPEC.md at `~/github/beta/arkiv/SPEC.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `repoindex/exporters/arkiv.py` | Modify | Schema discovery, record conversion, archive generation, SQLite bundling |
| `repoindex/commands/render.py` | Modify | Fetch publications from DB, pass to `export_archive` |
| `tests/test_exporters/test_arkiv.py` | Modify | Update null-field assertions, add publication/schema tests |
| `tests/test_export_arkiv.py` | Modify | Update archive tests for new collections, schema quality, SQLite |

---

### Task 1: Replace schema discovery with spec-compliant implementation

**Files:**
- Modify: `repoindex/exporters/arkiv.py` (replace `_collect_meta_keys` with `_discover_schema` + `_walk_metadata`)
- Test: `tests/test_export_arkiv.py`

The current `_collect_meta_keys` only collects key names and hardcodes `type: string` for everything. The arkiv spec requires `type` (inferred from values), `count` (how many records have this key), `values` (if cardinality <= 20), and `example` (if cardinality > 20).

- [ ] **Step 1: Write failing tests for schema discovery**

Add to `tests/test_export_arkiv.py`:

```python
class TestDiscoverSchema:
    def test_infers_string_type(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'name': 'foo'}}, {'metadata': {'name': 'bar'}}]
        schema = _discover_schema(records)
        assert schema['name']['type'] == 'string'
        assert schema['name']['count'] == 2

    def test_infers_number_type(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'stars': 5}}, {'metadata': {'stars': 10}}]
        schema = _discover_schema(records)
        assert schema['stars']['type'] == 'number'

    def test_infers_boolean_type(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'is_clean': True}}, {'metadata': {'is_clean': False}}]
        schema = _discover_schema(records)
        assert schema['is_clean']['type'] == 'boolean'

    def test_infers_array_type(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'tags': ['a', 'b']}}]
        schema = _discover_schema(records)
        assert schema['tags']['type'] == 'array'

    def test_low_cardinality_emits_values(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'lang': 'Python'}}, {'metadata': {'lang': 'R'}}, {'metadata': {'lang': 'Python'}}]
        schema = _discover_schema(records)
        assert 'values' in schema['lang']
        assert set(schema['lang']['values']) == {'Python', 'R'}
        assert 'example' not in schema['lang']

    def test_high_cardinality_emits_example(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'name': f'repo-{i}'}} for i in range(25)]
        schema = _discover_schema(records)
        assert 'values' not in schema['name']
        assert 'example' in schema['name']

    def test_nested_keys_use_dot_notation(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [{'metadata': {'github': {'stars': 5, 'forks': 1}}}]
        schema = _discover_schema(records)
        assert 'github.stars' in schema
        assert schema['github.stars']['type'] == 'number'
        # Parent dict keys are NOT emitted — only leaf keys per spec
        assert 'github' not in schema

    def test_count_reflects_presence(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [
            {'metadata': {'name': 'a', 'lang': 'Python'}},
            {'metadata': {'name': 'b'}},  # no lang
        ]
        schema = _discover_schema(records)
        assert schema['name']['count'] == 2
        assert schema['lang']['count'] == 1

    def test_empty_records(self):
        from repoindex.exporters.arkiv import _discover_schema
        schema = _discover_schema([])
        assert schema == {}

    def test_mixed_types_uses_most_common(self):
        from repoindex.exporters.arkiv import _discover_schema
        records = [
            {'metadata': {'val': 'text'}},
            {'metadata': {'val': 'more'}},
            {'metadata': {'val': 42}},
        ]
        schema = _discover_schema(records)
        assert schema['val']['type'] == 'string'  # 2 strings vs 1 number
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export_arkiv.py::TestDiscoverSchema -v`
Expected: FAIL (ImportError — `_discover_schema` doesn't exist yet)

- [ ] **Step 3: Implement `_discover_schema` and `_walk_metadata`**

Replace `_collect_meta_keys` in `repoindex/exporters/arkiv.py`:

```python
from collections import Counter

_CARDINALITY_THRESHOLD = 20


def _walk_metadata(obj, prefix, stats):
    """Walk a metadata dict, accumulating per-key statistics."""
    if not isinstance(obj, dict):
        return
    for k, v in obj.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if full_key not in stats:
            stats[full_key] = {
                'types': Counter(), 'count': 0,
                'values': set(), 'example': None,
            }
        s = stats[full_key]
        s['count'] += 1
        if isinstance(v, bool):
            s['types']['boolean'] += 1
            s['values'].add(v)
        elif isinstance(v, (int, float)):
            s['types']['number'] += 1
            s['values'].add(v)
            if s['example'] is None:
                s['example'] = v
        elif isinstance(v, list):
            s['types']['array'] += 1
            if s['example'] is None:
                s['example'] = v
        elif isinstance(v, dict):
            # Recurse into children — don't emit parent container keys (spec shows only leaf keys)
            _walk_metadata(v, full_key, stats)
        elif v is not None:
            s['types']['string'] += 1
            s['values'].add(str(v))
            if s['example'] is None:
                s['example'] = v


def _discover_schema(records: list) -> dict:
    """Discover metadata schema from arkiv records.

    Returns dict of key_path -> {type, count, values|example} per the arkiv spec.
    """
    stats = {}
    for record in records:
        meta = record.get('metadata', {})
        _walk_metadata(meta, '', stats)

    schema = {}
    for key, s in sorted(stats.items()):
        entry = {
            'type': s['types'].most_common(1)[0][0] if s['types'] else 'string',
            'count': s['count'],
        }
        if len(s['values']) <= _CARDINALITY_THRESHOLD and s['values']:
            entry['values'] = sorted(s['values'], key=lambda x: str(x))
        elif s['example'] is not None:
            entry['example'] = s['example']
        schema[key] = entry
    return schema
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_export_arkiv.py::TestDiscoverSchema -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Wire `_discover_schema` into `export_archive`**

In `export_archive`, replace the `_collect_meta_keys` calls with `_discover_schema`:

```python
# After writing repos.jsonl and events.jsonl, replace the schema section:

# schema.yaml — spec-compliant discovery
schema = {}
if repo_records:
    schema['repos'] = {
        'record_count': repo_count,
        'metadata_keys': _discover_schema(repo_records),
    }
if event_records:
    schema['events'] = {
        'record_count': event_count,
        'metadata_keys': _discover_schema(event_records),
    }
```

This requires accumulating the record dicts (not just writing them). Change the JSONL-writing loops to also collect records:

```python
repo_records = []
with open(output_dir / "repos.jsonl", "w", encoding="utf-8") as f:
    for repo in repos:
        record = _repo_to_arkiv(repo)
        f.write(json.dumps(record, default=str) + "\n")
        repo_records.append(record)
```

Same pattern for events (and later publications).

- [ ] **Step 6: Run full test suite for arkiv**

Run: `pytest tests/test_export_arkiv.py tests/test_exporters/test_arkiv.py -v`
Expected: PASS (existing `TestCollectMetaKeys` tests will need updating — see step 7)

- [ ] **Step 7: Remove old `TestCollectMetaKeys` tests, update `test_schema_yaml_structure`**

In `tests/test_export_arkiv.py`:
- Remove `TestCollectMetaKeys` class (replaced by `TestDiscoverSchema`)
- Update `test_schema_yaml_structure` to assert proper types, counts, values

```python
def test_schema_yaml_structure(self, tmp_path):
    from repoindex.exporters.arkiv import export_archive
    export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, version='0.12.0')
    with open(tmp_path / "schema.yaml") as f:
        schema = yaml.safe_load(f)
    assert 'repos' in schema
    assert 'events' in schema
    # Schema has real types, not just "string"
    repo_keys = schema['repos']['metadata_keys']
    assert repo_keys['name']['count'] == 1
    assert repo_keys['name']['type'] == 'string'
    assert repo_keys['is_clean']['type'] == 'boolean'
```

- [ ] **Step 8: Commit**

```
feat(arkiv): spec-compliant schema discovery with type inference, counts, values
```

---

### Task 2: Omit null fields from arkiv records

**Files:**
- Modify: `repoindex/exporters/arkiv.py` (`_repo_to_arkiv`, `_event_to_arkiv`)
- Modify: `tests/test_exporters/test_arkiv.py`

The arkiv spec says "all fields optional" — meaning omit them rather than setting to null. Currently `_repo_to_arkiv` always emits `"content": null` and `_event_to_arkiv` emits `"mimetype": null` for unannotated tags.

- [ ] **Step 1: Update tests to expect omission instead of null**

In `tests/test_exporters/test_arkiv.py`:

```python
# Change test_content_is_null:
def test_content_omitted(self):
    record = _repo_to_arkiv(SAMPLE_REPO)
    assert 'content' not in record

# Change test_unannotated_tag_no_content:
def test_unannotated_tag_fields_omitted(self):
    record = _event_to_arkiv(UNANNOTATED_TAG_EVENT)
    assert 'mimetype' not in record
    assert 'content' not in record

# Update test_export_preserves_all_arkiv_fields:
def test_export_preserves_present_arkiv_fields(self):
    """Verify present arkiv fields are correct."""
    e = ArkivExporter()
    out = io.StringIO()
    e.export([SAMPLE_REPO], out)
    out.seek(0)
    record = json.loads(out.readline())
    assert 'mimetype' in record
    assert 'uri' in record
    assert 'timestamp' in record
    assert 'metadata' in record
    assert 'content' not in record  # repos have no content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exporters/test_arkiv.py::TestRepoToArkiv::test_content_omitted -v`
Expected: FAIL

- [ ] **Step 3: Update `_repo_to_arkiv` to omit null fields**

```python
def _repo_to_arkiv(repo: dict) -> dict:
    record = {
        'mimetype': 'inode/directory',
        'uri': f'file://{repo.get("path", "")}',
        'timestamp': repo.get('scanned_at'),
        'metadata': {},
    }
    # ... rest unchanged
    return record
```

Remove the `'content': None` line. Also, only include `timestamp` if `scanned_at` is non-null:

```python
record = {'mimetype': 'inode/directory', 'uri': f'file://{path}', 'metadata': {}}
ts = repo.get('scanned_at')
if ts:
    record['timestamp'] = ts
```

- [ ] **Step 4: Update `_event_to_arkiv` to omit null fields**

```python
def _event_to_arkiv(event: dict) -> dict:
    # ... URI building unchanged ...
    record = {
        'uri': uri,
        'timestamp': event.get('timestamp'),
        'metadata': {
            'type': event.get('type'),
            'repo': event.get('repo_name'),
        },
    }
    if message:
        record['mimetype'] = 'text/plain'
        record['content'] = message
    # ... rest unchanged
    return record
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_exporters/test_arkiv.py tests/test_export_arkiv.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```
fix(arkiv): omit null fields from records per spec ("all fields optional")
```

---

### Task 3: Add publications collection to archive export

**Files:**
- Modify: `repoindex/exporters/arkiv.py` (add `_publication_to_arkiv`, update `export_archive`)
- Modify: `repoindex/commands/render.py` (fetch publications from DB)
- Test: `tests/test_export_arkiv.py`
- Test: `tests/test_exporters/test_arkiv.py`

Publications have URIs (registry URLs), timestamps, and structured metadata — they fit the arkiv record model naturally. The `publications` table has 98 records (59 published) in the user's database.

- [ ] **Step 1: Write tests for `_publication_to_arkiv`**

Add to `tests/test_exporters/test_arkiv.py`:

```python
from repoindex.exporters.arkiv import _publication_to_arkiv

SAMPLE_PUBLICATION = {
    'registry': 'pypi',
    'package_name': 'repoindex',
    'current_version': '0.12.0',
    'published': 1,
    'url': 'https://pypi.org/project/repoindex/',
    'doi': None,
    'downloads_total': None,
    'scanned_at': '2026-03-14T10:00:00',
    'repo_name': 'repoindex',
    'repo_path': '/home/user/github/repoindex',
}


class TestPublicationToArkiv:
    def test_mimetype(self):
        record = _publication_to_arkiv(SAMPLE_PUBLICATION)
        assert record['mimetype'] == 'application/json'

    def test_uri_from_url(self):
        record = _publication_to_arkiv(SAMPLE_PUBLICATION)
        assert record['uri'] == 'https://pypi.org/project/repoindex/'

    def test_metadata(self):
        record = _publication_to_arkiv(SAMPLE_PUBLICATION)
        meta = record['metadata']
        assert meta['registry'] == 'pypi'
        assert meta['package_name'] == 'repoindex'
        assert meta['version'] == '0.12.0'
        assert meta['published'] is True
        assert meta['repo'] == 'repoindex'

    def test_no_url_uses_repo_path(self):
        pub = {**SAMPLE_PUBLICATION, 'url': None}
        record = _publication_to_arkiv(pub)
        assert record['uri'] == 'file:///home/user/github/repoindex'

    def test_null_fields_omitted(self):
        record = _publication_to_arkiv(SAMPLE_PUBLICATION)
        meta = record['metadata']
        assert 'doi' not in meta
        assert 'downloads_total' not in meta
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exporters/test_arkiv.py::TestPublicationToArkiv -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `_publication_to_arkiv`**

```python
def _publication_to_arkiv(pub: dict) -> dict:
    """Convert a publication dict to an arkiv record."""
    url = pub.get('url')
    repo_path = pub.get('repo_path', '')
    uri = url if url else f'file://{repo_path}'

    record = {
        'mimetype': 'application/json',
        'uri': uri,
        'timestamp': pub.get('last_published') or pub.get('scanned_at'),
        'metadata': {},
    }

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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_exporters/test_arkiv.py::TestPublicationToArkiv -v`
Expected: PASS

- [ ] **Step 5: Wire publications into `export_archive`**

Update `export_archive` signature and body:

```python
def export_archive(
    output_dir,
    repos: list,
    events: list,
    publications: list = None,
    version: str = None,
) -> dict:
```

Add publications.jsonl writing after events.jsonl (same pattern):

```python
# publications.jsonl (only write file if there are publications)
pub_records = []
if publications:
    with open(output_dir / "publications.jsonl", "w", encoding="utf-8") as f:
        for pub in publications:
            record = _publication_to_arkiv(pub)
            f.write(json.dumps(record, default=str) + "\n")
            pub_records.append(record)

# Update schema to include publications
if pub_records:
    schema['publications'] = {
        'record_count': len(pub_records),
        'metadata_keys': _discover_schema(pub_records),
    }
```

Update README frontmatter `contents` to include publications:

```python
contents = [
    {'path': 'repos.jsonl', 'description': 'Repository metadata (inode/directory records)'},
    {'path': 'events.jsonl', 'description': 'Git events (text/plain records)'},
]
if pub_records:
    contents.append({'path': 'publications.jsonl', 'description': 'Package registry publications (application/json records)'})
```

Update return dict:

```python
return {'repos': len(repo_records), 'events': len(event_records), 'publications': len(pub_records)}
```

- [ ] **Step 6: Update `render.py` to fetch publications**

In `repoindex/commands/render.py`, within the `format_id == 'arkiv'` block, fetch publications alongside events:

```python
events = []
publications = []
try:
    with Database(config=config, read_only=True) as db:
        for repo in repos:
            repo_id = repo.get('id')
            if repo_id is not None:
                events.extend(get_events(db, repo_id=repo_id))
        # Fetch publications for these repos
        repo_ids = [r['id'] for r in repos if r.get('id')]
        if repo_ids:
            placeholders = ','.join('?' * len(repo_ids))
            db.execute(
                f"SELECT p.*, r.name as repo_name, r.path as repo_path "
                f"FROM publications p JOIN repos r ON p.repo_id = r.id "
                f"WHERE p.repo_id IN ({placeholders})",
                repo_ids,
            )
            publications = [dict(row) for row in db.fetchall()]
except Exception as e:
    click.echo(f"Warning: could not fetch events: {e}", err=True)

counts = export_archive(output_file, repos, events, publications=publications)
click.echo(
    f"Exported {counts['repos']} repos, {counts['events']} events, "
    f"{counts['publications']} publications to {output_file}/",
    err=True,
)
```

- [ ] **Step 7: Add archive test for publications**

In `tests/test_export_arkiv.py`:

```python
MOCK_PUBLICATIONS = [
    {
        'registry': 'pypi', 'package_name': 'myrepo', 'current_version': '1.0.0',
        'published': 1, 'url': 'https://pypi.org/project/myrepo/',
        'doi': None, 'downloads_total': None, 'scanned_at': '2026-02-28T10:00:00',
        'repo_name': 'myrepo', 'repo_path': '/home/user/github/myrepo',
    },
]


class TestExportArchivePublications:
    def test_publications_jsonl_created(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS)
        assert (tmp_path / "publications.jsonl").exists()

    def test_publications_in_schema(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS)
        with open(tmp_path / "schema.yaml") as f:
            schema = yaml.safe_load(f)
        assert 'publications' in schema
        assert schema['publications']['record_count'] == 1

    def test_no_publications_no_file(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=[])
        assert not (tmp_path / "publications.jsonl").exists()

    def test_publications_default_none(self, tmp_path):
        """Calling without publications kwarg should not crash."""
        from repoindex.exporters.arkiv import export_archive
        counts = export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
        assert counts['publications'] == 0
        assert not (tmp_path / "publications.jsonl").exists()

    def test_counts_include_publications(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        counts = export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS)
        assert counts['publications'] == 1
```

- [ ] **Step 8: Run full test suite**

Run: `pytest tests/test_export_arkiv.py tests/test_exporters/test_arkiv.py tests/test_render_command.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```
feat(arkiv): add publications.jsonl collection to archive export
```

---

### Task 4: Bundle SQLite derived database

**Files:**
- Modify: `repoindex/exporters/arkiv.py` (add `_bundle_sqlite`)
- Test: `tests/test_export_arkiv.py`

The arkiv spec says archives can include an `archive.db` SQLite file as a derived, queryable view. The schema is: `records(id, collection, mimetype, uri, content, timestamp, metadata JSON)` + `_schema` + `_metadata`.

- [ ] **Step 1: Write tests for SQLite bundling**

```python
import sqlite3


class TestArchiveSqlite:
    def test_archive_db_created(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS)
        assert (tmp_path / "archive.db").exists()

    def test_records_table_has_correct_schema(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        cursor = conn.execute("PRAGMA table_info(records)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert cols == {'id', 'collection', 'mimetype', 'uri', 'content', 'timestamp', 'metadata'}

    def test_records_count_matches_jsonl(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS, publications=MOCK_PUBLICATIONS)
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        conn.row_factory = sqlite3.Row
        repos_n = conn.execute("SELECT COUNT(*) FROM records WHERE collection='repos'").fetchone()[0]
        events_n = conn.execute("SELECT COUNT(*) FROM records WHERE collection='events'").fetchone()[0]
        pubs_n = conn.execute("SELECT COUNT(*) FROM records WHERE collection='publications'").fetchone()[0]
        conn.close()
        assert repos_n == 1
        assert events_n == 1
        assert pubs_n == 1

    def test_metadata_is_queryable_json(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        row = conn.execute(
            "SELECT json_extract(metadata, '$.name') FROM records WHERE collection='repos'"
        ).fetchone()
        conn.close()
        assert row[0] == 'myrepo'

    def test_schema_table_populated(self, tmp_path):
        from repoindex.exporters.arkiv import export_archive
        export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
        conn = sqlite3.connect(str(tmp_path / "archive.db"))
        rows = conn.execute("SELECT * FROM _schema WHERE collection='repos'").fetchall()
        conn.close()
        assert len(rows) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_export_arkiv.py::TestArchiveSqlite -v`
Expected: FAIL

- [ ] **Step 3: Implement `_bundle_sqlite`**

Add to `repoindex/exporters/arkiv.py`:

```python
import sqlite3

def _bundle_sqlite(output_dir, collections, schemas, readme_frontmatter, readme_body=''):
    """Create arkiv-format SQLite database from JSONL collections.

    Args:
        output_dir: Path to archive directory
        collections: dict of {name: [records]} (already-converted arkiv records)
        schemas: dict of {name: {metadata_keys: {...}}} (discovered schemas)
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
```

- [ ] **Step 4: Wire `_bundle_sqlite` into `export_archive`**

At the end of `export_archive`, after writing all JSONL/YAML/README files:

```python
# Bundle SQLite derived database
collections = {'repos': repo_records, 'events': event_records}
if pub_records:
    collections['publications'] = pub_records
_bundle_sqlite(output_dir, collections, schema, frontmatter)
```

- [ ] **Step 5: Update README contents to include archive.db**

```python
contents.append({'path': 'archive.db', 'description': 'SQLite derived database (queryable, regenerable from JSONL)'})
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_export_arkiv.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```
feat(arkiv): bundle SQLite derived database in archive exports
```

---

### Task 5: Fix stream exporter event filtering

**Files:**
- Modify: `repoindex/exporters/arkiv.py` (`ArkivExporter.export`)
- Test: `tests/test_exporters/test_arkiv.py`

The `ArkivExporter.export()` stream mode still fetches all events and filters in Python. Apply the same `repo_id` fix that archive mode has.

- [ ] **Step 1: Fix the export method**

```python
def export(self, repos, output, config=None):
    count = 0
    for repo in repos:
        record = _repo_to_arkiv(repo)
        output.write(json.dumps(record, default=str) + '\n')
        count += 1

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
            pass
    return count
```

- [ ] **Step 2: Run existing exporter tests**

Run: `pytest tests/test_exporters/test_arkiv.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```
fix(arkiv): use repo_id filtering in stream exporter (match archive mode)
```

---

### Task 6: Final integration — run full suite, update CLAUDE.md commands list

**Files:**
- Test all

- [ ] **Step 1: Run full test suite**

Run: `pytest --maxfail=5 -q`
Expected: All pass, no regressions

- [ ] **Step 2: Smoke test the archive export**

```bash
repoindex export arkiv -o /tmp/repoindex-arkiv --language python
ls /tmp/repoindex-arkiv/
# Should show: repos.jsonl events.jsonl publications.jsonl README.md schema.yaml archive.db

# Check schema quality
python -c "import yaml; print(yaml.safe_load(open('/tmp/repoindex-arkiv/schema.yaml'))['repos']['metadata_keys']['is_clean'])"
# Should show: {'type': 'boolean', 'count': ..., 'values': [False, True]}

# Check SQLite is queryable
sqlite3 /tmp/repoindex-arkiv/archive.db "SELECT collection, COUNT(*) FROM records GROUP BY collection"
# Should show counts per collection
```

- [ ] **Step 3: Commit final state**

```
chore: arkiv export overhaul complete — spec-compliant schema, publications, SQLite
```
