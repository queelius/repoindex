"""
Virtual filesystem commands for repoindex.

Provides stateless VFS operations using absolute paths.
These commands complement the shell's interactive VFS navigation
but work without maintaining state.
"""

import click
import json
from pathlib import Path
from typing import Dict, Any, List

from ..config import load_config
from ..utils import find_git_repos_from_config
from ..metadata import get_metadata_store
from ..vfs_utils import build_vfs_structure, resolve_vfs_path
from ..git_ops.utils import get_repos_from_vfs_path
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

console = Console()


def list_repository_contents(repo_path: str, json_output: bool = False):
    """List actual filesystem contents of a repository.

    Args:
        repo_path: Absolute path to repository
        json_output: Whether to output as JSONL
    """
    import os
    from pathlib import Path

    repo_path_obj = Path(repo_path)

    if not repo_path_obj.exists():
        click.echo(f"Error: Repository path does not exist: {repo_path}", err=True)
        raise click.Abort()

    # Get directory contents
    try:
        entries = []
        for item in sorted(repo_path_obj.iterdir()):
            # Skip .git directory for cleaner output
            if item.name == '.git':
                continue

            entry = {
                'name': item.name,
                'type': 'directory' if item.is_dir() else 'file',
                'size': item.stat().st_size if item.is_file() else None
            }
            entries.append(entry)

        if json_output:
            for entry in entries:
                print(json.dumps(entry))
        else:
            # Rich table output
            table = Table(show_header=True, header_style="bold cyan", title=f"Contents of {repo_path_obj.name}")
            table.add_column("Name", style="green")
            table.add_column("Type", style="blue")
            table.add_column("Size", justify="right", style="dim")

            for entry in entries:
                icon = '📁' if entry['type'] == 'directory' else '📄'
                size_str = ''
                if entry['size'] is not None:
                    # Format size nicely
                    size = entry['size']
                    if size < 1024:
                        size_str = f"{size}B"
                    elif size < 1024 * 1024:
                        size_str = f"{size/1024:.1f}KB"
                    else:
                        size_str = f"{size/(1024*1024):.1f}MB"

                table.add_row(
                    f"{icon} {entry['name']}",
                    entry['type'],
                    size_str
                )

            console.print(table)

    except PermissionError:
        click.echo(f"Error: Permission denied accessing {repo_path}", err=True)
        raise click.Abort()


@click.group(name='fs')
def fs_cmd():
    """Virtual filesystem operations.

    Access the repoindex virtual filesystem using absolute paths.
    The VFS organizes repositories by:

    \b
    - /repos/           All repositories
    - /by-language/     Grouped by programming language
    - /by-tag/          Hierarchical tag navigation
    - /by-status/       Grouped by git status (clean/dirty)

    These commands provide stateless access to the VFS that
    complements the interactive shell.

    Examples:

    \b
        repoindex fs ls /by-tag/alex/beta
        repoindex fs tree /by-tag
        repoindex fs find --language Python
        repoindex fs info /repos/myproject
    """
    pass


def _list_config_values(children: Dict[str, Any], json_output: bool = False):
    """List config values with simple table format."""
    results = []

    for name, child in sorted(children.items()):
        entry = {
            "name": name,
            "type": child.get('type', 'unknown'),
            "value": child.get('value', '')
        }
        results.append(entry)

    if json_output:
        # JSONL output
        for entry in results:
            print(json.dumps(entry))
    else:
        # Simple table for config values
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Name", style="green", width=30)
        table.add_column("Type", style="blue", width=15)
        table.add_column("Value", style="white")

        for entry in results:
            icon = {
                'directory': '📂',
                'config_value': '⚙️'
            }.get(entry.get('type'), '❓')

            name = f"{icon} {entry['name']}"
            type_str = entry['type']
            value = entry.get('value', '')

            table.add_row(name, type_str, value)

        console.print(table)


