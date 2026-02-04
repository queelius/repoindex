"""
Claude Code skill management for repoindex.

Provides commands to install/uninstall the repoindex skill for Claude Code,
enabling Claude to query and manage your repository collection.
"""

import click
import sys
from pathlib import Path

def get_version() -> str:
    """Get repoindex version from package metadata."""
    try:
        from importlib.metadata import version
        return version('repoindex')
    except Exception:
        return 'unknown'


def generate_skill_content() -> str:
    """Generate skill content with current version."""
    version = get_version()
    return f'''# repoindex - Repository Index Tool

Use the `repoindex` CLI to query and manage the user's git repository collection.

**Version**: {version}

Database: `~/.repoindex/repoindex.db` (SQLite). Use `repoindex sql` for direct SQL queries.

## CRITICAL: Publications Table is Source of Truth for Packages

The `publications` table is the **canonical source** for which packages are published
to PyPI, CRAN, Zenodo, etc. It is populated by `repoindex refresh --pypi --cran --zenodo`.

**ALWAYS query this table first** when:
- Counting published packages
- Populating package data in any external system (e.g., `.mf/projects_db.json`)
- Verifying whether a package is actually published

## Quick Start

```bash
# Refresh database (required before queries)
repoindex refresh

# Dashboard overview
repoindex status

# Query with convenience flags (pretty table by default)
repoindex query --dirty                    # Repos with uncommitted changes
repoindex query --language python          # Python repos
repoindex query --recent 7d                # Repos with recent commits
repoindex query --tag "work/*"             # Repos by tag

# Events from last week (pretty table by default)
repoindex events --since 7d
```

## Query Convenience Flags

```bash
# Local flags (no external API required)
repoindex query --dirty              # Repos with uncommitted changes
repoindex query --clean              # Clean repos
repoindex query --language python    # Filter by language (py, js, ts, rust, go, cpp)
repoindex query --recent 7d          # Recent activity
repoindex query --tag "work/*"       # Filter by tag (wildcards supported)
repoindex query --no-license         # Repos without license
repoindex query --no-readme          # Repos without README
repoindex query --has-citation       # Repos with citation files (CITATION.cff, .zenodo.json)
repoindex query --has-doi            # Repos with DOI in citation metadata
repoindex query --has-remote         # Repos with remote URL

# GitHub flags (requires --github during refresh)
repoindex query --starred            # Repos with GitHub stars
repoindex query --public             # Public repos only
repoindex query --private            # Private repos only
repoindex query --fork               # Forked repos only
repoindex query --no-fork            # Non-forked repos only
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
repoindex sql "SELECT name, language, github_stars FROM repos ORDER BY github_stars DESC LIMIT 10"

# Database info
repoindex sql --info
repoindex sql --schema

# Interactive SQL shell
repoindex sql -i
```

## Complete SQL Data Model

### repos table

Main repository data. One row per local repo path.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Primary key (autoincrement) |
| `name` | TEXT NOT NULL | Repository name |
| `path` | TEXT NOT NULL | Filesystem path (UNIQUE) |
| `branch` | TEXT | Current branch |
| `remote_url` | TEXT | Git remote URL |
| `owner` | TEXT | Repo owner |
| `is_clean` | BOOLEAN | Default 1. No uncommitted changes |
| `ahead` | INTEGER | Default 0. Commits ahead of upstream |
| `behind` | INTEGER | Default 0. Commits behind upstream |
| `has_upstream` | BOOLEAN | Default 0. Has remote tracking branch |
| `uncommitted_changes` | BOOLEAN | Default 0 |
| `untracked_files` | INTEGER | Default 0. Count of untracked files |
| `language` | TEXT | Primary language |
| `languages` | TEXT | JSON array of all languages |
| `description` | TEXT | Repo description |
| `readme_content` | TEXT | Full README text |
| `license_key` | TEXT | SPDX identifier (e.g., "MIT") |
| `license_name` | TEXT | Human-readable license name |
| `license_file` | TEXT | Path to license file |
| `has_readme` | BOOLEAN | Default 0 |
| `has_license` | BOOLEAN | Default 0 |
| `has_ci` | BOOLEAN | Default 0. Has CI config |
| `has_citation` | BOOLEAN | Default 0 |
| `citation_file` | TEXT | Path to CITATION.cff / .zenodo.json |
| `citation_doi` | TEXT | DOI from local citation file |
| `citation_title` | TEXT | Title from citation file |
| `citation_authors` | TEXT | JSON array of authors |
| `citation_version` | TEXT | Version from citation file |
| `citation_repository` | TEXT | Repository URL from citation |
| `citation_license` | TEXT | License from citation file |
| `github_owner` | TEXT | GitHub owner/org |
| `github_name` | TEXT | GitHub repo name |
| `github_description` | TEXT | GitHub description |
| `github_stars` | INTEGER | Default 0 |
| `github_forks` | INTEGER | Default 0 |
| `github_watchers` | INTEGER | Default 0 |
| `github_open_issues` | INTEGER | Default 0 |
| `github_is_fork` | BOOLEAN | Default 0 |
| `github_is_private` | BOOLEAN | Default 0 |
| `github_is_archived` | BOOLEAN | Default 0 |
| `github_has_issues` | BOOLEAN | Default 1 |
| `github_has_wiki` | BOOLEAN | Default 1 |
| `github_has_pages` | BOOLEAN | Default 0 |
| `github_pages_url` | TEXT | GitHub Pages URL |
| `github_topics` | TEXT | JSON array of topic strings |
| `github_created_at` | TIMESTAMP | |
| `github_updated_at` | TIMESTAMP | |
| `github_pushed_at` | TIMESTAMP | |
| `scanned_at` | TIMESTAMP | Default CURRENT_TIMESTAMP |
| `git_index_mtime` | REAL | For change detection |

### publications table

**Source of truth for published packages.** One row per (repo, registry) pair.
Populated by `repoindex refresh --pypi --cran --zenodo`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Primary key |
| `repo_id` | INTEGER NOT NULL | FK -> repos.id (CASCADE delete) |
| `registry` | TEXT NOT NULL | `'pypi'`, `'cran'`, `'zenodo'`, `'npm'`, `'cargo'`, `'docker'` |
| `package_name` | TEXT NOT NULL | Name on registry (may differ from repo name) |
| `current_version` | TEXT | Latest version on registry |
| `published` | BOOLEAN | Default 0. **1 = confirmed live on registry** |
| `url` | TEXT | Package URL on registry |
| `doi` | TEXT | DOI identifier (Zenodo only, e.g., `"10.5281/zenodo.1234567"`) |
| `downloads_total` | INTEGER | Total download count (PyPI) |
| `downloads_30d` | INTEGER | Last 30 days downloads |
| `last_published` | TIMESTAMP | When last version was published |
| `scanned_at` | TIMESTAMP | Default CURRENT_TIMESTAMP |

**UNIQUE constraint**: `(repo_id, registry)` -- one record per repo per registry.

**Key semantics:**
- `published = 0` -> repo has packaging files but package is NOT on the registry
- `published = 1` -> confirmed live on registry via API probe
- `package_name` may differ from repo `name` (e.g., repo `btk` -> pypi `bookmark-tk`)
- `doi` is only set for `registry = 'zenodo'`; use `repos.citation_doi` for local citation DOIs

### events table

Git activity log. One row per event.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Primary key |
| `repo_id` | INTEGER NOT NULL | FK -> repos.id |
| `event_id` | TEXT | Unique event identifier |
| `type` | TEXT NOT NULL | `'commit'`, `'git_tag'`, `'branch'`, `'merge'` |
| `timestamp` | TIMESTAMP NOT NULL | When event occurred |
| `ref` | TEXT | Branch/tag ref |
| `message` | TEXT | Commit/tag message |
| `author` | TEXT | Author name |
| `metadata` | TEXT | JSON blob with extra data |
| `scanned_at` | TIMESTAMP | Default CURRENT_TIMESTAMP |

### tags table

User-defined repo organization tags. Composite PK: `(repo_id, tag)`.

| Column | Type | Notes |
|--------|------|-------|
| `repo_id` | INTEGER NOT NULL | FK -> repos.id, part of PK |
| `tag` | TEXT NOT NULL | Tag string, part of PK |
| `source` | TEXT | Default `'user'`. Also `'implicit'`, `'github'` |
| `created_at` | TIMESTAMP | Default CURRENT_TIMESTAMP |

## Example SQL Queries

```bash
# Published packages by registry (THE definitive count)
repoindex sql "SELECT registry, COUNT(*) as count FROM publications WHERE published = 1 GROUP BY registry"

# All confirmed published packages with repo name
repoindex sql "SELECT p.registry, p.package_name, r.name as repo, p.url FROM publications p JOIN repos r ON p.repo_id = r.id WHERE p.published = 1 ORDER BY p.registry, p.package_name"

# Zenodo DOIs
repoindex sql "SELECT r.name, p.doi, p.url FROM publications p JOIN repos r ON p.repo_id = r.id WHERE p.registry = 'zenodo' AND p.published = 1"

# Repos with citation DOI (from local files, separate from Zenodo)
repoindex sql "SELECT name, citation_doi FROM repos WHERE citation_doi IS NOT NULL"

# Repos by star count
repoindex sql "SELECT name, github_stars FROM repos WHERE github_stars > 0 ORDER BY github_stars DESC"

# Repos missing license
repoindex sql "SELECT name, path FROM repos WHERE has_license = 0"

# Recent commits by repo (last 30 days)
repoindex sql "SELECT r.name, COUNT(*) as commits FROM events e JOIN repos r ON e.repo_id = r.id WHERE e.type = 'commit' AND e.timestamp > datetime('now', '-30 days') GROUP BY r.id ORDER BY commits DESC"

# Detected but unpublished packages (have packaging files, not on registry)
repoindex sql "SELECT p.registry, p.package_name, r.name as repo FROM publications p JOIN repos r ON p.repo_id = r.id WHERE p.published = 0 ORDER BY p.registry"

# Package name differs from repo name
repoindex sql "SELECT r.name as repo, p.package_name, p.registry FROM publications p JOIN repos r ON p.repo_id = r.id WHERE p.published = 1 AND r.name != p.package_name"
```

## Events

Events are populated by `refresh` and queried with `events`:

```bash
repoindex events --since 7d               # Last week (pretty table)
repoindex events --type commit --since 30d  # Commits only
repoindex events --repo myproject           # Filter by repo
repoindex events --stats                    # Summary statistics
repoindex events --json                     # JSONL for piping
```

## Refresh

```bash
repoindex refresh              # Smart refresh (changed repos only)
repoindex refresh --full       # Force full refresh
repoindex refresh --github     # Include GitHub metadata (stars, topics)
repoindex refresh --pypi       # Probe PyPI for all Python repos
repoindex refresh --cran       # Probe CRAN/Bioconductor for all R repos
repoindex refresh --zenodo     # Batch fetch Zenodo records via ORCID
repoindex refresh --external   # All external sources at once
repoindex refresh --since 30d  # Events from last 30 days
repoindex sql --reset && repoindex refresh --full  # Full rebuild
```

## Tag Management

```bash
repoindex tag add myproject topic:ml work/active   # Add tags
repoindex tag remove myproject work/active         # Remove tags
repoindex tag list                                 # List all tags
repoindex tag list -t "topic:*"                   # Filter tags
repoindex tag tree                                 # Hierarchical view
```

## Link Trees (symlinks organized by metadata)

```bash
repoindex link tree ~/links/by-tag --by tag        # Organize by tags
repoindex link tree ~/links/by-lang --by language  # Organize by language
repoindex link tree ~/links/by-year --by modified-year
repoindex link status ~/links/by-tag               # Check tree health
repoindex link refresh ~/links/by-tag --prune      # Remove broken links
```

## Copy (backup/redundancy)

```bash
repoindex copy ~/backup --language python          # Copy Python repos
repoindex copy ~/backup --dirty --dry-run          # Preview dirty repos
repoindex copy ~/backup --exclude-git              # Skip .git directories
```

## Export (ECHO format)

```bash
repoindex export ~/backup --include-readmes        # Export with READMEs
repoindex export ~/backup --include-events         # Include event history
repoindex export ~/backup --dry-run --pretty       # Preview
```

## Output Formats

Commands output pretty tables by default. Use `--json` for JSONL (for piping):

```bash
# Pretty tables (default)
repoindex query --language python
repoindex events --since 7d

# JSONL for piping/scripting
repoindex query --json --language python | jq '.name'
repoindex events --json --since 7d | jq '.type' | sort | uniq -c

# Brief output (just repo names)
repoindex query --brief --dirty
```

## Notes

- Database is populated by `repoindex refresh` (run first if data seems stale)
- Path is the canonical identity -- each local path is independent
- GitHub fields are namespaced with `github_` prefix
- Query flags: `--dirty`, `--clean`, `--language`, `--tag`, `--starred`, etc.
- `published = 0` means repo has packaging files but package isn't on the registry yet
- `published = 1` means confirmed live on the registry via API check
- `repos.citation_doi` holds DOIs from local citation files -- separate from Zenodo registry DOIs
- Zenodo refresh requires `author.orcid` in `~/.repoindex/config.yaml`
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
    skill_path.write_text(generate_skill_content())

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
        console.print("Global: [green]installed[/green]")
        console.print(f"  Path: {global_path}")
    else:
        console.print("Global: [dim]not installed[/dim]")
        console.print(f"  Path: [dim]{global_path}[/dim]")

    console.print()

    # Local status
    if local_path.exists():
        console.print("Local:  [green]installed[/green]")
        console.print(f"  Path: {local_path}")
    else:
        console.print("Local:  [dim]not installed[/dim]")
        console.print(f"  Path: [dim]{local_path}[/dim]")

    console.print()
    console.print("Install with: [bold]repoindex claude install [--global][/bold]")


@claude_handler.command('content')
def content():
    """Print the skill content (for manual installation)."""
    print(generate_skill_content())
