---
name: repo-query
description: Natural language repository search — translates questions into repoindex queries
argument-hint: "<question about your repos>"
allowed-tools:
  - Bash
  - Read
---

The user wants to find repositories matching a natural language description.
Translate their question into appropriate `repoindex` CLI commands.

## Translation Guide

Map natural language to repoindex flags and SQL:

| User says | Command |
|-----------|---------|
| "python repos" | `repoindex query --language python` |
| "dirty repos" | `repoindex query --dirty` |
| "repos with stars" | `repoindex query --starred` |
| "recently active" | `repoindex query --recent 7d` |
| "repos without license" | `repoindex query --no-license` |
| "published packages" | `repoindex sql "SELECT r.name, p.registry FROM publications p JOIN repos r ON p.repo_id = r.id WHERE p.published = 1"` |
| "most starred" | `repoindex query --starred --sort stars --limit 10` |
| "repos with DOI" | `repoindex query --has-doi` |
| complex queries | Use `repoindex sql "..."` with appropriate SQL |

## Steps

1. Parse the user's natural language query.
2. Choose the best repoindex command (prefer `query` flags; fall back to `sql` for complex queries).
3. Run the command.
4. Present results clearly. If there are many results, summarize and offer to show more detail.

Always show the command you ran so the user can reuse it.
