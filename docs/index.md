# repoindex

**Collection-aware metadata index for git repositories.**

repoindex provides a unified view across all your repositories, enabling queries, organization, and integration with LLM tools like Claude Code.

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
4. **Unix philosophy** - JSONL output, compose with pipes
5. **Read-only events** - Observe and report, don't act

## Quick Start

```bash
# Install
pip install repoindex

# Configure repository directories
repoindex config repos add ~/projects
repoindex config repos add ~/work/**

# See what's happening across your repos
repoindex events --since 7d --pretty

# Query with fuzzy matching
repoindex query "language ~= 'python' and stars > 10"

# Tag repositories for organization
repoindex tag add myproject work/active
repoindex tag add myproject topic:ml

# Interactive shell with VFS
repoindex shell
```

## Key Features

### Event System (30 event types)

Track what's happening across your entire collection:

```bash
# Local events (fast, no API)
repoindex events --since 7d --pretty

# Include GitHub events
repoindex events --github --since 7d

# Include package publishes
repoindex events --pypi --npm --cargo --since 30d

# Watch for new events
repoindex events --watch --github
```

**Event categories:**
- **Local git**: tags, commits, branches, merges
- **Local metadata**: version bumps, dependency updates, license changes, CI config changes
- **GitHub**: releases, PRs, issues, workflows, security alerts, repo renames/transfers, deployments, forks, stars
- **Registries**: PyPI, CRAN, npm, Cargo, Docker, RubyGems, NuGet, Maven

See [Events Overview](events/overview.md) for full documentation.

### Query Language

Find repositories with fuzzy matching:

```bash
# Fuzzy language match (typo-tolerant)
repoindex query "language ~= 'pyton'"

# Multiple conditions
repoindex query "language == 'Python' and stars > 100"

# Check tags
repoindex query "'ml' in tags"

# Complex queries
repoindex query "has_docs and not archived and stars > 10"
```

See [Query Language](catalog-query.md) for syntax details.

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

# Tag via filesystem operations
> cp /repos/newproject /by-tag/work/active

# Run events from shell
> events --github --since 1d
```

See [Shell & VFS](shell-vfs.md) for details.

### Repository Audit

Check repository health:

```bash
# Full audit
repoindex audit

# Auto-fix common issues
repoindex audit --fix

# Security checks
repoindex audit security
```

## Output Formats

All commands output JSONL by default for Unix pipeline composition:

```bash
# Stream to jq
repoindex events --since 7d | jq '.type' | sort | uniq -c

# Filter with grep
repoindex status | grep '"clean": false'

# Human-readable tables
repoindex events --since 7d --pretty
```

## Configuration

Configuration lives in `~/.repoindex/config.json`:

```json
{
  "general": {
    "repository_directories": [
      "~/projects",
      "~/work/**"
    ]
  },
  "events": {
    "default_types": ["git_tag", "commit", "version_bump"]
  },
  "github": {
    "token": "ghp_..."
  }
}
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

- "Which of my repos have security alerts?"
- "What got released this week?"
- "Which repos use Python 3.12?"
- "What needs attention?"

Add repoindex commands to your workflow via CLAUDE.md or use the [MCP server](mcp/overview.md) for structured access.

## Links

- **GitHub**: [github.com/queelius/repoindex](https://github.com/queelius/repoindex)
- **Issues**: [GitHub Issues](https://github.com/queelius/repoindex/issues)
- **PyPI**: [pypi.org/project/repoindex](https://pypi.org/project/repoindex/)

## License

MIT License - see [LICENSE](https://github.com/queelius/repoindex/blob/main/LICENSE)