def _list_with_metadata(children: Dict[str, Any], show_all: bool = False, json_output: bool = False):
    """List VFS children with metadata from the metadata store."""
    from ..metadata import get_metadata_store

    # Check if we're dealing with config_value nodes
    has_config_values = any(child.get('type') == 'config_value' for child in children.values())

    # For config values, use simple display
    if has_config_values:
        _list_config_values(children, json_output)
        return

    store = get_metadata_store()
    results = []

    for name, child in sorted(children.items()):
        entry = {
            "name": name,
            "type": child.get('type', 'unknown')
        }

        # Add basic VFS info
        if child.get('type') == 'symlink':
            entry['target'] = child.get('target')

        # Get metadata for repositories
        if child.get('type') in ('repository', 'symlink'):
            repo_path = child.get('path') or child.get('repo_path')
            if repo_path:
                metadata = store.get(repo_path)
                if metadata:
                    # Add selected metadata fields
                    entry['language'] = metadata.get('language', 'Unknown')

                    # Git status
                    status = metadata.get('status', {})
                    entry['branch'] = status.get('branch', 'unknown')
                    entry['clean'] = status.get('clean', True)
                    entry['dirty'] = status.get('has_uncommitted_changes', False)

                    if show_all:
                        # Include all metadata
                        entry['license'] = metadata.get('license', {})
                        entry['remote_url'] = metadata.get('remote_url')
                        entry['owner'] = metadata.get('owner')
                        entry['stars'] = metadata.get('stars')
                        entry['description'] = metadata.get('description')
                        entry['topics'] = metadata.get('topics', [])

        results.append(entry)

    if json_output:
        # JSONL output
        for entry in results:
            print(json.dumps(entry))
    else:
        # Rich table output
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Name", style="green", width=30)
        table.add_column("Type", style="blue", width=10)
        table.add_column("Language", style="cyan", width=12)
        table.add_column("Branch", style="yellow", width=15)
        table.add_column("Status", style="white", width=8)

        if show_all:
            table.add_column("Stars", justify="right", style="dim")
            table.add_column("Description", style="dim", width=40)

        for entry in results:
            icon = {
                'directory': '📂',
                'repository': '📦',
                'symlink': '🔗'
            }.get(entry.get('type'), '❓')

            name = f"{icon} {entry['name']}"
            type_str = entry['type']
            language = entry.get('language', '-')
            branch = entry.get('branch', '-')

            # Status indicator
            if entry.get('type') in ('repository', 'symlink'):
                status = '✓' if entry.get('clean', True) else '✗'
                status_color = 'green' if entry.get('clean', True) else 'yellow'
                status = f"[{status_color}]{status}[/{status_color}]"
            else:
                status = '-'

            row = [name, type_str, language, branch, status]

            if show_all:
                stars = str(entry.get('stars', '-'))
                desc = entry.get('description', '-')
                if desc and len(desc) > 40:
                    desc = desc[:37] + '...'
                row.extend([stars, desc or '-'])

            table.add_row(*row)

        console.print(table)


@fs_cmd.command('ls')
@click.argument('path', default='/')
@click.option('-l', '--long', is_flag=True, help='Long format with metadata')
@click.option('-a', '--all', is_flag=True, help='Show all metadata')
@click.option('--refresh', is_flag=True, help='Refresh metadata before listing')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSONL')
def fs_ls(path, long, all, refresh, json_output):
    """List VFS path contents.

    PATH: VFS path to list (default: /)

    Examples:

    \b
        repoindex fs ls /                    # Basic list
        repoindex fs ls -l /by-tag/work      # With metadata
        repoindex fs ls -la /by-language     # All metadata
        repoindex fs ls --refresh /repos     # Refresh first
    """
    config = load_config()

    # Refresh metadata if requested
    if refresh:
        from ..metadata import get_metadata_store
        store = get_metadata_store()
        # Get repos from this path and refresh them
        repos = get_repos_from_vfs_path(path) if path != '/' else []
        if repos:
            console.print(f"[yellow]Refreshing metadata for {len(repos)} repositories...[/yellow]")
            for repo in repos:
                store.refresh(repo)

    vfs = build_vfs_structure(config)
    node = resolve_vfs_path(vfs, path)

    if not node:
        click.echo(f"Error: Path not found: {path}", err=True)
        raise click.Abort()

    # If it's a repository or symlink, show actual filesystem contents
    if node['type'] in ('repository', 'symlink'):
        repo_path = node.get('path')
        if not repo_path:
            click.echo(f"Error: No path information for {node['type']}", err=True)
            raise click.Abort()

        # List actual files in the repository
        list_repository_contents(repo_path, json_output)
        return

    # Check if it's a directory
    if node['type'] != 'directory' or 'children' not in node:
        click.echo(f"Error: Not a directory: {path}", err=True)
        raise click.Abort()

    children = node['children']

    # Collect repository children with metadata if requested
    if (long or all) and children:
        _list_with_metadata(children, all, json_output)
    elif json_output:
        # JSONL output (minimal)
        for name, child in sorted(children.items()):
            entry = {
                "name": name,
                "type": child.get('type', 'unknown')
            }
            if child.get('type') == 'symlink':
                entry['target'] = child.get('target')
                entry['path'] = child.get('path')
            print(json.dumps(entry))
    else:
        # Rich table output (minimal)
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Name", style="green")
        table.add_column("Type", style="blue")
        table.add_column("Value", style="dim")

        for name, child in sorted(children.items()):
            icon = {
                'directory': '📂',
                'repository': '📦',
                'symlink': '🔗',
                'config_value': '⚙️'
            }.get(child.get('type'), '❓')

            type_str = child.get('type', 'unknown')

            # Show value for config_value, target for symlink
            if child.get('type') == 'symlink':
                target = child.get('target', '')
            elif child.get('type') == 'config_value':
                target = child.get('value', '')
            else:
                target = ''

            table.add_row(f"{icon} {name}", type_str, target)

        console.print(table)


