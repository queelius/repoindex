# Event System

repoindex provides an event scanning system that detects changes across your repository collection. Events are stored in the database and populated by `repoindex refresh`.

## Philosophy

The event system follows Unix principles:

- **Database-first**: Events are populated by `refresh`, then queried
- **Stream-friendly**: Use `--json` for JSONL output that pipes to `jq`
- **Composable**: Use with cron, GitHub Actions, or any automation tool
- **Fast queries**: Events are indexed in SQLite for quick retrieval

## Quick Start

```bash
# First, populate events into the database
repoindex refresh --since 7d

# Query recent events (default: last 7 days, pretty table)
repoindex events

# Stream events as JSONL for processing
repoindex events --json | jq '.type'

# Filter by type
repoindex events --type git_tag

# Summary statistics
repoindex events --stats
```

## Event Types

Events are populated during `repoindex refresh` by scanning git history:

| Event Type | Description |
|------------|-------------|
| `git_tag` | Git tags (releases, versions) |
| `commit` | Git commits |
| `branch` | Branch creation/deletion |
| `merge` | Merge commits |

## Command Options

| Option | Description |
|--------|-------------|
| `--type`, `-t` | Filter by event type (can be repeated) |
| `--repo`, `-r` | Filter by repository name |
| `--since`, `-s` | Events after this time (e.g., 1h, 7d, 2024-01-01) |
| `--until`, `-u` | Events before this time |
| `--limit`, `-n` | Maximum events to return (default: 100, 0 for unlimited) |
| `--json` | Output as JSONL (default: pretty table) |
| `--stats` | Show summary statistics only |

## Usage Examples

### Filter by Event Type

```bash
# Only git tags
repoindex events --type git_tag --since 30d

# Only commits
repoindex events --type commit --since 7d
```

### Filter by Repository

```bash
# Events for a specific repo
repoindex events --repo myproject --since 7d
```

### Time Specifications

```bash
# Relative time
repoindex events --since 1h      # Last hour
repoindex events --since 7d      # Last 7 days
repoindex events --since 2w      # Last 2 weeks

# Absolute time
repoindex events --since 2024-01-15
repoindex events --since 2024-01-15T10:30:00
```

### Output Formats

```bash
# Pretty table (default)
repoindex events --since 1d

# JSONL - one JSON object per line (for piping)
repoindex events --json --since 1d

# Statistics summary
repoindex events --stats
```

### Controlling Limits

```bash
# Default: 100 events
repoindex events --since 30d

# Custom limit
repoindex events --since 30d --limit 500

# Unlimited (careful with large time ranges!)
repoindex events --since 365d --limit 0
```

## Workflow

Events follow a two-step workflow:

1. **Refresh** - Scan repositories and populate events into database:
   ```bash
   repoindex refresh --since 30d
   ```

2. **Query** - Retrieve events from database:
   ```bash
   repoindex events --since 7d
   ```

## Composing with Other Tools

### Filter with jq

```bash
# Count events by type
repoindex events --json --since 7d | jq -r '.type' | sort | uniq -c | sort -rn

# Get unique repos with events
repoindex events --json --since 7d | jq -r '.repo_name' | sort -u
```

### Trigger Actions

```bash
# Process events in a script
repoindex events --json --type git_tag --since 1h | while read event; do
  repo=$(echo "$event" | jq -r '.repo_name')
  tag=$(echo "$event" | jq -r '.data.tag')
  echo "New tag: $repo $tag"
done
```

See [Event Types Reference](event-types.md) for details on each event type.
