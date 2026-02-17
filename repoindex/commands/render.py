"""
Render command for repoindex.

Renders repository data to various output formats (BibTeX, CSV,
Markdown, OPML, JSON-LD, etc.) using the exporter extension system.

Output goes to stdout by default for piping.
"""

import sys
from typing import Optional

import click

from ..config import load_config
from ..exporters import discover_exporters
from .ops import query_options, _get_repos_from_query


@click.command('render')
@click.argument('format_id', required=False, default=None)
@click.argument('query_string', required=False, default='')
@click.option('--output', '-o', 'output_file', type=click.Path(),
              help='Write to file instead of stdout')
@click.option('--list-formats', is_flag=True, help='List available export formats')
@click.option('--debug', is_flag=True, hidden=True, help='Debug mode')
@query_options
def render_handler(
    format_id: str,
    query_string: str,
    output_file: Optional[str],
    list_formats: bool,
    debug: bool,
    # Query flags from decorator
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
    Render repository data in various formats.

    FORMAT_ID selects the output format (e.g., bibtex, csv, markdown,
    opml, jsonld). Use --list-formats to see available formats.

    Supports the same query flags as the query command for filtering.
    Output goes to stdout by default (pipe-friendly).

    \b
    Examples:
        # List available formats
        repoindex render --list-formats

        # BibTeX for Python repos
        repoindex render bibtex --language python > refs.bib

        # CSV of starred repos
        repoindex render csv --starred > repos.csv

        # Markdown table of recent repos
        repoindex render markdown --recent 30d > recent.md

        # OPML outline
        repoindex render opml > repos.opml

        # JSON-LD for repos with DOI
        repoindex render jsonld --has-doi > repos.jsonld

        # Write to file
        repoindex render csv --language python -o python_repos.csv
    """
    exporters = discover_exporters()

    # List formats
    if list_formats:
        for fmt_id, exp in sorted(exporters.items()):
            click.echo(f"  {fmt_id:<12} {exp.name} ({exp.extension})")
        return

    # Require format_id when not listing
    if not format_id:
        available = ', '.join(sorted(exporters.keys()))
        click.echo(f"Error: Missing FORMAT_ID. Available: {available}", err=True)
        sys.exit(1)

    # Find the requested exporter
    if format_id not in exporters:
        available = ', '.join(sorted(exporters.keys()))
        click.echo(f"Error: Unknown format '{format_id}'. Available: {available}", err=True)
        sys.exit(1)

    exporter = exporters[format_id]
    config = load_config()

    # Query repos from database using the standard helper
    repos = _get_repos_from_query(
        config, query_string, debug=debug,
        dirty=dirty, clean=clean, language=language,
        recent=recent, starred=starred, tag=tag,
        no_license=no_license, no_readme=no_readme,
        has_citation=has_citation, has_doi=has_doi,
        archived=archived, public=public, private=private,
        fork=fork, no_fork=no_fork,
    )

    # Write output
    if output_file:
        with open(output_file, 'w') as f:
            count = exporter.export(repos, f, config=config)
        click.echo(f"Wrote {count} repos to {output_file} ({exporter.name})", err=True)
    else:
        count = exporter.export(repos, sys.stdout, config=config)
        click.echo(f"{count} repos rendered ({exporter.name})", err=True)
