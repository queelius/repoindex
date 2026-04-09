# v0.15.0: Unified MetadataSource, MCP Parity, Tag Derivation, Gitea Provider

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify PlatformProvider + RegistryProvider into a single MetadataSource ABC, add MCP tools for full LLM parity (tag, export), auto-derive tags from all metadata sources, and implement GiteaPlatformProvider to validate the abstraction.

**Architecture:**

One ABC (`MetadataSource`) replaces both `PlatformProvider` and `RegistryProvider`. Each source has a `target` field ("repos" or "publications") that tells the refresh loop where to store its output. Local file parsers (CITATION.cff, keywords, assets) become MetadataSources too : same interface, same discovery, same activation. After all sources run, a tag derivation step populates the `tags` table from all metadata (topics, keywords, language, boolean flags, publication status). The MCP server gains `tag` and `export` tools for full CLI/MCP parity.

**Tech Stack:** Python stdlib, existing provider infrastructure, MCP Python SDK

---

## Design Summary

### MetadataSource ABC (replaces PlatformProvider + RegistryProvider)

```python
class MetadataSource(ABC):
    source_id: str = ""     # "github", "pypi", "citation_cff"
    name: str = ""          # "GitHub", "Python Package Index"
    target: str = "repos"   # "repos" or "publications"
    batch: bool = False     # True for Zenodo-style prefetch

    @abstractmethod
    def detect(self, repo_path, repo_record=None) -> bool:
        """Does this source apply to this repo?"""

    @abstractmethod
    def fetch(self, repo_path, repo_record=None, config=None) -> Optional[dict]:
        """Fetch metadata. Returns dict of fields, or None."""

    def prefetch(self, config) -> None:
        """Optional batch pre-fetch (Zenodo-style)."""
```

### Sources (all implement MetadataSource)

| Source | target | Detection | Fetch returns |
|--------|--------|-----------|---------------|
| `github` | repos | github.com in remote_url | `{github_stars, github_owner, ...}` |
| `gitea` | repos | configurable hosts (codeberg.org default) | `{gitea_stars, gitea_forks, ...}` |
| `pypi` | publications | pyproject.toml/setup.py | `{registry: "pypi", version, ...}` |
| `cran` | publications | DESCRIPTION | `{registry: "cran", version, ...}` |
| `zenodo` | publications | batch ORCID | `{registry: "zenodo", doi, ...}` |
| `npm` | publications | package.json | `{registry: "npm", version, ...}` |
| `cargo` | publications | Cargo.toml | `{registry: "cargo", version, ...}` |
| `citation_cff` | repos | CITATION.cff exists | `{citation_doi, citation_authors, ...}` |
| `keywords` | repos | pyproject.toml/package.json/Cargo.toml | `{keywords: [...]}` |
| `local_assets` | repos | various files | `{has_codemeta, has_funding, ...}` |

### Tag derivation (post-refresh step)

After all sources run, `_derive_tags()` populates the tags table:

```
tags table:
  repo_id | tag              | source
  1       | topic:python     | github
  1       | topic:cli        | github
  1       | keyword:git      | pyproject
  1       | lang:python      | implicit
  1       | has:ci           | implicit
  1       | has:license      | implicit
  1       | published:pypi   | pypi
  1       | has:doi          | zenodo
```

### MCP tools (full parity)

```
get_manifest()           # overview (exists)
get_schema(table?)       # introspection (exists)
run_sql(query)           # read-only SQL (exists)
refresh(sources?)        # sync metadata (exists)
tag(repo, action, tag)   # manage user tags (NEW)
export(output_dir, query?) # arkiv archive (NEW)
```

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `repoindex/sources/__init__.py` | Create | MetadataSource ABC + `discover_sources()` |
| `repoindex/sources/github.py` | Create | GitHubSource (migrate from providers/github.py) |
| `repoindex/sources/gitea.py` | Create | GiteaSource (new, codeberg.org default) |
| `repoindex/sources/pypi.py` | Create | PyPISource (migrate from providers/pypi.py) |
| `repoindex/sources/cran.py` | Create | CRANSource (migrate from providers/cran.py) |
| `repoindex/sources/zenodo.py` | Create | ZenodoSource (migrate from providers/zenodo.py) |
| `repoindex/sources/npm.py` | Create | NpmSource (migrate from providers/npm.py) |
| `repoindex/sources/cargo.py` | Create | CargoSource (migrate from providers/cargo.py) |
| `repoindex/sources/conda.py` | Create | CondaSource (migrate) |
| `repoindex/sources/docker.py` | Create | DockerSource (migrate) |
| `repoindex/sources/rubygems.py` | Create | RubyGemsSource (migrate) |
| `repoindex/sources/go.py` | Create | GoSource (migrate) |
| `repoindex/sources/citation_cff.py` | Create | CitationCffSource (extract from repo service) |
| `repoindex/sources/keywords.py` | Create | KeywordsSource (extract from repo service) |
| `repoindex/sources/local_assets.py` | Create | LocalAssetsSource (extract from repo service) |
| `repoindex/commands/refresh.py` | Modify | Use `discover_sources()`, unified refresh loop |
| `repoindex/tags.py` or `repoindex/services/tag_derivation.py` | Create | `_derive_tags()` post-refresh step |
| `repoindex/mcp/server.py` | Modify | Add `tag` and `export` tools |
| `repoindex/providers/__init__.py` | Deprecate | Keep for backward compat, delegate to sources |

