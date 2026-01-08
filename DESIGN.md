# repoindex Design Specification

**Version**: 0.10.0 (planned)
**Status**: Approved Specification
**Last Updated**: 2026-01-06

This document captures design decisions, architecture, and requirements for repoindex based on detailed discussion and analysis.

---

## Vision

**repoindex is a collection-aware metadata index for git repositories.**

It provides a unified view across all your repositories, enabling queries, organization, and integration with LLM tools like Claude Code.

```
Claude Code (deep work on ONE repo)
         │
         │ "What else do I have?"
         │ "Which repos need X?"
         ▼
    repoindex (collection awareness)
         │
         ├── query       → filter and search
         ├── status      → health dashboard
         ├── events      → what happened
         └── tags        → organization
```

### Target User

**Power developers** with CLI proficiency managing multiple repositories. Documentation tone and features should assume comfort with Unix tools, SQL, and git internals.

---

## Core Principles

### 1. Collection, Not Content

repoindex knows *about* repositories, not *inside* them.

- ✓ "You have 45 Python repos"
- ✓ "12 are published on PyPI"
- ✓ "3 repos have uncommitted changes"
- ✗ "This function has a bug"
- ✗ "Here's refactored code"

### 2. SQLite as Materialized View

The SQLite database is a **cache over git**, not a separate data store.

- Git repositories are the source of truth
- Database reflects what git shows at scan time
- Events are append-only (INSERT OR IGNORE by event_id)
- Old events persist even if source changes
- Manual reset: `sql --reset` + `refresh --full` when needed

### 3. Three Query Layers

Different tools for different complexity levels:

| Layer | Usage | Example |
|-------|-------|---------|
| **Flags (80%)** | Common filters, zero learning curve | `--dirty --language python` |
| **DSL (15%)** | Complex logic, readable power | `has_event('commit', since='7d') and stars > 5` |
| **SQL (5%)** | Full power, edge cases | `SELECT * FROM repos JOIN events...` |

### 4. Unix Philosophy

- Compose via pipes: JSONL output streams to jq, grep, etc.
- Pretty output by default for interactive use
- `--json` flag for machine-readable JSONL
- Errors to stderr, data to stdout

---

## Architecture

### Layered Structure

```
┌─────────────────────────────────────────────────────┐
│                    CLI Layer                         │
│  repoindex/commands/*.py                            │
│  - Parse arguments (Click)                          │
│  - Call services                                    │
│  - Format output (pretty or JSONL)                  │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│                  Service Layer                       │
│  repoindex/services/*.py                            │
│  - RepositoryService: discover, status, filter      │
│  - TagService: add, remove, query tags              │
│  - EventService: scan events                        │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│                  Domain Layer                        │
│  repoindex/domain/*.py                              │
│  - Repository, Tag, Event dataclasses               │
│  - Pure functions, no I/O                           │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│               Infrastructure Layer                   │
│  repoindex/infra/*.py                               │
│  - GitClient, GitHubClient                          │
│  - FileStore, Database                              │
└─────────────────────────────────────────────────────┘
```

### Database Schema

Core tables with **changes from current**:

```sql
-- KEEP: repos, tags, events, publications
-- REMOVE: dependencies (not implemented, out of scope)
-- REMOVE: repo_snapshots (abandoned feature)
-- ADD: scan_errors (track failed repos)

CREATE TABLE scan_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT,
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Full-Text Search

Keep FTS5 index on repos with **full README content**:

```sql
CREATE VIRTUAL TABLE repos_fts USING fts5(
    name,
    description,
    readme_content,
    content='repos',
    content_rowid='id'
);
```

Storage impact: ~1-5MB for 143 repos. Acceptable.

---

## Commands (11 total)

### Core Commands

| Command | Purpose | Output Default |
|---------|---------|----------------|
| `status` | Health dashboard | Pretty table |
| `query` | Filter repositories | Pretty table |
| `events` | Query event history | Pretty table |
| `sql` | Raw SQL + DB maintenance | Pretty table |
| `refresh` | Sync database from git | Progress output |

### Organization Commands

| Command | Purpose |
|---------|---------|
| `tag add/remove/list/tree` | Manage tags |
| `view list/show/create/delete` | Saved queries |
| `config show/repos/init` | Configuration |

### Integration Commands

| Command | Purpose |
|---------|---------|
| `claude install/uninstall/show` | Claude Code skill |
| `shell` | Interactive VFS navigation |

### Removed Commands

- **MCP server**: Delete `repoindex/mcp/` entirely. CLI is sufficient for Claude Code integration via the skill.

---

## Query System

### Flag-Based Queries (Primary Interface)

```bash
# Common filters (AND together)
repoindex query --dirty              # Uncommitted changes
repoindex query --clean              # Clean repos
repoindex query --language python    # By language
repoindex query --recent 7d          # Recent activity
repoindex query --starred            # Has GitHub stars
repoindex query --tag "work/*"       # By tag pattern
repoindex query --no-license         # Missing license
repoindex query --no-readme          # Missing README

