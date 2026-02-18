# repoindex — Claude Code Plugin

Collection-aware repository intelligence for Claude Code. Query, analyze, and
maintain your git repository collection from within Claude Code conversations.

**Requires**: [repoindex](https://github.com/queelius/repoindex) CLI installed and on PATH.

## Components

| Type | Name | Purpose |
|------|------|---------|
| Skill | `repoindex` | CLI reference — query flags, SQL data model, operations |
| Skill | `repo-polish` | Audit-driven release preparation workflow |
| Command | `/repo-status` | Quick collection dashboard |
| Command | `/repo-query` | Natural language repo search |
| Agent | `repo-explorer` | Deep collection analysis and reporting |

## Install

```bash
# Local — point Claude Code at the plugin directory
claude plugin add /path/to/repoindex/claude-plugin

# Or symlink into your plugins workspace
ln -s /path/to/repoindex/claude-plugin ~/github/alex-claude-plugins/repoindex
```

## Prerequisites

```bash
pip install repoindex
repoindex refresh          # Populate the database
repoindex refresh --github # Optional: add GitHub metadata
```

## License

MIT
