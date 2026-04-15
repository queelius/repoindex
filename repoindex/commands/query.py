"""
Query command for repoindex.

Provides powerful querying capabilities over repository metadata
using a simple, intuitive query language that compiles to SQL.
"""

import click
import json
import re
import sys
from typing import Optional, List

from ..config import load_config
from ..database import (
    Database,
    compile_query,
    QueryCompileError,
)


# DSL operators and keywords that indicate a structured query
DSL_PATTERNS = [
    r'==', r'!=', r'>=', r'<=', r'>', r'<', r'~=',
    r'\bcontains\b', r'\bin\b', r'\band\b', r'\bor\b', r'\bnot\b',
    r'\border\s+by\b', r'\blimit\b', r'\bhas_event\b', r'\btagged\b',
    r'\bupdated_since\b', r'\bis_published\b', r'\bhas_doi\b', r"'[^']*'", r'"[^"]*"',
]

# Known boolean field names that should be treated as DSL predicates, not text search
BOOLEAN_FIELDS = {
    # Local boolean fields
    'is_clean', 'clean', 'has_readme', 'has_license', 'has_ci',
    'has_upstream', 'uncommitted_changes', 'uncommitted',
    'has_citation',  # Citation detection (CITATION.cff, .zenodo.json, etc.)
    # GitHub boolean fields (short aliases)
    'is_fork', 'is_archived', 'archived', 'is_private', 'private', 'has_pages',
    # GitHub boolean fields (explicit prefix)
    'github_is_fork', 'github_is_archived', 'github_is_private',
    'github_has_issues', 'github_has_wiki', 'github_has_pages',
}


def _load_query_views(config: dict) -> dict:
    """Load query-based views for `@name` expansion in the DSL.

    Views live in ~/.repoindex/views.yaml (managed by ViewService), not in
    config.yaml. Only query-based views are inlineable into the DSL — list-
    based and composite views are resolved by ViewService separately. Any
    error loading views.yaml is logged and the returned dict is empty, so
    the query command stays usable if the file is malformed.
    """
    views: dict = dict(config.get('views', {}))  # legacy config-yaml path
    try:
        from ..services.view_service import ViewService
        service = ViewService(config=config)
        service.load()
        for name in service.list_views():
            spec = service.get_spec(name)
            if spec is not None and spec.query:
                views.setdefault(name, spec.query)
    except Exception as e:
        click.echo(
            json.dumps({'warning': f'Could not load views: {e}', 'type': 'view_load_warning'}),
            err=True,
        )
    return views


def _is_simple_text_query(query_string: str) -> bool:
    """
    Check if a query is a simple text search (not a DSL query).

    Simple text queries are plain words/phrases without DSL operators.
    Examples of simple queries: "python", "machine learning", "auth"
    Examples of DSL queries: "language == 'Python'", "stars > 10"
    """
    query_string = query_string.strip()

    if not query_string:
        return False

    # Check if it's a known boolean field (DSL predicate, not text search)
    if query_string.lower() in BOOLEAN_FIELDS:
        return False

    for pattern in DSL_PATTERNS:
        if re.search(pattern, query_string, re.IGNORECASE):
            return False

    if re.search(r'\w+\s*\(', query_string):
        return False

    if query_string.startswith('@'):
        return False

    return True