# Combine flags (implicit AND)
repoindex query --dirty --language python --recent 7d
```

### DSL Queries (Power Users)

```bash
# Boolean logic
repoindex query "language == 'Python' and stars > 10"
repoindex query "dirty or recent('7d')"
repoindex query "not archived and has_ci"

# Functions
repoindex query "has_event('commit', since='30d')"
repoindex query "tagged('work/*')"
repoindex query "updated_since('7d')"

# Ordering and limits
repoindex query "language == 'Python' order by stars desc limit 10"

# View references
repoindex query "@python-active and is_clean"

# Explain mode (NEW)
repoindex query --explain "language == 'Python' and stars > 10"
# Shows: SELECT * FROM repos WHERE language = ? AND stars > ? [params: Python, 10]
```

### Raw SQL (Edge Cases)

```bash
# Direct queries
repoindex sql "SELECT name, stars FROM repos ORDER BY stars DESC LIMIT 10"

# Interactive shell
repoindex sql -i

# DB maintenance (NEW)
repoindex sql --info       # Path, size, version
repoindex sql --schema     # Show tables
repoindex sql --stats      # Row counts, sizes
repoindex sql --integrity  # Check for corruption
repoindex sql --vacuum     # Optimize/compact
repoindex sql --reset      # Drop and recreate
```

---

## Tag System

### Tag Sources

Tags come from three sources, all coexisting:

| Source | Examples | Editable |
|--------|----------|----------|
| **User** (explicit) | `work/active`, `priority:high` | Yes |
| **System** (implicit) | `lang:python`, `dir:github`, `repo:myproject` | No |
| **Provider** (GitHub) | `topic:machine-learning`, `license:mit` | No |

### Reserved Namespaces

System-only prefixes that users cannot create:

- `lang:` - Auto-detected language
- `dir:` - Parent directory name
- `repo:` - Repository name
- `type:` - Project type (node, python, rust)
- `ci:` - CI system detected
- `has:` - Feature detection (readme, license, tests)

### Tag Operations

```bash
# Add/remove user tags
repoindex tag add myproject work/active topic:ml
repoindex tag remove myproject work/active

# Query by tag
repoindex tag list                    # All tags
repoindex tag list -t "work/*"        # Repos with tag
repoindex tag tree                    # Hierarchical view
```

---

## Event System

### Event Model

Events are **append-only observations** of git history:

- Scanned from git on `refresh`
- Deduplicated by stable `event_id`
- Never deleted (historical record)
- Time-bounded by `--since` on refresh

### Event Types

Currently implemented:
- `git_tag` - Tag created
- `commit` - Commit pushed

### Event Queries

```bash
# Query events (pretty by default)
repoindex events                      # Last 7 days
repoindex events --since 30d          # Custom window
repoindex events --type git_tag       # Filter by type
repoindex events --repo myproject     # Filter by repo
repoindex events --stats              # Summary statistics
repoindex events --json               # JSONL for piping
```

---

## Status Dashboard

The `status` command shows a **full dashboard** with:

### Counts
- Total repositories, events, tags
- Database size, last refresh time

### Health Warnings
- Repos with uncommitted changes (dirty)
- Repos not scanned recently (stale)
- Scan errors from last refresh

### Action Suggestions
- "Run `refresh` to update database" if stale
- "Run `refresh --github` to fetch GitHub metadata"

---

## Refresh Behavior

### Default (Smart Refresh)

```bash
repoindex refresh
```

- Scans repos where `.git/index` mtime changed since last scan
- Inserts new events (INSERT OR IGNORE)
- Updates repo metadata

### Full Refresh

```bash
repoindex refresh --full
```

- Rescans all repos regardless of mtime
- Does NOT delete existing events

### With External Sources

```bash
# Explicit opt-in (config can set defaults)
repoindex refresh --github    # Fetch GitHub metadata
repoindex refresh --pypi      # Check PyPI publication
repoindex refresh --cran      # Check CRAN publication

# Combined
repoindex refresh --github --pypi --since 30d
```

### Failure Behavior

- **GitHub unreachable**: Fail fast if `--github` specified
- **Individual repo errors**: Log warning, continue, track in `scan_errors` table
- **Rate limit hit**: Proactive warning showing remaining quota

---

## Configuration

### Format

**YAML only** (remove JSON support for simplicity):

```yaml
# ~/.repoindex/config.yaml

