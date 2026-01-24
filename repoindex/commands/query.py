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
    r'\bupdated_since\b', r'\bis_published\b', r"'[^']*'", r'"[^"]*"',
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
    dirty: bool,
    clean: bool,
    language: Optional[str],
    recent: Optional[str],
    starred: bool,
    tag: Optional[List[str]],
    no_license: bool,
    no_readme: bool,
    has_citation: bool,
    has_doi: bool,
    archived: bool,
    public: bool,
    private: bool,
    fork: bool,
    no_fork: bool,
) -> str:
    """Build a DSL query string from convenience flags."""
    predicates = []

    # Start with user's query if provided
    if query_string:
        predicates.append(f"({query_string})")

    # Dirty/clean status
    if dirty:
        predicates.append("not is_clean")
    if clean:
        predicates.append("is_clean")

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

    # Starred repos (GitHub stars)
    if starred:
        predicates.append("github_stars > 0")

    # Tag filters
    if tag:
        for t in tag:
            predicates.append(f"tagged('{t}')")

    # Audit-style flags (use bare boolean predicates - local)
    if no_license:
        predicates.append("not has_license")
    if no_readme:
        predicates.append("not has_readme")

    # Citation detection (CITATION.cff, .zenodo.json, etc.)
    if has_citation:
        predicates.append("has_citation")

    # DOI detection (repos with a DOI in citation metadata)
    if has_doi:
        predicates.append("citation_doi != ''")

    # GitHub archive status
    if archived:
        predicates.append("github_is_archived")

    # GitHub visibility flags
    if public:
        predicates.append("not github_is_private")
    if private:
        predicates.append("github_is_private")

    # GitHub fork flags
    if fork:
        predicates.append("github_is_fork")
    if no_fork:
        predicates.append("not github_is_fork")

    # Join predicates with 'and'
    if not predicates:
        return ""
    return " and ".join(predicates)


@click.command()
@click.argument('query_string', required=False, default='')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL (default: pretty table)')
@click.option('--brief', is_flag=True, help='Compact output: just repo names (one per line)')
@click.option('--fields', help='Comma-separated list of fields to display')
@click.option('--limit', type=int, help='Limit number of results')
@click.option('--explain', 'show_explain', is_flag=True, help='Show compiled SQL and params without executing')
@click.option('--fts', is_flag=True, help='Use full-text search instead of DSL query')
@click.option('--debug', is_flag=True, help='Enable debug logging')
# Convenience flags
@click.option('--dirty', is_flag=True, help='Repos with uncommitted changes')
@click.option('--clean', is_flag=True, help='Repos with no uncommitted changes')
@click.option('--language', '-l', help='Filter by language (e.g., python, js, rust)')
@click.option('--recent', '-r', help='Repos with recent commits (e.g., 7d, 30d)')
@click.option('--starred', is_flag=True, help='Repos with stars')
@click.option('--tag', '-t', multiple=True, help='Filter by tag (supports wildcards)')
@click.option('--no-license', is_flag=True, help='Repos without a license')
@click.option('--no-readme', is_flag=True, help='Repos without a README')
@click.option('--has-citation', is_flag=True, help='Repos with citation files (CITATION.cff, .zenodo.json)')
@click.option('--has-doi', is_flag=True, help='Repos with DOI in citation metadata')
@click.option('--archived', is_flag=True, help='Archived repos only')
@click.option('--public', is_flag=True, help='Public repos only')
@click.option('--private', is_flag=True, help='Private repos only')
@click.option('--fork', is_flag=True, help='Forked repos only')
@click.option('--no-fork', is_flag=True, help='Non-forked repos only (original repos)')
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
    dirty: bool,
    clean: bool,
    language: Optional[str],
    recent: Optional[str],
    starred: bool,
    tag: tuple,
    no_license: bool,
    no_readme: bool,
    has_citation: bool,
    has_doi: bool,
    archived: bool,
    public: bool,
    private: bool,
    fork: bool,
    no_fork: bool,
):
    """
    Query repositories using a powerful query language.

    The query is compiled to SQL and executed against the local database.
    Run 'repoindex refresh' first to populate the database.

    Output is a formatted table by default. Use --json for JSONL output.

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

        # Audit queries
        repoindex query --no-license
        repoindex query --no-readme

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
    has_flags = any([dirty, clean, language, recent, starred, tag, no_license, no_readme,
                     has_citation, has_doi, archived, public, private, fork, no_fork])
    if has_flags:
        query_string = _build_query_from_flags(
            query_string if query_string else None,
            dirty, clean, language, recent, starred, list(tag),
            no_license, no_readme, has_citation, has_doi, archived, public, private, fork, no_fork
        )

    # If no query and no flags, show all repos
    if not query_string:
        query_string = "1 == 1"  # Match all

    # Determine output mode: pretty is default, --json switches to JSONL
    pretty = not output_json and not brief

    # Full-text search mode (explicit or auto-detected)
    if fts or (_is_simple_text_query(query_string) and query_string != "1 == 1"):
        _execute_fts_query(config, query_string, pretty, brief, fields, limit, debug)
        return

    # Compile to SQL
    try:
        views = config.get('views', {})
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
    results = []

    with Database(config=config, read_only=True) as db:
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
    results = []

    with Database(config=config, read_only=True) as db:
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


def _display_pretty_results(results: list, fields: Optional[str]):
    """Display results in a pretty table."""
    from rich.console import Console
    from rich.table import Table
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
        columns = ['name', 'language', 'branch']
        if any(r.get('github_stars') for r in results):
            columns.insert(2, 'github_stars')
        columns.append('tags')

    for col in columns:
        table.add_column(col.title().replace('_', ' '))

    for result in results:
        row = []
        for col in columns:
            if col == 'name':
                row.append(result.get('name', result.get('path', '').split('/')[-1]))
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
