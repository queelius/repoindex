# Events

Events are populated by `repoindex refresh` and stored in SQLite.

## Usage

```bash
repoindex events --since 7d                       # Pretty table (default)
repoindex events --type git_tag --since 30d        # Filter by type
repoindex events --type commit --since 7d
repoindex events --repo myproject --since 7d       # Filter by repo
repoindex events --stats                           # Summary statistics
repoindex events --json --since 7d                 # JSONL for piping
repoindex events --since 30d --limit 500           # Custom limit
repoindex events --since 365d --limit 0            # Unlimited
```

## Options

| Option | Description |
|--------|-------------|
| `--type`, `-t` | Filter by event type (repeatable) |
| `--repo`, `-r` | Filter by repository name |
| `--since`, `-s` | After time: `1h`, `7d`, `2w`, `2024-01-15` |
| `--until`, `-u` | Before time |
| `--limit`, `-n` | Max events (default: 100, 0 = unlimited) |
| `--json` | JSONL output |
| `--stats` | Summary only |

## Event Types

| Type | Description |
|------|-------------|
| `git_tag` | Tags (releases, versions) |
| `commit` | Commits |
| `branch` | Branch creation/deletion |
| `merge` | Merge commits |

## Composing with jq

```bash
# Count by type
repoindex events --json --since 7d | jq -r '.type' | sort | uniq -c | sort -rn

# Unique repos with events
repoindex events --json --since 7d | jq -r '.repo_name' | sort -u

# Process new tags
repoindex events --json --type git_tag --since 1h | while read event; do
  echo "$(echo $event | jq -r '.repo_name'): $(echo $event | jq -r '.data.tag')"
done
```

## JSON Schema

```json
{"type": "git_tag", "timestamp": "2024-01-15T10:30:00", "repo_name": "myproject",
 "data": {"tag": "v1.2.0", "message": "Release 1.2.0", "hash": "abc1234"}}

{"type": "commit", "timestamp": "2024-01-15T09:00:00", "repo_name": "myproject",
 "data": {"hash": "abc1234", "message": "Fix auth bug", "author": "dev@example.com"}}

{"type": "branch", "timestamp": "2024-01-15T08:00:00", "repo_name": "myproject",
 "data": {"branch": "feature/new-auth", "action": "created"}}

{"type": "merge", "timestamp": "2024-01-15T11:00:00", "repo_name": "myproject",
 "data": {"hash": "def5678", "message": "Merge 'feature/new-auth'", "merged_branch": "feature/new-auth"}}
```