def _build_query_from_flags(
    query_string: Optional[str],
    dirty: bool = False,
    language: Optional[str] = None,
    recent: Optional[str] = None,
    tag: Optional[List[str]] = None,
    *,
    sort: Optional[str] = None,
) -> str:
    """Build a DSL query string from convenience flags."""
    predicates = []

    # Start with user's query if provided
    if query_string:
        predicates.append(f"({query_string})")

    # Dirty status
    if dirty:
        predicates.append("not is_clean")

    # Language filter
    if language:
        # Normalize language name
        lang_map = {
            'py': 'Python',
            'python': 'Python',
            'js': 'JavaScript',
            'javascript': 'JavaScript',
            'ts': 'TypeScript',
            'typescript': 'TypeScript',
            'rb': 'Ruby',
            'ruby': 'Ruby',
            'rs': 'Rust',
            'rust': 'Rust',
            'go': 'Go',
            'golang': 'Go',
            'cpp': 'C++',
            'c++': 'C++',
        }
        normalized = lang_map.get(language.lower(), language)
        predicates.append(f"language == '{normalized}'")

    # Recent activity
    if recent:
        predicates.append(f"has_event('commit', since='{recent}')")

    # Tag filters
    if tag:
        for t in tag:
            predicates.append(f"tagged('{t}')")

    # Join predicates with 'and'
    if not predicates:
        query = ""
    else:
        query = " and ".join(predicates)

    # Append sort clause
    if sort:
        sort = sort.strip()
        # Allow shorthand: "stars" → "github_stars desc", "name" → "name asc"
        sort_aliases = {
            'stars': 'github_stars desc',
            'name': 'name asc',
            'language': 'language asc',
            'updated': 'scanned_at desc',
        }
        resolved = sort_aliases.get(sort.lower(), sort)
        if query:
            query += f" order by {resolved}"
        else:
            query = f"1 == 1 order by {resolved}"

    return query


@click.command()
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL (default: pretty table)')
@click.option('--brief', is_flag=True, help='Compact output: just repo names (one per line)')
@click.option('--fields', '--columns', help='Comma-separated list of fields to display')
@click.option('--limit', type=int, help='Limit number of results')
@click.option('--explain', 'show_explain', is_flag=True, help='Show compiled SQL and params without executing')
@click.option('--fts', is_flag=True, help='Use full-text search instead of DSL query')
@click.option('--debug', is_flag=True, help='Enable debug logging')
# Convenience flags
@click.option('--language', '-l', help='Filter by language (e.g., python, r, js)')
@click.option('--dirty', is_flag=True, help='Repos with uncommitted changes')
@click.option('--tag', '-t', multiple=True, help='Filter by tag (supports wildcards)')
@click.option('--recent', '-r', help='Repos with recent commits (e.g., 7d, 30d)')
@click.option('--sort', '-s', help='Sort results (e.g., stars, name, language, or field [asc|desc])')
@click.option('--count', is_flag=True, help='Output only the count of matching repos')
def query_handler(
    query_string: str,
    output_json: bool,
    brief: bool,
    fields: Optional[str],
    limit: Optional[int],
    show_explain: bool,
    fts: bool,
    debug: bool,
    # Convenience flags
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
    sort: Optional[str],
    count: bool,
):
    """
    Query repositories using a powerful query language.

    The query is compiled to SQL and executed against the local database.
    Run 'repoindex refresh' first to populate the database.

    Output is a formatted table by default. Use --json for JSONL output.

    \b
    Examples:
        # List all repos (pretty table by default)
        repoindex query
        # Simple text search (auto-detected)
        repoindex query "bayes"
        # Convenience flags
        repoindex query --dirty
        repoindex query --language python
        repoindex query --recent 7d
        repoindex query --tag "work/*"
        # Sorting
        repoindex query --language python --sort stars
        repoindex query --sort "name asc"
        # Count matching repos
        repoindex query --language python --count
        # Combine flags with DSL
        repoindex query "stars > 10" --language python
        # JSONL output for piping
        repoindex query --json | jq '.name'
        # DSL queries
        repoindex query "language == 'Python' and stars > 10"
        repoindex query "is_clean and not archived"
        repoindex query "has_event('commit', since='30d')"
        # Ordering and limiting
        repoindex query "language == 'Python' order by stars desc"
        repoindex query "stars > 0 order by stars desc limit 10"
        # Show compiled SQL and params
        repoindex query "language == 'Python'" --explain
    """
    config = load_config()

    if debug:
        import logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    # Build query from flags
    has_flags = any([dirty, language, recent, tag, sort])
    if has_flags:
        query_string = _build_query_from_flags(
            query_string if query_string else None,
            dirty=dirty, language=language, recent=recent, tag=list(tag),
            sort=sort,
        )

    # If no query and no flags, show all repos
    if not query_string:
        query_string = "1 == 1"  # Match all

    # Determine output mode: pretty is default, --json switches to JSONL
    pretty = not output_json and not brief and not count

    # Full-text search mode (explicit or auto-detected)
    if fts or (_is_simple_text_query(query_string) and query_string != "1 == 1"):
        if count:
            _execute_fts_count(config, query_string, limit, debug)
        else:
            _execute_fts_query(config, query_string, pretty, brief, fields, limit, debug)
        return

    # Compile to SQL
    try:
        views = _load_query_views(config)
        compiled = compile_query(query_string, views=views)

        if limit and not compiled.limit:
            compiled = compile_query(f"{query_string} limit {limit}", views=views)

        if show_explain:
            # Pretty formatted explain output
            click.echo(f"SQL: {compiled.sql}", err=False)
            click.echo(f"Params: {compiled.params}", err=False)
            if compiled.order_by:
                click.echo(f"Order by: {compiled.order_by}", err=False)
            if compiled.limit:
                click.echo(f"Limit: {compiled.limit}", err=False)
            return

        if count:
            _execute_sql_count(config, compiled, debug)
        else:
            _execute_sql_query(config, compiled, pretty, brief, fields, debug)

    except QueryCompileError as e:
        print(json.dumps({
            'error': str(e),
            'type': 'query_compile_error',
            'query': query_string,
        }), file=sys.stderr)
        sys.exit(1)


