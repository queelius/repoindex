# Getting Started

Get up and running with repoindex in minutes.

## Prerequisites

- Python 3.8 or higher
- Git installed and configured
- Optional: `gh` CLI for GitHub features

## Installation

```bash
pip install repoindex
```

Verify installation:

```bash
repoindex --version
repoindex --help
```

## Quick Setup

### 1. Configure Repository Directories

Tell repoindex where your repositories live:

```bash
# Add directories to scan
repoindex config repos add ~/projects
repoindex config repos add ~/work/**

# Verify configuration
repoindex config show
```

The `**` pattern recursively searches subdirectories.

### 2. Set Up GitHub Token (Optional)

For GitHub-specific events (releases, PRs, security alerts):

```bash
export REPOINDEX_GITHUB_TOKEN="ghp_your_token_here"
```

Or add to config:

```json
{
  "github": {
    "token": "ghp_your_token_here"
  }
}
```

## Your First Commands

### Check Status

```bash
# Status of all repositories
repoindex status -r --pretty

# Find repos with uncommitted changes (using jq)
repoindex status -r | jq 'select(.status.uncommitted_changes == true)'
```

### View Events

See what's happening across your collection:

```bash
# Events in the last 7 days
repoindex events --since 7d --pretty

# Include GitHub events
repoindex events --github --since 7d --pretty

# Only git tags (releases)
repoindex events --type git_tag --since 30d

# Relative timestamps
repoindex events --since 1d --pretty --relative-time
```

### Query Repositories

Find repos with fuzzy matching:

```bash
# Fuzzy language match
repoindex query "language ~= 'pyton'"

# Multiple conditions
repoindex query "language == 'Python' and stars > 10"

# Has specific features
repoindex query "has_docs and not archived"
```

### Organize with Tags

```bash
# Add tags
repoindex tag add myproject work/active
repoindex tag add myproject topic:ml

# List repos by tag
repoindex tag list -t "work/*"

# Show tag hierarchy
repoindex tag tree
```

### Interactive Shell

```bash
repoindex shell

# Navigate like a filesystem
> cd /by-tag/work/active
> ls
> events --since 1d
> exit
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

## Output Formats

All commands output JSONL by default for Unix pipeline composition:

```bash
# Stream to jq
repoindex events --since 7d | jq '.type' | sort | uniq -c

# Pretty tables for humans
repoindex events --since 7d --pretty

# Filter specific repos
repoindex status -r | jq 'select(.name | contains("api"))'
```

## Configuration File

Configuration lives at `~/.repoindex/config.json`:

```json
{
  "general": {
    "repository_directories": [
      "~/projects",
      "~/work/**"
    ]
  },
  "github": {
    "token": "ghp_..."
  },
  "events": {
    "default_types": [
      "git_tag", "commit", "version_bump"
    ]
  }
}
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `REPOINDEX_CONFIG` | Path to config file |
| `REPOINDEX_GITHUB_TOKEN` | GitHub API token |
| `REPOINDEX_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING) |

## Next Steps

- **[Usage Guide](usage.md)** - Full command reference
- **[Events](events/overview.md)** - Event system documentation
- **[Query Language](catalog-query.md)** - Query syntax
- **[Shell & VFS](shell-vfs.md)** - Interactive shell

## Getting Help

- **Command Help**: `repoindex <command> --help`
- **GitHub Issues**: [Report bugs](https://github.com/queelius/repoindex/issues)

## Troubleshooting

### No repositories found
- Check `repository_directories` in config
- Verify directories contain `.git` folders
- Run `repoindex config show` to check settings

### GitHub API rate limit
- Add a GitHub token (increases limits from 60 to 5000/hour)
- Skip GitHub events: `repoindex events` (local only by default)

### Permission errors
- Check file permissions in repository directories
- Ensure git credentials are configured
