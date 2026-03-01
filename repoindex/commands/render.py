"""
Export command for repoindex.

Exports repository data to various output formats (BibTeX, CSV,
Markdown, OPML, JSON-LD, arkiv, html, etc.) using the exporter
extension system.

Output goes to stdout by default for piping.
"""

import sys
from typing import Optional

import click

from ..config import load_config
from ..database.connection import Database
from ..exporters import discover_exporters
from .ops import query_options, _get_repos_from_query


@click.command('export')
@click.argument('format_id', required=False, default=None)
@click.argument('query_string', required=False, default='')
@click.option('--output', '-o', 'output_file', type=click.Path(),
              help='Write to file instead of stdout')
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
    name: Optional[str],
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
    has_remote: bool,
    archived: bool,
    public: bool,
    private: bool,
    fork: bool,
    no_fork: bool,
):
    """
    Export repository data in various formats.

    FORMAT_ID selects the output format (e.g., bibtex, csv, markdown,
    opml, jsonld, arkiv, html). Use --list-formats to see available formats.

    Supports the same query flags as the query command for filtering.
    Output goes to stdout by default (pipe-friendly).

    \b
    Examples:
        # List available formats
        repoindex export --list-formats

        # BibTeX for Python repos
        repoindex export bibtex --language python > refs.bib

        # CSV of starred repos
        repoindex export csv --starred > repos.csv

        # Arkiv archive to directory
        repoindex export arkiv -o ~/exports/repos/

        # HTML browser to directory
        repoindex export html -o ~/exports/html/

        # Write to file
        repoindex export csv --language python -o python_repos.csv
    """
    exporters = discover_exporters()

    # List formats
    if list_formats:
        for fmt_id, exp in sorted(exporters.items()):
            click.echo(f"  {fmt_id:<12} {exp.name} ({exp.extension})")
        click.echo(f"  {'html':<12} HTML Browser (.html)")
        return

    # Require format_id when not listing
    if not format_id:
        available = ', '.join(sorted(list(exporters.keys()) + ['html']))
        click.echo(f"Error: Missing FORMAT_ID. Available: {available}", err=True)
        sys.exit(1)

    # HTML export — special case (needs raw DB, not Exporter ABC)
    if format_id == 'html':
        if not output_file:
            click.echo("Error: HTML export requires -o <directory>", err=True)
            sys.exit(1)
        from ..exporters.html import export_html
        from ..database.connection import get_db_path
        config = load_config()
        db_path = get_db_path(config)
        if not db_path.exists():
            click.echo(f"Error: Database not found at {db_path}", err=True)
            sys.exit(1)
        export_html(output_file, db_path)
        click.echo(f"Exported HTML browser to {output_file}/index.html", err=True)
        return

    # Find the requested exporter
    if format_id not in exporters:
        available = ', '.join(sorted(list(exporters.keys()) + ['html']))
        click.echo(f"Error: Unknown format '{format_id}'. Available: {available}", err=True)
        sys.exit(1)

    exporter = exporters[format_id]
    config = load_config()

    # Query repos from database using the standard helper
    repos = _get_repos_from_query(
        config, query_string, debug=debug,
        name=name, dirty=dirty, clean=clean, language=language,
        recent=recent, starred=starred, tag=tag,
        no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi,
        has_remote=has_remote,
        archived=archived, public=public, private=private,
        fork=fork, no_fork=no_fork,
    )

    # Write output
    if output_file:
        # Directory-based export for arkiv format
        if format_id == 'arkiv':
            from ..exporters.arkiv import export_archive
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
            click.echo(f"Wrote {count} repos to {output_file} ({exporter.name})", err=True)
    else:
        count = exporter.export(repos, sys.stdout, config=config)
        click.echo(f"{count} records exported ({exporter.name})", err=True)
