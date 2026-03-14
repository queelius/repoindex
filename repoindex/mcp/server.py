"""
MCP server for repoindex.

Provides LLM access to the repoindex database via tools:
- get_manifest: Overview of database contents
- get_schema: SQL DDL for schema introspection
- run_sql: Execute read-only SQL queries
- refresh: Trigger a database refresh

Requires: pip install repoindex[mcp]

Security: run_sql relies on the read-only database connection mode for
write protection. The prefix check is a courtesy guard for better error
messages, not a security boundary.
"""

import re
import subprocess
from contextlib import contextmanager

from ..config import load_config
from ..database.connection import Database, get_db_path

_TABLE_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


@contextmanager
def _open_db():
    """Open a read-only database connection with loaded config."""
    config = load_config()
    with Database(config=config, read_only=True) as db:
        yield db, config


def _get_manifest_impl() -> dict:
    """Get overview of the repoindex database."""
    with _open_db() as (db, config):
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
        'database': str(get_db_path(config)),
        'tables': tables,
        'summary': {
            'languages': languages,
            'last_refresh': last_refresh,
        },
    }


def _get_schema_impl(table=None) -> dict:
    """Get SQL DDL schema for one or all tables."""
    with _open_db() as (db, _config):
        if table:
            if not _TABLE_NAME_RE.match(table):
                return {'error': f'Invalid table name: {table}'}
            db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            ddl_rows = db.fetchall()
            if not ddl_rows:
                return {'error': f'Table not found: {table}'}
            db.execute(f"PRAGMA table_info({table})")
            columns = [dict(r) for r in db.fetchall()]
            return {
                'table': table,
                'ddl': [r['sql'] for r in ddl_rows if r['sql']],
                'columns': columns,
            }
        else:
            db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' ORDER BY name"
            )
            return {'ddl': [r['sql'] for r in db.fetchall() if r['sql']]}


MAX_ROWS = 500


def _run_sql_impl(query: str) -> dict:
    """Execute a read-only SQL query."""
    normalized = query.strip().upper()
    if not (normalized.startswith('SELECT') or normalized.startswith('WITH')):
        return {'error': 'Only SELECT and WITH (CTE) queries are allowed.'}

    try:
        with _open_db() as (db, _config):
            db.execute(query)
            rows = [dict(r) for r in db.fetchmany(MAX_ROWS + 1)]
            truncated = len(rows) > MAX_ROWS
            if truncated:
                rows = rows[:MAX_ROWS]
            return {
                'rows': rows,
                'row_count': len(rows),
                'truncated': truncated,
            }
    except Exception as e:
        return {'error': str(e)}


def _refresh_impl(github: bool = False, full: bool = False) -> dict:
    """Run the repoindex refresh command as a subprocess."""
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
            return {
                'status': 'error',
                'error': result.stderr.strip() or result.stdout.strip(),
            }
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'error': 'Refresh timed out after 5 minutes'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def create_server():
    """Create and return a FastMCP server instance."""
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
