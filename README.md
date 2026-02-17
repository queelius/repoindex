# repoindex

[![PyPI Version](https://img.shields.io/pypi/v/repoindex.svg)](https://pypi.org/project/repoindex/)
[![Python Support](https://img.shields.io/pypi/pyversions/repoindex.svg)](https://pypi.org/project/repoindex/)
[![Test Coverage](https://img.shields.io/badge/coverage-86%25-brightgreen.svg)](https://github.com/queelius/repoindex)
[![Build Status](https://img.shields.io/badge/tests-1477%2B%20passing-brightgreen.svg)](https://github.com/queelius/repoindex)
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
         +-- ops         -> collection operations
         +-- render      -> export formats
```

## Core Capabilities

- **Repository Discovery** - Find and track repos across directories
- **Tag-Based Organization** - Hierarchical tags for categorization
- **Registry Awareness** - PyPI, CRAN, npm, Cargo, Conda, Docker, RubyGems, Go, Zenodo (extensible)
- **Event Tracking** - New tags, releases, publishes (28 event types)
- **Statistics** - Aggregations across the collection
- **Query Language** - Filter and search with expressions
- **Collection Operations** - Multi-repo git push/pull, file generation, GitHub ops
- **Metadata Audit** - Check repos across essentials, development, discoverability, documentation
- **Render/Export Formats** - BibTeX, CSV, Markdown, OPML, JSON-LD, Arkiv via extensible exporter system

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

### Ops (collection operations)
```bash
# Multi-repo git operations
repoindex ops git push --dry-run
repoindex ops git pull --language python
repoindex ops git status --dirty

# Metadata audit
repoindex ops audit --language python
repoindex ops audit --category essentials --severity critical

# Generate boilerplate files
repoindex ops generate license --license mit --no-license --dry-run
repoindex ops generate codemeta --language python --dry-run
repoindex ops generate gitignore --lang python --dry-run

# GitHub operations (requires gh CLI)
repoindex ops github set-topics --from-pyproject --language python --dry-run
```

### Render (export formats)
```bash
# BibTeX for references
repoindex render bibtex --language python > refs.bib

# CSV for spreadsheets
repoindex render csv --starred > repos.csv

# Markdown reports
repoindex render markdown --recent 30d > recent.md

# OPML for feeds
repoindex render opml > repos.opml

# JSON-LD for linked data
repoindex render jsonld --has-doi > repos.jsonld

# Arkiv universal records (repos + events as JSONL)
repoindex render arkiv --language python > repos.arkiv.jsonl

# List available formats
repoindex render --list-formats
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

author:
  name: "Alex Towell"
  email: "alex@example.com"
  orcid: "0000-0001-6443-9897"
```

Configuration commands:
```bash
repoindex config set author.name "Your Name"
repoindex config get author
repoindex config unset refresh.providers.npm
repoindex config show           # Pretty YAML output
repoindex config show --json    # JSON output
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
├── refresh             # Database sync (repos + events + providers)
├── render              # Export as BibTeX, CSV, Markdown, OPML, JSON-LD, Arkiv

├── copy                # Copy repositories with filtering (backup)
├── link                # Symlink tree management
│   ├── tree            # Create symlink trees organized by metadata
│   ├── refresh         # Update existing tree (remove broken links)
│   └── status          # Show tree health status
├── ops                 # Collection-level operations
│   ├── git             # Multi-repo git push/pull/status
│   ├── audit           # Metadata completeness audit
│   ├── generate        # Boilerplate file generation
│   └── github          # GitHub write ops (topics, description)
├── tag                 # Organization (add/remove/list/tree)
├── view                # Curated views (list/show/create/delete)
├── config              # Settings (show/set/get/unset/repos/init)
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

1477+ tests, 86% coverage.

## Author

**Alexander Towell** (Alex Towell) — [GitHub](https://github.com/queelius) / [ORCID](https://orcid.org/0000-0001-6443-9897) / [PyPI](https://pypi.org/user/queelius) / [Blog](https://metafunctor.com)

## License

MIT License - see [LICENSE](LICENSE) for details.
