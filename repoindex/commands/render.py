"""
Export command for repoindex.

Default: produces a longecho-compliant arkiv archive with an embedded
HTML browser (site/index.html). Format-based exports (bibtex, csv, etc.)
are available via the exporter plugin system.

Use 'repoindex query' to preview which repos will be exported.
"""

import sys
from typing import Optional

import click

from ..config import load_config
from ..database.connection import Database
from .ops import query_options, _get_repos_from_query


@click.command('export')
@click.argument('format_id', required=False, default=None)
@click.argument('query_string', required=False, default='')
@click.option('--output', '-o', 'output_file', type=click.Path(),
              help='Output directory (arkiv archive) or file (format export)')
@click.option('--list-formats', is_flag=True, help='List available export formats')
@click.option('--debug', is_flag=True, hidden=True, help='Debug mode')
@query_options
def export_handler(
    format_id: str,
    query_string: str,
    output_file: Optional[str],
    list_formats: bool,
    debug: bool,
    # Query flags from decorator
    language: Optional[str],
    dirty: bool,
    tag: tuple,
    recent: Optional[str],
):
    """
    Export repository data as a longecho-compliant archive.

    Without FORMAT_ID, produces an arkiv archive directory containing
    JSONL data, schema, SQLite database, and an interactive HTML browser.
    Use 'repoindex query' to preview which repos will be exported.

    With FORMAT_ID, uses the exporter plugin system (bibtex, csv, etc.).
    Use --list-formats to see available format plugins.

    \b
    Examples:
        # Arkiv archive (default) — longecho-compliant with HTML browser
        repoindex export -o ~/archives/repos/

        # Filtered archive
        repoindex export -o ~/archives/python/ --language python

        # With DSL query
        repoindex export -o ~/archives/starred/ "github_stars > 0"

        # Format-based exports (via exporter plugins)
        repoindex export bibtex --language python > refs.bib
        repoindex export csv -o repos.csv

        # List available format plugins
        repoindex export --list-formats
    """
    from ..exporters import discover_exporters

    # List formats
    if list_formats:
        exporters = discover_exporters()
        for fmt_id, exp in sorted(exporters.items()):
            click.echo(f"  {fmt_id:<12} {exp.name} ({exp.extension})")
        return

    # No format specified + -o given → arkiv archive (the default)
    if not format_id:
        if not output_file:
            click.echo(
                "Usage: repoindex export -o <directory> [QUERY]\n"
                "       repoindex export FORMAT [QUERY] [-o FILE]\n\n"
                "Use --list-formats for format plugins, or -o for arkiv archive.",
                err=True,
            )
            sys.exit(1)
        _export_archive(output_file, query_string, debug, language, dirty, tag, recent)
        return

    # Explicit "arkiv" format → same as default archive
    if format_id == 'arkiv':
        if not output_file:
            click.echo("Error: arkiv export requires -o <directory>", err=True)
            sys.exit(1)
        _export_archive(output_file, query_string, debug, language, dirty, tag, recent)
        return

    # Format-based export via exporter plugins
    exporters = discover_exporters()
    if format_id not in exporters:
        available = ', '.join(sorted(exporters.keys()))
        click.echo(f"Error: Unknown format '{format_id}'. Available: {available}", err=True)
        sys.exit(1)

    exporter = exporters[format_id]
    config = load_config()
    repos = _get_repos_from_query(
        config, query_string, debug=debug,
        language=language, dirty=dirty, tag=tag, recent=recent,
    )

    if output_file:
        with open(output_file, 'w') as f:
            count = exporter.export(repos, f, config=config)
        click.echo(f"Wrote {count} repos to {output_file} ({exporter.name})", err=True)
    else:
        count = exporter.export(repos, sys.stdout, config=config)
        click.echo(f"{count} records exported ({exporter.name})", err=True)


def _export_archive(output_file, query_string, debug, language, dirty, tag, recent):
    """Produce a longecho-compliant arkiv archive with embedded HTML browser."""
    from ..database.connection import get_db_path
    from ..database.events import get_events
    from ..exporters.arkiv import export_archive
    from ..exporters.html import export_html
    from pathlib import Path

    config = load_config()
    repos = _get_repos_from_query(
        config, query_string, debug=debug,
        language=language, dirty=dirty, tag=tag, recent=recent,
    )

    events = []
    publications = []
    try:
        with Database(config=config, read_only=True) as db:
            for repo in repos:
                repo_id = repo.get('id')
                if repo_id is not None:
                    events.extend(get_events(db, repo_id=repo_id))
            # Fetch publications for filtered repos
            repo_ids = [r['id'] for r in repos if r.get('id')]
            if repo_ids:
                placeholders = ','.join('?' * len(repo_ids))
                db.execute(
                    f"SELECT p.*, r.name as repo_name, r.path as repo_path "
                    f"FROM publications p JOIN repos r ON p.repo_id = r.id "
                    f"WHERE p.repo_id IN ({placeholders})",
                    tuple(repo_ids),
                )
                publications = [dict(row) for row in db.fetchall()]
    except Exception as e:
        click.echo(f"Warning: could not fetch data: {e}", err=True)

    counts = export_archive(output_file, repos, events, publications=publications)

    # Bundle site/ with HTML browser (longecho site/ convention)
    output_path = Path(output_file)
    site_dir = output_path / "site"
    db_path = get_db_path(config)
    if db_path.exists():
        try:
            export_html(site_dir, db_path)
        except Exception as e:
            click.echo(f"Warning: could not generate site/: {e}", err=True)

    click.echo(
        f"Exported {counts['repos']} repos, {counts['events']} events, "
        f"{counts['publications']} publications to {output_file}/",
        err=True,
    )
