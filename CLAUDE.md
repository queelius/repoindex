# CLAUDE.md

## Project Overview

**repoindex is a filesystem git catalog.** It indexes local git directories — the filesystem path IS the canonical identity. External platforms (GitHub, PyPI, CRAN) provide opt-in enrichment metadata, namespaced with prefixes (`github_stars`, `pypi_published`).

**Version**: 0.13.0 | **Design**: [DESIGN.md](DESIGN.md)

## Development Commands

```bash
make install                    # Create .venv, install deps + package in dev mode
make test                       # Run tests (auto-activates .venv)
make build                      # Build wheel + sdist
make clean                      # Remove .venv, build artifacts, caches

# Direct pytest (activate venv first: source .venv/bin/activate)
pytest --maxfail=3 -v                               # Quick run
pytest tests/test_core.py -v                         # Single file
pytest -k "test_status" -v                           # Pattern match
pytest --cov=repoindex --cov-report=html             # Coverage (ALWAYS after changes)
```

All `make` targets auto-activate `.venv/`. Test suite has **1600+ tests** in `tests/`.

## Architecture

### Layer Diagram

```
Commands (CLI)  →  Services  →  Database/Infra  →  Domain
commands/            services/    database/          domain/
                                  infra/
```

- **Domain** (`domain/`): Frozen dataclasses — `Repository`, `Tag`, `Event`, `OperationDetail`, `AuditCheck`. No I/O.
- **Database** (`database/`): SQLite via `Database` context manager, query compiler (DSL to SQL), schema migrations, CRUD. File: `~/.repoindex/index.db`.
- **Infrastructure** (`infra/`): Git subprocess wrapper, GitHub API client, Zenodo client, file store.
- **Services** (`services/`): Business logic — discovery, tags, events, auditing, git ops, copy, link, boilerplate, views.
- **Commands** (`commands/`): Thin Click wrappers. Parse args, call services, format output (pretty tables default, `--json` for JSONL).

### Extension Systems

**Providers** (`providers/`): Registry detection via `RegistryProvider` ABC (`detect`, `check`, `match`, `prefetch`). Built-in: pypi, cran, zenodo, npm, cargo, conda, docker, rubygems, go. User extensions: `~/.repoindex/providers/*.py` with module-level `provider` attribute.

**Exporters** (`exporters/`): Output renderers via `Exporter` ABC (`export(repos, output, config)`). Built-in: bibtex, csv, markdown, opml, jsonld, arkiv. User extensions: `~/.repoindex/exporters/*.py` with module-level `exporter` attribute. The `export` command defaults to longecho-compliant arkiv archives; format-based exports are secondary.

Discovery: `discover_providers(only=['pypi','npm'])` / `discover_exporters()`.

**MCP Server** (`mcp/`): Provides LLM access to the database via 4 tools (`get_manifest`, `get_schema`, `run_sql`, `refresh`). Entry point: `repoindex mcp`. Requires `pip install repoindex[mcp]`.

### Database Usage

```python
from repoindex.database import Database, compile_query, QueryCompileError

with Database(config=config, read_only=True) as db:
    db.execute("SELECT name FROM repos WHERE language = ?", ("Python",))

compiled = compile_query("language == 'Python' and github_stars > 10")
# compiled.sql, compiled.params
```

Schema v5, migrations in `database/schema.py`. See **SQL Data Model** below for table details.

### Other Key Modules

- `cli.py` — Entry point, registers all commands
- `config.py` — YAML config loading with env var overrides
- `events.py` — Stateless event scanning from git history
- `query.py` — Query language parser with `rapidfuzz` fuzzy matching

## Critical Patterns

### `run_command()` Returns `(stdout, returncode)`

```python
output, rc = run_command("git status", cwd=repo_path, capture_output=True)

# Mocking:
mock_run_command.return_value = ("output", 0)   # Success
mock_run_command.return_value = (None, 1)        # Failure
```

### Repo Resolution in Commands

- `commands/query.py`: `_build_query_from_flags()` — converts CLI flags to query
- `commands/ops.py`: `_resolve_repos()`, `_get_repos_from_query()` — fetch filtered repos from DB
- `commands/ops.py`: `query_options` decorator — shared `--dirty`, `--language`, `--tag`, `--recent` flags (4 essential shorthands; other filters via DSL)

### Output Contract

- **Read commands** (`query`, `events`, `show`): Pretty tables by default, `--json` for JSONL
- **Write commands** (`ops`, `copy`, `link`, `export`): Pretty output by default, `--json` for JSONL
- Errors to stderr as JSON: `{"error": "msg", "type": "...", "context": {...}}`
- `--brief` for repo names only (one per line)
- Use `flush=True` on JSONL prints for streaming

