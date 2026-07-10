# CLAUDE.md

## Project Overview

**repoindex is a filesystem git catalog.** It indexes local git directories: the filesystem path IS the canonical identity. External platforms (GitHub, Gitea, PyPI, CRAN, Zenodo) provide opt-in enrichment metadata.

**Version**: 2.0.0 | **Design**: [DESIGN.md](DESIGN.md) | **Stability**: [STABILITY.md](STABILITY.md)

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

All `make` targets auto-activate `.venv/`. Test suite has **~2050 tests** in `tests/`.

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

**Sources** (`sources/`): Three-level type hierarchy rooted at `Source`:

```
Source (ABC)
├── LocalScanner       reads files in the repo; populates repos table
└── RemoteSource       network-backed, has auth
    ├── GitForge       hosts git repos; populates repos table; has write actions
    └── Registry       package registry; populates publications table
```

Source modules live in three subdirectories:

* `sources/scanners/`: citation_cff, keywords, local_assets.
* `sources/forges/`: github, gitea.
* `sources/registries/`: pypi, cran, zenodo, npm, cargo, conda, docker, rubygems, go.

User extension dirs follow the same shape: `~/.repoindex/sources/scanners/*.py`, `~/.repoindex/sources/forges/*.py`, `~/.repoindex/sources/registries/*.py`. Each module exports a module-level `source` attribute that is a subclass instance.

`GitForge` carries optional capability methods (default raises `NotImplementedError`): `enumerate_user_repos`, `set_topics`, `set_description`, `set_archived`, `set_visibility`, `set_default_branch`, `enable_pages`. The cross-platform `ops set-*` commands look up a repo's `forge_id` and dispatch to the matching GitForge.

Batch sources (zenodo) implement `prefetch()` and return `True` from `detect()` unconditionally. Sources run in parallel via `ThreadPoolExecutor` during refresh.

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

Schema v10, migrations in `database/schema.py` (the DB is a cache: a version bump drops and rebuilds all tables). See **SQL Data Model** below for table details.

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
- CLI: `click.testing.CliRunner`, mock `_resolve_repos` to skip DB
- Domain: direct instantiation, no mocking needed
- `pyfakefs` available for complex filesystem scenarios

## Commands (13 total)

```
repoindex
├── status             Health dashboard
├── events             Query events from database (--forge for forge events only)
├── sql                Raw SQL + DB maintenance (--info, --schema, --reset, --vacuum)
├── refresh            Sync DB from filesystem (--github, --pypi, --cran, --external, --forge-events)
├── show               Detailed single-repo view
├── digest             Summarize recent activity (conventional commit breakdown)
├── export             Longecho-compliant arkiv archive (default) or format plugins
├── copy               Copy repos (filter via --dirty/--language/--tag/--recent)
├── link               Symlink tree management (tree/refresh/status)
├── ops                Collection operations
│   ├── audit              Quality / metadata audit
│   ├── git                Multi-repo push/pull/status
│   ├── generate           Boilerplate (codemeta, license, gitignore, etc.)
│   ├── wip-snapshot       Remote-recoverable snapshots of dirty working trees
│   ├── mirror             Push --mirror to forges with role: mirror
│   ├── sync               Clone repos you own on enumerable forges
│   ├── set-topics         Cross-platform topic setter (GitForge dispatch)
│   ├── set-description    Cross-platform description setter
│   ├── set-archived       Cross-platform archived flag
│   ├── set-visibility     Cross-platform public/private toggle
│   ├── set-default-branch Cross-platform default branch
│   └── set-pages          Cross-platform Pages enable
├── tag                Tag management (add/remove/list/tree/move)
├── config             Settings management
└── mcp                MCP server (stdio transport, requires repoindex[mcp])
```

`db` command exists as hidden deprecated alias for `sql`.

The `query` and `view` commands were removed in v0.16.0 (DSL and views.yaml machinery). The `ops github` subgroup and `ops generate gh-pages` were removed in v2.0.0; use the cross-platform `ops set-*` commands instead, which dispatch via `forge_id` to whichever GitForge owns the repo.

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

