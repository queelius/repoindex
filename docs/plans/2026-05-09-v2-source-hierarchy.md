# v2.0 Plan: Source Hierarchy Refactor

**Status**: completed in v2.0 (commits 379ea2c through 6ef08e6).
**Target version**: 2.0.0
**Estimated scope**: 5 waves, 2-3 weeks of subagent work

## The problem

`MetadataSource` is one ABC over three substantively different concepts:

- **Git forges** (github, gitea, gitlab, codeberg, sourcehut): host the repo over git, expose API to read AND write metadata, enumerable via `/user/repos`.
- **Registries** (pypi, cran, zenodo, npm, cargo, conda, docker, rubygems, go): publish packaged versions of repos. One-way relationship: repo gets published *to* the registry. No git hosting.
- **Local scanners** (citation_cff, keywords, local_assets): read files inside the repo. No network, no auth.

The flattened ABC manifests as awkwardness everywhere:

- The `target: Literal["repos", "publications"]` field is a discriminator that should be implicit in subclass.
- `ops github set-topics` is hardcoded to GitHub when the operation is universal across forges.
- `ops generate gh-pages` is GitHub-specific when "Pages" exists on Gitea, GitLab, Codeberg.
- `ops mirror` config has its own top-level section when mirrors are conceptually just configured forges with a redundancy role.
- Per-platform schema columns (`github_topics`, `gitea_topics`, hypothetically `gitlab_topics`) duplicate the same concept across rows.
- Cross-source concepts (archived, pages_url, default_branch, is_fork) have no canonical column.
- Sync from platform isn't expressible because there's no abstraction for "platforms that enumerate."

## The new hierarchy

```python
class Source(ABC):
    """Marker base for everything in ~/.repoindex/sources/**/*.py."""
    source_id: str
    name: str

    @abstractmethod
    def detect(self, repo_path, repo_record=None) -> bool: ...

    @abstractmethod
    def fetch(self, repo_path, repo_record=None, config=None) -> Optional[dict]: ...


class LocalScanner(Source):
    """Reads files in the local repo. No network, no auth.
    Output goes to repos table."""
    pass  # no extra capabilities


class RemoteSource(Source):
    """Network-backed source with auth. Output destination depends on subclass."""
    pass


class GitForge(RemoteSource):
    """Hosts git repos. Has API for both metadata (read) and actions (write).
    Output goes to repos table; populates forge_id, topics, is_archived, etc.
    """
    # Optional capabilities. Default raises NotImplementedError.
    def enumerate_user_repos(self, config) -> Iterator[RemoteRepo]: ...
    def set_topics(self, repo_record, topics, config) -> None: ...
    def set_description(self, repo_record, description, config) -> None: ...
    def set_archived(self, repo_record, archived, config) -> None: ...
    def set_visibility(self, repo_record, public, config) -> None: ...
    def set_default_branch(self, repo_record, branch, config) -> None: ...
    def enable_pages(self, repo_record, branch, path, config) -> None: ...


class Registry(RemoteSource):
    """Package registry. Publishes artifacts; doesn't host source.
    Output goes to publications table."""
    batch: bool = False
    # Optional, only on registries where it makes sense:
    def enumerate_user_packages(self, config) -> Iterator[RemotePackage]: ...
```

The `target` field is **gone**. Where data lands is implicit in the subclass:
- `LocalScanner.fetch()` and `GitForge.fetch()` populate `repos`.
- `Registry.fetch()` populates `publications`.

## Schema changes

### `repos` table

**Add** (generic, populated by whichever GitForge owns the repo):
- `forge_id TEXT`: which GitForge owns this repo (`github`, `gitea`, etc.). Resolved from `remote_url` during refresh.
- `forge_owner TEXT`: owner/organization on the forge (replaces `github_owner`, `gitea_owner`).
- `forge_name TEXT`: repo name on the forge.
- `topics TEXT`: JSON array of topics.
- `is_archived BOOLEAN`
- `is_fork BOOLEAN`
- `is_private BOOLEAN`
- `pages_url TEXT`
- `default_branch TEXT` (already exists implicitly via git, but expose from forge for consistency)
- `forge_description TEXT`: the description as set on the forge (separate from local README content).
- `stars INTEGER`
- `forks_count INTEGER`
- `open_issues INTEGER`

**Drop**:
- All `github_*` columns
- All `gitea_*` columns

This is destructive. Schema v8 -> v9. Migration strategy: drop-and-rebuild from local repos + external sources via `repoindex refresh --external`. Acceptable for v2.0 break.

### `publications` table

No change. Already platform-agnostic (`registry` field discriminates).

### `forge_id` lookup

A small registry maps URL hostnames to `forge_id`:
```python
FORGE_HOST_MAP = {
    'github.com': 'github',
    'codeberg.org': 'gitea',  # codeberg runs gitea
    # gitea instances: configured per host in user config
    # gitlab.com: 'gitlab',
    ...
}
```

Plus a config mechanism for self-hosted Gitea/GitLab instances:
```yaml
forges:
  - source_id: gitea
    instances:
      - host: gitea.example.com
        token_env: GITEA_TOKEN
```

## Config changes

### Single `forges:` section replaces `mirrors:`

