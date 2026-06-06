# Forge Events Capability: Design Spec

**Date:** 2026-06-06
**Status:** Approved (brainstorm), pending implementation plan
**Topic:** Decouple forge event-fetching from GitHub by moving it behind a `GitForge` capability dispatched by `forge_id`, de-platform the event-type taxonomy, implement GitHub and Gitea, and wire forge events into `refresh` behind a discrete opt-in toggle.

## Goal

Make forge events (releases, pull requests, issues) the third face of the `GitForge` abstraction, alongside metadata (`fetch()`) and write actions (`set_*`), all dispatched identically by `forge_id`. Remove the GitHub-specific `scan_github_*` pile from the `events` module, and actually fetch and store forge events during `refresh` so they become queryable.

## Motivation

The forge abstraction (`GitForge`, a `RemoteSource`) has three faces:

| Face | Mechanism | State before this work |
|------|-----------|------------------------|
| Read metadata (stars, topics, archived) | `Source.fetch()` to unified `repos` columns, polymorphic | Unified in V2.B |
| Write actions (set topics/description/visibility) | `GitForge.set_*()` capabilities, dispatched by `forge_id` | Unified in V2.C |
| Event history (releases, PRs, issues) | Nine `scan_github_*` functions in `events/__init__.py`, GitHub-only, via the `gh` CLI | Never migrated |

The event face is the holdout. It is GitHub-locked, lives outside the Source family, is not a `GitForge` capability, bakes the platform into the event-type names (`github_release`), and is effectively dead in `refresh` (refresh only requests local VCS event types, so forge events are never fetched or stored). This spec finishes the V2 unification for events.

## Locked decisions

1. **Scope: refactor and activate.** Move forge events behind the capability AND wire them into `refresh` so they flow into the database and become queryable.
2. **Provenance via `repos.forge_id`.** Events link to their repo by `repo_id`; the forge is the repo's existing `forge_id`, reached by a join. No new column.
3. **Event kinds: `release`, `pull_request`, `issue`.** Stars/forks remain as counts on the repo row (`repos.stars`, `repos.forks_count`), not events. GitHub-only kinds (workflow_run, deployment, security_alert, repo_events) are dropped.
4. **Both GitHub and Gitea implemented.** Full cross-forge parity, matching `set_*`. Note: the user's Gitea/Codeberg repos are mirrors with no independent activity, so the Gitea fetcher will usually return little or nothing today; the value is the end-to-end abstraction proof and future-readiness.
5. **Discrete opt-in toggle for refresh.** Config `refresh.external_sources.forge_events` (default `false`) and a `--forge-events` CLI flag. Independent of `--external`.
6. **Auth via the forge API token client.** `fetch_events` uses each forge's existing token-based API client (the same path as `fetch()` and `set_*`). The `gh` CLI dependency is dropped.

## Architecture: capability and dispatch

Add one method to the `GitForge` ABC in `repoindex/sources/__init__.py`, mirroring the `set_*` shape:

```python
def fetch_events(self, repo_record: dict, since: datetime, config: dict) -> Iterator[Event]:
    """Yield forge events (release, pull_request, issue) since the cutoff.

    Default raises NotImplementedError so forges without event support
    degrade gracefully, exactly like the optional set_* actions.
    """
    raise NotImplementedError(f"{self.source_id} does not support fetch_events")
```

`refresh` resolves the owning forge with the existing `repoindex/services/forge_actions.py` helper `lookup_repo_forge(repo_record)` (which returns the `GitForge` whose `source_id == repo_record['forge_id']`), then calls `fetch_events`. A forge without the capability raises `NotImplementedError`, which the caller catches and skips. No forge branching exists outside the forge modules.

## Data model and taxonomy

