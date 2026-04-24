# repoindex

**A filesystem git catalog for your repository collection.**

repoindex indexes local git directories. The filesystem path IS the canonical
identity. External platforms (GitHub, PyPI, CRAN, npm, Cargo, Zenodo, and
more) provide opt-in enrichment as namespaced columns (`github_stars`,
`pypi_version`). The SQLite database at `~/.repoindex/index.db` is a
materialized view over the filesystem plus external state.

The primary consumer is an LLM using the MCP server. The CLI is the human
secondary interface.

## Install

```bash
pip install repoindex         # CLI only
pip install repoindex[mcp]    # CLI + MCP server
```

## Quick Start

```bash
repoindex config init          # Create ~/.repoindex/config.yaml
repoindex refresh              # Populate the database
repoindex status               # Dashboard overview
```

## MCP Server (Primary Interface)

```bash
repoindex mcp                  # stdio transport for Claude / MCP-aware agents
```

Six tools:

- `get_manifest`: tables, row counts, last refresh, language breakdown
- `get_schema(table?)`: SQL DDL for the whole database or one table
- `run_sql(query)`: read-only SQL (SELECT / WITH), up to 500 rows
- `refresh(github?, pypi?, cran?, external?, full?)`: trigger a refresh
- `tag(repo, action, tag)`: add / remove / list user tags
- `export(output_dir, language?, dirty?, tag?, recent?)`: arkiv archive

SQL is the API. Schema is self-describing via `get_schema`, then the
assistant composes whatever query it needs.

## CLI Commands

| Command | Purpose |
|---------|---------|
| `status` | Dashboard: counts, health, last refresh, action suggestions |
| `show <repo>` | Detailed view of one repository |
| `events` | Query git events from the database |
| `digest` | Recent-activity summary by repo, with commit-type breakdown |
| `sql` | Raw SQL + DB maintenance (`--info`, `--schema`, `--reset`, `--vacuum`) |
| `refresh` | Sync DB from filesystem (`--github`, `--pypi`, `--external`, `--full`) |
| `export` | Longecho-compliant arkiv archive (default) or format plugins |
| `copy` | Copy repos with filtering (backup or redundancy) |
| `link` | Symlink tree management (`tree`, `refresh`, `status`) |
| `ops` | Collection operations (`git`, `generate`, `github`, `audit`, `mirror`, `wip-snapshot`) |
| `tag` | Tag management (`add`, `remove`, `list`, `tree`, `move`) |
| `config` | Settings management (`show`, `get`, `set`, `unset`, `init`, `repos`) |
| `mcp` | Start the MCP server (stdio transport) |

See `ops.md`, `events.md`, `export.md` for per-command reference.

## Filter Flags

Four shorthands available on operation commands (`copy`, `export`, `ops *`,
`link tree`):

```bash
repoindex export -o out/ --dirty
repoindex export -o out/ --language python
repoindex export -o out/ --tag "work/*"
repoindex export -o out/ --recent 7d
```

For anything more expressive, use SQL.

## SQL for Everything Else

```bash
repoindex sql "SELECT name, github_stars FROM repos WHERE github_stars > 0 ORDER BY github_stars DESC LIMIT 10"
repoindex sql "SELECT r.name FROM publications p JOIN repos r ON p.repo_id=r.id WHERE p.registry='pypi' AND p.published=1"
repoindex sql --info
repoindex sql --schema
```

The schema is documented in `CLAUDE.md` and inline via `repoindex sql --schema`.

## Refresh

```bash
repoindex refresh                    # Smart refresh (only changed repos)
repoindex refresh --full             # Force full rescan
repoindex refresh --github           # GitHub metadata
repoindex refresh --source pypi      # One registry source
repoindex refresh --external         # All external sources
repoindex refresh --since 30d        # Events from last 30 days
```

Built-in metadata sources: GitHub, Gitea, CITATION.cff, project keywords,
local asset detection, PyPI, CRAN, npm, Cargo, Conda, Docker, RubyGems, Go,
Zenodo.

User sources: drop a Python file in `~/.repoindex/sources/` exporting a
module-level `source = MetadataSource(...)`.

## Configuration

```yaml
# ~/.repoindex/config.yaml
repository_directories:
  - ~/github/**
  - ~/work

github:
  token: ghp_...

mirrors:
  - name: codeberg
    url_template: "https://codeberg.org/queelius/{repo}.git"

author:
  name: "Alexander Towell"
  alias: "Alex Towell"
  email: "lex@metafunctor.com"
  orcid: "0000-0001-6443-9897"

repository_tags:
  /home/user/github/myproject:
    - work/active
    - topic:ml
```

Environment variables:

- `REPOINDEX_CONFIG`: override the config path
- `GITHUB_TOKEN`: used if `github.token` is not set

Config commands:

```bash
repoindex config show            # Pretty YAML
repoindex config show --json     # JSON
repoindex config get author.name
repoindex config set author.name "Your Name"
repoindex config unset refresh.external_sources.github
```

## Tags

Hierarchical tags. Three sources, all stored in one `tags` table:

- `user`: added explicitly via `repoindex tag add` (stable)
- `implicit`: derived during refresh (`lang:python`, `dir:github`, `repo:NAME`, `has:readme`, `license:mit`)
- `github`: derived from GitHub topics (`topic:machine-learning`)

```bash
repoindex tag add myrepo work/active topic:ml
repoindex tag remove myrepo work/active
repoindex tag list -t "work/*"
repoindex tag tree
```

The set of implicit and GitHub-derived tags can grow across releases; user
tags are stable (see `STABILITY.md`).

## Claude Code Plugin

```bash
/plugin marketplace add queelius/claude-code-marketplace
/plugin install repoindex@queelius
```

The plugin configures the MCP server and provides repoindex-aware
skills.

## Design

- `DESIGN.md`: architecture and philosophy (path is identity, database as
  materialized view, two query layers, MCP as primary consumer)
- `STABILITY.md`: backward-compatibility contract for v1.0

## Links

- [GitHub](https://github.com/queelius/repoindex) / [PyPI](https://pypi.org/project/repoindex/) / [Issues](https://github.com/queelius/repoindex/issues)
- Author: **Alexander Towell** ([Alex Towell](https://metafunctor.com)) /
  [ORCID](https://orcid.org/0000-0001-6443-9897) /
  [lex@metafunctor.com](mailto:lex@metafunctor.com)
- MIT License
