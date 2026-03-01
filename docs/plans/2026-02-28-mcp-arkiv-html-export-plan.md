# MCP Server + Export Enhancements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add MCP server (4 tools) and enhance the export command: rename `render` to `export`, make `export arkiv -o <dir>` produce a full archive, add `export html -o <dir>` for a self-contained SQLite browser.

**Architecture:** MCP server is a standalone module (`repoindex/mcp/`) using FastMCP. The existing `render` command is renamed to `export` (with `render` kept as deprecated alias). For directory-based formats (arkiv, html), `-o <dir>` triggers archive/directory output instead of stream output.

**Tech Stack:** Python 3.8+, Click, mcp SDK (FastMCP), SQLite, sql.js (WASM), HTML/CSS/JS

---

## Feature 1: MCP Server

### Task 1: Add MCP optional dependency

**Files:**
- Modify: `pyproject.toml:22-30`

**Step 1: Add the mcp optional dependency**

Add to `[project.optional-dependencies]`:
```toml
mcp = ["mcp>=1.0.0"]
```
Also add `"mcp>=1.0.0"` to the `all` list.

**Step 2: Install**

Run: `cd /home/spinoza/github/beta/repoindex && pip install -e ".[mcp]"`
Expected: installs successfully

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add mcp optional dependency"
```

---

### Task 2: MCP server — get_manifest tool

**Files:**
- Create: `repoindex/mcp/__init__.py`
- Create: `repoindex/mcp/server.py`
- Create: `tests/test_mcp.py`

**Step 1: Write failing test**

```python
# tests/test_mcp.py
"""Tests for the MCP server tools."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


def test_get_manifest_structure(mock_db):
    mock_db.fetchone.side_effect = [
        {'count': 143}, {'count': 2841}, {'count': 312}, {'count': 28},
    ]
    mock_db.fetchall.side_effect = [
        [{'language': 'Python', 'cnt': 45}, {'language': 'R', 'cnt': 12}],
        [{'started_at': '2026-02-28T10:00:00'}],
    ]
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _get_manifest_impl
        result = _get_manifest_impl()
    assert result['tables']['repos']['row_count'] == 143
    assert 'languages' in result['summary']


def test_get_manifest_empty_db(mock_db):
    mock_db.fetchone.side_effect = [
        {'count': 0}, {'count': 0}, {'count': 0}, {'count': 0},
    ]
    mock_db.fetchall.side_effect = [[], []]
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _get_manifest_impl
        result = _get_manifest_impl()
    assert result['tables']['repos']['row_count'] == 0
```

**Step 2: Run test — verify fail**

Run: `pytest tests/test_mcp.py -v`
Expected: FAIL (module not found)

**Step 3: Implement**

```python
# repoindex/mcp/__init__.py
"""MCP server for repoindex."""
```

```python
# repoindex/mcp/server.py
"""
MCP server for repoindex.

Provides LLM access to the repoindex database via tools:
- get_manifest: Overview of database contents
- get_schema: SQL DDL for schema introspection
- run_sql: Execute read-only SQL queries
- refresh: Trigger a database refresh

