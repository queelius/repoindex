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

### Repository Status

```bash
# Status of all repositories (JSONL output)
repoindex status -r

# Human-readable table
repoindex status -r --pretty

# Status for specific directory
repoindex status --dir ~/projects -r

# Filter by query
repoindex status -q "language == 'Python'"
```

### Events

Track what's happening across your repositories:

```bash
# Events in the last 7 days (default)
repoindex events --pretty

# Events since specific time
repoindex events --since 24h --pretty
repoindex events --since 7d
repoindex events --since 2024-01-15

# Filter by event type
repoindex events --type git_tag --since 30d
repoindex events --type commit --since 1d

# Include GitHub events (requires API)
repoindex events --github --since 7d

# Include package registry events
repoindex events --pypi --npm --cargo --since 30d

# Watch mode for continuous monitoring
repoindex events --watch --interval 300

# Unlimited results (default limit is 100)
repoindex events --since 30d --limit 0
```

See [Events Overview](events/overview.md) for full documentation.

### Query Language

Find repositories with fuzzy matching:

```bash
# Fuzzy language match (typo-tolerant)
repoindex query "language ~= 'pyton'"

# Multiple conditions
repoindex query "language == 'Python' and stars > 10"

# Check tags
repoindex query "'ml' in tags"

# Complex queries
repoindex query "has_docs and not archived and stars > 10"
```

See [Query Language](catalog-query.md) for syntax details.

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

## Configuration

### Configuration File

Configuration lives at `~/.repoindex/config.json`:

```json
{
  "general": {
    "repository_directories": [
      "~/projects",
      "~/work/**"
    ]
  },
  "events": {
    "default_types": ["git_tag", "commit", "version_bump"]
  },
  "github": {
    "token": "ghp_..."
  }
}
```

### Configuration Commands

```bash
# Show current configuration
repoindex config show

# Add repository directory
repoindex config repos add ~/projects
repoindex config repos add ~/work/**

# Set GitHub token
export REPOINDEX_GITHUB_TOKEN="ghp_your_token"
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `REPOINDEX_CONFIG` | Path to config file |
| `REPOINDEX_GITHUB_TOKEN` | GitHub API token |
| `REPOINDEX_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING) |

## Repository Operations

### Clone Repositories

```bash
# Clone all your GitHub repositories
repoindex get

# Clone to a specific directory
repoindex get --dir ~/projects
```

### Update Repositories

```bash
# Update all repositories in current directory
repoindex update

# Update recursively
repoindex update -r

# Update specific directory
repoindex update --dir ~/projects -r
```

### List Repositories

```bash
# List all tracked repositories
repoindex list

# List with metadata
repoindex list --pretty

# Filter by tag
repoindex list -t "lang:python"
```

## Output Formats

All commands output JSONL (newline-delimited JSON) by default:

```bash
# Stream to jq
repoindex events --since 7d | jq '.type' | sort | uniq -c

# Filter specific repos
repoindex status -r | jq 'select(.name | contains("api"))'

# Human-readable tables
repoindex events --since 7d --pretty
```

### Pipeline Examples

```bash
# Find Python repos with uncommitted changes
repoindex status -r | jq 'select(.status.uncommitted_changes == true and .language == "Python")'

# Count events by type
repoindex events --since 30d | jq '.type' | sort | uniq -c

# Get repo names needing attention
repoindex status -r | jq -r 'select(.status.clean == false) | .name'
```

## Common Workflows

### Morning Check

```bash
# What happened overnight?
repoindex events --since 12h --pretty

# Any security alerts?
repoindex events --github --type security_alert --since 7d

# Repos with uncommitted work
repoindex status -r | jq 'select(.status.uncommitted_changes == true) | .name'
```

### Release Tracking

```bash
# Recent releases across all repos
repoindex events --type git_tag --since 30d --pretty

# Include GitHub releases
repoindex events --github --type github_release --since 30d
```

### Package Monitoring

```bash
# Python packages published
repoindex events --pypi --since 30d --pretty

# All registry events
repoindex events --pypi --npm --cargo --since 30d
```

## Advanced Features

### Metadata Store

Refresh repository metadata:

```bash
# Refresh all metadata
repoindex metadata refresh

# Refresh with GitHub data
repoindex metadata refresh --github

# View metadata for a repo
repoindex metadata show myproject
```

### Repository Audit

Check repository health:

```bash
# Full audit
repoindex audit

# Auto-fix common issues
repoindex audit --fix

# Security checks
repoindex audit security
```

### MCP Server

For LLM integration:

```bash
# Start MCP server
repoindex mcp serve

# Or use CLI directly with Claude Code
# (documented in MCP Overview)
```

## Performance Tips

### Fast Status Checks

```bash
# Skip time-consuming checks
repoindex status --no-pypi-check --no-pages-check

# Local-only events (no API calls)
repoindex events --since 7d  # Default is local-only
```

### Event Limits

```bash
# Increase limit for more results
repoindex events --since 30d --limit 500

# Unlimited results
repoindex events --since 90d --limit 0
```

## Troubleshooting

### No Repositories Found

- Check `repository_directories` in config
- Verify directories contain `.git` folders
- Run `repoindex config show` to check settings

### GitHub API Rate Limit

- Add a GitHub token (increases limits from 60 to 5000/hour)
- Skip GitHub events: `repoindex events` (local only by default)

### Permission Errors

- Check file permissions in repository directories
- Ensure git credentials are configured

## Testing (for Contributors)

```bash
# Install development dependencies
pip install -e ".[test]"

# Run all tests (625+ tests)
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
- **[Event Types Reference](events/event-types.md)** - All 28 event types
