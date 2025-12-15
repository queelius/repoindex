import click
from repoindex.config import load_config
import json
import os

@click.group("config")
def config_cmd():
    """Configuration management commands."""
    pass

# Register repos subgroup
from .config_repos import config_repos
config_cmd.add_command(config_repos)

@config_cmd.command("generate")
def generate_config():
    """Generate an example configuration file."""
    example = {
        "general": {
            "repository_directories": ["~/github", "~/projects/*/repos", "~/work/code"],
            "github_username": "your_username"
        },
        "service": {"enabled": True, "interval_minutes": 120},
        "social_media": {"platforms": {"twitter": {"enabled": False}}}
    }
    config_path = os.path.expanduser("~/.repoindexrc")
    if os.path.exists(config_path):
        click.echo(f"Example configuration already exists at {config_path}. Example configuration:\n{json.dumps(example, indent=2)}")
        return
    with open(config_path, "w") as f:
        json.dump(example, f, indent=2)
    click.echo(f"Example configuration written to {config_path}. Example configuration:\n{json.dumps(example, indent=2)}")

@config_cmd.command("show")
@click.option("--pretty", is_flag=True, help="Display as formatted JSON instead of single-line JSONL")
@click.option("--path", is_flag=True, help="Show the config file path being used")
def show_config(pretty, path):
    """Show the current configuration with all merges applied.
    
    By default, outputs single-line JSON (JSONL format).
    Use --pretty for human-readable formatted output.
    Use --path to see which config file is being used.
    """
    from repoindex.config import get_config_path
    
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
