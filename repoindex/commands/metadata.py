"""
Metadata store management commands for repoindex.
"""

import click
import json
import re
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.progress import Progress
from rich import box

from ..metadata import get_metadata_store
from ..config import load_config
from ..utils import find_git_repos_from_config


def _parse_age(age_str: str) -> int:
    """Parse age string like '7d', '12h', '30m' to seconds."""
    match = re.match(r'^(\d+)([dhms])$', age_str.lower())
    if not match:
        return None
    
    value = int(match.group(1))
    unit = match.group(2)
    
    multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400
    }
    
    return value * multipliers[unit]


def _should_refresh(metadata: dict, max_age_seconds: int) -> bool:
    """Check if metadata should be refreshed based on age."""
    if not metadata or '_updated' not in metadata:
        return True
    
    try:
        updated_time = datetime.fromisoformat(metadata['_updated'].replace('Z', '+00:00'))
        age = datetime.utcnow() - updated_time
        return age.total_seconds() > max_age_seconds
    except:
        return True


def _format_age(metadata: dict) -> str:
    """Format the age of metadata in human-readable form."""
    if not metadata or '_updated' not in metadata:
        return 'unknown'
    
    try:
        updated_time = datetime.fromisoformat(metadata['_updated'].replace('Z', '+00:00'))
        age = datetime.utcnow() - updated_time
        seconds = age.total_seconds()
        
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m"
        elif seconds < 86400:
            return f"{int(seconds / 3600)}h"
        else:
            return f"{int(seconds / 86400)}d"
    except:
        return 'unknown'


@click.group('metadata')
def metadata_cmd():
    """Manage repository metadata store."""
    pass


@metadata_cmd.command('refresh')
@click.option('--github', is_flag=True, help='Fetch data from GitHub API')
@click.option('--path', help='Refresh specific repository path')
@click.option('--pretty', is_flag=True, help='Display progress bar')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.option('--max-age', help='Only refresh if older than (e.g., "7d", "12h", "30m")')
def refresh_metadata(github: bool, path: str, pretty: bool, debug: bool, max_age: str):
    """Refresh metadata for repositories."""
    # Configure logging if debug mode
    if debug:
        import logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    store = get_metadata_store()
    
    # Parse max age if provided
    max_age_seconds = None
    if max_age:
        max_age_seconds = _parse_age(max_age)
        if max_age_seconds is None:
            click.echo(f"Invalid max-age format: {max_age}. Use format like '7d', '12h', '30m'", err=True)
            return
    
    if path:
        # Refresh single repository
        if max_age_seconds:
            existing = store.get(path)
            if existing and not _should_refresh(existing, max_age_seconds):
                print(json.dumps({
                    'path': path,
                    'status': 'skipped',
                    'reason': 'up-to-date',
                    'age': _format_age(existing)
                }, ensure_ascii=False), flush=True)
                return
        
        metadata = store.refresh(path, fetch_github=github)
        print(json.dumps(metadata, ensure_ascii=False), flush=True)
    else:
        # Refresh all repositories
        config = load_config()
        repo_dirs = config.get("general", {}).get("repository_directories", [])
        repos = list(find_git_repos_from_config(repo_dirs))
        
        if pretty:
            console = Console()
            with Progress() as progress:
                task = progress.add_task("[cyan]Refreshing metadata...", total=len(repos))
                
                for metadata in store.refresh_all(repos, fetch_github=github,
                                                progress_callback=lambda c, t: progress.update(task, completed=c)):
                    # Just update progress
                    pass
                
                console.print(f"[green]✓[/green] Refreshed metadata for {len(repos)} repositories")
        else:
            # Stream results as JSONL with progress
            # Filter repos by age if max_age is specified
            repos_to_refresh = repos
            if max_age_seconds:
                repos_to_refresh = []
                skipped = 0
                for repo_path in repos:
                    existing = store.get(repo_path)
                    if not existing or _should_refresh(existing, max_age_seconds):
                        repos_to_refresh.append(repo_path)
                    else:
                        skipped += 1
                
                if skipped > 0:
                    print(json.dumps({
                        'type': 'info',
                        'message': f'Skipping {skipped} up-to-date repositories'
                    }, ensure_ascii=False), flush=True)
            
            # Update totals
            total = len(repos_to_refresh)
            completed = 0
            errors = 0
            
            # Print initial progress
            print(json.dumps({
                'type': 'progress',
                'total': total,
                'completed': 0,
                'errors': 0,
                'status': 'starting'
            }, ensure_ascii=False), flush=True)
            
            for metadata in store.refresh_all(repos_to_refresh, fetch_github=github):
                completed += 1
                
                # Output the result
                status_obj = {
                    'type': 'result',
                    'path': metadata['path'],
                    'name': metadata.get('name'),
                    'status': 'error' if 'error' in metadata else 'success'
                }
                if 'error' in metadata:
                    status_obj['error'] = metadata['error']
                    errors += 1
                print(json.dumps(status_obj, ensure_ascii=False), flush=True)
                
                # Output progress update every 10 repos or on errors
                if completed % 10 == 0 or 'error' in metadata:
                    print(json.dumps({
                        'type': 'progress',
                        'total': total,
                        'completed': completed,
                        'errors': errors,
                        'percent': round(completed / total * 100, 1)
                    }, ensure_ascii=False), flush=True)
            
            # Final summary
            print(json.dumps({
                'type': 'summary',
                'total': total,
                'completed': completed,
                'errors': errors,
                'status': 'completed'
            }, ensure_ascii=False), flush=True)


