# repoindex Architecture Vision

## Overview

repoindex is a comprehensive multi-platform git project management system that helps developers manage the full lifecycle of their projects across multiple platforms - from local development through hosting, distribution, documentation, and promotion.

## Core Philosophy

- **Local-first with remote awareness**: Your local git repositories are the ground truth
- **Unix Philosophy**: Commands do one thing well and compose via JSONL streams  
- **Extensible**: Plugin architecture for providers and custom operations
- **Unified Interface**: One tool to manage projects across all platforms

## JSONL: The Universal Interface

Every repoindex command outputs newline-delimited JSON (JSONL) by default, making it perfect for pipeline composition with standard Unix tools.

### Why JSONL?
- **Streamable**: Process millions of repos without loading all into memory
- **Composable**: Pipe through `jq`, `grep`, `awk`, or custom scripts
- **Parseable**: Every line is valid JSON, easy to process in any language
- **Human-friendly**: Use `--pretty` flag when you want formatted tables

### Pipeline Examples

```bash
# Find Python projects with uncommitted changes
repoindex status | jq 'select(.has_uncommitted_changes == true and .language == "Python")'

# List repos with both GitHub and PyPI presence  
repoindex query --json | jq 'select(.topics | contains(["pypi"]) and .provider == "github")'

# Get total stars across all projects
repoindex query "provider == 'github'" | jq -s 'map(.stargazers_count // 0) | add'

# Find outdated documentation
repoindex metadata refresh | \
  jq 'select(.has_pages == true and (.pushed_at | fromdateiso8601) < (now - 86400 * 30))'

# Export active projects to Hugo
repoindex query "has_uncommitted or open_issues_count > 0" | \
  repoindex export --format hugo --stdin

# Chain operations: find, update, and report
repoindex query --json | \
  jq 'select(.language == "Python" and .topics | contains(["cli"]))' | \
  jq -r '.path' | \
  xargs -I {} repoindex update {} | \
  jq '{repo: .name, status: .update_status}'

# Complex aggregation: repos by language
repoindex query --json | \
  jq -s 'group_by(.language) | 
    map({language: .[0].language, count: length, stars: map(.stargazers_count // 0) | add})'
```

### Structured Output Schema

Every command returns predictable JSON structures:

```json
// repoindex status output
{
  "path": "/home/user/projects/myrepo",
  "name": "myrepo",
  "provider": "github",
  "has_uncommitted_changes": true,
  "branch": "main",
  "language": "Python",
  "stargazers_count": 42
}

// repoindex query output  
{
  "path": "/home/user/projects/myrepo",
  "name": "myrepo",
  "tags": ["lang:python", "tool:cli"],
  "language": "Python",
  "stars": 42
}
```

This enables powerful workflows:
```bash
# Morning routine: check what needs attention
repoindex status | jq -r '
  select(.has_uncommitted_changes or .open_issues_count > 0) | 
  "\(.name): \(
    if .has_uncommitted_changes then "uncommitted changes" else "" end
  ) \(
    if .open_issues_count > 0 then "\(.open_issues_count) issues" else "" end
  )"'
```

### `repoindex` - Repository Operations
**Focus**: Direct operations on git repositories
```bash
repoindex status     # Repository health and metadata
repoindex sync       # Sync with remotes
repoindex clean      # Cleanup operations
repoindex backup     # Archive repositories
repoindex migrate    # Move between services (GitHub -> GitLab)
repoindex health     # Check repository integrity
```

### `ghj` - GitHub Metadata & Search
**Focus**: GitHub API data mining and analysis
```bash
ghj search --query "language:python stars:>100"
ghj analyze --user username
ghj export --format csv
```

### `repodocs` - Documentation Generation
**Focus**: Transform repositories into documentation sites
```bash
repodocs generate --input repos.jsonl --output-dir ./site
repodocs hugo --theme academic
repodocs search-index --engine lunr
```

## Data Flow Architecture

```
┌─────────┐    JSONL    ┌──────────┐    JSONL    ┌──────────┐
│  repoindex  │──────────→  │    jq    │──────────→  │ repodocs │
│ status  │             │ filter   │             │ generate │
└─────────┘             └──────────┘             └──────────┘
     │                       │                       │
     │                       ▼                       ▼
     │                  ┌──────────┐             ┌──────────┐
     │                  │   ghj    │             │   Hugo   │
     │                  │ enrich   │             │   Site   │
     │                  └──────────┘             └──────────┘
     │
     ▼ JSONL
┌──────────┐
│ Custom   │
│ Scripts  │
└──────────┘
```

## repoindex Export Group Proposal

For the export functionality in `repoindex`, focus on repository-level operations:

### Export Operations
```bash
# Repository migration
repoindex export github-to-gitlab --repos repos.jsonl
repoindex export backup --format tar.gz
repoindex export clone-bundle --include-lfs

# Integration exports
repoindex export dashboard --format json    # For external dashboards
repoindex export metrics --format prometheus
repoindex export inventory --format csv
```

### NOT in repoindex export
- Documentation generation (belongs in `repodocs`)
- Markdown conversion (belongs in `repodocs`) 
- Static site generation (belongs in `repodocs`)

## Example Workflow

```bash
# 1. Discover and analyze repositories
repoindex status --recursive > repos.jsonl

# 2. Filter for specific criteria
cat repos.jsonl | jq 'select(.github.on_github and .license.name)' > public-repos.jsonl

# 3. Migrate to GitLab
repoindex export github-to-gitlab --input public-repos.jsonl

# 4. Generate documentation site
repodocs generate --input public-repos.jsonl --template hugo-academic

# 5. Enrich with GitHub API data
ghj enrich --input public-repos.jsonl > enriched-repos.jsonl
```

## Plugin Architecture for repoindex

```python
# repoindex/plugins/export/gitlab.py
@click.command("gitlab")
@click.option("--input", type=click.File('r'))
def export_to_gitlab(input):
    """Export repositories to GitLab."""
    for line in input:
        repo = json.loads(line)
        # Migration logic here
        yield {"repo": repo["name"], "status": "migrated", "url": new_url}
```

## Benefits of This Architecture

1. **Focused Tools**: Each tool has a clear, single responsibility
2. **Composability**: JSONL streaming enables powerful combinations
3. **Extensibility**: Plugin architecture for custom operations
4. **Reusability**: Components can be mixed and matched
5. **Maintenance**: Easier to maintain smaller, focused codebases

## Recommendation

Keep `repoindex` focused on repository operations. Add export functionality for:
- Repository migration between services
- Backup and archival operations
- Integration with external tools (dashboards, monitoring)

Create separate tools for documentation generation and GitHub API analysis.