- **repos**: Identity (`path` UNIQUE), git status, metadata, license, citation, plus unified forge fields populated by the active GitForge: `forge_id`, `forge_host`, `forge_owner`, `forge_name`, `forge_description`, `topics` (JSON array as TEXT), `is_archived`, `is_fork`, `is_private`, `pages_url`, `default_branch`, `stars`, `forks_count`, `watchers`, `open_issues`, `has_issues`, `has_wiki`, `has_pages`, `forge_created_at`, `forge_updated_at`, `forge_pushed_at`.
- **events**: `repo_id` FK, `event_id` UNIQUE, type (git: `git_tag`/`commit`/`branch`/`merge`; forge, opt-in via `refresh --forge-events`: `release`/`pull_request`/`issue`), timestamp, ref, message, author, metadata JSON.
- **tags**: `repo_id` FK, tag, source (`user`/`implicit`/`forge`/`pyproject`/`pypi`/`cran`/`zenodo`/...).
- **publications**: `repo_id` FK CASCADE, registry (`pypi`/`cran`/`zenodo`/`npm`/`cargo`/`docker`/...), package_name (may differ from repo name), version, published flag, downloads, doi (version-specific), concept_doi (version-independent; what citations prefer).
- **scan_errors**: Failed repos during refresh.
- **refresh_log**: Tracks refresh runs for digest/staleness.
- **repos_fts**: FTS5 index on name, description, readme_content.

Common SQL patterns (`repoindex sql "..."`):
```sql
SELECT name, forge_id, stars FROM repos WHERE stars > 0 ORDER BY stars DESC LIMIT 10
SELECT r.name, COUNT(*) n FROM events e JOIN repos r ON e.repo_id=r.id WHERE e.type='commit' AND e.timestamp > datetime('now','-30 days') GROUP BY r.id ORDER BY n DESC
SELECT r.name, p.registry, p.package_name FROM publications p JOIN repos r ON p.repo_id=r.id WHERE p.published=1
SELECT name, forge_id, is_archived FROM repos WHERE is_archived = 1
```

## Configuration

YAML only (`~/.repoindex/config.yaml`; legacy JSON auto-migrated). Override path with `REPOINDEX_CONFIG`.

Key sections: `repository_directories` (glob patterns), `exclude_directories` (subtree exclusion list), `forges` (per-platform config: source_id, host, role, token_env, url_template, user, sync_into), `repository_tags`, `author` (name, alias, email, orcid, github; used by audit and boilerplate).

Example `forges:` section:

```yaml
forges:
  github:
    token_env: GITHUB_TOKEN
    role: primary
  codeberg:
    source_id: gitea
    host: codeberg.org
    role: mirror
    token_env: CODEBERG_TOKEN
    url_template: "https://codeberg.org/queelius/{repo}.git"
```

## Design Principles

1. **Path is Identity**. Filesystem path defines a repo, not remote URL.
2. **Database-First**. `refresh` populates SQLite; read commands query it (no live scanning).
3. **Unix Philosophy**. Compose via pipes, JSONL streams, errors to stderr.
4. **Unified Forge Fields**. Repo metadata uses generic columns (`stars`, `topics`, `is_archived`, ...) with `forge_id` for provenance. Publications stay namespaced by registry.
5. **Two Query Layers**. Flags for humans at the terminal; SQL (direct or via MCP `run_sql`) for anything structured. The MCP is the dominant consumer.
6. **Pluggable Extensions**. `Source` family (`LocalScanner` / `GitForge` / `Registry`) and `Exporter` ABC, discovered from `~/.repoindex/sources/{scanners,forges,registries}/*.py` and `~/.repoindex/exporters/*.py`.

## Project Structure

- Entry point: `cli.py:main()` | Build system: **hatchling** (not setuptools)
- User data: `~/.repoindex/`: `config.yaml`, `index.db`, `sources/{scanners,forges,registries}/*.py`, `exporters/*.py`
