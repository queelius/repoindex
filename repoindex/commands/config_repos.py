"""
Repository directory management commands.

Commands for managing the list of repository directories in the configuration.
"""

import click
from rich.console import Console
from rich.table import Table

from ..config import load_config, save_config
from ..metadata import get_metadata_store

console = Console()


@click.group("repos")
def config_repos():
    """Manage repository directories in configuration.

    These commands modify the list of directories where repoindex
    searches for git repositories.
    """
    pass


@config_repos.command("add")
@click.argument("path")
@click.option("--refresh", is_flag=True, help="Refresh metadata for repositories in the new path")
def repos_add(path, refresh):
    """Add a repository directory to configuration.

    PATH: Directory path to add (supports ~/ and glob patterns like **)

    Examples:

    \b
        repoindex config repos add ~/github/**
        repoindex config repos add ~/projects --refresh
        repoindex config repos add /absolute/path/to/repos
    """
    config = load_config()

    # Ensure repository_directories exists
    if 'repository_directories' not in config:
        config['repository_directories'] = []

    # Check if path already exists
    if path in config['repository_directories']:
        console.print(f"[yellow]Path already in configuration:[/yellow] {path}")
        return

    # Add the path
    config['repository_directories'].append(path)

    # Save configuration
    save_config(config)
    console.print(f"[green]✓[/green] Added repository directory: [cyan]{path}[/cyan]")

    # Optionally refresh metadata
    if refresh:
        from ..utils import find_git_repos_from_config
        console.print(f"[yellow]Discovering repositories in {path}...[/yellow]")

        # Find repos in the new path
        repos = find_git_repos_from_config([path], recursive=False)

        if repos:
            console.print(f"[yellow]Refreshing metadata for {len(repos)} repositories...[/yellow]")
            store = get_metadata_store()

            for repo in repos:
                store.refresh(repo, fetch_github=False)

            console.print(f"[green]✓[/green] Refreshed metadata for {len(repos)} repositories")
        else:
            console.print("[dim]No repositories found in the specified path[/dim]")


@config_repos.command("remove")
@click.argument("path")
def repos_remove(path):
    """Remove a repository directory from configuration.

    PATH: Directory path to remove (must match exactly as stored)

    Examples:

    \b
        repoindex config repos remove ~/github/**
        repoindex config repos remove ~/old-projects
    """
    config = load_config()

    # Check if path exists in config
    repo_dirs = config.get('repository_directories', [])

    if not repo_dirs:
        console.print("[yellow]No repository directories configured[/yellow]")
        return

    if path not in repo_dirs:
        console.print(f"[yellow]Path not found in configuration:[/yellow] {path}")
        console.print("\n[dim]Current configured paths:[/dim]")
        for p in repo_dirs:
            console.print(f"  {p}")
        return

    # Remove the path
    repo_dirs.remove(path)
    config['repository_directories'] = repo_dirs

    # Save configuration
    save_config(config)
    console.print(f"[green]✓[/green] Removed repository directory: [cyan]{path}[/cyan]")


@config_repos.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSONL")
def repos_list(json_output):
    """List all configured repository directories.

    Shows the repository directory paths and the number of
    repositories discovered in each path.

    Examples:

    \b
        repoindex config repos list
        repoindex config repos list --json
    """
    config = load_config()

    # Get repository directories
    repo_dirs = config.get('repository_directories', [])

    if not repo_dirs:
        if json_output:
            import json
            print(json.dumps({"repository_directories": []}))
        else:
            console.print("[yellow]No repository directories configured[/yellow]")
        return

    if json_output:
        import json
        for i, path in enumerate(repo_dirs):
            print(json.dumps({
                "index": i,
                "path": path
            }))
    else:
        # Rich table output
        from ..utils import find_git_repos_from_config

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("Path", style="green")
        table.add_column("Repos", justify="right", style="yellow")

        for i, path in enumerate(repo_dirs):
            # Count repos in this path
            try:
                repos = find_git_repos_from_config([path], recursive=False)
                count = len(repos)
            except Exception:
                count = "?"

            table.add_row(str(i), path, str(count))

        console.print(table)
        console.print(f"\n[dim]Total:[/dim] {len(repo_dirs)} configured paths")


@config_repos.command("clear")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def repos_clear(yes):
    """Clear all repository directories from configuration.

    This removes all configured repository directory paths.
    Requires confirmation unless --yes is provided.

    Examples:

    \b
        repoindex config repos clear
        repoindex config repos clear --yes
    """
    config = load_config()

    # Get current paths
    repo_dirs = config.get('repository_directories', [])

    if not repo_dirs:
        console.print("[yellow]No repository directories configured[/yellow]")
        return

    # Show what will be cleared
    console.print(f"[yellow]About to clear {len(repo_dirs)} repository directories:[/yellow]")
    for path in repo_dirs:
        console.print(f"  - {path}")

    # Confirm unless --yes
    if not yes:
        if not click.confirm("\nAre you sure you want to clear all repository directories?"):
            console.print("[dim]Cancelled[/dim]")
            return

    # Clear the list
    config['repository_directories'] = []

    # Save configuration
    save_config(config)
    console.print("[green]✓[/green] Cleared all repository directories")
