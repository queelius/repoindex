"""
Exclude directory management commands.

Commands for managing the list of excluded directories in the configuration.
Excluded directories are filtered out during repository discovery, so repos
under these paths won't appear in query, events, export, etc.
"""

import click
from rich.console import Console
from rich.table import Table

from ..config import load_config, save_config

console = Console()


@click.group("excludes")
def config_excludes():
    """Manage excluded directories in configuration.

    These commands modify the list of directories that repoindex
    skips during repository discovery.
    """
    pass


@config_excludes.command("add")
@click.argument("path")
def excludes_add(path):
    """Add a directory to the exclude list.

    PATH: Directory path to exclude (supports ~/ paths)

    Examples:

    \b
        repoindex config excludes add ~/github/archived
        repoindex config excludes add ~/github/forks
        repoindex config excludes add /absolute/path/to/skip
    """
    config = load_config()

    # Ensure exclude_directories exists
    if 'exclude_directories' not in config:
        config['exclude_directories'] = []

    # Check if path already exists
    if path in config['exclude_directories']:
        console.print(f"[yellow]Path already in exclude list:[/yellow] {path}")
        return

    # Add the path
    config['exclude_directories'].append(path)

    # Save configuration
    save_config(config)
    console.print(f"[green]\u2713[/green] Added exclude directory: [cyan]{path}[/cyan]")


@config_excludes.command("remove")
@click.argument("path")
def excludes_remove(path):
    """Remove a directory from the exclude list.

    PATH: Directory path to remove (must match exactly as stored)

    Examples:

    \b
        repoindex config excludes remove ~/github/archived
        repoindex config excludes remove ~/github/forks
    """
    config = load_config()

    # Check if path exists in config
    exclude_dirs = config.get('exclude_directories', [])

    if not exclude_dirs:
        console.print("[yellow]No exclude directories configured[/yellow]")
        return

    if path not in exclude_dirs:
        console.print(f"[yellow]Path not found in exclude list:[/yellow] {path}")
        console.print("\n[dim]Current excluded paths:[/dim]")
        for p in exclude_dirs:
            console.print(f"  {p}")
        return

    # Remove the path
    exclude_dirs.remove(path)
    config['exclude_directories'] = exclude_dirs

    # Save configuration
    save_config(config)
    console.print(f"[green]\u2713[/green] Removed exclude directory: [cyan]{path}[/cyan]")


@config_excludes.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSONL")
def excludes_list(json_output):
    """List all excluded directories.

    Shows the directory paths that are excluded from repository discovery.

    Examples:

    \b
        repoindex config excludes list
        repoindex config excludes list --json
    """
    config = load_config()

    # Get exclude directories
    exclude_dirs = config.get('exclude_directories', [])

    if not exclude_dirs:
        if json_output:
            import json
            print(json.dumps({"exclude_directories": []}))
        else:
            console.print("[yellow]No exclude directories configured[/yellow]")
        return

    if json_output:
        import json
        for i, path in enumerate(exclude_dirs):
            print(json.dumps({
                "index": i,
                "path": path
            }))
    else:
        # Rich table output
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("Path", style="green")

        for i, path in enumerate(exclude_dirs):
            table.add_row(str(i), path)

        console.print(table)
        console.print(f"\n[dim]Total:[/dim] {len(exclude_dirs)} excluded paths")


@config_excludes.command("clear")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def excludes_clear(yes):
    """Clear all excluded directories from configuration.

    This removes all configured exclude directory paths.
    Requires confirmation unless --yes is provided.

    Examples:

    \b
        repoindex config excludes clear
        repoindex config excludes clear --yes
    """
    config = load_config()

    # Get current paths
    exclude_dirs = config.get('exclude_directories', [])

    if not exclude_dirs:
        console.print("[yellow]No exclude directories configured[/yellow]")
        return

    # Show what will be cleared
    console.print(f"[yellow]About to clear {len(exclude_dirs)} exclude directories:[/yellow]")
    for path in exclude_dirs:
        console.print(f"  - {path}")

    # Confirm unless --yes
    if not yes:
        if not click.confirm("\nAre you sure you want to clear all exclude directories?"):
            console.print("[dim]Cancelled[/dim]")
            return

    # Clear the list
    config['exclude_directories'] = []

    # Save configuration
    save_config(config)
    console.print("[green]\u2713[/green] Cleared all exclude directories")
