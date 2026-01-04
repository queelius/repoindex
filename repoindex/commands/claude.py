"""
Claude Code skill management for repoindex.

Provides commands to install/uninstall the repoindex skill for Claude Code,
enabling Claude to query and manage your repository collection.
"""

import click
import json
import sys
from pathlib import Path
from typing import Optional

# Skill definition - the prompt that teaches Claude how to use repoindex
SKILL_CONTENT = '''Use repoindex to explore and query the user's repository collection.

## Quick Start

```bash
# Refresh database (required before queries)
repoindex refresh

# Dashboard overview
repoindex status

# Query with convenience flags
repoindex query --dirty                    # Repos with uncommitted changes
repoindex query --language python          # Python repos
repoindex query --recent 7d                # Repos with recent commits
repoindex query --tag "work/*"             # Repos by tag

# Events from last week
repoindex events --since 7d --pretty
```

## Query Convenience Flags

```bash
repoindex query --dirty              # Repos with uncommitted changes
repoindex query --clean              # Clean repos
repoindex query --language python    # Filter by language (py, js, ts, rust, go, cpp)
repoindex query --recent 7d          # Recent activity
repoindex query --starred            # Repos with stars
repoindex query --tag "work/*"       # Filter by tag (wildcards supported)
repoindex query --no-license         # Repos without license
repoindex query --no-readme          # Repos without README
repoindex query --archived           # Archived repos only

# Combine flags
repoindex query --language python --recent 7d --dirty
```

## Query DSL

The query DSL compiles to SQL:
- **Comparisons**: `==`, `!=`, `>`, `<`, `>=`, `<=`, `~=` (fuzzy)
- **Boolean**: `and`, `or`, `not`
- **Functions**: `has_event('type', since='30d')`, `tagged('pattern/*')`, `updated_since('7d')`
- **Ordering**: `order by field [asc|desc]`
- **Limiting**: `limit N`

```bash
repoindex query "language == 'Python' and stars > 0 order by stars desc limit 10"
repoindex query "has_event('commit', since='7d') and is_clean"
repoindex query "tagged('work/*')"
```

## Raw SQL Access

```bash
# Direct SQL queries
repoindex sql "SELECT name, language, stars FROM repos ORDER BY stars DESC LIMIT 10"

# Database info
repoindex sql --info
repoindex sql --schema

# Interactive SQL shell
repoindex sql -i
```

## Events

Events are populated by `refresh` and queried with `events`:

```bash
repoindex events --since 7d --pretty      # Last week
repoindex events --type commit --since 30d  # Commits only
repoindex events --repo myproject           # Filter by repo
repoindex events --stats                    # Summary statistics
```

## Refresh

```bash
repoindex refresh              # Smart refresh (changed repos only)
repoindex refresh --full       # Force full refresh
repoindex refresh --github     # Include GitHub metadata
repoindex refresh --since 30d  # Events from last 30 days
repoindex sql --reset && repoindex refresh --full  # Full rebuild
```
'''

SKILL_DESCRIPTION = 'repoindex - Repository Index Tool'


def get_global_skills_dir() -> Path:
    """Get the global Claude skills directory."""
    return Path.home() / '.claude' / 'commands'


def get_local_skills_dir() -> Path:
    """Get the local (project) Claude skills directory."""
    return Path.cwd() / '.claude' / 'commands'


def get_skill_path(global_install: bool) -> Path:
    """Get the path where the skill file should be installed."""
    base = get_global_skills_dir() if global_install else get_local_skills_dir()
    return base / 'repoindex.md'


@click.group()
def claude_handler():
    """Manage repoindex skill for Claude Code.

    Install the repoindex skill to enable Claude to query your repository
    collection using natural language.

    Examples:

        # Install globally (all projects)
        repoindex claude install --global

        # Install locally (current project only)
        repoindex claude install

        # Show current installation
        repoindex claude show

        # Uninstall
        repoindex claude uninstall --global
    """
    pass


@claude_handler.command('install')
@click.option('--global', 'global_install', is_flag=True, help='Install globally (~/.claude/commands/)')
@click.option('--force', is_flag=True, help='Overwrite existing skill file')
def install(global_install: bool, force: bool):
    """Install the repoindex skill for Claude Code.

    By default, installs to the current project's .claude/commands/ directory.
    Use --global to install to ~/.claude/commands/ for all projects.
    """
    skill_path = get_skill_path(global_install)
    location = "global" if global_install else "local"

    # Check if already exists
    if skill_path.exists() and not force:
        click.echo(f"Skill already installed at {skill_path}", err=True)
        click.echo("Use --force to overwrite", err=True)
        sys.exit(1)

    # Create directory if needed
    skill_path.parent.mkdir(parents=True, exist_ok=True)

    # Write skill file
    skill_path.write_text(SKILL_CONTENT)

    click.echo(f"Installed repoindex skill ({location})")
    click.echo(f"  Path: {skill_path}")
    click.echo()
    click.echo("Claude can now use /repoindex to query your repositories.")
    click.echo("Make sure to run 'repoindex refresh' first to populate the database.")


@claude_handler.command('uninstall')
@click.option('--global', 'global_install', is_flag=True, help='Uninstall from global location')
def uninstall(global_install: bool):
    """Uninstall the repoindex skill from Claude Code."""
    skill_path = get_skill_path(global_install)
    location = "global" if global_install else "local"

    if not skill_path.exists():
        click.echo(f"Skill not installed at {location} location", err=True)
        click.echo(f"  Expected: {skill_path}", err=True)
        sys.exit(1)

    skill_path.unlink()
    click.echo(f"Uninstalled repoindex skill ({location})")
    click.echo(f"  Removed: {skill_path}")


@claude_handler.command('show')
def show():
    """Show current repoindex skill installation status."""
    from rich.console import Console

    console = Console()
    global_path = get_skill_path(global_install=True)
    local_path = get_skill_path(global_install=False)

    console.print("repoindex Claude Code Skill")
    console.print("=" * 40)
    console.print()

    # Global status
    if global_path.exists():
        console.print(f"Global: [green]installed[/green]")
        console.print(f"  Path: {global_path}")
    else:
        console.print(f"Global: [dim]not installed[/dim]")
        console.print(f"  Path: [dim]{global_path}[/dim]")

    console.print()

    # Local status
    if local_path.exists():
        console.print(f"Local:  [green]installed[/green]")
        console.print(f"  Path: {local_path}")
    else:
        console.print(f"Local:  [dim]not installed[/dim]")
        console.print(f"  Path: [dim]{local_path}[/dim]")

    console.print()
    console.print("Install with: [bold]repoindex claude install [--global][/bold]")


@claude_handler.command('content')
def content():
    """Print the skill content (for manual installation)."""
    print(SKILL_CONTENT)