- Generic `type` values: `release`, `pull_request`, `issue`, joining the existing `commit`, `git_tag`, `branch`, `merge`. The `github_*`-prefixed vocabulary is removed.
- Provenance is `repos.forge_id` via the `repo_id` FK join. Example query: `SELECT ... FROM events e JOIN repos r ON e.repo_id = r.id WHERE r.forge_id = 'gitea' AND e.type = 'release'`.
- **No schema or migration change.** Forge events were never stored, so there is nothing to migrate. The `events` table already carries `type`, `timestamp`, `ref`, `message`, `author`, and `metadata`.
- `event_id` (the UNIQUE dedup key used by `insert_events`' `INSERT OR IGNORE`) is constructed stably per kind so re-fetch is idempotent:
  - release: `release:{forge_id}:{owner}/{name}:{tag}`
  - pull_request: `pull_request:{forge_id}:{owner}/{name}#{number}`
  - issue: `issue:{forge_id}:{owner}/{name}#{number}`
- Domain `Event` field mapping: `type` (generic kind), `timestamp` (`published_at` for releases, `created_at` for PRs and issues, so the timestamp marks when the event happened), `ref` (tag for releases, number for PR/issue), `message` (title/name), `author` (login), `metadata` (state, url, and other forge-specific bits as JSON).

## Forge implementations

Both forges implement `fetch_events` against their existing API token client (the one already used for `fetch()` and `set_*`). The `gh` CLI is not used. Owner and name come from `repo_record['forge_owner']` and `repo_record['forge_name']`.

**GitHub (`repoindex/sources/forges/github.py`)**, REST API:
- Releases: `GET /repos/{owner}/{name}/releases` (returned newest-first), stop when `published_at` falls before `since`.
- Pull requests: `GET /repos/{owner}/{name}/pulls?state=all&sort=created&direction=desc`, stop when `created_at` falls before `since`.
- Issues: `GET /repos/{owner}/{name}/issues?state=all&sort=created&direction=desc`, filtering out any entry that carries a `pull_request` field (GitHub's issues endpoint includes PRs), stop when `created_at` falls before `since`.
- Sorting by the creation field (descending) makes the stop condition monotonic, so pagination halts as soon as the window is exceeded.

**Gitea (`repoindex/sources/forges/gitea.py`)**, GitHub-compatible REST API:
- Releases: `GET /repos/{owner}/{name}/releases`
- Pull requests: `GET /repos/{owner}/{name}/pulls?state=all`
- Issues: `GET /repos/{owner}/{name}/issues?state=all&type=issues`
- Same pagination and stop-at-`since` logic.

Each API record is translated into a domain `Event` via a small per-forge mapping function. The translation is the only forge-specific logic; the dispatch and storage are shared.

## Refresh wiring and gating

- Config key `refresh.external_sources.forge_events` (default `false`), added to `get_default_config()` and the YAML template, matching the existing "slow external operations are opt-in by default" philosophy.
- CLI flag `--forge-events` on `repoindex refresh`. It is independent of `--external`: `--external` continues to fetch metadata and registries only; `--forge-events` (or the config toggle) is what triggers event fetching. It needs only the forge token, not `--external`.
- In `refresh`'s per-repo step (`_process_repo` in `repoindex/commands/refresh.py`), after the existing local VCS event scan, if forge events are enabled: dispatch `fetch_events` by `forge_id`, then `insert_events(db, events, repo_id)` (existing dedup path). Per-repo failures are isolated.
- Dependency on `forge_id`: dispatch resolves the forge from `repo_record['forge_id']`, which is populated by the forge metadata `fetch()` (V2.B). A repo never refreshed with `--external`/`--github` has a NULL `forge_id`, so `lookup_repo_forge` returns `None` and the repo is skipped. In practice `--forge-events` pairs with (or follows) a metadata refresh; document this in the flag help and skip cleanly when `forge_id` is unknown.

## events module cleanup and CLI surface

- Delete the nine `scan_github_*` functions and their `gh`-CLI helpers from `repoindex/events/__init__.py`. The release/PR/issue logic moves into the forge clients. The GitHub-only kinds (workflow_run, deployment, security_alert, repo_events, forks, stars) are dropped, not ported.
- Keep the platform-agnostic local scanners: `scan_commits`, `scan_git_tags`, `scan_branches`, `scan_merges`, and the git-file-based `scan_version_bumps` / `scan_deps_updates` if present.
- Constants: replace `GITHUB_EVENT_TYPES` with `FORGE_EVENT_TYPES = ['release', 'pull_request', 'issue']`; update `ALL_EVENT_TYPES`. In `repoindex/services/event_service.py`, rename `GITHUB_TYPES` to `FORGE_TYPES` and update `_build_types`.
- `events` command: the `--github` flag becomes `--forge`, with `--github` kept as a hidden deprecated alias for backward compatibility.

## Error handling

- `NotImplementedError` from a forge means it has no event support: skip silently.
- Network, auth, 404, or rate-limit errors on a single repo: warn to stderr and continue, matching existing refresh resilience. Reuse the GitHub client's configured rate-limit backoff (`github.rate_limit` in config).
- No token configured: forge events are skipped with a single clear notice, not per-repo spam.

## Testing

- Unit tests for `fetch_events` on each forge with a mocked API client (canned JSON responses), asserting `Event` objects with generic `type`, correct timestamp, stable `event_id`, and author.
- The `since` pagination-stop logic (stops when records fall before the cutoff).
- Dispatch: a refresh with `--forge-events` calls the correct forge's `fetch_events` by `forge_id`; `NotImplementedError` is skipped; per-repo errors are isolated.
- Taxonomy guard: assert stored `type` values carry no `github_` prefix.
- Regression fence: a source-grep guard asserting no `scan_github_*` function remains (in the style of the existing doc-breadcrumb guards).
- CLI: `events --forge` and the `--github` alias both resolve.

## Non-goals (out of scope)

- GitHub-only event kinds (workflow_run, deployment, security_alert, repo_events): dropped, not ported.
- Star/fork events: counts already live on the repo row; individual star/fork events are not collected.
- Any schema or migration change: none is needed.
- Backfilling historical forge events beyond the `--since` window applied at refresh time.

## STABILITY and compatibility

- Adding `fetch_events` to the `GitForge` ABC with a default that raises is additive and STABILITY-safe.
- The event-type vocabulary change (`github_release` to `release`) is forward-only: those types were never stored, so there is no data to migrate, and the cache is regenerated by `refresh` regardless.
- The `events --github` flag is preserved as a hidden alias for `--forge`.
- Everything is behavior-preserving except the new opt-in `--forge-events` path.