---

## Task Breakdown

### Task 1: Create MetadataSource ABC and discover_sources()

Create `repoindex/sources/__init__.py` with the unified ABC. Keep backward compat by having `providers/__init__.py` re-export old ABCs.

### Task 2: Migrate existing providers to MetadataSource

Convert each provider file to implement `MetadataSource` instead of `PlatformProvider`/`RegistryProvider`. This is mostly mechanical : rename `match()` to `fetch()` for registry sources, keep `detect()` + `enrich()` → `fetch()` for platform sources.

For publications sources: `fetch()` returns a dict with `registry`, `name`, `version`, `published`, `url`, `doi`, `downloads`, `downloads_30d`, `last_updated` keys : same as PackageMetadata.to_dict().

For repos sources: `fetch()` returns a dict of column names + values to merge into repos table.

### Task 3: Extract local file scanners into MetadataSources

Move `_extract_keywords`, `_detect_local_assets`, and CITATION.cff parsing from `repository_service.py` / `database/repository.py` into dedicated source files:
- `sources/citation_cff.py` : parses CITATION.cff, returns `{citation_doi, ...}`
- `sources/keywords.py` : parses pyproject.toml/Cargo.toml/package.json, returns `{keywords: [...]}`
- `sources/local_assets.py` : checks file existence, returns `{has_codemeta, ...}`

These are "local sources" : no HTTP, detected by file existence, always fast.

### Task 4: Create GiteaSource (Codeberg)

New source for Gitea-based platforms (Codeberg, Forgejo, self-hosted).

```python
class GiteaSource(MetadataSource):
    source_id = "gitea"
    name = "Gitea / Codeberg"
    target = "repos"

    def detect(self, repo_path, repo_record=None):
        url = (repo_record or {}).get('remote_url', '')
        hosts = self._get_hosts(config)  # default: ['codeberg.org']
        return any(host in url for host in hosts)

    def fetch(self, repo_path, repo_record=None, config=None):
        # Parse URL, call Gitea API: GET /api/v1/repos/{owner}/{name}
        # Return: {gitea_stars, gitea_forks, gitea_description, ...}
```

Detection: URL host match against configured list. Default: `['codeberg.org']`.
Config: `gitea.hosts: ['codeberg.org', 'gitea.mycompany.com']`
API: Gitea REST v1 (`/api/v1/repos/{owner}/{name}`)

New schema columns: `gitea_stars`, `gitea_forks`, `gitea_description`, `gitea_is_fork`, `gitea_is_private`, `gitea_is_archived`, `gitea_topics`, `gitea_created_at`, `gitea_updated_at`, `gitea_owner`, `gitea_name`.

### Task 5: Rewire refresh command for MetadataSource

Replace the current two-loop system (platforms + providers) with one loop:

```python
sources = discover_sources(only=active_source_names)

# Prefetch batch sources
for s in sources:
    if s.batch:
        s.prefetch(config)

# Per-repo processing
for repo in repos:
    for source in sources:
        if source.detect(repo.path, repo_dict):
            data = source.fetch(repo.path, repo_dict, config)
            if data:
                if source.target == "repos":
                    _update_repo_fields(db, repo_id, data)
                elif source.target == "publications":
                    _upsert_publication(db, repo_id, data)

    # After all sources: derive tags
    _derive_tags(db, repo_id, repo_dict)
```

