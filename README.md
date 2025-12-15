# repoindex

[![PyPI Version](https://img.shields.io/pypi/v/repoindex.svg)](https://pypi.org/project/repoindex/)
[![Python Support](https://img.shields.io/pypi/pyversions/repoindex.svg)](https://pypi.org/project/repoindex/)
[![Test Coverage](https://img.shields.io/badge/coverage-86%25-brightgreen.svg)](https://github.com/queelius/repoindex)
[![Build Status](https://img.shields.io/badge/tests-604%20passing-brightgreen.svg)](https://github.com/queelius/repoindex)
[![License](https://img.shields.io/pypi/l/repoindex.svg)](https://github.com/queelius/repoindex/blob/main/LICENSE)

**A collection-aware metadata index for git repositories.**

repoindex provides a unified view across all your repositories, enabling queries, organization, and integration with LLM tools like Claude Code.

## Philosophy

repoindex knows *about* your repos (metadata, tags, status), while tools like Claude Code work *inside* them (editing, generating). Together they provide full portfolio awareness.

```
Claude Code (deep work on ONE repo)
         |
         |  "What else do I have?"
         |  "Which repos need X?"
         v
    repoindex (collection awareness)
         |
         +-- repo://...     -> what exists
         +-- tags://...     -> organization
         +-- stats://...    -> aggregations
         +-- events://...   -> what happened
```

## Core Capabilities

- **Repository Discovery** - Find and track repos across directories
- **Tag-Based Organization** - Hierarchical tags for categorization
- **Registry Awareness** - PyPI, CRAN publication status
- **Event Tracking** - New tags, releases, publishes
- **Statistics** - Aggregations across the collection
- **Query Language** - Filter and search with expressions
- **MCP Server** - LLM integration endpoint for Claude Code

## Installation

```bash
pip install repoindex
```

Or from source:

```bash
git clone https://github.com/queelius/repoindex.git
cd repoindex
make install
```

## Quick Start

```bash
# Configure repository directories
repoindex config generate

# List all repositories
repoindex list

# Check repository status
repoindex status -r --pretty

# Tag repositories for organization
repoindex tag add myproject topic:ml work/active

# Query repositories
repoindex query "language == 'Python' and 'ml' in tags"

# Scan for recent events (releases, tags)
repoindex events --since 7d --pretty

# View statistics
repoindex stats --groupby language
```

## Output Format

All commands output **JSONL** (newline-delimited JSON) by default, making them perfect for Unix pipelines:

```bash
# Find repos with uncommitted changes
repoindex status | jq 'select(.status.clean == false)'

# Count repos by language
repoindex list | jq -s 'group_by(.language) | map({lang: .[0].language, count: length})'

# Get all Python repos with ML tags
repoindex query "language == 'Python'" | jq 'select(.tags | contains(["topic:ml"]))'
```

Use `--pretty` for human-readable table output.

## MCP Server (Claude Code Integration)

repoindex includes an MCP (Model Context Protocol) server for integration with LLM tools:

```bash
# Start MCP server
repoindex mcp serve
```

### Resources (read-only data)
- `repo://list` - All repositories with basic metadata
- `repo://{name}` - Full metadata for one repository
- `repo://{name}/status` - Git status for one repository
- `tags://list` - All tags
- `tags://tree` - Hierarchical tag view
- `stats://summary` - Overall statistics
- `events://recent` - Recent events

### Tools (actions)
- `repoindex_tag(repo, tag)` - Add tag to repository
- `repoindex_untag(repo, tag)` - Remove tag from repository
- `repoindex_query(expression)` - Query repositories
- `repoindex_refresh(repo?)` - Refresh metadata
- `repoindex_stats(groupby)` - Get statistics

## Tag System

Tags provide powerful organization:

```bash
# Explicit tags (user-assigned)
repoindex tag add myrepo topic:ml/research work/client/acme

# Implicit tags (auto-generated)
# - repo:name, dir:parent, lang:python, owner:username
# - status:clean/dirty, visibility:public/private
# - stars:10+, stars:100+, stars:1000+

# Query with tags
repoindex list -t "lang:python" -t "topic:ml/*"

# Tag tree view
repoindex tag tree
```

## Query Language

Powerful queries with fuzzy matching:

```bash
# Exact match
repoindex query "language == 'Python'"

# Fuzzy match (handles typos)
repoindex query "language ~= 'pyton'"

# Comparisons
repoindex query "stars > 100"

# Boolean combinations
repoindex query "language == 'Python' and 'ml' in tags"

# List membership
repoindex query "'machine-learning' in topics"
```

## Event Scanning

Track activity across your repositories:

```bash
# Recent events (default: last 7 days)
repoindex events --pretty

# Events since specific time
repoindex events --since 24h
repoindex events --since 2024-01-15

# Filter by type
repoindex events --type git_tag
repoindex events --type commit

# Continuous monitoring
repoindex events --watch --interval 300
```

## Configuration

Configuration file: `~/.repoindex/config.json`

```json
{
  "general": {
    "repository_directories": [
      "~/github",
      "~/projects/*/repos"
    ]
  },
  "github": {
    "token": "ghp_..."
  },
  "repository_tags": {
    "/path/to/repo": ["topic:ml", "work/active"]
  }
}
```

Environment variables:
- `REPOINDEX_CONFIG` - Custom config file path
- `REPOINDEX_GITHUB_TOKEN` - GitHub API token
- `REPOINDEX_METADATA_PATH` - Custom metadata store path

## Architecture

repoindex follows a clean layered architecture:

```
Commands (CLI)  ->  Services  ->  Domain Objects
     |                |                |
   Parse args    Business logic   Pure data
   Format output No side effects  Immutable
   Handle I/O    Return generators Consistent schema
```

### Layers

- **Domain** - Immutable data objects (Repository, Tag, Event)
- **Infrastructure** - External system clients (GitClient, GitHubClient, FileStore)
- **Services** - Business logic (RepositoryService, TagService, EventService)
- **Commands** - Thin CLI wrappers that use services

## Development

```bash
# Setup
make install

# Run tests
make test

# Run with coverage
pytest --cov=repoindex --cov-report=html

# Build docs
make docs
```

604 tests, 86% coverage.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

(c) 2025 [Alex Towell](https://github.com/queelius)