general:
  repository_directories:
    - ~/github
    - ~/projects/*/repos

github:
  token: ${GITHUB_TOKEN}  # Environment variable reference
  rate_limit:
    max_retries: 3
    max_delay_seconds: 60

refresh:
  default_since: 30d
  enable_pypi: false
  enable_cran: false

repository_tags:
  /home/user/github/myproject:
    - work/active
    - priority:high
```

### Environment Variables

- `REPOINDEX_CONFIG` - Config file path
- `GITHUB_TOKEN` or `REPOINDEX_GITHUB_TOKEN` - GitHub API token

### Path Handling

- Non-existent paths: **Warn once**, continue
- Glob patterns supported: `~/github/**`

---

## Claude Code Integration

### Skill Management

```bash
repoindex claude install [--global]   # Install skill
repoindex claude uninstall [--global] # Remove skill
repoindex claude show                 # Show status
repoindex claude content              # Print skill content
```

### Skill Generation

Skill content should be **generated from CLI introspection**:

- Extract commands and options from Click
- Build examples dynamically
- Include version number
- Warn and confirm before overwriting existing skill

### Skill Location

- Global: `~/.claude/commands/repoindex.md`
- Local: `./.claude/commands/repoindex.md`

---

## Views Feature

### Purpose

Save named queries for reuse.

### Storage

Views store **DSL expressions** (not raw SQL):

```bash
repoindex view create python-active "language == 'Python' and has_event('commit', since='30d')"
repoindex view list
repoindex view show python-active
repoindex view delete python-active
```

### Usage

Reference views in queries with `@`:

```bash
repoindex query "@python-active and is_clean"
```

### Future Enhancement

Consider making views composable (views referencing other views) and/or parameterized (view templates).

---

## Shell (VFS Interface)

### Status

**Needs redesign** - keep but lower priority.

### Current Concept

Interactive navigation of repository collection:

```
/repos/           # All repositories
/repos/myproject/ # Single repo metadata
/tags/            # Tag hierarchy
/events/          # Recent events
```

### Planned Improvements

- Better navigation UX
- Integration with query system
- Possibly FUSE mount for filesystem access

---

## Output Formats

### Default: Pretty Tables

```bash
repoindex query --dirty
# Shows formatted table with columns
```

### JSONL for Piping

```bash
repoindex query --json --dirty | jq '.name'
```

### Brief Mode

```bash
repoindex query --brief --dirty
# Just repo names, one per line
```

---

## Error Handling

### Scan Errors

Tracked in `scan_errors` table:

```sql
CREATE TABLE scan_errors (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    error_type TEXT NOT NULL,    -- 'permission', 'corrupt', 'not_git'
    error_message TEXT,
    scanned_at TIMESTAMP
);
```

### Display

- Show error count in `status` dashboard
- List errors with `repoindex sql "SELECT * FROM scan_errors"`

---

## Removed/Deprecated

### Removed in v0.10.0

| Item | Reason |
|------|--------|
| MCP server (`repoindex/mcp/`) | CLI sufficient, complexity not justified |
| Dependencies table | Not implemented, out of scope |
| Repo snapshots table | Abandoned feature |
| JSON config support | YAML only for simplicity |

### Deprecated (Hidden)

| Item | Replacement |
|------|-------------|
| `db` command | Use `sql --info`, `sql --reset`, etc. |

---

## Development Guidelines

### Testing

- 604+ tests in `tests/` directory
- Use pyfakefs for filesystem mocking
- Run with coverage: `pytest --cov=repoindex --cov-report=html`
- Target: >86% coverage

### Adding Commands

1. Create `repoindex/commands/your_command.py`
2. Use service layer for business logic
3. Register in `repoindex/cli.py`
4. Write tests in `tests/test_your_command.py`
5. Update skill content generation

### Output Pattern

```python
@click.command()
@click.option('--json', 'output_json', is_flag=True)
def command(output_json):
    results = service.get_data()

    if output_json:
        for item in results:
            print(json.dumps(item), flush=True)
    else:
        render.table(list(results))
```

---

## Version History

| Version | Changes |
|---------|---------|
| 0.9.2 | Documentation updates, pretty output default |
| 0.9.1 | Bug fixes (status counts, events --pretty) |
| 0.9.0 | CLI simplification, SQLite database |
| 0.10.0 | (Planned) This specification |

---

## Open Questions

Items for future consideration:

1. **View composition**: Allow views to reference other views?
2. **View parameters**: Template-style views with `$1`, `$2` placeholders?
3. **Shell redesign**: What would a better VFS interface look like?
4. **FTS queries**: How to expose full-text search in DSL/flags?
