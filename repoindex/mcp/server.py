"""
MCP server for repoindex.

Provides LLM access to the repoindex database via tools:
- get_manifest: Overview of database contents
- get_schema: SQL DDL for schema introspection
- run_sql: Execute read-only SQL queries
- refresh: Trigger a database refresh
- tag: Manage user-assigned repo tags
- export: Produce longecho-compliant arkiv archive

Requires: pip install repoindex[mcp]

Security: run_sql relies on the read-only database connection mode for
write protection. The prefix check is a courtesy guard for better error
messages, not a security boundary.
"""

import fcntl
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from ..config import load_config
from ..database.connection import Database, get_db_path

_TABLE_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _sanitize_error(msg: str) -> str:
    """Strip user-identifying paths from error messages."""
    home = str(Path.home())
    if home in msg:
        msg = msg.replace(home, '~')
    return msg


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


def _run_cli(cmd: list, timeout: int, timeout_msg: str,
             ok_extra: Optional[dict] = None) -> dict:
    """Invoke a repoindex CLI subcommand and shape the result as an MCP dict.

    Collapses the identical subprocess-run + status/error shaping used by
    ``_refresh_impl``, ``_tag_impl``, and ``_export_impl``. On timeout,
    returns ``timeout_msg`` so each caller can phrase its own message.
    On other exceptions, returns a sanitized ``{type.__name__}: {e}``.

    ok_extra is merged into the ok-branch dict — callers that need
    ``output`` or echo-back fields set them there.
    """
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=str(Path.home()),
        )
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'error': timeout_msg}
    except Exception as e:
        return {'status': 'error', 'error': _sanitize_error(f'{type(e).__name__}: {e}')}

    if result.returncode == 0:
        out = {'status': 'ok', 'output': result.stdout.strip()}
        if ok_extra:
            out.update(ok_extra)
        return out
    return {
        'status': 'error',
        'error': result.stderr.strip() or result.stdout.strip(),
    }


def _strip_sql_comments(query: str) -> str:
    """Remove leading SQL comments and whitespace before prefix check."""
    while True:
        stripped = query.lstrip()
        if stripped.startswith('--'):
            # Skip to end of line
            nl = stripped.find('\n')
            if nl == -1:
                return ''
            query = stripped[nl+1:]
        elif stripped.startswith('/*'):
            end = stripped.find('*/')
            if end == -1:
                return ''
            query = stripped[end+2:]
        else:
            return stripped


def _run_sql_impl(query: str) -> dict:
    """Execute a read-only SQL query."""
    cleaned = _strip_sql_comments(query)
    normalized = cleaned.upper()
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
        # SQL errors are useful for the LLM — don't sanitize
        return {'error': str(e)}


# Refresh timeout: 30 minutes covers collections of ~1000 repos with all
# external sources enabled (GitHub API, PyPI, CRAN, Zenodo, etc.).
# Smaller collections finish much faster; this is just an upper bound.
_REFRESH_TIMEOUT_SECONDS = 1800


def _refresh_impl(
    github: bool = False,
    full: bool = False,
    pypi: bool = False,
    cran: bool = False,
    external: bool = False,
) -> dict:
    """Run the repoindex refresh command as a subprocess."""
    # Acquire lock to prevent concurrent refreshes. Any failure during
    # acquisition must close lock_fd if it was opened, or we leak the fd.
    lock_path = Path.home() / '.repoindex' / 'refresh.lock'
    lock_fd = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = open(lock_path, 'w')
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if lock_fd is not None:
            lock_fd.close()
        return {
            'status': 'error',
            'error': 'Another refresh is already running. Wait for it to complete.'
        }
    except Exception as e:
        if lock_fd is not None:
            lock_fd.close()
        return {
            'status': 'error',
            'error': _sanitize_error(f'Could not acquire refresh lock: {e}'),
        }

    try:
        cmd = ['repoindex', 'refresh']
        if github:
            cmd.append('--github')
        if pypi:
            cmd.extend(['--source', 'pypi'])
        if cran:
            cmd.extend(['--source', 'cran'])
        if external:
            cmd.append('--external')
        if full:
            cmd.append('--full')
        return _run_cli(
            cmd,
            timeout=_REFRESH_TIMEOUT_SECONDS,
            timeout_msg=f'Refresh timed out after {_REFRESH_TIMEOUT_SECONDS // 60} minutes',
        )
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass


