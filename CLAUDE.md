# CLAUDE.md

## Project Overview

**repoindex is a filesystem git catalog.** It indexes local git directories — the filesystem path IS the canonical identity. External platforms (GitHub, PyPI, CRAN) provide opt-in enrichment metadata, namespaced with prefixes (`github_stars`, `pypi_published`).

**Version**: 1.0.0 | **Design**: [DESIGN.md](DESIGN.md) | **Stability**: [STABILITY.md](STABILITY.md)

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

All `make` targets auto-activate `.venv/`. Test suite has **~2000 tests** in `tests/`.

## Architecture

### Layer Diagram

```
Commands (CLI)  →  Services  →  Database/Infra  →  Domain
commands/            services/    database/          domain/
                                  infra/
```

- **Domain** (`domain/`): Frozen dataclasses (`Repository`, `Tag`, `Event`, `OperationDetail`, `AuditCheck`). No I/O.
- **Database** (`database/`): SQLite via `Database` context manager, schema migrations, CRUD, flag-to-SQL builder (`services/flag_query.py`). File: `~/.repoindex/index.db`.
- **Infrastructure** (`infra/`): Git subprocess wrapper, GitHub API client, Zenodo client, file store.
- **Services** (`services/`): Business logic (discovery, tags, events, auditing, git ops, copy, link, boilerplate, flag_query, tag_derivation).
- **Commands** (`commands/`): Thin Click wrappers. Parse args, call services, format output (pretty tables default, `--json` for JSONL).

### Extension Systems

**Sources** (`sources/`): Single ABC (`MetadataSource`) for all external metadata, discovered from `~/.repoindex/sources/*.py` (module-level `source` attribute). Each source has a `target` of `"repos"` (merged into the `repos` table: github, gitea, citation_cff, keywords, local_assets) or `"publications"` (upserted into the `publications` table: pypi, cran, zenodo, npm, cargo, conda, docker, rubygems, go). Batch sources (zenodo) implement `prefetch()` and return `True` from `detect()` unconditionally. All 14 built-in sources are native `MetadataSource` subclasses; adapters and the old `providers/` package are gone. Sources run in parallel via `ThreadPoolExecutor` during refresh.

**Exporters** (`exporters/`): Output renderers via `Exporter` ABC (`export(repos, output, config)`). Built-in: bibtex, csv, markdown, opml, jsonld, arkiv. User extensions: `~/.repoindex/exporters/*.py` with module-level `exporter` attribute. The `export` command defaults to longecho-compliant arkiv archives; format-based exports are secondary.

Discovery: `discover_sources()` / `discover_exporters()`.

**MCP Server** (`mcp/`): Provides LLM access to the database via 6 tools (`get_manifest`, `get_schema`, `run_sql`, `refresh`, `tag`, `export`). Entry point: `repoindex mcp`. Requires `pip install repoindex[mcp]`.

### Database Usage

```python
from repoindex.database import Database
from repoindex.services.flag_query import build_where_and_params, fetch_repos_by_flags

with Database(config=config, read_only=True) as db:
    db.execute("SELECT name FROM repos WHERE language = ?", ("Python",))

where, params = build_where_and_params(language='Python', dirty=True)
repos = fetch_repos_by_flags(config, language='Python', recent='7d')
```

Schema v8, migrations in `database/schema.py`. See **SQL Data Model** below for table details.

### Other Key Modules

- `cli.py`: Entry point, registers all commands.
- `config.py`: YAML config loading with env var overrides.
- `events.py`: Stateless event scanning from git history.
- `services/flag_query.py`: Direct flag-to-SQL builder (replaces the old DSL).
- `services/tag_derivation.py`: Pure functions deriving tags from repo rows.

## Critical Patterns

### `run_command()` Returns `(stdout, returncode)`

```python
output, rc = run_command("git status", cwd=repo_path, capture_output=True)

# Mocking:
mock_run_command.return_value = ("output", 0)   # Success
mock_run_command.return_value = (None, 1)        # Failure
```

