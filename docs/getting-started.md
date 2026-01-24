# Getting Started

Get up and running with repoindex in minutes.

## Prerequisites

- Python 3.8 or higher
- Git installed and configured
- Optional: GitHub token for enhanced metadata

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

### 1. Initialize Configuration

```bash
# Create default configuration
repoindex config init

# Verify configuration
repoindex config show
```

Configuration is stored at `~/.repoindex/config.yaml`.

### 2. Refresh Database

```bash
# Populate the database with your repositories
repoindex refresh
```

### 3. Set Up GitHub Token (Optional)

For GitHub-specific metadata (stars, topics, etc.):

```bash
export GITHUB_TOKEN="ghp_your_token_here"
```

Or add to config:

```yaml
github:
  token: ghp_your_token_here
```

Then refresh with GitHub metadata:

```bash
repoindex refresh --github
```

## Your First Commands

### Check Status

```bash
# Dashboard overview
repoindex status
```

### Query Repositories

```bash
# Find repos with uncommitted changes (pretty table by default)
repoindex query --dirty

# Find Python repos
repoindex query --language python

# Find repos by tag
repoindex query --tag "work/*"

# JSONL output for piping
repoindex query --json --dirty | jq '.name'
```

### View Events

See what's happening across your collection:

```bash
# Events in the last 7 days (pretty table by default)
repoindex events --since 7d

# Only git tags (releases)
repoindex events --type git_tag --since 30d

# Summary statistics
repoindex events --stats
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
```

## Output Formats

Commands output pretty tables by default for human readability:

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

## Configuration File

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

## Environment Variables

| Variable | Description |
|----------|-------------|
| `REPOINDEX_CONFIG` | Path to config file |
| `GITHUB_TOKEN` | GitHub API token |
| `REPOINDEX_GITHUB_TOKEN` | GitHub API token (alternative) |
| `REPOINDEX_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING) |

## Claude Code Integration

Install the repoindex skill for Claude Code:

```bash
# Install globally (all projects)
repoindex claude install --global
```

Then use `/repoindex` in Claude Code conversations for collection awareness.

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
- Check `repository_directories` in config with `repoindex config show`
- Verify directories contain `.git` folders
- Run `repoindex refresh --full` to rebuild database

### GitHub API rate limit
- Add a GitHub token (increases limits from 60 to 5000/hour)
- Skip GitHub metadata: `repoindex refresh` (local only by default)

### Permission errors
- Check file permissions in repository directories
- Ensure git credentials are configured
