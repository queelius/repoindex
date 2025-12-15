# Event System

repoindex provides a powerful event scanning system that detects changes across your repository collection. The system is **read-only** and **stateless** - it observes and reports, leaving action to external tools.

## Philosophy

The event system follows Unix principles:

- **Observe, don't act**: repoindex detects events but doesn't modify anything
- **Stream-friendly**: Default JSONL output pipes to `jq`, `grep`, or custom handlers
- **Composable**: Use with cron, GitHub Actions, or any automation tool
- **Fast by default**: Local events require no API calls; remote events are opt-in

## Quick Start

```bash
# See what happened in your repos this week
repoindex events --since 7d --pretty

# Stream events as JSONL for processing
repoindex events --since 1d | jq '.type'

# Include GitHub releases and PRs
repoindex events --github --since 7d --pretty

# Watch for new events continuously
repoindex events --watch --github
```

## Event Categories

### Local Events (Default, Fast)

These scan git history directly - no API calls needed:

| Event Type | Description |
|------------|-------------|
| `git_tag` | Git tags (releases, versions) |
| `commit` | Git commits |
| `branch` | Branch creation/deletion |
| `merge` | Merge commits |
| `version_bump` | Changes to version files (pyproject.toml, package.json, etc.) |
| `deps_update` | Dependency file changes |
| `license_change` | LICENSE file modifications |
| `ci_config_change` | CI/CD config changes (.github/workflows, .gitlab-ci.yml) |
| `docs_change` | Documentation changes (docs/, *.md) |
| `readme_change` | README file changes |

### GitHub Events (--github)

Requires GitHub API access via `gh` CLI:

| Event Type | Description |
|------------|-------------|
| `github_release` | GitHub releases |
| `pr` | Pull requests |
| `issue` | Issues |
| `workflow_run` | GitHub Actions runs |
| `security_alert` | Dependabot security alerts |
| `repo_rename` | Repository renamed |
| `repo_transfer` | Repository transferred to new owner |
| `repo_visibility` | Public/private visibility changed |
| `repo_archive` | Repository archived/unarchived |
| `deployment` | Deployments (gh-pages, production, etc.) |
| `fork` | Repository forked by another user |
| `star` | Repository starred by a user |

### Registry Events (opt-in)

Detect package publishes across ecosystems:

| Flag | Event Type | Registry |
|------|------------|----------|
| `--pypi` | `pypi_publish` | PyPI (Python) |
| `--cran` | `cran_publish` | CRAN (R) |
| `--npm` | `npm_publish` | npm (JavaScript) |
| `--cargo` | `cargo_publish` | crates.io (Rust) |
| `--docker` | `docker_publish` | Docker Hub |
| `--gem` | `gem_publish` | RubyGems (Ruby) |
| `--nuget` | `nuget_publish` | NuGet (.NET) |
| `--maven` | `maven_publish` | Maven Central (Java) |

## Usage Examples

### Filter by Event Type

```bash
# Only git tags
repoindex events --type git_tag --since 30d

# Only security alerts
repoindex events --type security_alert --github

# Multiple types
repoindex events --type git_tag --type github_release --github
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
# JSONL (default) - one JSON object per line
repoindex events --since 1d

# Pretty table with colors
repoindex events --since 1d --pretty

# Relative timestamps ("2h ago")
repoindex events --since 1d --pretty --relative-time

# Statistics summary
repoindex events --since 7d --stats --pretty
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

## Configuration

Set default event types in `~/.repoindex/config.json`:

```json
{
  "events": {
    "default_types": [
      "git_tag", "commit", "branch", "merge",
      "version_bump", "deps_update",
      "license_change", "ci_config_change", "docs_change", "readme_change"
    ]
  }
}
```

By default, only local (fast) events are enabled. Add remote events explicitly.

## Composing with Other Tools

### Filter with jq

```bash
# Get repos with security alerts
repoindex events --github --type security_alert --since 7d | jq -r '.repo_name' | sort -u

# Count events by type
repoindex events --since 7d | jq -r '.type' | sort | uniq -c | sort -rn
```

### Trigger Actions

```bash
# Post to Slack on new releases
repoindex events --type git_tag --since 1h | while read event; do
  repo=$(echo "$event" | jq -r '.repo_name')
  tag=$(echo "$event" | jq -r '.data.tag')
  curl -X POST "$SLACK_WEBHOOK" -d "{\"text\": \"New release: $repo $tag\"}"
done
```

### Watch Mode

```bash
# Continuous monitoring with custom interval
repoindex events --watch --github --interval 300
```

## Shell Integration

The interactive shell also supports events:

```bash
repoindex shell
> events --since 1d --pretty
> events --github --type github_release
> events --stats
```

See [Shell & VFS](../shell-vfs.md) for more shell commands.
