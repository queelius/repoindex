import click
import json
import sys
from pathlib import Path

from repoindex.config import load_config, get_config_path


def detect_default_repo_dir() -> str:
    """
    Detect the most likely repository directory.

    Checks common locations in order of priority:
    1. ~/github
    2. ~/repos
    3. ~/projects
    4. ~/src
    5. ~/code
    6. Home directory (fallback)

    Returns the first directory that exists and contains git repos.
    """
    from repoindex.utils import find_git_repos

    home = Path.home()
    candidates = [
        home / "github",
        home / "repos",
        home / "projects",
        home / "src",
        home / "code",
    ]

    for candidate in candidates:
        if candidate.exists():
            # Check if it has git repos
            repos = list(find_git_repos(str(candidate), recursive=True, max_repos=1))
            if repos:
                return str(candidate)

    return str(home)


@click.group("config")
def config_cmd():
    """Configuration management commands."""
    pass


# Register repos subgroup
from .config_repos import config_repos  # noqa: E402
config_cmd.add_command(config_repos)

# Register excludes subgroup
from .config_excludes import config_excludes  # noqa: E402
config_cmd.add_command(config_excludes)


@config_cmd.command("init")
@click.option("-d", "--dir", "directory", type=click.Path(exists=True),
              help="Directory to scan for repositories")
@click.option("-y", "--yes", is_flag=True, help="Auto-confirm (non-interactive)")
@click.option("--recursive/--no-recursive", default=True,
              help="Recursively scan for repos (default: recursive)")
def config_init(directory, yes, recursive):
    """Initialize repoindex configuration.

    Detects repository directories and creates ~/.repoindex/config.json.

    \b
    Examples:
        # Auto-detect repos directory
        repoindex config init
        # Use specific directory
        repoindex config init -d ~/projects
        # Non-interactive mode
        repoindex config init -y -d ~/github
    """
    from rich.console import Console
    console = Console()

    # Check for existing config
    config_path = get_config_path()
    if config_path.exists() and not yes:
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not click.confirm("Overwrite existing configuration?", default=False):
            console.print("Aborted.")
            sys.exit(0)

    # Determine repo directory
    if directory:
        repo_dir = directory
    else:
        repo_dir = detect_default_repo_dir()
        if not yes:
            console.print(f"Detected repository directory: [cyan]{repo_dir}[/cyan]")
            if not click.confirm("Use this directory?", default=True):
                repo_dir = click.prompt("Enter repository directory",
                                       default=str(Path.home() / "github"))

    # Use ~ for home paths
    home = str(Path.home())
    if repo_dir.startswith(home):
        repo_dir = "~" + repo_dir[len(home):]

    # Add ** for recursive
    if recursive:
        repo_dir = repo_dir.rstrip("/") + "/**"

    # Create config
    config = {
        "repository_directories": [repo_dir],
    }

    # Create config directory
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Save config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    console.print(f"\n[green]Configuration created at {config_path}[/green]")
    console.print(f"  Repository directory: {repo_dir}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Run [cyan]repoindex refresh[/cyan] to populate the database")
    console.print("  2. Run [cyan]repoindex status[/cyan] to see your repositories")
    console.print("  3. Run [cyan]repoindex query \"language == 'Python'\"[/cyan] to search")


@config_cmd.command("show")
@click.option("--pretty", is_flag=True, help="Display as formatted JSON instead of single-line JSONL")
@click.option("--path", is_flag=True, help="Show the config file path being used")
def show_config(pretty, path):
    """Show the current configuration with all merges applied.

    By default, outputs single-line JSON (JSONL format).
    Use --pretty for human-readable formatted output.
    Use --path to see which config file is being used.
    """
    if path:
        config_path = get_config_path()
        print(json.dumps({"config_path": str(config_path)}))
        return

    config = load_config()

    if pretty:
        # Pretty print for human readability
        print(json.dumps(config, indent=2, ensure_ascii=False))
    else:
        # Default: single-line JSON (JSONL)
        print(json.dumps(config, ensure_ascii=False))
