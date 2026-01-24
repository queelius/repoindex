# Usage Guide

Complete reference for all repoindex commands and features.

## Installation

```bash
pip install repoindex
```

Verify installation:

```bash
repoindex --version
repoindex --help
```

## Core Commands

### Dashboard Status

```bash
# Dashboard overview of your collection
repoindex status
```

### Query Repositories

```bash
# Query with convenience flags (pretty table by default)
repoindex query --dirty                    # Uncommitted changes
repoindex query --clean                    # Clean repos
repoindex query --language python          # Python repos
repoindex query --recent 7d                # Recent activity
repoindex query --tag "work/*"             # Filter by tag

# GitHub flags (requires --github during refresh)
repoindex query --starred                  # Has GitHub stars
repoindex query --public                   # Public repos
repoindex query --private                  # Private repos
repoindex query --fork                     # Forked repos
repoindex query --no-fork                  # Non-forked repos
repoindex query --archived                 # Archived repos

# Citation flags
repoindex query --has-citation             # Has citation files
repoindex query --has-doi                  # Has DOI in citation

# Query DSL
repoindex query "language == 'Python' and github_stars > 10"

# Output options
repoindex query --json --language python   # JSONL output
repoindex query --brief --dirty            # Just repo names
```

### Events

Track what's happening across your repositories:

```bash
# Events from database (pretty table by default)
repoindex events --since 7d

# Events since specific time
repoindex events --since 24h
repoindex events --since 2024-01-15

# Filter by event type
repoindex events --type git_tag --since 30d
repoindex events --type commit --since 7d

# Filter by repository
repoindex events --repo myproject

# Summary statistics
repoindex events --stats

# JSONL output for piping
repoindex events --json --since 7d | jq '.type' | sort | uniq -c
```

See [Events Overview](events/overview.md) for full documentation.

### Tag Management

Organize repositories with hierarchical tags:

```bash
# Add tags
repoindex tag add myproject work/active
repoindex tag add myproject topic:ml/research

# Remove tags
repoindex tag remove myproject work/active

# Move between tags
repoindex tag move myproject work/active work/completed

# List all tags
repoindex tag list

# List repositories with specific tag
repoindex tag list -t "work/*"

# Show tag hierarchy
repoindex tag tree
repoindex tag tree -t work  # Show subtree
```

### Interactive Shell

```bash
# Launch interactive shell with VFS
repoindex shell

# Navigate like a filesystem
> cd /by-tag/work/active
> ls
> events --since 1d
> exit
```

See [Shell & VFS](shell-vfs.md) for details.

## Database Management

### Refresh

```bash
# Smart refresh (changed repos only)
repoindex refresh

# Force full refresh
repoindex refresh --full

# Include external metadata
repoindex refresh --github         # GitHub metadata
repoindex refresh --pypi           # PyPI package status
repoindex refresh --cran           # CRAN package status
repoindex refresh --external       # All external sources

# Refresh specific directory
repoindex refresh -d ~/projects

# Events scan range
repoindex refresh --since 30d

# Preview mode
repoindex refresh --dry-run
```

### SQL Access

```bash
# Direct SQL queries
repoindex sql "SELECT name, language, github_stars FROM repos ORDER BY github_stars DESC LIMIT 10"

# Database info
repoindex sql --info
repoindex sql --schema
repoindex sql --stats        # Row counts per table
repoindex sql --path         # Database file path

# Interactive SQL shell
repoindex sql -i

# Output formats
repoindex sql "SELECT * FROM repos" --format json
repoindex sql "SELECT * FROM repos" --format csv
repoindex sql "SELECT * FROM repos" --format table

# Query from file
repoindex sql -f query.sql

# Database maintenance
repoindex sql --integrity    # Check database integrity
repoindex sql --vacuum       # Compact and optimize
repoindex sql --reset        # Delete and recreate database
```

## Additional Commands

### Export (ECHO format)

Export repository index in durable, self-describing format:

```bash
# Basic export
repoindex export ~/backup

# Include README snapshots
repoindex export ~/backup --include-readmes

# Include event history
repoindex export ~/backup --include-events

# Include git summaries
repoindex export ~/backup --include-git-summary 10

# Full export with archives
repoindex export ~/backup --include-readmes --include-events --archive-repos

# Preview
repoindex export ~/backup --dry-run --pretty
```

### Copy (backup/redundancy)

Copy repositories with filtering:

```bash
# Copy all repos
repoindex copy ~/backup

# Copy with filters
repoindex copy ~/backup --language python
repoindex copy ~/backup --dirty
repoindex copy ~/backup --tag "work/*"

# Options
repoindex copy ~/backup --exclude-git          # Skip .git
repoindex copy ~/backup --preserve-structure   # Keep dir hierarchy
repoindex copy ~/backup --collision rename     # Handle conflicts
repoindex copy ~/backup --dry-run --pretty     # Preview
```

