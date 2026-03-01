# MCP Server + Arkiv Export Design

**Date**: 2026-02-28
**Status**: Approved

## Overview

Two features for repoindex v0.12.0:

1. **MCP Server** — stdio transport, 3 tools (`get_manifest`, `get_schema`, `run_sql`) for LLM access to the repoindex database
2. **Arkiv Export** — `repoindex export arkiv <dir>` produces a full arkiv archive (JSONL + README.md + schema.yaml)

## Feature 1: MCP Server

### Architecture

```
Claude Code / LLM client
    ↕ stdio (JSON-RPC)
repoindex/mcp/server.py
    ↓
repoindex.database.Database (read_only=True)
    ↓
~/.repoindex/index.db
```

### Tools

#### `get_manifest()`

No parameters. Returns an overview of the repoindex database for the LLM to understand what data is available.

Response shape:
```json
{
  "description": "repoindex filesystem git catalog",
  "database": "~/.repoindex/index.db",
  "tables": {
    "repos": {"row_count": 143, "description": "Repository metadata"},
    "events": {"row_count": 2841, "description": "Git events (commits, tags)"},
    "tags": {"row_count": 312, "description": "Repository tags"},
    "publications": {"row_count": 28, "description": "Package registry publications"}
  },
  "summary": {
    "languages": {"Python": 45, "R": 12, "JavaScript": 8, ...},
    "last_refresh": "2026-02-28T10:00:00Z"
  }
}
```

#### `get_schema(table?)`

Optional `table` parameter (string). Returns SQL DDL for schema introspection.

- No argument: returns all CREATE TABLE statements
- With argument: returns DDL + column descriptions for that table

#### `run_sql(query)`

Required `query` parameter (string). Executes read-only SQL.

- Only SELECT and WITH statements allowed
- Returns JSON array of row objects
- Errors return structured error message
- Row limit: 500 rows default (prevent accidental full table dumps)

### Implementation

**File**: `repoindex/mcp/server.py`

Uses the `mcp` Python SDK (`FastMCP` convenience class):

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("repoindex")

@mcp.tool()
def get_manifest() -> dict: ...

@mcp.tool()
def get_schema(table: str | None = None) -> dict: ...

@mcp.tool()
def run_sql(query: str) -> dict: ...
```

**CLI entry point**: `repoindex mcp` subcommand starts the server.

**Dependency**: Add `mcp>=1.0.0` to pyproject.toml optional dependencies:
```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0.0"]
```

### Configuration

Users add to their Claude Code MCP config:

```json
{
  "mcpServers": {
    "repoindex": {
      "command": "repoindex",
      "args": ["mcp"]
    }
  }
}
```

## Feature 2: Arkiv Export

### Architecture

```
repoindex export arkiv <output-dir>
    ↓
ArkivArchiveExporter (new class)
    ↓
output-dir/
├── README.md          # YAML frontmatter + description
├── schema.yaml        # Metadata key schema
├── repos.jsonl        # Repo records (inode/directory)
└── events.jsonl       # Event records (text/plain)
```

### Command

```bash
# Full archive export
repoindex export arkiv ~/exports/repoindex/

# With query filters (same flags as query command)
repoindex export arkiv ~/exports/python-repos/ --language python

# Dry run
repoindex export arkiv ~/exports/test/ --dry-run
```

### Implementation

**File**: `repoindex/commands/export.py`

New `export` command group with `arkiv` subcommand. Reuses the existing `_repo_to_arkiv()` and `_event_to_arkiv()` converters from `exporters/arkiv.py`.

Additionally:
- Generates `README.md` with YAML frontmatter per arkiv spec
- Generates `schema.yaml` by scanning the output JSONL

The existing `repoindex render arkiv` continues to work for stdout piping. The new `repoindex export arkiv <dir>` is the structured archive version.

### README.md Template

```yaml
---
name: repoindex export
description: Git repository metadata from repoindex
datetime: 2026-02-28
generator: repoindex v0.12.0
contents:
  - path: repos.jsonl
    description: Repository metadata (inode/directory records)
  - path: events.jsonl
    description: Git events — commits and tags (text/plain records)
---

# repoindex Export

This archive contains git repository metadata exported from repoindex.

## Collections

- **repos.jsonl** — Repository identity, git status, language, license, GitHub metadata, citations
- **events.jsonl** — Git commits and tags with messages and timestamps
```

### Schema Discovery

Use arkiv's own `discover_schema()` on the generated JSONL files, or compute schema inline since we know the structure. Write to `schema.yaml` per arkiv spec.

## Testing

### MCP Server Tests

- `tests/test_mcp.py`: Test each tool function directly (no stdio transport)
- Mock `Database` to return canned data
- Verify `run_sql` rejects non-SELECT queries
- Verify `get_manifest` returns expected structure
- Verify `get_schema` with and without table argument

### Arkiv Export Tests

- `tests/test_export_arkiv.py`: Test archive generation
- Verify README.md has correct YAML frontmatter
- Verify schema.yaml has correct metadata keys
- Verify repos.jsonl and events.jsonl are valid JSONL
- Verify each record follows arkiv universal record format
- Verify query filter integration (--language, --dirty, etc.)

## Dependencies

Add to pyproject.toml:
```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0.0"]
```

The arkiv export does NOT depend on the `arkiv` package — it generates the format directly using the existing converter functions. Schema discovery can use stdlib JSON scanning.
