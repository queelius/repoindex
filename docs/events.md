# Events

Events are populated by `repoindex refresh` and stored in the `events`
table. They are append-only: refresh inserts with `INSERT OR IGNORE` on a
stable `event_id`, so old events persist even after the source branch or
ref is gone.

## Usage

```bash
repoindex events --since 7d                        # Pretty table (default)
repoindex events --type git_tag --since 30d        # Filter by type
repoindex events --type commit --since 7d
repoindex events --repo myproject --since 7d       # Filter by repo name
repoindex events --stats                           # Summary only
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
| `--stats` | Summary statistics only |

## Event Types

Built-in local event types (always scanned):

| Type | Description |
|------|-------------|
| `git_tag` | Tags (releases, versions) |
| `commit` | Commits |
| `branch` | Branch creation / deletion (from reflog) |
| `merge` | Merge commits |
| `version_bump` | Changes to version files (`pyproject.toml`, `package.json`, ...) |
| `deps_update` | Dependency file changes (`requirements.txt`, lock files, ...) |
| `license_change` | LICENSE file modifications |
| `ci_config_change` | CI/CD config changes (`.github/workflows`, `.gitlab-ci.yml`, ...) |
| `docs_change` | Documentation file changes under `docs/` |
| `readme_change` | README file changes |

Remote event types (opt-in per refresh flag, require network and possibly
a token):

| Type | Source |
|------|--------|
| `github_release`, `pr`, `issue`, `workflow_run`, `security_alert`, `repo_rename`, `repo_transfer`, `repo_visibility`, `repo_archive`, `deployment`, `fork`, `star` | `refresh --github` |
| `pypi_publish` | `refresh --pypi` |
| `cran_publish` | `refresh --cran` |
| `npm_publish`, `cargo_publish`, `docker_publish`, `gem_publish`, `nuget_publish`, `maven_publish` | `refresh --source <id>` or `--external` |

The exact enabled set depends on the sources you enable and the
configuration; see `repoindex refresh --help`.

## Composing with jq

```bash
# Count by type
repoindex events --json --since 7d | jq -r '.type' | sort | uniq -c | sort -rn

# Unique repos with events
repoindex events --json --since 7d | jq -r '.repo_name' | sort -u

# Process new tags as a stream
repoindex events --json --type git_tag --since 1h | while read event; do
  echo "$(echo $event | jq -r '.repo_name'): $(echo $event | jq -r '.data.tag')"
done
```

## Querying Events via SQL

For anything more expressive than the filter flags, go straight to SQL:

```bash
# Most active repos in the last 30 days
repoindex sql "
  SELECT r.name, COUNT(*) AS n
  FROM events e JOIN repos r ON e.repo_id = r.id
  WHERE e.type = 'commit' AND e.timestamp > datetime('now', '-30 days')
  GROUP BY r.id
  ORDER BY n DESC
  LIMIT 20
"

# Every tag created since Jan 1
repoindex sql "
  SELECT r.name, e.ref, e.timestamp
  FROM events e JOIN repos r ON e.repo_id = r.id
  WHERE e.type = 'git_tag' AND e.timestamp >= '2026-01-01'
  ORDER BY e.timestamp DESC
"
```

The `events` table schema is documented in `CLAUDE.md` and is part of the
stable surface (see `STABILITY.md`).

## JSON Output Shape

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