Requires: pip install repoindex[mcp]
"""

import subprocess

from ..config import load_config
from ..database.connection import Database


def _get_db():
    """Get a read-only Database instance."""
    config = load_config()
    return Database(config=config, read_only=True)


def _get_manifest_impl() -> dict:
    db = _get_db()
    with db:
        tables = {}
        for table_name, desc in [
            ('repos', 'Repository metadata'),
            ('events', 'Git events (commits, tags)'),
            ('tags', 'Repository tags'),
            ('publications', 'Package registry publications'),
        ]:
            db.execute(f"SELECT COUNT(*) as count FROM {table_name}")
            row = db.fetchone()
            tables[table_name] = {
                'row_count': row['count'] if row else 0,
                'description': desc,
            }

        db.execute(
            "SELECT language, COUNT(*) as cnt FROM repos "
            "WHERE language IS NOT NULL GROUP BY language ORDER BY cnt DESC"
        )
        languages = {r['language']: r['cnt'] for r in db.fetchall()}

        db.execute(
            "SELECT started_at FROM refresh_log ORDER BY started_at DESC LIMIT 1"
        )
        refresh_rows = db.fetchall()
        last_refresh = refresh_rows[0]['started_at'] if refresh_rows else None

    return {
        'description': 'repoindex filesystem git catalog',
        'database': str(db.db_path),
        'tables': tables,
        'summary': {
            'languages': languages,
            'last_refresh': last_refresh,
        },
    }
```

**Step 4: Run test — verify pass**

Run: `pytest tests/test_mcp.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add repoindex/mcp/__init__.py repoindex/mcp/server.py tests/test_mcp.py
git commit -m "feat(mcp): add get_manifest tool"
```

---

### Task 3: MCP server — get_schema tool

**Files:**
- Modify: `repoindex/mcp/server.py`
- Modify: `tests/test_mcp.py`

**Step 1: Write failing tests**

Append to `tests/test_mcp.py`:

```python
def test_get_schema_all_tables(mock_db):
    mock_db.fetchall.return_value = [
        {'sql': 'CREATE TABLE repos (id INTEGER PRIMARY KEY)'},
        {'sql': 'CREATE TABLE events (id INTEGER PRIMARY KEY)'},
    ]
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl()
    assert len(result['ddl']) == 2


def test_get_schema_single_table(mock_db):
    mock_db.fetchall.side_effect = [
        [{'sql': 'CREATE TABLE repos (id INTEGER PRIMARY KEY, name TEXT)'}],
        [{'cid': 0, 'name': 'id', 'type': 'INTEGER', 'notnull': 0, 'dflt_value': None, 'pk': 1},
         {'cid': 1, 'name': 'name', 'type': 'TEXT', 'notnull': 1, 'dflt_value': None, 'pk': 0}],
    ]
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table='repos')
    assert result['columns'][0]['name'] == 'id'


def test_get_schema_unknown_table(mock_db):
    mock_db.fetchall.side_effect = [[], []]
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _get_schema_impl
        result = _get_schema_impl(table='nonexistent')
    assert result['ddl'] == []
```

**Step 2: Run — fail**

Run: `pytest tests/test_mcp.py -k "get_schema" -v`

**Step 3: Implement**

Append to `repoindex/mcp/server.py`:

```python
def _get_schema_impl(table=None) -> dict:
    db = _get_db()
    with db:
        if table:
            db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            ddl_rows = db.fetchall()
            db.execute(f"PRAGMA table_info({table})")
            columns = [dict(r) for r in db.fetchall()]
            return {'table': table, 'ddl': [r['sql'] for r in ddl_rows if r['sql']], 'columns': columns}
        else:
            db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' ORDER BY name"
            )
            return {'ddl': [r['sql'] for r in db.fetchall() if r['sql']]}
```

**Step 4: Run — pass**

Run: `pytest tests/test_mcp.py -k "get_schema" -v`

**Step 5: Commit**

```bash
git add repoindex/mcp/server.py tests/test_mcp.py
git commit -m "feat(mcp): add get_schema tool"
```

---

### Task 4: MCP server — run_sql tool

**Files:**
- Modify: `repoindex/mcp/server.py`
- Modify: `tests/test_mcp.py`

**Step 1: Write failing tests**

Append to `tests/test_mcp.py`:

```python
def test_run_sql_select(mock_db):
    mock_db.fetchall.return_value = [{'name': 'repoindex', 'language': 'Python'}]
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELECT name, language FROM repos")
    assert result['rows'] == [{'name': 'repoindex', 'language': 'Python'}]


def test_run_sql_cte(mock_db):
    mock_db.fetchall.return_value = [{'cnt': 5}]
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("WITH x AS (SELECT 1) SELECT COUNT(*) as cnt FROM repos")
    assert 'rows' in result


def test_run_sql_rejects_insert(mock_db):
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _run_sql_impl
        assert 'error' in _run_sql_impl("INSERT INTO repos (name, path) VALUES ('x', '/x')")


def test_run_sql_rejects_drop(mock_db):
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _run_sql_impl
        assert 'error' in _run_sql_impl("DROP TABLE repos")


def test_run_sql_rejects_delete(mock_db):
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _run_sql_impl
        assert 'error' in _run_sql_impl("DELETE FROM repos")


def test_run_sql_syntax_error(mock_db):
    from sqlite3 import OperationalError
    mock_db.execute.side_effect = OperationalError("syntax error")
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _run_sql_impl
        assert 'error' in _run_sql_impl("SELCT * FROM repos")


def test_run_sql_row_limit(mock_db):
    mock_db.fetchall.return_value = [{'id': i} for i in range(600)]
    with patch('repoindex.mcp.server._get_db', return_value=mock_db):
        from repoindex.mcp.server import _run_sql_impl
        result = _run_sql_impl("SELECT id FROM repos")
    assert len(result['rows']) == 500
    assert result['truncated'] is True
```

**Step 2: Run — fail**

Run: `pytest tests/test_mcp.py -k "run_sql" -v`

**Step 3: Implement**

Append to `repoindex/mcp/server.py`:

```python
MAX_ROWS = 500


def _run_sql_impl(query: str) -> dict:
    normalized = query.strip().upper()
    if not (normalized.startswith('SELECT') or normalized.startswith('WITH')):
        return {'error': 'Only SELECT and WITH (CTE) queries are allowed.'}

    db = _get_db()
    try:
        with db:
            db.execute(query)
            rows = [dict(r) for r in db.fetchall()]
            truncated = len(rows) > MAX_ROWS
            if truncated:
                rows = rows[:MAX_ROWS]
            return {'rows': rows, 'row_count': len(rows), 'truncated': truncated}
    except Exception as e:
        return {'error': str(e)}
```

**Step 4: Run — pass**

Run: `pytest tests/test_mcp.py -k "run_sql" -v`

**Step 5: Commit**

```bash
git add repoindex/mcp/server.py tests/test_mcp.py
git commit -m "feat(mcp): add run_sql tool with read-only guard and row limit"
```

---

### Task 5: MCP server — refresh tool

**Files:**
- Modify: `repoindex/mcp/server.py`
- Modify: `tests/test_mcp.py`

Runs `repoindex refresh` as a subprocess — cleanest way to trigger the full refresh pipeline from a long-running server.

**Step 1: Write failing tests**

Append to `tests/test_mcp.py`:

```python
def test_refresh_runs_subprocess():
    with patch('repoindex.mcp.server.subprocess') as mock_sp:
        mock_sp.run.return_value = MagicMock(returncode=0, stdout='Refreshed 42 repos', stderr='')
        from repoindex.mcp.server import _refresh_impl
        result = _refresh_impl()
    assert result['status'] == 'ok'
    assert '42' in result['output']


def test_refresh_with_flags():
    with patch('repoindex.mcp.server.subprocess') as mock_sp:
        mock_sp.run.return_value = MagicMock(returncode=0, stdout='Done', stderr='')
        from repoindex.mcp.server import _refresh_impl
        _refresh_impl(github=True, full=True)
    cmd = mock_sp.run.call_args[0][0]
    assert '--github' in cmd
    assert '--full' in cmd


def test_refresh_failure():
    with patch('repoindex.mcp.server.subprocess') as mock_sp:
        mock_sp.run.return_value = MagicMock(returncode=1, stdout='', stderr='Config not found')
        from repoindex.mcp.server import _refresh_impl
        result = _refresh_impl()
    assert result['status'] == 'error'
```

**Step 2: Run — fail**

Run: `pytest tests/test_mcp.py -k "refresh" -v`

**Step 3: Implement**

Append to `repoindex/mcp/server.py`:

```python
def _refresh_impl(github: bool = False, full: bool = False) -> dict:
    cmd = ['repoindex', 'refresh']
    if github:
        cmd.append('--github')
    if full:
        cmd.append('--full')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return {'status': 'ok', 'output': result.stdout.strip()}
        else:
            return {'status': 'error', 'error': result.stderr.strip() or result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'error': 'Refresh timed out after 5 minutes'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}
```

**Step 4: Run — pass**

Run: `pytest tests/test_mcp.py -k "refresh" -v`

**Step 5: Commit**

```bash
git add repoindex/mcp/server.py tests/test_mcp.py
git commit -m "feat(mcp): add refresh tool"
```

---

### Task 6: Wire FastMCP and add CLI entry point

**Files:**
- Modify: `repoindex/mcp/server.py` (add `create_server` at bottom)
- Create: `repoindex/commands/mcp_cmd.py`
- Modify: `repoindex/cli.py`

**Step 1: Write failing test**

Append to `tests/test_mcp.py`:

```python
from click.testing import CliRunner


def test_mcp_cli_registered():
    from repoindex.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ['mcp', '--help'])
    assert result.exit_code in (0, 1)
```

**Step 2: Run — fail**

Run: `pytest tests/test_mcp.py::test_mcp_cli_registered -v`

**Step 3: Implement**

Add to bottom of `repoindex/mcp/server.py`:

```python
def create_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError(
            "MCP server requires the 'mcp' package. "
            "Install with: pip install repoindex[mcp]"
        )

    mcp = FastMCP("repoindex")

    @mcp.tool()
    def get_manifest() -> dict:
        """Get overview of the repoindex database: tables, row counts, languages, last refresh."""
        return _get_manifest_impl()

    @mcp.tool()
    def get_schema(table: str | None = None) -> dict:
        """Get SQL DDL schema. No arg = all tables. With table name = DDL + column details."""
        return _get_schema_impl(table=table)

    @mcp.tool()
    def run_sql(query: str) -> dict:
        """Execute read-only SQL (SELECT/WITH only). Returns up to 500 rows as JSON."""
        return _run_sql_impl(query)

    @mcp.tool()
    def refresh(github: bool = False, full: bool = False) -> dict:
        """Refresh the repoindex database. github=True for GitHub metadata, full=True for full rescan."""
        return _refresh_impl(github=github, full=full)

    return mcp
```

Create `repoindex/commands/mcp_cmd.py`:

```python
"""MCP server command for repoindex."""
import click


@click.command('mcp')
def mcp_handler():
    """Start the MCP server (stdio transport).

    Provides LLM access to the repoindex database.
    Requires: pip install repoindex[mcp]
    """
    try:
        from ..mcp.server import create_server
    except ImportError:
        click.echo(
            "Error: MCP server requires the 'mcp' package.\n"
            "Install with: pip install repoindex[mcp]",
            err=True,
        )
        raise SystemExit(1)

    server = create_server()
    server.run()
```

Modify `repoindex/cli.py` — add import and registration:

```python
from repoindex.commands.mcp_cmd import mcp_handler
# ...
cli.add_command(mcp_handler, name='mcp')
```

**Step 4: Run — pass**

Run: `pytest tests/test_mcp.py -v`

**Step 5: Full suite**

Run: `pytest --maxfail=5 -q`

**Step 6: Commit**

```bash
git add repoindex/mcp/server.py repoindex/commands/mcp_cmd.py repoindex/cli.py
git commit -m "feat(mcp): wire FastMCP server and add 'repoindex mcp' CLI command"
```

---

## Feature 2: Rename render to export + enhance arkiv + add HTML

### Task 7: Rename `render` to `export` with deprecated alias

**Files:**
- Modify: `repoindex/commands/render.py:20,23,52-84` (command name, help text, examples)
- Modify: `repoindex/cli.py:18,53` (registration)
- Modify: `tests/test_render_command.py` (update references)

This is a pure rename. The handler function stays `render_handler` internally (or rename to `export_handler`). The CLI command name changes from `render` to `export`. A hidden deprecated `render` alias is kept.

**Step 1: Write failing test for new name**

Add to `tests/test_render_command.py`:

```python
class TestExportAlias:
    def test_export_command_works(self, runner, mock_query):
        """The 'export' command name is registered."""
        from repoindex.cli import cli
        result = runner.invoke(cli, ['export', 'csv'])
        assert result.exit_code == 0
        assert 'test-repo' in result.output

    def test_render_deprecated_still_works(self, runner, mock_query):
        """The 'render' command still works as deprecated alias."""
        from repoindex.cli import cli
        result = runner.invoke(cli, ['render', 'csv'])
        assert result.exit_code == 0
```

**Step 2: Run — fail**

Run: `pytest tests/test_render_command.py::TestExportAlias -v`
Expected: FAIL (no 'export' command)

**Step 3: Implement the rename**

In `repoindex/commands/render.py`:
- Change `@click.command('render')` to `@click.command('export')`
- Update the docstring/examples to say `export` instead of `render`
- Rename the function from `render_handler` to `export_handler`

In `repoindex/cli.py`:
- Change import: `from repoindex.commands.render import export_handler`
- Change registration: `cli.add_command(export_handler, name='export')`
- Add deprecated alias:
  ```python
  import copy as copy_module
  _render_deprecated = copy_module.copy(export_handler)
  _render_deprecated.hidden = True
  _render_deprecated.deprecated = True
  cli.add_command(_render_deprecated, name='render')
  ```

In `tests/test_render_command.py`:
- Update `from repoindex.commands.render import export_handler` (was `render_handler`)
- Update all `runner.invoke(render_handler, ...)` to `runner.invoke(export_handler, ...)`
- Update mock patch paths from `repoindex.commands.render._get_repos_from_query` etc. (these stay the same since the file didn't move)

**Step 4: Run — pass**

Run: `pytest tests/test_render_command.py -v`

**Step 5: Full suite**

Run: `pytest --maxfail=5 -q`

**Step 6: Commit**

```bash
git add repoindex/commands/render.py repoindex/cli.py tests/test_render_command.py
git commit -m "refactor: rename render command to export (render kept as deprecated alias)"
```

---

### Task 8: Enhance arkiv export — directory output with full archive

**Files:**
- Modify: `repoindex/commands/render.py:120-127` (output logic for arkiv)
- Modify: `repoindex/exporters/arkiv.py` (add `export_archive` function)
- Create: `tests/test_export_arkiv.py`

When `-o <dir>` is given for the `arkiv` format, produce the full archive (repos.jsonl + events.jsonl + README.md + schema.yaml) instead of streaming JSONL.

**Step 1: Write failing tests**

```python
# tests/test_export_arkiv.py
"""Tests for arkiv directory export."""
import json
import pytest
import yaml
from pathlib import Path


MOCK_REPOS = [
    {
        'id': 1, 'name': 'myrepo', 'path': '/home/user/github/myrepo',
        'branch': 'main', 'language': 'Python', 'is_clean': 1,
        'description': 'A test repo', 'remote_url': 'https://github.com/user/myrepo',
        'owner': 'user', 'license_key': 'MIT', 'scanned_at': '2026-02-28T10:00:00',
        'has_readme': 1, 'has_license': 1, 'has_ci': 0, 'has_citation': 0,
        'languages': '["Python", "Shell"]', 'readme_content': None,
        'tags': '["topic/cli"]',
        'citation_doi': None, 'citation_title': None, 'citation_version': None,
        'citation_repository': None, 'citation_license': None, 'citation_authors': None,
        'github_stars': 5, 'github_forks': 1, 'github_watchers': 3,
        'github_open_issues': 2, 'github_is_fork': 0, 'github_is_private': 0,
        'github_is_archived': 0, 'github_description': 'A repo index tool',
        'github_created_at': '2025-01-01', 'github_updated_at': '2026-02-28',
        'github_topics': '["cli", "git"]',
    },
]

MOCK_EVENTS = [
    {
        'repo_name': 'myrepo', 'repo_path': '/home/user/github/myrepo',
        'type': 'commit', 'timestamp': '2026-02-28T09:30:00',
        'ref': 'abc1234', 'message': 'feat: add export',
        'author': 'user', 'data': {},
    },
]


def test_export_archive_creates_all_files(tmp_path):
    from repoindex.exporters.arkiv import export_archive
    export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
    assert (tmp_path / "repos.jsonl").exists()
    assert (tmp_path / "events.jsonl").exists()
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "schema.yaml").exists()


def test_repos_jsonl_valid_arkiv(tmp_path):
    from repoindex.exporters.arkiv import export_archive
    export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
    with open(tmp_path / "repos.jsonl") as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert len(records) == 1
    assert records[0]['mimetype'] == 'inode/directory'
    assert records[0]['uri'].startswith('file://')
    assert 'metadata' in records[0]


def test_events_jsonl_valid_arkiv(tmp_path):
    from repoindex.exporters.arkiv import export_archive
    export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
    with open(tmp_path / "events.jsonl") as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert len(records) == 1
    assert records[0]['mimetype'] == 'text/plain'
    assert records[0]['content'] == 'feat: add export'
    assert records[0]['metadata']['type'] == 'commit'


def test_readme_yaml_frontmatter(tmp_path):
    from repoindex.exporters.arkiv import export_archive
    export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
    content = (tmp_path / "README.md").read_text()
    assert content.startswith('---\n')
    parts = content.split('---\n', 2)
    fm = yaml.safe_load(parts[1])
    assert fm['name'] == 'repoindex export'
    paths = [c['path'] for c in fm['contents']]
    assert 'repos.jsonl' in paths
    assert 'events.jsonl' in paths


def test_schema_yaml_structure(tmp_path):
    from repoindex.exporters.arkiv import export_archive
    export_archive(tmp_path, MOCK_REPOS, MOCK_EVENTS)
    with open(tmp_path / "schema.yaml") as f:
        schema = yaml.safe_load(f)
    assert 'repos' in schema
    assert 'events' in schema


def test_empty_export(tmp_path):
    from repoindex.exporters.arkiv import export_archive
    export_archive(tmp_path, [], [])
    assert (tmp_path / "repos.jsonl").exists()
    assert (tmp_path / "repos.jsonl").stat().st_size == 0
```

**Step 2: Run — fail**

Run: `pytest tests/test_export_arkiv.py -v`

**Step 3: Implement `export_archive` in `repoindex/exporters/arkiv.py`**

Add to `repoindex/exporters/arkiv.py` (after the existing `ArkivExporter` class):

```python
def export_archive(
    output_dir,
    repos: list,
    events: list,
    version: str | None = None,
) -> dict:
    """Write full arkiv archive to output_dir.

    Creates: repos.jsonl, events.jsonl, README.md, schema.yaml

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


