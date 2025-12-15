# MCP Server

repoindex provides an MCP (Model Context Protocol) server for integration with LLM tools.

!!! note "For Claude Code Users"
    If you're using Claude Code, you may find direct CLI access more powerful than MCP.
    Claude Code can run `repoindex events --pretty` directly and compose with other tools.
    See the [CLI usage guide](../usage.md) for patterns.

## Overview

The MCP server exposes repoindex functionality through:

- **Resources**: Read-only data access (repos, tags, stats, events)
- **Tools**: Actions (tag, untag, query, refresh)

## Starting the Server

```bash
repoindex mcp serve
```

## Resources

| Resource URI | Description |
|--------------|-------------|
| `repo://` | Repository collection |
| `tags://` | Tag hierarchy |
| `stats://` | Aggregate statistics |
| `events://` | Recent events |

## Tools

| Tool | Description |
|------|-------------|
| `repoindex_tag` | Add a tag to a repository |
| `repoindex_untag` | Remove a tag from a repository |
| `repoindex_query` | Query repositories with expression |
| `repoindex_refresh` | Refresh repository metadata |
| `repoindex_stats` | Get collection statistics |

## Configuration

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "repoindex": {
      "command": "repoindex",
      "args": ["mcp", "serve"]
    }
  }
}
```

## When to Use MCP vs CLI

**Use MCP when:**
- Your LLM client doesn't have shell access
- You need structured resource discovery
- Working with non-Claude LLM tools

**Use CLI when:**
- You have direct shell access (Claude Code)
- You want to compose with Unix tools (`jq`, `grep`, etc.)
- You need the full power of JSONL streaming
- You're automating with scripts or cron

## CLI Equivalent Commands

Most MCP operations have CLI equivalents:

| MCP Tool | CLI Equivalent |
|----------|----------------|
| `repoindex_tag` | `repoindex tag add <repo> <tag>` |
| `repoindex_untag` | `repoindex tag remove <repo> <tag>` |
| `repoindex_query` | `repoindex query "<expression>"` |
| `repoindex_refresh` | `repoindex metadata refresh` |
| `repoindex_stats` | `repoindex metadata stats` |

For event streaming:
```bash
# CLI approach (more flexible)
repoindex events --github --since 7d | jq '.type'
```