```yaml
forges:
  github:
    token_env: GITHUB_TOKEN
    role: primary  # default

  codeberg:           # codeberg-as-mirror example
    source_id: gitea  # codeberg runs gitea
    host: codeberg.org
    token_env: CODEBERG_TOKEN
    role: mirror
    url_template: "https://codeberg.org/queelius/{repo}.git"

  gitea-gdrive:
    source_id: gitea
    host: file:///mnt/gdrive/git-mirrors  # actually a bare-repo dir
    role: mirror
    url_template: "file:///mnt/gdrive/git-mirrors/{repo}.git"
```

`role` values:
- `primary`: the canonical forge for repos hosted there. Detected from `remote_url`.
- `mirror`: redundancy target. `ops mirror` pushes to these.
- (future) `archive`: read-only snapshots.

The old top-level `mirrors:` config section is removed.

## Command changes

### Generalized actions (replace `ops github *`)

```
ops set-topics REPO TOPIC...        # was: ops github set-topics
ops set-description REPO DESC       # was: ops github set-description
ops set-archived REPO {true|false}  # new
ops set-visibility REPO {public|private}  # new
ops set-default-branch REPO BRANCH  # new
ops set-pages REPO --branch B --path P    # was: ops generate gh-pages
```

Each looks up the repo's `forge_id`, calls the right GitForge implementation. If the forge doesn't support that operation, refuse with a clear error.

### Sync (new)

```
ops sync [--from NAME]... [--all] [--into PATH] [--dry-run]
         [--include-archived] [--filter PATTERN]
```

Lists user's repos on each enumerable GitForge. Clones any not present locally. Strictly additive.

### Removed

- `ops github` subgroup (entire): actions promoted to top level.
- `ops generate gh-pages`: replaced by `ops set-pages`.

## Source layout

User extension dirs:
```
~/.repoindex/sources/forges/        # GitForge subclasses
~/.repoindex/sources/registries/    # Registry subclasses
~/.repoindex/sources/scanners/      # LocalScanner subclasses
```

Built-in:
```
repoindex/sources/forges/__init__.py     # github.py, gitea.py
repoindex/sources/registries/__init__.py # pypi, cran, zenodo, ...
repoindex/sources/scanners/__init__.py   # citation_cff, keywords, local_assets
```

`discover_sources()` returns a flat list as before; type-narrowing via `isinstance` checks at call sites.

## Wave plan

### Wave V2.A: ABC hierarchy (foundation)
- Define `Source`, `LocalScanner`, `RemoteSource`, `GitForge`, `Registry` in `repoindex/sources/__init__.py`.
- Reparent the 14 existing sources.
- Drop the `target` field.
- Reorganize files into `forges/`, `registries/`, `scanners/` subdirs.
- All existing tests pass; add tests for subclass typing.
- No schema change yet, no command change.

### Wave V2.B: Schema unification
- v9 migration: add unified columns, populate from existing platform-prefixed columns where possible during migration, then drop old columns.
- Update `database/repository.py` upserts to write unified columns.
- Update `services/tag_derivation.py` to read unified columns.
- Update `mcp/server.py` and `commands/show.py` to surface unified columns.
- Refresh logic resolves `forge_id` from `remote_url` and routes write to the right unified columns.

### Wave V2.C: Cross-forge actions
- Implement optional methods on github + gitea sources.
- Replace `ops github *` commands with generic `ops set-*` commands.
- `ops generate gh-pages` -> `ops set-pages`.
- New `ops sync` command.

### Wave V2.D: Mirrors as forge role
- Migrate `mirrors:` config to `forges:` with `role: mirror`.
- `services/mirror_service.py` reads forges-with-role.
- `commands/ops.py` `mirror_handler` updated.
- Drop `services/mirror_service.MirrorTarget` in favor of forge entries.

### Wave V2.E: Polish + ship
- Update `DESIGN.md`, `STABILITY.md`, `CLAUDE.md` for v2.0 surface.
- Update `~/github/alex-claude-plugins/repoindex/` slash commands and agents.
- Bump to v2.0.0.
- Tag, push, hold PyPI for burn-in.

## Out of scope (deferred)

- **Multi-remote repos** with multiple forge memberships. A repo with `origin=github` and `codeberg=codeberg` still has one canonical `forge_id` derived from `origin`. Multi-platform membership stays for v2.x.
- **Cross-forge action transactions** (set topics on 5 forges, one fails). Per-forge errors surface, no atomic rollback.
- **Forge-specific extensions** (GitHub Discussions, GitLab MRs, Gitea Issues with custom fields). Stay in the forge-specific modules; not exposed through the generic API.
- **Source-side enumeration of registries** (npm `whoami packages`, cargo `owner --list`). Possible but `ops sync` v1 is forge-only.

## What this enables

After v2.0:

- The MCP layer answers "what do I own on Codeberg that isn't local?" via SQL on the synced data.
- A new GitForge (sourcehut, GitLab, etc.) is one file under `~/.repoindex/sources/forges/` and works everywhere immediately.
- Set-topics across all forges is a single operation. The "set both GitHub and Codeberg topics consistently" workflow becomes `ops set-topics REPO foo bar` if the repo is mirrored to both, or two invocations if forks have diverged.
- The `archived` concept is uniform: GitHub-archived, Gitea-archived, or path-derived (`dir:archived`) all set the same `is_archived` column.
- Mirrors are first-class forge entries, not a side concept with its own config block.