def _collect_meta_keys(d: dict, prefix: str = '') -> list:
    """Collect all keys from a nested dict."""
    keys = []
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        keys.append(full_key)
        if isinstance(v, dict):
            keys.extend(_collect_meta_keys(v, full_key))
    return keys
```

Then modify `repoindex/commands/render.py` output section (lines 120-127) to detect arkiv + directory output:

```python
    # Write output
    if output_file:
        import os
        # Directory-based export for arkiv
        if format_id == 'arkiv' and (os.path.isdir(output_file) or not os.path.splitext(output_file)[1]):
            from ..exporters.arkiv import export_archive
            from ..database.connection import Database
            from ..database.events import get_events

            events = []
            repo_paths = {r.get('path') for r in repos}
            try:
                with Database(config=config, read_only=True) as db:
                    for event in get_events(db):
                        if event.get('repo_path') in repo_paths:
                            events.append(event)
            except Exception:
                pass

            counts = export_archive(output_file, repos, events)
            click.echo(
                f"Exported {counts['repos']} repos and {counts['events']} events to {output_file}/",
                err=True,
            )
        else:
            with open(output_file, 'w') as f:
                count = exporter.export(repos, f, config=config)
            click.echo(f"Wrote {count} records to {output_file} ({exporter.name})", err=True)
    else:
        count = exporter.export(repos, sys.stdout, config=config)
        click.echo(f"{count} records exported ({exporter.name})", err=True)
