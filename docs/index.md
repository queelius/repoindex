# repoindex

**A filesystem git catalog for your repository collection.**

repoindex provides a unified view across all your local git repositories, enabling queries, organization, and integration with LLM tools like Claude Code.

## Philosophy

```
Claude Code (deep work on ONE repo)
         |
         | "What else do I have?"
         | "Which repos need X?"
         v
      repoindex (collection awareness)
         |
         +-- status      -> what exists
         +-- tags        -> organization
         +-- query       -> discovery
         +-- events      -> what happened
```

**Core Principles:**

1. **Collection, not content** - Know *about* repos, not *inside* them
2. **Metadata, not manipulation** - Track state, don't edit files
3. **Index, not IDE** - We're the catalog, not the workbench
4. **Unix philosophy** - Pretty tables by default, JSONL for pipes
5. **Read-only events** - Observe and report, don't act

## Quick Start

```bash
# Install
pip install repoindex

# Initialize configuration
repoindex config init

# Refresh database (required before queries)
repoindex refresh

# Dashboard overview
repoindex status

# Query with convenience flags
repoindex query --dirty                    # Uncommitted changes
repoindex query --language python          # Python repos
repoindex query --recent 7d                # Recent commits
repoindex query --tag "work/*"             # By tag

# Tag repositories for organization
repoindex tag add myproject work/active
repoindex tag add myproject topic:ml

# See what happened
repoindex events --since 7d
```

## Key Features

### Query System

Find repositories with convenience flags or the query DSL:

```bash
# Convenience flags (pretty table by default)
repoindex query --dirty                    # Uncommitted changes
repoindex query --language python          # Python repos
repoindex query --starred                  # Has GitHub stars (requires --github during refresh)
repoindex query --has-citation             # Has citation files
repoindex query --has-doi                  # Has DOI in citation

# Query DSL
repoindex query "language == 'Python' and github_stars > 10"
repoindex query "language ~= 'pyton'"      # Fuzzy matching (typo-tolerant)
repoindex query "tagged('work/*')"         # Query by tag

# JSONL output for piping
repoindex query --json --language python | jq '.name'
```

See [Query Language](catalog-query.md) for syntax details.

### Event System

Track what's happening across your entire collection:

```bash
# Events from database (pretty table by default)
repoindex events --since 7d

# Filter by type
repoindex events --type git_tag --since 30d
repoindex events --type commit --since 7d

# Filter by repository
repoindex events --repo myproject

# Summary statistics
repoindex events --stats

# JSONL for piping
repoindex events --json --since 7d | jq '.type' | sort | uniq -c
```

**Event categories:**
- **Local git**: tags, commits, branches, merges

See [Events Overview](events/overview.md) for full documentation.

### Tag System

Organize repos with hierarchical tags:

```bash
# Add tags
repoindex tag add myproject work/active
repoindex tag add myproject topic:ml/research

# List by tag
repoindex tag list -t "work/*"

# Show tag hierarchy
repoindex tag tree
```

Tags support:
- Hierarchical paths: `work/active`, `topic/ml/research`
- Key:value format: `lang:python`, `status:maintained`
- Implicit tags: Auto-generated from metadata (`repo:name`, `dir:parent`)

### Interactive Shell

VFS-based shell for navigating your collection:

```bash
repoindex shell

# Navigate like a filesystem
> cd /by-tag/work/active
> ls
myproject  otherproject

# Run events from shell
> events --since 1d
```

See [Shell & VFS](shell-vfs.md) for details.

## Output Formats

Commands output pretty tables by default. Use `--json` for JSONL:

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

## Refresh Database

```bash
repoindex refresh                  # Smart refresh (changed repos only)
repoindex refresh --full           # Force full refresh
repoindex refresh --github         # Include GitHub metadata
repoindex refresh --pypi           # Include PyPI package status
repoindex refresh --cran           # Include CRAN package status
repoindex refresh --external       # Include all external metadata
repoindex refresh --since 30d      # Events from last 30 days
```

## Configuration

Configuration lives in `~/.repoindex/config.yaml`:

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

Or use environment variables:
- `REPOINDEX_GITHUB_TOKEN`
- `REPOINDEX_CONFIG`

## Documentation

- **[Getting Started](getting-started.md)** - Installation and first steps
- **[Usage Guide](usage.md)** - Core commands and configuration
- **[Events](events/overview.md)** - Event system documentation
- **[Query Language](catalog-query.md)** - Query syntax and examples
- **[Shell & VFS](shell-vfs.md)** - Interactive shell
- **[Changelog](changelog.md)** - Release history

## For Claude Code Users

repoindex complements Claude Code by providing collection awareness. While Claude Code works deeply within a single repository, repoindex answers questions like:

- "Which of my repos have uncommitted changes?"
- "What got released this week?"
- "Which repos use Python?"
- "What needs attention?"

Install the skill for easy access:

```bash
repoindex claude install --global
```

Then use `/repoindex` in Claude Code conversations.

## Links

- **GitHub**: [github.com/queelius/repoindex](https://github.com/queelius/repoindex)
- **Issues**: [GitHub Issues](https://github.com/queelius/repoindex/issues)
- **PyPI**: [pypi.org/project/repoindex](https://pypi.org/project/repoindex/)

## License

MIT License - see [LICENSE](https://github.com/queelius/repoindex/blob/main/LICENSE)