### Link Trees

Create symlink trees organized by metadata:

```bash
# Create by tag
repoindex link tree ~/links/by-tag --by tag

# Create by language
repoindex link tree ~/links/by-lang --by language

# Other organization options
repoindex link tree ~/links/by-year --by modified-year
repoindex link tree ~/links/by-owner --by owner

# With query filters
repoindex link tree ~/links/python --by tag --language python

# Preview
repoindex link tree ~/links/test --by tag --dry-run --pretty

# Check status
repoindex link status ~/links/by-tag

# Refresh (remove broken links)
repoindex link refresh ~/links/by-tag --prune
```

### Views (Curated Collections)

Views are ordered repository collections with optional metadata overlays:

```bash
# List all views
repoindex view list
repoindex view list --templates

# Show view definition
repoindex view show portfolio

# Evaluate view (resolve to repositories)
repoindex view eval portfolio
repoindex view eval portfolio --full    # Include overlay details

# Create views
repoindex view create portfolio --repos repoindex ctk btk
repoindex view create python-libs --query "language == 'Python'"
repoindex view create ml-research --tags "research/ml" "research/nlp"
repoindex view create active --extends portfolio

# Add overlays/annotations
repoindex view overlay portfolio repoindex -d "Repository management toolkit"
repoindex view overlay teaching project --highlight -n "Start here"

# Delete view
repoindex view delete old-portfolio --force

# Find views containing a repo
repoindex view repos myproject
```

Views support composition (union, intersect, subtract) for building complex collections.

## Configuration

### Configuration File

Configuration lives at `~/.repoindex/config.yaml`:

```yaml
repository_directories:
  - ~/projects
  - ~/work/**

github:
  token: ghp_...

repository_tags:
  /path/to/repo:
    - topic:ml
    - work/active
```

### Configuration Commands

```bash
# Initialize configuration
repoindex config init

# Show current configuration
repoindex config show

# List repository directories
repoindex config repos
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `REPOINDEX_CONFIG` | Path to config file |
| `GITHUB_TOKEN` | GitHub API token |
| `REPOINDEX_GITHUB_TOKEN` | GitHub API token (alternative) |
| `REPOINDEX_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING) |

## Output Formats

Commands output pretty tables by default:

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

### Pipeline Examples

```bash
# Get Python repos with uncommitted changes
repoindex query --json --language python --dirty | jq '.name'

# Count events by type
repoindex events --json --since 30d | jq '.type' | sort | uniq -c

# Get repo names needing attention
repoindex query --brief --dirty
```

## Common Workflows

### Morning Check

```bash
# What happened overnight?
repoindex events --since 12h

# Repos with uncommitted work
repoindex query --dirty

# Dashboard overview
repoindex status
```

### Release Tracking

```bash
# Recent releases across all repos
repoindex events --type git_tag --since 30d

# Repos with recent tags
repoindex query --recent 7d
```

## Claude Code Integration

Install the skill for Claude Code:

```bash
# Install globally (all projects)
repoindex claude install --global

# Install locally (current project)
repoindex claude install

# Show installation status
repoindex claude show

# Uninstall
repoindex claude uninstall --global
```

## Performance Tips

### Fast Queries

```bash
# Local-only queries (no external API)
repoindex query --dirty
repoindex query --language python

# Use brief mode for scripts
repoindex query --brief --dirty
```

### Refresh Optimization

```bash
# Smart refresh only updates changed repos
repoindex refresh

# Full refresh when needed
repoindex refresh --full

# Limit event scan range
repoindex refresh --since 7d
```

## Troubleshooting

### No Repositories Found

- Run `repoindex config show` to check settings
- Verify directories contain `.git` folders
- Run `repoindex refresh --full` to rebuild database

### GitHub API Rate Limit

- Add a GitHub token (increases limits from 60 to 5000/hour)
- Skip GitHub metadata: `repoindex refresh` (local only by default)

### Permission Errors

- Check file permissions in repository directories
- Ensure git credentials are configured

## Testing (for Contributors)

```bash
# Install development dependencies
pip install -e ".[test]"

# Run all tests (810+ tests)
pytest

# Run with coverage report
pytest --cov=repoindex --cov-report=html

# Run specific test modules
pytest tests/test_events.py -v
```

## Next Steps

- **[Events Overview](events/overview.md)** - Event system details
- **[Query Language](catalog-query.md)** - Query syntax
- **[Shell & VFS](shell-vfs.md)** - Interactive shell
- **[Event Types Reference](events/event-types.md)** - All event types
