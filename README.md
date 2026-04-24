# repoindex

[![PyPI Version](https://img.shields.io/pypi/v/repoindex.svg)](https://pypi.org/project/repoindex/)
[![Python Support](https://img.shields.io/pypi/pyversions/repoindex.svg)](https://pypi.org/project/repoindex/)
[![License](https://img.shields.io/pypi/l/repoindex.svg)](https://github.com/queelius/repoindex/blob/main/LICENSE)

**A filesystem git catalog for your repository collection.**

> The filesystem is where your work lives. repoindex is where your work
> becomes legible.

repoindex indexes local git directories. The filesystem path IS the
canonical identity. External platforms (GitHub, PyPI, CRAN, Zenodo, npm,
Cargo, and others) provide opt-in enrichment as namespaced columns
(`github_stars`, `pypi_version`, `citation_doi`). The SQLite database at
`~/.repoindex/index.db` is a materialized view of the filesystem plus
external state. `refresh` is the only writer; every other command reads.

The primary consumer is an LLM using the MCP server. The CLI is the
human secondary interface.

## Install

```bash
pip install repoindex         # CLI only
pip install repoindex[mcp]    # CLI + MCP server
```

From source:

```bash
git clone https://github.com/queelius/repoindex.git
cd repoindex
make install
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

The server exposes six tools. SQL is the API:

| Tool | Purpose |
|------|---------|
| `get_manifest()` | Tables, row counts, last refresh, language breakdown |
| `get_schema(table?)` | SQL DDL for the whole database or one table |
| `run_sql(query)` | Read-only SQL (SELECT / WITH), up to 500 rows |
| `refresh(github?, pypi?, cran?, external?, full?)` | Trigger a refresh |
| `tag(repo, action, tag)` | Add / remove / list user tags |
| `export(output_dir, language?, dirty?, tag?, recent?)` | Longecho-compliant arkiv archive |

The assistant can answer any collection-level question by:

1. `get_schema()` to see what tables exist.
2. Compose the SQL query it needs.
3. `run_sql(query)` to get results.

No pre-decided "list repos by language" / "get starred repos" / "find
dirty repos" tools. The schema is self-describing; SQL does the rest.

Install the Claude Code plugin to wire the server automatically:

```bash
/plugin marketplace add queelius/claude-code-marketplace
/plugin install repoindex@queelius
```

## CLI

| Command | Purpose |
|---------|---------|
| `status` | Dashboard: counts, health, last refresh, next-action hints |
| `show <repo>` | Detailed view of a single repository |
| `events` | Query git events (commits, tags, branches, merges, releases) |
| `digest` | Summarize recent activity by repo |
| `sql` | Raw SQL + DB maintenance (`--info`, `--schema`, `--reset`, `--vacuum`) |
| `refresh` | Sync DB from filesystem (`--github`, `--pypi`, `--external`, `--full`) |
| `export` | Longecho-compliant arkiv archive (default) or format plugins |
| `copy` | Copy filtered repos to a destination directory |
| `link` | Symlink tree management (`tree`, `refresh`, `status`) |
| `ops` | Collection operations (`git`, `generate`, `github`, `audit`, `mirror`, `wip-snapshot`) |
| `tag` | Tag management (`add`, `remove`, `list`, `tree`, `move`) |
| `config` | Settings management |
| `mcp` | Start the MCP server |

### Filter Flags

Four shorthands available on every operation command:

```bash
repoindex export -o out/ --dirty
repoindex export -o out/ --language python
repoindex export -o out/ --tag "work/*"
repoindex export -o out/ --recent 7d
```

For anything more expressive, use SQL.

### SQL for Everything Else

```bash
repoindex sql "SELECT name, github_stars FROM repos WHERE github_stars > 0 ORDER BY github_stars DESC LIMIT 10"
repoindex sql "SELECT r.name, p.package_name, p.current_version
               FROM publications p JOIN repos r ON p.repo_id = r.id
               WHERE p.registry = 'pypi' AND p.published = 1"
repoindex sql --info
repoindex sql --schema
```

Schema documented in `CLAUDE.md` and inline via `repoindex sql --schema`.
The schema is part of the 1.x stable surface; see `STABILITY.md`.

### Events

```bash
repoindex events --since 7d
repoindex events --type git_tag --since 30d
repoindex events --repo myproject
repoindex events --stats
repoindex events --json --since 7d | jq -r '.type' | sort | uniq -c
```

### Ops

```bash
# Multi-repo git operations
repoindex ops git push --dry-run
repoindex ops git pull --language python
repoindex ops git status --dirty

# Metadata audit
repoindex ops audit --language python
repoindex ops audit --category essentials --severity critical

# Generate boilerplate files
repoindex ops generate license --license mit --dry-run
repoindex ops generate codemeta --language python --dry-run
repoindex ops generate gitignore --lang python --dry-run

# GitHub operations (requires gh CLI)
repoindex ops github set-topics --from-pyproject --language python --dry-run

# Redundancy
repoindex ops mirror --to codeberg --language python --dry-run

# Dirty-tree snapshots
repoindex ops wip-snapshot --dry-run
```

### Export

```bash
# Default: longecho-compliant arkiv archive with HTML browser
repoindex export -o ~/archives/repos/

# Format plugins
repoindex export csv -o repos.csv
repoindex export bibtex --language python > refs.bib
repoindex export --list-formats
```

See `docs/export.md`.

## Refresh

```bash
repoindex refresh                   # Smart refresh (only changed repos)
repoindex refresh --full            # Force full rescan
repoindex refresh --github          # GitHub metadata
repoindex refresh --source pypi     # One registry source
repoindex refresh --external        # All external sources
repoindex refresh --since 30d       # Events from last 30 days
repoindex sql --reset               # Drop and recreate (then refresh --full)
```

Built-in metadata sources: GitHub, Gitea, CITATION.cff, project keywords,
local asset detection, PyPI, CRAN, npm, Cargo, Conda, Docker, RubyGems,
Go, Zenodo.

Add your own: drop a Python file in `~/.repoindex/sources/` exporting a
module-level `source = MetadataSource(...)`. The `MetadataSource` ABC is
part of the stable surface.

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

```bash
repoindex config show
repoindex config get author.name
repoindex config set author.name "Your Name"
repoindex config unset refresh.external_sources.github
```

Environment variables:

- `REPOINDEX_CONFIG`: override the config file path
- `GITHUB_TOKEN`: used if `github.token` is not set

## Architecture

```
Commands (CLI, Click)
  repoindex/commands/*.py
         |
         v
Services (business logic)
  repoindex/services/*.py
         |
         +---> Database (SQLite, schema migrations, query helpers)
         +---> Infrastructure (git, GitHub, Zenodo, PyPI, files)
         +---> Domain (frozen dataclasses)
```

- **Domain**: `Repository`, `Tag`, `Event`, `AuditCheck`, `OperationDetail`. No I/O.
- **Database**: `~/.repoindex/index.db`. Read-only enforced at connection level.
- **Infrastructure**: everything that reaches outside the process.
- **Services**: business logic. Internal, not a public API.
- **Commands**: thin Click wrappers. Pretty output default, `--json` for JSONL.

See `DESIGN.md` for the full philosophy and `STABILITY.md` for the
backward-compatibility contract.

## Development

```bash
make install               # Create .venv and install in dev mode
make test                  # Run tests
pytest --cov=repoindex     # With coverage
make build                 # Wheel and sdist
```

1700+ tests in `tests/`. Target coverage above 86%.

## Documentation

- `CLAUDE.md`: current architecture and operational reference
- `DESIGN.md`: philosophy and architecture rationale
- `STABILITY.md`: v1.0 backward-compatibility contract
- `docs/index.md`: docs landing page
- `docs/events.md`, `docs/export.md`, `docs/ops.md`: per-command references

## Author

**Alexander Towell** (Alex Towell) /
[GitHub](https://github.com/queelius) /
[ORCID](https://orcid.org/0000-0001-6443-9897) /
[PyPI](https://pypi.org/user/queelius) /
[Blog](https://metafunctor.com)

Contact: [lex@metafunctor.com](mailto:lex@metafunctor.com)

## License

MIT. See [LICENSE](LICENSE).