### Repo Resolution in Commands

- `services/flag_query.py`: `build_where_and_params()` and `fetch_repos_by_flags()` compile filter flags directly to SQL (no intermediate DSL).
- `commands/ops.py`: `_resolve_repos()`, `_get_repos_from_query()` fetch filtered repos from DB via `flag_query`.
- `commands/ops.py`: `query_options` decorator provides the four supported filter flags: `--dirty`, `--language`, `--tag`, `--recent`. For anything more expressive, use `repoindex sql` or the MCP `run_sql` tool.

### Output Contract

- **Read commands** (`events`, `show`, `status`, `digest`): Pretty tables by default, `--json` for JSONL.
- **Write commands** (`ops`, `copy`, `link`, `export`): Pretty output by default, `--json` for JSONL.
- Errors to stderr as JSON: `{"error": "msg", "type": "...", "context": {...}}`.
- `--brief` for repo names only (one per line).
- Use `flush=True` on JSONL prints for streaming.

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

## Commands (11 total)

```
repoindex
├── status    # Health dashboard
├── events    # Query git events from database
├── sql       # Raw SQL + DB maintenance (--info, --schema, --reset, --vacuum)
├── refresh   # Sync DB from filesystem (--github, --pypi, --cran, --external)
├── show      # Detailed single-repo view
├── digest    # Summarize recent activity (conventional commit breakdown)
├── export    # Longecho-compliant arkiv archive (default) or format plugins
├── copy      # Copy repos (filter via --dirty/--language/--tag/--recent)
├── link      # Symlink tree management (tree/refresh/status)
├── ops       # Collection operations
│   ├── git          # Multi-repo push/pull/status
│   ├── generate     # Boilerplate (codemeta, license, gitignore, etc.)
│   └── wip-snapshot # Remote-recoverable snapshots of dirty working trees
├── tag       # Tag management (add/remove/list/tree)
├── config    # Settings management
└── mcp       # MCP server (stdio transport, requires repoindex[mcp])
```

`db` command exists as hidden deprecated alias for `sql`.

The old `query` and `view` commands were removed in v0.16.0 along with
the DSL compiler and views.yaml machinery. Use filter flags on `copy`,
`link`, `ops`, and `export`; drop to `repoindex sql` (or the MCP
`run_sql` tool) for anything more expressive.

## Filter Flags

The four filter flags (`--dirty`, `--language`, `--tag`, `--recent`) are
accepted by `copy`, `link`, `ops` subcommands, and `export`. They compose
with implicit AND. Tag values support `*` wildcards. Recent accepts
durations like `7d`, `30d`, `2w`, `6m`, `1y` or an ISO date. Example:

```
repoindex ops wip-snapshot --language python --tag 'work/*' --recent 14d
repoindex copy --dirty --language rust -d /mnt/backup
```

Compilation lives in `services/flag_query.py`. Any filter that flags
can't express belongs in `repoindex sql` or an MCP `run_sql` query.

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

1. **Path is Identity**. Filesystem path defines a repo, not remote URL.
2. **Database-First**. `refresh` populates SQLite; read commands query it (no live scanning).
3. **Unix Philosophy**. Compose via pipes, JSONL streams, errors to stderr.
4. **Namespaced Fields**. `github_stars`, `pypi_published`, `cran_version`.
5. **Two Query Layers**. Flags for humans at the terminal; SQL (direct or via MCP `run_sql`) for anything structured. The MCP is by far the dominant consumer.
6. **Pluggable Extensions**. Single `MetadataSource` ABC and `Exporter` ABC, discovered from `~/.repoindex/sources/*.py` and `~/.repoindex/exporters/*.py`.

## Project Structure

- Entry point: `cli.py:main()` | Build system: **hatchling** (not setuptools)
- User data: `~/.repoindex/`: `config.yaml`, `index.db`, `sources/*.py`, `exporters/*.py`