def _execute_sql_query(config, compiled, pretty, brief, fields, debug):
    """Execute a compiled SQL query."""
    from . import warn_if_stale
    results = []

    with Database(config=config, read_only=True) as db:
        warn_if_stale(db)
        if debug:
            print(f"DEBUG: SQL: {compiled.sql}", file=sys.stderr)
            print(f"DEBUG: Params: {compiled.params}", file=sys.stderr)

        db.execute(compiled.sql, compiled.params)
        rows = db.fetchall()

        for row in rows:
            record = dict(row)
            db.execute("SELECT tag FROM tags WHERE repo_id = ?", (record['id'],))
            record['tags'] = [r['tag'] for r in db.fetchall()]

            if pretty:
                results.append(record)
            else:
                _output_result(record, fields, brief)

    if pretty:
        _display_pretty_results(results, fields)


def _execute_fts_query(config, query_string, pretty, brief, fields, limit, debug):
    """Execute a full-text search query."""
    from . import warn_if_stale
    results = []

    with Database(config=config, read_only=True) as db:
        warn_if_stale(db)
        sql = """
            SELECT r.*, GROUP_CONCAT(t.tag) as tags_csv
            FROM repos r
            JOIN repos_fts fts ON fts.rowid = r.id
            LEFT JOIN tags t ON t.repo_id = r.id
            WHERE repos_fts MATCH ?
            GROUP BY r.id
            ORDER BY rank
        """
        if limit:
            sql += f" LIMIT {limit}"

        if debug:
            print(f"DEBUG: FTS: {query_string}", file=sys.stderr)

        db.execute(sql, (query_string,))

        for row in db.fetchall():
            record = dict(row)
            tags_csv = record.pop('tags_csv', None)
            record['tags'] = tags_csv.split(',') if tags_csv else []

            if pretty:
                results.append(record)
            else:
                _output_result(record, fields, brief)

    if pretty:
        _display_pretty_results(results, fields)


def _execute_sql_count(config, compiled, debug):
    """Execute a compiled SQL query and output just the count."""
    from . import warn_if_stale

    with Database(config=config, read_only=True) as db:
        warn_if_stale(db)
        if debug:
            print(f"DEBUG: SQL: {compiled.sql}", file=sys.stderr)
        db.execute(compiled.sql, compiled.params)
        rows = db.fetchall()
        print(len(rows))