### Adding New Commands

1. Create `commands/your_command.py` with Click handler
2. Add service method in `services/` if needed
3. Register in `cli.py` via `cli.add_command(handler, name='name')`
4. Write tests in `tests/test_your_command.py`

### Testing Patterns

- Services: mock infrastructure with `MagicMock`, use `tmp_path` for filesystem
- CLI: `click.testing.CliRunner` — mock `_resolve_repos` to skip DB
- Domain: direct instantiation, no mocking needed
- `pyfakefs` available for complex filesystem scenarios

## Commands (16 total)

```
repoindex
├── status    # Health dashboard
├── query     # Filter repos (DSL expressions + 4 shorthand flags)
├── events    # Query git events from database
├── sql       # Raw SQL + DB maintenance (--info, --schema, --reset, --vacuum)
├── refresh   # Sync DB from filesystem (--github, --pypi, --cran, --external)
├── show      # Detailed single-repo view
├── digest    # Summarize recent activity (conventional commit breakdown)
├── export    # Longecho-compliant arkiv archive (default) or format plugins
├── copy      # Copy repos with query filtering
├── link      # Symlink tree management (tree/refresh/status)
├── ops       # Collection operations
│   ├── git   # Multi-repo push/pull/status
│   └── generate  # Boilerplate (codemeta, license, gitignore, etc.)
├── tag       # Tag management (add/remove/list/tree)
├── view      # Saved named queries
├── config    # Settings management
├── mcp       # MCP server (stdio transport, requires repoindex[mcp])
└── shell     # Interactive VFS navigation
```

`db` command exists as hidden deprecated alias for `sql`.

## Query DSL

Operators: `==`, `!=`, `~=` (fuzzy), `=~` (regex), `>`, `<`, `>=`, `<=`, `contains`, `in`
Boolean: `and`, `or`, `not`. Dot notation: `license.key`. View refs: `@viewname`.

```
"language == 'Python' and github_stars > 10"
"language ~= 'pyton'"                         # fuzzy match
"'ml' in github_topics"                       # list membership
"@python-active and is_clean"                 # view reference
```

Field mappings and compilation in `database/query_compiler.py`. In-memory matching in `query.py`.

## SQL Data Model

- **repos**: Identity (`path` UNIQUE), git status, metadata, license, citation, GitHub fields (`github_*` prefixed).
- **events**: `repo_id` FK, `event_id` UNIQUE, type (`git_tag`/`commit`/`branch`/`merge`), timestamp, ref, message, author, metadata JSON.
- **tags**: `repo_id` FK, tag, source (`user`/`implicit`/`github`).
- **publications**: `repo_id` FK CASCADE, registry (`pypi`/`cran`/`zenodo`/`npm`/`cargo`/`docker`), package_name (may differ from repo name), version, published flag, downloads, doi.
- **scan_errors**: Failed repos during refresh.
- **refresh_log**: Tracks refresh runs for digest/staleness.
- **repos_fts**: FTS5 index on name, description, readme_content.

Common SQL patterns (`repoindex sql "..."`):
```sql
SELECT name, github_stars FROM repos WHERE github_stars > 0 ORDER BY github_stars DESC LIMIT 10
SELECT r.name, COUNT(*) n FROM events e JOIN repos r ON e.repo_id=r.id WHERE e.type='commit' AND e.timestamp > datetime('now','-30 days') GROUP BY r.id ORDER BY n DESC
SELECT r.name, p.registry, p.package_name FROM publications p JOIN repos r ON p.repo_id=r.id WHERE p.published=1
```

## Configuration

YAML only (`~/.repoindex/config.yaml`; legacy JSON auto-migrated). Override path with `REPOINDEX_CONFIG`.

Key sections: `repository_directories` (glob patterns), `github.token` (or `GITHUB_TOKEN`), `repository_tags`, `author` (name, alias, email, orcid, github — used by audit and boilerplate).

## Design Principles

1. **Path is Identity** — filesystem path defines a repo, not remote URL
2. **Database-First** — `refresh` populates SQLite; read commands query it (no live scanning)
3. **Unix Philosophy** — compose via pipes, JSONL streams, errors to stderr
4. **Namespaced Fields** — `github_stars`, `pypi_published`, `cran_version`
5. **Three Query Layers** — DSL primary, 4 shorthand flags, raw SQL for power users
6. **Pluggable Extensions** — provider/exporter ABCs with `~/.repoindex/` user directories

## Project Structure

- Entry point: `cli.py:main()` | Build system: **hatchling** (not setuptools)
- User data: `~/.repoindex/` — `config.yaml`, `index.db`, `providers/*.py`, `exporters/*.py`