Parallel execution: all sources for one repo run concurrently via ThreadPoolExecutor (already built).

CLI changes:
- `--source <name>` replaces both `--provider <name>` and `--github`
- `--external` activates all sources
- `--provider` kept as deprecated alias for `--source`
- `--github` kept as deprecated alias for `--source github`
- Local sources (citation_cff, keywords, local_assets) run by default (no flag needed : they're fast)

### Task 6: Implement tag derivation

Add `_derive_tags(db, repo_id, repo_record)` that populates the tags table from all metadata fields:

```python
def _derive_tags(db, repo_id, record):
    """Derive tags from metadata fields. Runs after all sources."""
    derived = []

    # Platform topics
    for field, source in [('github_topics', 'github'), ('gitea_topics', 'gitea')]:
        for topic in json.loads(record.get(field) or '[]'):
            derived.append((f'topic:{topic}', source))

    # Project keywords
    for kw in json.loads(record.get('keywords') or '[]'):
        derived.append((f'keyword:{kw}', 'pyproject'))

    # Language
    lang = record.get('language')
    if lang:
        derived.append((f'lang:{lang.lower()}', 'implicit'))

    # Boolean flags
    for flag in ('has_readme', 'has_license', 'has_ci', 'has_citation',
                 'has_codemeta', 'has_funding', 'has_contributors', 'has_changelog'):
        if record.get(flag):
            derived.append((flag.replace('has_', 'has:'), 'implicit'))

    # Publication status (query publications table)
    db.execute("SELECT registry FROM publications WHERE repo_id = ? AND published = 1", (repo_id,))
    for row in db.fetchall():
        derived.append((f'published:{row["registry"]}', row['registry']))

    # Sync derived tags (remove stale, add new)
    _sync_derived_tags(db, repo_id, derived)
```

This means after a full refresh, every repo has auto-derived tags that are queryable:
```bash
repoindex query "tagged('lang:python') and tagged('has:ci')"
repoindex query "tagged('published:pypi')"
repoindex query "tagged('topic:cli')"
```

### Task 7: Add MCP tools (tag + export)

Add two new tools to `repoindex/mcp/server.py`:

```python
@mcp.tool()
def tag(repo: str, action: str, tag: str = "") -> dict:
    """Manage user-assigned repo tags. Actions: add, remove, list.
    Derived tags (from GitHub, PyPI, etc.) are auto-populated during refresh."""

@mcp.tool()
def export(output_dir: str, query: str = "") -> dict:
    """Export repos as longecho-compliant arkiv archive to output_dir.
    Optional query filters which repos are exported."""
```

Both implemented as subprocess calls (same pattern as `refresh`).

### Task 8: Update plugin : replace skills with agents

Convert the repoindex Claude Code plugin:

**Remove skills:**
- `repoindex` (CLI reference) : MCP covers this
- `repo-query` (NL search) : `run_sql` covers this
- `repo-status` (dashboard) : `run_sql` covers this

**Keep/convert:**
- `repo-polish` → becomes a `repo-doctor` agent

**Add agents:**
- `repo-doctor` : "what needs attention?" Multi-step triage using MCP tools
- `repo-polish` : "prepare this repo for release" using MCP tools

### Task 9: Tests and integration

- Tests for MetadataSource ABC
- Tests for each migrated source
- Tests for GiteaSource
- Tests for tag derivation
- Tests for new MCP tools
- Full suite regression test
- Smoke test: `repoindex refresh --external`, verify tags populated, verify MCP tools work

---

## Sequencing

Tasks 1-3 are the foundation (ABC + migration). Tasks 4-6 are features that depend on 1-3. Tasks 7-8 are independent of the source refactor. Task 9 is final validation.

```
Task 1: MetadataSource ABC                    ─┐
Task 2: Migrate existing providers             ├─ Foundation
Task 3: Extract local file scanners            ─┘
Task 4: GiteaSource (Codeberg)                ─── Depends on 1
Task 5: Rewire refresh command                ─── Depends on 1-3
Task 6: Tag derivation                        ─── Depends on 5
Task 7: MCP tools (tag, export)               ─── Independent
Task 8: Plugin agents                         ─── Depends on 7
Task 9: Tests + integration                   ─── Final
```

Tasks 7 can start immediately (independent). Tasks 1-3 are sequential. Task 4 can start after Task 1. Tasks 5-6 need 1-3 done.
