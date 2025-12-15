"""
Query command for repoindex.

Provides powerful querying capabilities over repository metadata
using a simple, intuitive query language with fuzzy matching.
"""

import click
import json
from typing import Optional

from ..config import load_config
from ..query import Query
from ..utils import find_git_repos_from_config
from ..core import _get_repository_status_for_path
from ..metadata import get_metadata_store


@click.command()
@click.argument('query_string')
@click.option('--threshold', default=80, help='Fuzzy matching threshold (0-100)')
@click.option('--pretty', is_flag=True, help='Display results as a formatted table')
@click.option('--brief', is_flag=True, help='Compact output: just repo names (one per line)')
@click.option('--full', is_flag=True, help='Fetch full metadata (slower but more accurate)')
@click.option('--fields', help='Comma-separated list of fields to display')
@click.option('--json-full', is_flag=True, help='Output full JSON metadata')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.option('--limit', type=int, help='Limit number of repos to process (for testing)')
def query_handler(query_string: str, threshold: int, pretty: bool, brief: bool, full: bool,
                  fields: Optional[str], json_full: bool, debug: bool, limit: Optional[int]):
    """
    Query repositories using a simple but powerful query language.
    
    Examples:
        
        # Simple text search (searches everywhere)
        repoindex query "django"
        repoindex query "machine learning"
        
        # Field queries
        repoindex query "language == 'Python'"
        repoindex query "stargazers_count > 100"
        repoindex query "license.key == 'mit'"
        
        # Fuzzy matching
        repoindex query "language ~= 'pyton'"    # Matches Python!
        repoindex query "topics contains 'secrty'"  # Matches security!
        
        # Boolean logic
        repoindex query "language == 'Python' and stargazers_count > 10"
        repoindex query "has_issues or has_wiki"
        repoindex query "not archived"
        
        # Tag queries
        repoindex query "tags contains 'project:active'"
        repoindex query "'tools:cli' in tags"
    """
    # Configure logging if debug mode
    if debug:
        import logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    config = load_config()
    query = Query(query_string)
    
    # Get all repositories
    repo_dirs = config.get("general", {}).get("repository_directories", [])
    repos = find_git_repos_from_config(repo_dirs)
    
    # Apply limit if specified
    if limit:
        repos = list(repos)[:limit]
    
    # Get metadata for each repo
    results = []
    processed = 0
    store = get_metadata_store()
    
    for repo_path in repos:
        if debug and processed % 10 == 0:
            import sys
            print(f"DEBUG: Processed {processed} repositories...", file=sys.stderr)
        try:
            # Get metadata from store
            metadata = store.get(repo_path)
            
            # If not in store or full refresh requested, fetch it
            if not metadata or full:
                metadata = store.refresh(repo_path, fetch_github=full)
            
            # Skip if no metadata
            if not metadata:
                continue
            
            # Evaluate query
            if query.evaluate(metadata, threshold):
                results.append(metadata)
                # Stream output immediately if not pretty mode
                if not pretty:
                    _output_result(metadata, fields, json_full, brief)
                    
        except Exception as e:
            # Skip repos with errors
            if debug:
                import sys
                print(f"DEBUG: Error processing {repo_path}: {e}", file=sys.stderr)
            continue
        finally:
            processed += 1
    
    # Display results only if pretty mode (table format)
    if pretty:
        _display_pretty_results(results, fields)


def _output_result(result: dict, fields: Optional[str], json_full: bool, brief: bool = False):
    """Output a single result in JSONL format."""
    if brief:
        # Brief mode: just output repo name
        name = result.get('name', result['path'].split('/')[-1])
        print(name, flush=True)
    elif json_full:
        # Output full JSON metadata
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        # Standard JSONL output with selected fields
        output = {
            'path': result['path'],
            'name': result.get('name', result['path'].split('/')[-1])
        }

        # Add requested fields
        if fields:
            for field in fields.split(','):
                field = field.strip()
                if '.' in field:
                    # Handle nested fields
                    value = result
                    for part in field.split('.'):
                        value = value.get(part, {}) if isinstance(value, dict) else None
                    if value is not None:
                        output[field] = value
                elif field in result:
                    output[field] = result[field]
        else:
            # Default fields (compact - no readme/description)
            if 'tags' in result and result['tags']:
                output['tags'] = result['tags']
            if 'language' in result:
                output['language'] = result['language']
            if 'stargazers_count' in result:
                output['stars'] = result['stargazers_count']

        print(json.dumps(output, ensure_ascii=False), flush=True)




def _display_pretty_results(results: list, fields: Optional[str]):
    """Display results in a pretty table."""
    from rich.console import Console
    from rich.table import Table
    from rich import box
    
    console = Console()
    
    if not results:
        console.print("[yellow]No repositories found matching the query.[/yellow]")
        return
    
    # Create table
    table = Table(
        title=f"Query Results ({len(results)} repositories)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Determine columns
    if fields:
        columns = ['name'] + [f.strip() for f in fields.split(',')]
    else:
        # Default columns based on available data
        columns = ['name', 'language', 'tags']
        if any('stargazers_count' in r for r in results):
            columns.insert(2, 'stars')
    
    # Add columns to table
    for col in columns:
        table.add_column(col.title().replace('_', ' '))
    
    # Add rows
    for result in results:
        row = []
        for col in columns:
            if col == 'name':
                row.append(result.get('name', result['path'].split('/')[-1]))
            elif col == 'tags':
                tags = result.get('tags', [])
                # Limit tags shown
                if len(tags) > 3:
                    row.append(', '.join(tags[:3]) + f' (+{len(tags)-3})')
                else:
                    row.append(', '.join(tags))
            elif col == 'stars':
                row.append(str(result.get('stargazers_count', 0)))
            else:
                # Handle nested fields
                if '.' in col:
                    value = result
                    for part in col.split('.'):
                        value = value.get(part, {}) if isinstance(value, dict) else None
                    row.append(str(value) if value is not None else '')
                else:
                    row.append(str(result.get(col, '')))
        
        table.add_row(*row)
    
    console.print(table)
    console.print(f"\n[bold]Total:[/bold] {len(results)} repositories")