```

**Step 4: Run — pass**

Run: `pytest tests/test_export_arkiv.py -v`

**Step 5: Full suite**

Run: `pytest --maxfail=5 -q`

**Step 6: Commit**

```bash
git add repoindex/exporters/arkiv.py repoindex/commands/render.py tests/test_export_arkiv.py
git commit -m "feat: arkiv directory export with README.md + schema.yaml"
```

---

### Task 9: Add HTML export format

**Files:**
- Modify: `repoindex/commands/render.py` (handle html format with directory output)
- Create: `repoindex/exporters/html.py`
- Create: `tests/test_export_html.py`

HTML export embeds the SQLite database (base64) into a single `index.html` using sql.js. It doesn't use the Exporter ABC — it takes the raw DB file.

**Step 1: Write failing tests**

```python
# tests/test_export_html.py
"""Tests for HTML export."""
import pytest
import sqlite3
from pathlib import Path


@pytest.fixture
def sample_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE repos (id INTEGER PRIMARY KEY, name TEXT, path TEXT,
            language TEXT, description TEXT, branch TEXT, is_clean BOOLEAN,
            github_stars INTEGER, scanned_at TEXT);
        INSERT INTO repos VALUES (1, 'myrepo', '/home/user/myrepo', 'Python',
            'A test repo', 'main', 1, 5, '2026-02-28');
        CREATE TABLE events (id INTEGER PRIMARY KEY, repo_id INTEGER,
            type TEXT, timestamp TEXT, ref TEXT, message TEXT, author TEXT);
        INSERT INTO events VALUES (1, 1, 'commit', '2026-02-28', 'abc123',
            'initial commit', 'user');
        CREATE TABLE tags (repo_id INTEGER, tag TEXT, source TEXT);
        INSERT INTO tags VALUES (1, 'python', 'implicit');
        CREATE TABLE publications (id INTEGER PRIMARY KEY, repo_id INTEGER,
            registry TEXT, package_name TEXT, published BOOLEAN);
    """)
    conn.commit()
    conn.close()
    return db_path


def test_html_creates_index_html(tmp_path, sample_db):
    from repoindex.exporters.html import export_html
    output_dir = tmp_path / "html_out"
    export_html(output_dir, sample_db)
    assert (output_dir / "index.html").exists()


def test_html_references_sql_js(tmp_path, sample_db):
    from repoindex.exporters.html import export_html
    output_dir = tmp_path / "html_out"
    export_html(output_dir, sample_db)
    content = (output_dir / "index.html").read_text()
    assert 'sql-wasm' in content


def test_html_embeds_database(tmp_path, sample_db):
    from repoindex.exporters.html import export_html
    output_dir = tmp_path / "html_out"
    export_html(output_dir, sample_db)
    content = (output_dir / "index.html").read_text()
    assert 'DB_BASE64' in content


def test_html_is_single_file(tmp_path, sample_db):
    from repoindex.exporters.html import export_html
    output_dir = tmp_path / "html_out"
    export_html(output_dir, sample_db)
    files = list(output_dir.iterdir())
    assert len(files) == 1
    assert files[0].name == "index.html"
```

**Step 2: Run — fail**

Run: `pytest tests/test_export_html.py -v`

**Step 3: Implement `repoindex/exporters/html.py`**

Create `repoindex/exporters/html.py` with `export_html(output_dir, db_path)` that:
- Reads the SQLite DB as bytes, base64-encodes it
- Embeds into an HTML template with:
  - sql.js loaded from CDN (`https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/sql-wasm.js`)
  - Dark theme (GitHub-style: `#0d1117` background, `#c9d1d9` text)
  - Tabbed views: Repos, Events, Tags, Publications, SQL Console
  - Header with stats (repo count, event count, language count)
  - Client-side search filter
  - Column sorting (click headers)
  - Boolean badge formatting (`is_clean`, `has_*`, `published`)
  - SQL Console with textarea + Run button
- Writes single `index.html` to output_dir

Then modify `repoindex/commands/render.py` to handle `html` format:
- Detect `format_id == 'html'` before the exporter lookup
- Require `-o <dir>` (error if stdout)
- Call `export_html(output_dir, db_path)` directly

**Step 4: Run — pass**

Run: `pytest tests/test_export_html.py -v`

**Step 5: Full suite**

Run: `pytest --maxfail=5 -q`

**Step 6: Commit**

```bash
git add repoindex/exporters/html.py repoindex/commands/render.py tests/test_export_html.py
git commit -m "feat: add HTML export — self-contained SQLite browser"
```

---

## Finalization

### Task 10: Update package metadata and version

**Files:**
- Modify: `pyproject.toml:7` (version to 0.12.0)
- Modify: `pyproject.toml:42` (add `repoindex.mcp` to packages)

**Step 1: Update**

```toml
version = "0.12.0"
packages = [ "repoindex", "repoindex.commands", "repoindex.integrations", "repoindex.providers", "repoindex.exporters", "repoindex.mcp",]
```

**Step 2: Reinstall and run coverage**

Run: `pip install -e ".[mcp]" && pytest --cov=repoindex --cov-report=term-missing --maxfail=5 -q`

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: bump to v0.12.0, add repoindex.mcp to packages"
```

---

### Task 11: Smoke test

**Step 1: Full test suite**

Run: `pytest --maxfail=5 -v`

**Step 2: CLI smoke tests**

```bash
timeout 2 repoindex mcp 2>&1 || true
repoindex export --list-formats
repoindex export arkiv -o /tmp/ri-arkiv-test/ --dry-run  # dry-run won't work yet, test actual
repoindex export html -o /tmp/ri-html-test/
repoindex export csv --language python | head -5
```

**Step 3: Verify deprecated alias**

Run: `repoindex render --list-formats`
Expected: works, same output as `export --list-formats`