@fs_cmd.command('tree')
@click.argument('path', default='/by-tag')
@click.option('--max-depth', type=int, default=3, help='Maximum depth to show')
def fs_tree(path, max_depth):
    """Show VFS tree view.

    PATH: VFS path to show tree for (default: /by-tag)

    Examples:

    \b
        repoindex fs tree /by-tag
        repoindex fs tree /by-language --max-depth 2
    """
    config = load_config()
    vfs = build_vfs_structure(config)

    node = resolve_vfs_path(vfs, path)

    if not node:
        click.echo(f"Error: Path not found: {path}", err=True)
        raise click.Abort()

    # Create Rich tree
    tree = Tree(f"[bold cyan]{path}[/bold cyan]")

    def add_to_tree(parent, node_children, depth=0):
        if depth >= max_depth:
            return

        for name, child in sorted(node_children.items()):
            if child.get('type') == 'directory' and 'children' in child:
                branch = parent.add(f"[yellow]{name}/[/yellow]")
                add_to_tree(branch, child['children'], depth + 1)
            elif child.get('type') == 'symlink':
                parent.add(f"[blue]{name}[/blue] → [dim]{child.get('target', '')}[/dim]")
            else:
                parent.add(f"[green]{name}[/green]")

    if 'children' in node:
        add_to_tree(tree, node['children'])

    console.print(tree)


@fs_cmd.command('find')
@click.option('--language', help='Filter by language')
@click.option('--tag', help='Filter by tag')
@click.option('--status', type=click.Choice(['clean', 'dirty']), help='Filter by git status')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSONL')
def fs_find(language, tag, status, json_output):
    """Find repositories by criteria.

    Examples:

    \b
        repoindex fs find --language Python
        repoindex fs find --tag alex/beta
        repoindex fs find --status dirty
    """
    config = load_config()
    vfs = build_vfs_structure(config)

    results = []

    # Search logic
    if language:
        path = f"/by-language/{language}"
        node = resolve_vfs_path(vfs, path)
        if node and 'children' in node:
            for name, child in node['children'].items():
                if child.get('type') in ['repository', 'symlink']:
                    results.append({
                        'name': name,
                        'path': child.get('path', ''),
                        'vfs_path': f"{path}/{name}",
                        'match': 'language'
                    })

    if tag:
        path = f"/by-tag/{tag}"
        node = resolve_vfs_path(vfs, path)
        if node and 'children' in node:
            for name, child in node['children'].items():
                if child.get('type') in ['repository', 'symlink']:
                    results.append({
                        'name': name,
                        'path': child.get('path', ''),
                        'vfs_path': f"{path}/{name}",
                        'match': 'tag'
                    })

    if status:
        path = f"/by-status/{status}"
        node = resolve_vfs_path(vfs, path)
        if node and 'children' in node:
            for name, child in node['children'].items():
                if child.get('type') in ['repository', 'symlink']:
                    results.append({
                        'name': name,
                        'path': child.get('path', ''),
                        'vfs_path': f"{path}/{name}",
                        'match': 'status'
                    })

    if not language and not tag and not status:
        # No filters, return all repos
        repos_node = vfs['/']['children']['repos']['children']
        for name, child in repos_node.items():
            results.append({
                'name': name,
                'path': child.get('path', ''),
                'vfs_path': f"/repos/{name}",
                'match': 'all'
            })

    # Output results
    if json_output:
        for result in results:
            print(json.dumps(result))
    else:
        if not results:
            console.print("[yellow]No repositories found[/yellow]")
            return

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Name", style="green")
        table.add_column("Path", style="dim")
        table.add_column("Match", style="blue")

        for result in results:
            table.add_row(result['name'], result['path'], result['match'])

        console.print(table)
        console.print(f"\n[cyan]Found {len(results)} repositories[/cyan]")


@fs_cmd.command('info')
@click.argument('path')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSON')
def fs_info(path, json_output):
    """Show detailed information about a VFS path.

    PATH: VFS path to inspect

    Examples:

    \b
        repoindex fs info /repos/myproject
        repoindex fs info /by-tag/alex/beta
    """
    config = load_config()
    vfs = build_vfs_structure(config)

    node = resolve_vfs_path(vfs, path)

    if not node:
        click.echo(f"Error: Path not found: {path}", err=True)
        raise click.Abort()

    # Build info dictionary
    info = {
        "path": path,
        "type": node.get('type', 'unknown'),
    }

    if node.get('type') == 'symlink':
        info['target'] = node.get('target')
        info['real_path'] = node.get('path')
    elif node.get('type') == 'repository':
        info['real_path'] = node.get('path')
    elif node.get('type') == 'directory' and 'children' in node:
        info['children_count'] = len(node['children'])
        info['children'] = list(node['children'].keys())

    if json_output:
        print(json.dumps(info, indent=2))
    else:
        console.print(f"[bold cyan]VFS Path Info:[/bold cyan] {path}")
        console.print(f"[blue]Type:[/blue] {info['type']}")

        if 'target' in info:
            console.print(f"[blue]Target:[/blue] {info['target']}")
        if 'real_path' in info:
            console.print(f"[blue]Real Path:[/blue] {info['real_path']}")
        if 'children_count' in info:
            console.print(f"[blue]Children:[/blue] {info['children_count']}")
            console.print("[dim]" + ", ".join(info['children'][:10]) + "[/dim]")
            if len(info['children']) > 10:
                console.print(f"[dim]... and {len(info['children']) - 10} more[/dim]")