@metadata_cmd.command('show')
@click.argument('repo_selector')
@click.option('--pretty', is_flag=True, help='Display as formatted output')
def show_metadata(repo_selector: str, pretty: bool):
    """Show metadata for a specific repository.
    
    REPO_SELECTOR can be:
    - A path to a repository
    - A tag selector (e.g., "repo:repoindex", "lang:python")
    """
    store = get_metadata_store()
    
    # Check if it's a tag selector
    if ':' in repo_selector and not repo_selector.startswith('/'):
        # It's a tag selector - find repos with this tag
        from ..commands.catalog import get_repositories_by_tags
        config = load_config()
        
        repos = list(get_repositories_by_tags([repo_selector], config))
        if not repos:
            click.echo(f"No repository found matching tag {repo_selector}", err=True)
            return
        
        # Use the first match
        repo_path = repos[0]['path']
        metadata = store.get(repo_path)
    else:
        # It's a direct path
        metadata = store.get(repo_selector)
    
    if not metadata:
        click.echo(f"No metadata found for {repo_selector}", err=True)
        return
    
    if pretty:
        console = Console()
        
        # Basic info table
        table = Table(title=f"Metadata for {metadata.get('name', repo_path)}",
                     box=box.ROUNDED, show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        
        # Add rows
        for key, value in metadata.items():
            if not key.startswith('_') and not isinstance(value, (dict, list)):
                table.add_row(key, str(value))
        
        console.print(table)
        
        # Show nested data
        if metadata.get('languages'):
            console.print("\n[bold]Languages:[/bold]")
            for lang, bytes_count in metadata['languages'].items():
                console.print(f"  {lang}: {bytes_count:,} bytes")
        
        if metadata.get('topics'):
            console.print(f"\n[bold]Topics:[/bold] {', '.join(metadata['topics'])}")
            
    else:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))


@metadata_cmd.command('stats')
@click.option('--pretty', is_flag=True, help='Display as formatted table')
def metadata_stats(pretty: bool):
    """Show metadata store statistics."""
    store = get_metadata_store()
    stats = store.stats()
    
    if pretty:
        console = Console()
        
        # Overview
        console.print(f"[bold]Metadata Store Statistics[/bold]\n")
        console.print(f"Total repositories: {stats['total_repositories']}")
        console.print(f"Store size: {stats['store_size']:,} bytes")
        
        # Provider breakdown
        if stats['providers']:
            table = Table(title="Repositories by Provider", box=box.SIMPLE)
            table.add_column("Provider")
            table.add_column("Count", justify="right")
            
            for provider, count in sorted(stats['providers'].items()):
                table.add_row(provider, str(count))
            
            console.print("\n", table)
        
        # Language breakdown (top 10)
        if stats['languages']:
            table = Table(title="Top 10 Languages", box=box.SIMPLE)
            table.add_column("Language")
            table.add_column("Repositories", justify="right")
            
            for lang, count in sorted(stats['languages'].items(), 
                                    key=lambda x: x[1], reverse=True)[:10]:
                table.add_row(lang, str(count))
            
            console.print("\n", table)
        
        # GitHub stats
        console.print(f"\n[bold]GitHub Statistics:[/bold]")
        console.print(f"Total stars: {stats['total_stars']:,}")
        console.print(f"Total forks: {stats['total_forks']:,}")
    else:
        print(json.dumps(stats, ensure_ascii=False))


@metadata_cmd.command('clear')
@click.confirmation_option(prompt='Are you sure you want to clear all metadata?')
def clear_metadata():
    """Clear all metadata from the store."""
    store = get_metadata_store()
    store.clear()
    click.echo("Metadata store cleared.")


@metadata_cmd.command('export')
@click.argument('output_file', type=click.Path())
@click.option('--indent', type=int, default=2, help='JSON indentation')
def export_metadata(output_file: str, indent: int):
    """Export metadata store to a file."""
    store = get_metadata_store()
    
    with open(output_file, 'w') as f:
        json.dump(store._metadata, f, indent=indent, ensure_ascii=False)
    
    click.echo(f"Exported metadata to {output_file}")


@metadata_cmd.command('import')
@click.argument('input_file', type=click.Path(exists=True))
@click.option('--merge', is_flag=True, help='Merge with existing metadata')
def import_metadata(input_file: str, merge: bool):
    """Import metadata from a file."""
    store = get_metadata_store()
    
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    if not merge:
        store.clear()
    
    # Import each repository
    count = 0
    for repo_path, metadata in data.items():
        store.update(repo_path, metadata, merge=merge)
        count += 1
    
    click.echo(f"Imported metadata for {count} repositories")