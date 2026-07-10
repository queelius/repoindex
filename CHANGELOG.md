# Changelog

All notable changes to repoindex are documented here.

## Unreleased

## 2.2.1 - 2026-07-10

Post-release code-review remediation: 16 verified findings across the 2.1/2.2
feature bundles, plus two performance improvements to forge-event fetching.

### Fixed

- `refresh --forge-events` now fetches events for repos the incremental skip
  leaves untouched. The skip keys on `.git/index` mtime, which forge activity
  (releases, PRs, issues) never changes, so in steady state the flag fetched
  nothing unless `--full` was passed.
- The concept-DOI feature works end-to-end. Refresh no longer drops
  `concept_doi` when storing registry results (`PackageMetadata.from_dict`
  derives the round-trip from the dataclass fields), and the format-export
  path now merges publication DOIs into repo rows, so the bibtex/jsonld
  preference for the concept DOI actually fires.
- Arkiv archives emit the citable concept DOI under `doi` again (as every
  pre-2.2 export did); the version-specific DOI moved to a new `version_doi`
  key instead of silently changing the meaning of `doi`.
- `events --forge` combined with a non-forge `--type` (e.g. `commit`) is a
  clean usage error. Previously the empty type intersection was treated as
  "no filter" and returned every event type. The `--type` help text no longer
  advertises the removed `pr` type.
- Invalid `--since`/`--until`/`--recent` values produce a usage error instead
  of a Python traceback, across events, refresh, copy, link, export, and all
  `ops` subcommands (shared click param type). An unparseable config
  `events.since` reports cleanly too.
- GitHub event pagination no longer truncates silently: network errors and
  unexpected HTTP statuses raise (surfaced as per-repo warnings) instead of
  ending the stream as if complete, which permanently hid the missing events
  behind `INSERT OR IGNORE` dedup. Pagination also authenticates via
  `gh auth token` when no token env var is set, and feeds rate-limit headers
  into the client's tracker.
- Gitea release pagination early-stops on `created_at` (the list order)
  rather than `published_at`, avoiding false stops on late-published or
  backdated releases: the same hazard the GitHub client already handled.
- The MCP `run_sql` tool has its description again. FastMCP captures the
  description at registration time, so the post-decoration `__doc__`
  assignment shipped an empty string to every client.
- The schema v10 history comment no longer claims events/refresh_log survive
  migration (the DB is a cache; a version bump drops and rebuilds).

### Added

- MCP `refresh` tool accepts `forge_events=true`, making the forge-events
  capability reachable by the MCP (its dominant consumer), not just the CLI.

### Changed (internal)

- Forge-event fetches run as a second phase after the repo loop: network
  requests fan out in a thread pool while all database writes stay on the
  main thread. With the default config window, each repo's fetch now narrows
  to events newer than what the database already holds (an explicit `--since`
  is honored verbatim for backfills).
- The GitHub and Gitea event translations share one `GitForge` helper (the
  cross-forge payload contract lives in one place), single-row and batched
  event inserts share one SQL statement and row mapping, and the
  forge-dispatch index is built once per refresh run instead of re-importing
  source modules per repo.

## 2.2.0 - 2026-06-07

### Added

- Forge events (release, pull_request, issue) are now fetched behind a
  `GitForge.fetch_events` capability dispatched by `forge_id`, implemented for
  GitHub and Gitea via their API token clients. Enable during refresh with
  `--forge-events` (or config `refresh.external_sources.forge_events`); opt-in,
  default off. Event types are generic and forge provenance is the repo's
  `forge_id` (no schema change). The `events` command gains `--forge` (with
  `--github` kept as a hidden alias).

### Removed

- The GitHub-specific `scan_github_*` functions and the `github_`-prefixed event
  type vocabulary (`GITHUB_EVENT_TYPES`). Forge event-fetching now goes through
  the forge abstraction; the event type constant is `FORGE_EVENT_TYPES`.

### Changed (behavior)

- Event scanning is now bounded by a single configurable time window instead
  of a hidden per-repo commit-count cap. The scanner previously kept only the
  50 most recent commits per repo, so commit counts saturated at 50 and history
  was truncated. The 50-count cap on commits and merges is removed; how far back
  `refresh` scans is set by `events.since` in config (default `6m`), and the
  `--since` flag overrides it.

## 2.1.0 - 2026-06-05

Trust-repair and performance bundle: remove silent failures and make
documentation, packaging, and version metadata honest and self-enforcing.

### Changed (behavior)

- Duration tokens are now parsed by a single shared parser
  (`repoindex/services/timespec.py`, `parse_since`). The token `m` now means
  MONTHS everywhere; use `min` for minutes. This silently changes
  `repoindex events --since 6m` and `repoindex digest --since 6m` from six
  minutes to six months. Supported tokens: `s`/`sec` (seconds), `min`
  (minutes), `h` (hours), `d` (days), `w` (weeks), `m`/`M` (months, approximated
  as 30 days), `y` (years, approximated as 365 days).
- Invalid duration strings now raise an error instead of silently falling back
  to a default window (the old `events` 7d, `refresh` 90d, and `--recent` 30d
  silent fallbacks were footguns). Click option defaults (`events --since 7d`,
  `refresh --since 90d`, `digest --since 7d`) are unchanged.
- A non-empty positional query (a stale pre-v0.16 DSL expression) passed to
  `ops`, `copy`, `link`, or `wip-snapshot` now raises a migration error instead
  of being silently ignored (which previously acted on the whole collection).
  Use `--language`/`--tag`/`--recent` or `repoindex sql`.
- Bulk `ops set-*` mutations (`--all`, more than one repo) now prompt for
  confirmation on an interactive TTY; add `--yes/-y` to skip. Scripted, piped,
  `--dry-run`, `--json`, and single-repo runs never prompt.
- Schema bumped to v10 (adds a nullable `publications.concept_doi` column).
  Consistent with the cache design, a schema-version bump drops and rebuilds
  the database from the filesystem; run `repoindex refresh` afterward to
  repopulate (and `refresh --external` to restore stars/releases/publications).

### Added

- `publications.concept_doi` column and `PackageMetadata.concept_doi`: the
  version-independent Zenodo concept DOI is now stored distinctly from the
  per-version DOI, and citation exporters (bibtex, jsonld) prefer it.
- `get_schema` (MCP) now exposes views (`v_active_repos`, `v_stale_repos`,
  `v_repo_stats`) and the `repos_fts` full-text table; `get_manifest` gains
  planning aggregates (dirty, unpushed, published, stale, by_forge_id,
  refresh_stale); `run_sql` carries a documented FTS/exemplar docstring.
- `readme_content` is now populated during refresh (capped at 100 KB), so
  full-text README search, the audit readme check, and the arkiv export
  README body all work.
- CI matrix workflow (Python 3.10/3.11/3.12) and a version-consistency test
  that keeps `pyproject.toml`, `__version__`, `CITATION.cff`, and
  `codemeta.json` in agreement.

### Removed

- Abandoned `pathlib` backport and unused `tweepy` from dependencies;
  Python floor raised to `>=3.10`; drift-prone `requirements.txt` deleted
  (`make install` now uses the `dev` extra).

### Fixed

- mkdocs nav pointed at deleted pages (`mkdocs build --strict` aborted);
  onboarding strings cited removed `repoindex query` / `repoindex init`
  commands; README/docs referenced a nonexistent plugin marketplace. All
  repaired and guarded by tests.