def _execute_fts_count(config, query_string, limit, debug):
    """Execute a full-text search query and output just the count."""
    from . import warn_if_stale

    with Database(config=config, read_only=True) as db:
        warn_if_stale(db)
        sql = """
            SELECT COUNT(*) as cnt
            FROM repos r
            JOIN repos_fts fts ON fts.rowid = r.id
            WHERE repos_fts MATCH ?
        """
        if debug:
            print(f"DEBUG: FTS count: {query_string}", file=sys.stderr)
        db.execute(sql, (query_string,))
        row = db.fetchone()
        count = min(row['cnt'], limit) if limit else row['cnt']
        print(count)


def _output_result(result: dict, fields: Optional[str], brief: bool = False):
    """Output a single result in JSONL format."""
    if brief:
        print(result.get('name', result.get('path', '').split('/')[-1]), flush=True)
        return

    output = {
        'path': result.get('path', ''),
        'name': result.get('name', result.get('path', '').split('/')[-1])
    }

    if fields:
        for field in fields.split(','):
            field = field.strip()
            if '.' in field:
                value = result
                for part in field.split('.'):
                    value = value.get(part, {}) if isinstance(value, dict) else None
                if value is not None:
                    output[field] = value
            elif field in result:
                output[field] = result[field]
    else:
        if result.get('tags'):
            output['tags'] = result['tags']
        if result.get('language'):
            output['language'] = result['language']
        if result.get('github_stars'):
            output['github_stars'] = result['github_stars']
        if 'branch' in result:
            output['branch'] = result['branch']

    print(json.dumps(output, ensure_ascii=False, default=str), flush=True)


def _shorten_path(path: str) -> str:
    """Shorten a filesystem path for display (replace $HOME with ~)."""
    from pathlib import Path
    home = str(Path.home())
    if path.startswith(home):
        return '~' + path[len(home):]
    return path


def _display_pretty_results(results: list, fields: Optional[str]):
    """Display results in a pretty table."""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    from rich import box

    console = Console()

    if not results:
        console.print("[yellow]No repositories found matching the query.[/yellow]")
        return

    table = Table(
        title=f"Query Results ({len(results)} repositories)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )

    if fields:
        columns = ['name'] + [f.strip() for f in fields.split(',')]
    else:
        columns = ['name', 'path', 'language', 'is_clean']
        if any(r.get('github_stars') for r in results):
            columns.append('github_stars')
        columns.append('description')

    for col in columns:
        if col == 'is_clean':
            table.add_column('Clean', justify='center')
        elif col == 'description':
            table.add_column('Description', max_width=40, no_wrap=True)
        elif col == 'path':
            table.add_column('Path', style='dim')
        else:
            table.add_column(col.title().replace('_', ' '))

    for result in results:
        row = []
        for col in columns:
            if col == 'name':
                row.append(result.get('name', result.get('path', '').split('/')[-1]))
            elif col == 'path':
                row.append(_shorten_path(result.get('path', '')))
            elif col == 'is_clean':
                clean = result.get('is_clean')
                if clean is None:
                    row.append('[dim]?[/dim]')
                elif clean:
                    row.append('[green]yes[/green]')
                else:
                    row.append('[yellow]no[/yellow]')
            elif col == 'description':
                desc = result.get('description', '') or ''
                if len(desc) > 40:
                    desc = desc[:37] + '...'
                row.append(desc)
            elif col == 'tags':
                tags = result.get('tags', [])
                if isinstance(tags, str):
                    tags = tags.split(',') if tags else []
                if len(tags) > 3:
                    row.append(', '.join(tags[:3]) + f' (+{len(tags)-3})')
                else:
                    row.append(', '.join(tags))
            elif col == 'github_stars':
                row.append(str(result.get('github_stars', 0) or 0))
            elif '.' in col:
                value = result
                for part in col.split('.'):
                    value = value.get(part, {}) if isinstance(value, dict) else None
                row.append(str(value) if value is not None else '')
            else:
                row.append(str(result.get(col, '') or ''))
        table.add_row(*row)

    console.print(table)
    console.print(f"\n[bold]Total:[/bold] {len(results)} repositories")
