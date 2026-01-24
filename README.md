# repoindex

[![PyPI Version](https://img.shields.io/pypi/v/repoindex.svg)](https://pypi.org/project/repoindex/)
[![Python Support](https://img.shields.io/pypi/pyversions/repoindex.svg)](https://pypi.org/project/repoindex/)
[![Test Coverage](https://img.shields.io/badge/coverage-86%25-brightgreen.svg)](https://github.com/queelius/repoindex)
[![Build Status](https://img.shields.io/badge/tests-810%2B%20passing-brightgreen.svg)](https://github.com/queelius/repoindex)
[![License](https://img.shields.io/pypi/l/repoindex.svg)](https://github.com/queelius/repoindex/blob/main/LICENSE)

**A filesystem git catalog for managing your repository collection.**

repoindex provides a unified view across all your local git repositories, enabling queries, organization, and integration with LLM tools like Claude Code.

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
         +-- query       -> filter and search
         +-- status      -> health dashboard
         +-- events      -> what happened
         +-- tags        -> organization
```

## Core Capabilities

- **Repository Discovery** - Find and track repos across directories
- **Tag-Based Organization** - Hierarchical tags for categorization
- **Registry Awareness** - PyPI, CRAN publication status
- **Event Tracking** - New tags, releases, publishes
- **Statistics** - Aggregations across the collection
- **Query Language** - Filter and search with expressions

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
# Initialize configuration
repoindex config init

# Refresh database (required before queries)
repoindex refresh

# Dashboard overview
repoindex status

# Query repositories (pretty table by default)
repoindex query --language python
repoindex query --dirty
repoindex query --tag "work/*"

# Events from last week
repoindex events --since 7d

# Tag management
repoindex tag add myproject topic:ml work/active
repoindex tag tree

# JSONL output for piping
repoindex query --json --language python | jq '.name'
```

## Output Format

Commands output **pretty tables** by default for human readability.
Use `--json` for JSONL output (piping/scripting):

```bash
# Pretty table (default)
repoindex query --language python

# JSONL for piping
repoindex query --json --language python | jq '.name'
repoindex events --json --since 7d | jq '.type' | sort | uniq -c

# Brief mode (just repo names)
repoindex query --brief --dirty
```

## Query Flags

**Local flags** (no external API required):
```bash
repoindex query --dirty              # Uncommitted changes
repoindex query --clean              # No uncommitted changes
repoindex query --language python    # Python repos (detected locally)
repoindex query --recent 7d          # Recent local commits
repoindex query --tag "work/*"       # By tag
repoindex query --no-license         # Missing license file
repoindex query --no-readme          # Missing README
repoindex query --has-citation       # Has citation files (CITATION.cff, .zenodo.json)
repoindex query --has-doi            # Has DOI in citation metadata
repoindex query --has-remote         # Has any remote URL
```

**GitHub flags** (requires `--github` during refresh):
```bash
repoindex query --starred            # Has GitHub stars
repoindex query --private            # Private on GitHub
repoindex query --public             # Public on GitHub
repoindex query --fork               # Is a fork on GitHub
repoindex query --no-fork            # Non-forked repos only
repoindex query --archived           # Archived on GitHub
```

## Query Language

Powerful queries with fuzzy matching:

```bash
# Exact match
repoindex query "language == 'Python'"

# Fuzzy match (handles typos)
repoindex query "language ~= 'pyton'"

# Comparisons
repoindex query "github_stars > 100"

# Boolean combinations
repoindex query "language == 'Python' and tagged('work/*')"

# List membership
repoindex query "'machine-learning' in github_topics"
```

## Event Tracking

Track activity across your repositories:

```bash
# Recent events (default: last 7 days)
repoindex events --since 7d

# Events since specific time
repoindex events --since 24h
repoindex events --since 2024-01-15

# Filter by type
repoindex events --type git_tag
repoindex events --type commit

# Filter by repository
repoindex events --repo myproject

# Summary statistics
repoindex events --stats
```

## Tag System

Tags provide powerful organization:

```bash
# Explicit tags (user-assigned)
repoindex tag add myrepo topic:ml/research work/client/acme

# Query with tags
repoindex query --tag "work/*"
repoindex query "tagged('topic:ml/*')"

# Tag tree view
repoindex tag tree
```

## Refresh Database

```bash
repoindex refresh                  # Smart refresh (changed repos only)
repoindex refresh --full           # Force full refresh
repoindex refresh --github         # Include GitHub metadata
repoindex refresh --pypi           # Include PyPI package status
repoindex refresh --cran           # Include CRAN package status
repoindex refresh --external       # Include all external metadata
repoindex refresh --since 30d      # Events from last 30 days
repoindex sql --reset              # Reset database (then refresh --full)
```

## Additional Commands

### Export (ECHO format)
```bash
repoindex export ~/backup --include-readmes    # Export with READMEs
repoindex export ~/backup --include-events     # Include event history
repoindex export ~/backup --dry-run --pretty   # Preview
```

### Copy (backup/redundancy)
```bash
repoindex copy ~/backup --language python      # Copy Python repos
repoindex copy ~/backup --dirty --dry-run      # Preview dirty repos
```

### Link Trees (symlinks organized by metadata)
```bash
repoindex link tree ~/links/by-tag --by tag        # Organize by tags
repoindex link tree ~/links/by-lang --by language  # Organize by language
repoindex link status ~/links/by-tag               # Check tree health
repoindex link refresh ~/links/by-tag --prune      # Remove broken links
```

### Raw SQL Access
```bash
repoindex sql "SELECT name, language, github_stars FROM repos ORDER BY github_stars DESC LIMIT 10"
repoindex sql --info                          # Database info
repoindex sql --schema                        # Show schema
repoindex sql -i                              # Interactive SQL shell
```

## Configuration

Configuration file: `~/.repoindex/config.yaml`

```yaml
repository_directories:
  - ~/github
  - ~/projects/*/repos

github:
  token: ghp_...

repository_tags:
  /path/to/repo:
    - topic:ml
    - work/active
```

Environment variables:
- `REPOINDEX_CONFIG` - Custom config file path
- `GITHUB_TOKEN` or `REPOINDEX_GITHUB_TOKEN` - GitHub API token

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

## Commands Reference

```
repoindex
├── status              # Dashboard: health overview
├── query               # Human-friendly repo search with flags
├── events              # Query events from database
├── sql                 # Raw SQL queries + database management
├── refresh             # Database sync (repos + events)
├── export              # ECHO format export (durable, self-describing)
├── copy                # Copy repositories with filtering (backup/redundancy)
├── link                # Symlink tree management
│   ├── tree            # Create symlink trees organized by metadata
│   ├── refresh         # Update existing tree (remove broken links)
│   └── status          # Show tree health status
├── tag                 # Organization (add/remove/list/tree)
├── view                # Curated views (list/show/create/delete)
├── config              # Settings (show/repos/init)
├── claude              # Skill management (install/uninstall/show)
└── shell               # Interactive mode
```

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

810+ tests, 86% coverage.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

(c) 2025 [Alex Towell](https://github.com/queelius)
