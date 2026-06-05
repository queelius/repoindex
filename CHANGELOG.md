# Changelog

All notable changes to repoindex are documented here.

## Unreleased

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
