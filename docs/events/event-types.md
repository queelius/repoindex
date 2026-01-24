# Event Types Reference

Reference for event types supported by repoindex.

## Git Events

Events scanned from git history during `repoindex refresh`.

### git_tag

Git tags, typically used for releases and versions.

```json
{
  "type": "git_tag",
  "timestamp": "2024-01-15T10:30:00",
  "repo_name": "myproject",
  "repo_path": "/path/to/myproject",
  "data": {
    "tag": "v1.2.0",
    "message": "Release 1.2.0",
    "hash": "abc1234"
  }
}
```

### commit

Individual git commits.

```json
{
  "type": "commit",
  "timestamp": "2024-01-15T09:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "abc1234def5678",
    "message": "Fix authentication bug",
    "author": "developer@example.com"
  }
}
```

### branch

Branch creation and deletion (detected from reflog).

```json
{
  "type": "branch",
  "timestamp": "2024-01-15T08:00:00",
  "repo_name": "myproject",
  "data": {
    "branch": "feature/new-auth",
    "action": "created"
  }
}
```

### merge

Merge commits.

```json
{
  "type": "merge",
  "timestamp": "2024-01-15T11:00:00",
  "repo_name": "myproject",
  "data": {
    "hash": "def5678",
    "message": "Merge branch 'feature/new-auth' into main",
    "merged_branch": "feature/new-auth"
  }
}
```

## Event Type Summary

| Event Type | Description | Detection |
|------------|-------------|-----------|
| `git_tag` | Git tags (releases, versions) | Git log |
| `commit` | Git commits | Git log |
| `branch` | Branch creation/deletion | Git reflog |
| `merge` | Merge commits | Git log |

## Filtering Events

Use `--type` to filter by specific event type:

```bash
# Only git tags
repoindex events --type git_tag

# Only commits
repoindex events --type commit

# Multiple types
repoindex events --type git_tag --type commit
```

## Event Storage

Events are stored in the SQLite database (`~/.repoindex/repoindex.db`) during `refresh`:

```bash
# Populate events for last 30 days
repoindex refresh --since 30d

# Then query
repoindex events --since 7d
```