def _tag_impl(repo: str, action: str, tag: str = "") -> dict:
    """Manage user-assigned repo tags."""
    if action not in ('add', 'remove', 'list'):
        return {'error': f'Invalid action: {action}. Use add, remove, or list.'}

    if action == 'list':
        with _open_db() as (db, _config):
            if repo:
                db.execute(
                    "SELECT t.tag, t.source FROM tags t "
                    "JOIN repos r ON t.repo_id = r.id "
                    "WHERE r.name = ? ORDER BY t.tag",
                    (repo,)
                )
            else:
                db.execute("SELECT DISTINCT tag, source FROM tags ORDER BY tag")
            rows = [dict(r) for r in db.fetchall()]
            return {'tags': rows, 'count': len(rows)}

    # add/remove validation
    if action in ('add', 'remove'):
        if not repo or not repo.strip():
            return {'error': f'Repository is required for {action} action.'}
        if not tag or not tag.strip():
            return {'error': f'Tag is required for {action} action.'}
        if repo.startswith('-') or tag.startswith('-'):
            return {
                'error': 'Repository and tag must not start with "-" (would be parsed as a flag).'
            }

    # add/remove via subprocess (writes to DB)
    cmd = ['repoindex', 'tag', action, repo, tag]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return {'status': 'ok', 'action': action, 'repo': repo, 'tag': tag}
        else:
            return {
                'status': 'error',
                'error': result.stderr.strip() or result.stdout.strip(),
            }
    except Exception as e:
        return {'status': 'error', 'error': _sanitize_error(str(e))}


def _export_impl(output_dir: str, query: str = "") -> dict:
    """Export repos as longecho-compliant arkiv archive."""
    # Reject queries that would be parsed as CLI flags by Click.
    if query.startswith('-'):
        return {
            'status': 'error',
            'error': 'query must not start with "-" (would be parsed as a flag).',
        }
    # Validate output_dir before invoking the CLI to prevent clobbering.
    p = Path(output_dir).expanduser().resolve()

    # Refuse to write into common sensitive dotfile directories
    home = Path.home().resolve()
    sensitive_dirs = {'.ssh', '.gnupg', '.aws', '.config', '.kube'}
    try:
        rel = p.relative_to(home)
        first = rel.parts[0] if rel.parts else ''
        if first in sensitive_dirs:
            return {
                'status': 'error',
                'error': _sanitize_error(f'Refusing to write to sensitive directory: {p}'),
            }
    except ValueError:
        # Not under home, that's fine
        pass

    # If directory exists and is non-empty, require it to look like an arkiv archive
    # (has a README.md with arkiv frontmatter) — prevents clobbering arbitrary dirs
    if p.exists():
        if not p.is_dir():
            return {
                'status': 'error',
                'error': _sanitize_error(f'output_dir exists and is not a directory: {p}'),
            }
        contents = list(p.iterdir())
        if contents:
            readme = p / 'README.md'
            if readme.exists():
                # Check it's an arkiv archive (has the right frontmatter)
                try:
                    head = readme.read_text(encoding='utf-8', errors='replace')[:500]
                    if 'generator: repoindex' not in head and 'arkiv' not in head.lower():
                        return {
                            'status': 'error',
                            'error': _sanitize_error(
                                f'output_dir exists but does not look like an arkiv archive: {p}. '
                                f'Use a new directory or empty an existing one.'
                            ),
                        }
                except Exception:
                    return {
                        'status': 'error',
                        'error': _sanitize_error(f'output_dir exists with unreadable content: {p}'),
                    }
            else:
                return {
                    'status': 'error',
                    'error': _sanitize_error(
                        f'output_dir exists and is non-empty but has no README.md: {p}. '
                        f'Use a new directory or empty an existing one.'
                    ),
                }

    # CLI signature: repoindex export [FORMAT_ID] [QUERY] -o DIR
    # When query is present, we must pass 'arkiv' explicitly so click doesn't
    # parse the query string as FORMAT_ID.
    cmd = ['repoindex', 'export']
    if query:
        cmd.extend(['arkiv', query])
    cmd.extend(['-o', str(p)])
    return _run_cli(
        cmd,
        timeout=120,
        timeout_msg='Export timed out after 2 minutes',
        ok_extra={'output_dir': str(p)},
    )


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
    def refresh(
        github: bool = False,
        pypi: bool = False,
        cran: bool = False,
        external: bool = False,
        full: bool = False,
    ) -> dict:
        """Refresh the repoindex database.

        Sources to enable:
        - github=True: GitHub stars, topics, fork status
        - pypi=True: PyPI version, downloads
        - cran=True: CRAN version
        - external=True: ALL external sources (github + all registries + zenodo)

        full=True: force re-scan of all repos (default: smart, only changed)

        Local sources (CITATION.cff, keywords, asset detection) always run.

        WRITES TO DISK: modifies ~/.repoindex/index.db. Concurrent refreshes
        are prevented via file lock.
        """
        return _refresh_impl(
            github=github,
            pypi=pypi,
            cran=cran,
            external=external,
            full=full,
        )

    @mcp.tool()
    def tag(repo: str, action: str, tag: str = "") -> dict:
        """Manage user-assigned repo tags. Actions: add, remove, list.
        Derived tags (from GitHub topics, PyPI, etc.) are auto-populated during refresh."""
        return _tag_impl(repo, action, tag)

    @mcp.tool()
    def export(output_dir: str, query: str = "") -> dict:
        """Export repos as longecho-compliant arkiv archive to output_dir.
        Includes JSONL data, schema, SQLite database, and HTML browser.
        Optional query filters which repos are exported (DSL or @view)."""
        return _export_impl(output_dir, query)

    return mcp
