# Trust-Repair + Perf Bundle (v2.1) Design

**Status**: approved 2026-05-12, ready for implementation planning.
**Scope**: repoindex Python package (`/home/spinoza/github/beta/repoindex`) plus
trivial fixes to the Claude Code plugin (`/home/spinoza/github/alex-claude-plugins/repoindex`).
**Target release**: v2.1.0 (additive and behavior-fix only; no STABILITY.md breaches).

This spec was produced from a 7-lens improvement sweep, then a 6-cluster
verification pass that confirmed each claim against the real code. Line numbers
below are from that verification and should be reconfirmed at implementation time
(the code may have shifted by a few lines).

## Purpose

Repair the places where repoindex v2.0 lies to its two users (the human at the
terminal and the LLM through MCP), and remove the single largest refresh
bottleneck. Every item is either a correctness fix, a trust fix (docs/config that
disagree with reality), a confirmed performance win, or an additive data fix. No
new feature surface. No architectural rewrites (those are deferred, see Non-Goals).

## Locked Decisions

1. **Python floor: drop to `>=3.10`.** The code already uses PEP-604 unions
   (`str | None`) that are evaluated eagerly, so the true floor is already 3.10,
   and STABILITY.md documents the `get_schema(table: str | None = None)` signature.
   We make the floor honest rather than retrofit `from __future__ import annotations`.
   3.8 and 3.9 are end-of-life. The user is effectively the only consumer.
2. **Duration token `m` means months everywhere.** Introduce `min` for minutes,
   keep `h` for hours, keep `M` as a months alias. This silently changes
   `events --since 6m` and `digest --since 6m` from minutes to months, so it is a
   documented CHANGELOG entry. Invalid duration strings raise (no silent fallback
   to 7d/30d/90d, which were themselves footguns).
3. **Schema v10: preserve-and-restore + `concept_doi`.** One schema bump that
   (a) preserves `events` and `refresh_log` across migration instead of dropping
   them, and (b) adds a nullable `concept_doi` column to `publications`. Both are
   additive and 2.x-legal.
4. **Repo scope: Python repo plus trivial plugin fixes.** The repo-polish.md
   single-repo-targeting rewrite is deferred because it depends on a new
   `ops generate --name/--path` selector (a feature, filed separately).

## Architecture Context (unchanged)

The fixes respect the existing layering (Commands to Services to Database/Infra to
Domain) and the v2.0 contracts: path is identity, the database is a materialized
view, SQL is the read API, writes are explicit and narrow. Nothing here makes SQL
writable, adds broad MCP mutation, changes `forge_id` cardinality, or introduces a
query DSL. See `DESIGN.md` for the grain this bundle must not violate.

## Commit Groups

Implemented and committed as nine isolated commits (eight in the Python repo, one
in the plugin repo). One theme per commit so regressions bisect cleanly. The two
"silent semantic change" commits (perf language detection, timespec) and the
schema commit each carry a CHANGELOG entry.

### Commit 1: `perf` (Python repo)

- **Language detection rewrite.** `repoindex/services/repository_service.py`
  `_detect_languages` (around lines 433-480) runs ~19 per-extension `glob`
  calls per repo that descend into `.venv`/`node_modules`. Replace with a single
  `os.walk` that prunes `EXCLUDE_DIRS` from `dirnames` in place and increments one
  inverted extension-to-language map. Measured target: ~0.8s to ~0.001s per repo.
  - **Behavior preservation is mandatory.** Current code overwrites per extension,
    so R is counted only from `.R` (the `.r` count is lost). A naive rewrite that
    sums `.r` + `.R` would silently change stored `language` values. Write a
    characterization test FIRST that pins today's primary-language selection
    (including the `.r`/`.R` quirk and insertion-order tie-break), then make the
    rewrite byte-identical in output. The `.r`/`.R` correction, if wanted, is a
    separate conscious change with its own test, not part of this perf commit.
  - Guard against the substring-exclusion bug: a repo whose absolute path contains
    an `EXCLUDE_DIRS` token (e.g. a repo literally under a dir named `build`) must
    not be wrongly pruned. Test this.
- **Batched event inserts.** `repoindex/database/events.py` `insert_events`
  (around lines 44-61) inserts row-at-a-time. Build param tuples and issue one
  `executemany`. Report the inserted count via a `conn.total_changes` delta so the
  `events_added` stat stays correct under `INSERT OR IGNORE` dedup.
- **Batched `cleanup_missing_repos`.** `repoindex/database/repository.py` (around
  lines 381-396) does per-row `os.path.exists` plus an individual DELETE. Collect
  the missing ids, issue one chunked `DELETE ... WHERE id IN (...)`. Keep the
  `exists()` check (behavior-preserving: prune only repos gone from disk). Do NOT
  switch to set-difference pruning (that changes which repos get removed; deferred).

### Commit 2: `mcp` (Python repo)

`repoindex/mcp/server.py`:
- **Expose views to `get_schema`.** The schema defines activity views
  (`v_active_repos`, `v_stale_repos`, `v_repo_stats`, possibly `v_repo_health`) that
  `get_schema` hides by filtering `type='table'` (around lines 95, 108-112). Change
  to `type IN ('table','view')`.
- **Expose `repos_fts`.** The `%_fts%` NOT LIKE filter hides the FTS table entirely,
  so the LLM never learns to use `MATCH` and falls back to `LIKE` full scans. Change
  the exclusion to `%_fts_%` (trailing underscore) so the shadow tables
  (`repos_fts_data` etc.) stay hidden but `repos_fts` shows. Add a one-line "use
  MATCH for full-text search" hint in the schema output or tool docstring.
- **Planning aggregates in `get_manifest`.** `_get_manifest_impl` (around lines
  48-85) returns only table row-counts, languages, and last_refresh. Add additive
  `summary` keys: dirty count, unpushed count, published vs unpublished count, DOI
  count, stale count, count by `forge_id`, and a refresh-staleness flag (age vs a
  threshold). All additive; existing consumers keep working.
- **`run_sql` docstring.** Add canonical exemplars (FTS `MATCH`, published-but-no-
  citation, stale repos) and fix the `version` vs `current_version` column mismatch
  that breaks an LLM's first publications query.

Note: `get_manifest` does NOT use the `str | None` annotation (verification
correction); the Python-floor work is in Commit 7, scoped to `get_schema`,
`digest.py`, and `fs_utils.py`.

### Commit 3: `schema(v10)` (Python repo, isolated, highest risk)

`repoindex/database/schema.py` `apply_schema()` (around line 333) currently DROPs
all tables on any version mismatch, including append-only `events` and
`refresh_log`, contradicting DESIGN.md section 4. Local commit/tag events re-scan
from git, but external-sourced events (releases, PRs, issues, stars, publishes from
`--github`/`--external`) and the entire `refresh_log` are genuinely lost.

- **Preserve-and-restore.** On migration: copy `events` and `refresh_log` to temp
  tables, drop/recreate the schema, re-insert (`INSERT OR IGNORE` dedupes events by
  `event_id`). Keep `SCHEMA_V1` as the single source of DDL truth. This is approach
  (A) from the scoping doc; the full ALTER ladder (B) is deferred.
- **`concept_doi` column.** Add a nullable `concept_doi` to `publications` (additive,
  2.x-legal). Update `PackageMetadata` (domain) with a `concept_doi` field. In
  `repoindex/sources/registries/zenodo.py` (around line 106-115) stop collapsing via
  `concept_doi or doi`: store the version DOI in `doi` and the concept DOI in
  `concept_doi`. Update `repoindex/services/repository_service.py` (around line 556)
  population path. The concept DOI is what a paper cites, so citation and bibtex
  exporters should prefer `concept_doi` when present, falling back to `doi`.
- Bump `CURRENT_VERSION` to 10. Migration test must assert external events survive
  a v9 to v10 upgrade.

### Commit 4: `footguns(cli)` (Python repo)

- **`query_string` soft-guard.** `repoindex/commands/ops.py` (and `audit`): the
  dead positional `query_string` (removed-DSL residue) is silently ignored, so
  `repoindex ops git push "language=='Python'"` acts on the WHOLE collection. Keep
  the `@click.argument` but, when it is non-empty, raise a clear migration error:
  "positional queries were removed in v0.16; use --language/--tag/--recent or
  `repoindex sql`". Apply across all ops/audit handlers that still declare it
  (~13 handlers). Fix the misleading DSL docstring examples in every handler.
- **`set-*` confirmation gate.** The six `ops set-*` handlers mutate N forge repos
  in `--all` mode with no prompt. Add `click.confirm` plus a `--yes/-y` flag, gated
  on `N > 1` AND not `--dry-run` AND not `--json` AND `isatty` (do not hang scripted
  or piped invocations). Mirrors the existing `ops git push` contract.

### Commit 5: `footguns(timespec)` (Python repo)

- **Unified parser.** Create `repoindex/services/timespec.py` with a single
  `parse_duration` implementing the locked semantics: `d`=days, `w`=weeks,
  `m`/`M`=months, `y`=years, `h`=hours, `min`=minutes; raise `ValueError` on
  unparseable input (no silent default). Route all four current parsers through it:
  `repoindex/services/flag_query.py` (around line 51), the events package
  (around line 199), `repoindex/commands/refresh.py` (around line 679), and the
  digest path. Re-point existing parser tests; add `tests/test_timespec.py` with a
  full matrix. CHANGELOG: `events --since 6m` and `digest --since 6m` now mean six
  months, not six minutes.

### Commit 6: `footguns(data)` (Python repo)

- **Populate `readme_content`.** The column is indexed in `repos_fts` and
  trigger-wired but never written. Populate it in the upsert path
  (`repoindex/database/repository.py` `_repo_to_record`, after README detection)
  with a truncated read (pick a cap, e.g. 100 KB, to bound memory and DB size).
  FTS triggers propagate automatically. This silently activates readme FTS search,
  the audit readme checks, and the arkiv export readme body. Tests: README repo
  yields non-NULL truncated content; `repos_fts MATCH` on README body returns the
  repo; arkiv exporter emits the body.

### Commit 7: `packaging` (Python repo)

- Remove `pathlib` (abandoned backport that shadows stdlib) and `tweepy` (unused)
  from `pyproject.toml` dependencies (around line 14) and from `requirements.txt`.
  Keep `toml` (still the only TOML writer at `pypi_metadata.py` around line 636);
  the `tomli_w` swap is deferred.
- Delete `requirements.txt` entirely (pyproject extras plus hatchling are the
  source of truth; `make install` already installs the package). Removes the drift
  class (phantom `Jinja2`).
- Set `requires-python = ">=3.10"`, update trove classifiers, update
  `codemeta.json` Python version. Add a CI matrix at `.github/workflows/` running
  3.10/3.11/3.12 (none exists today). Minimal: install, `pytest`, `mkdocs build
  --strict`.
- Version sync: bring `CITATION.cff` and `codemeta.json` (version, dateModified,
  releaseNotes URL) from their stale 0.10.1 up to the CURRENT package version
  (`pyproject` is 2.0.0 today). This commit fixes the drift; it does not pick the
  next release number. Delete stale `dist/` artifacts (0.15.3 wheels). Add a tiny
  check (test or `make` target) asserting equality across `pyproject`,
  `repoindex/__init__.__version__`, `CITATION.cff`, and `codemeta.json` so the
  drift class cannot recur.

### Release step (after all nine commits, not one of them)

The actual version bump to 2.1.0 and tag is a final release action, consistent with
prior practice (a `chore: bump to vX` commit plus tag). At that point all four
version sources move together to 2.1.0, the equality check from Commit 7 enforces
agreement, and the plugin `marketplace.json` / `plugin.json` are bumped to match.
PyPI upload remains held for burn-in per the project's established cadence.

### Commit 8: `docs` (Python repo)

- `mkdocs.yml` nav points at deleted `catalog-query.md` and `render.md` and omits
  `export.md`. Repoint render to export, drop the dead catalog-query entry, ensure
  `export.md` is reachable. `mkdocs build --strict` must pass.
- Onboarding breadcrumbs cite removed commands `repoindex query` and
  `repoindex init`. Fix the strings at `config.py` (around line 134, the config
  init footer), `status.py` (around line 150, the status footer), and
  `refresh.py` (around line 222, the "use repoindex init" hint). No `init` alias is
  added (out of scope); the strings point at real commands.
- README.md (around line 76) and `docs/index.md` (around line 185) reference a
  nonexistent `claude-code-marketplace`. Replace with `queelius/claude-anvil`.

### Commit 9: `plugin` (plugin repo, separate)

`/home/spinoza/github/alex-claude-plugins/repoindex`:
- Delete the dead `gitea_forks` reference in `agents/repo-explorer.md` (around line
  60; the correct unified fields are already on lines 58-59).
- Bring `.claude-plugin/marketplace.json` repoindex entry from its stale 0.16.0 up
  to the current package version (2.0.0) and refresh its description. (`plugin.json`
  is already 2.0.0; leave it, optionally fix the `repository` URL at line 10.) The
  move to 2.1.0 happens with the release step, alongside the package.
- `skills/workflows/SKILL.md`: replace the dead `@tag-name` DSL reference with the
  `--tag` flag.
- `agents/repo-polish.md`: minimal doc-only fix removing the false single-repo
  targeting promise (`"name == 'REPO'"` DSL examples that would scaffold across ALL
  repos); rewrite to use the filter flags or per-repo `cd`. The full single-repo
  workflow rewrite that needs `ops generate --name/--path` is deferred.

## Verification Strategy

Per fix:
- **Language detection**: characterization test pinning current primary-language
  output (incl `.r`/`.R` quirk, tie-break, EXCLUDE_DIRS pruning, the path-substring
  exclusion bug, empty repo to (None, [])); plus a timed before/after `refresh` on a
  repo set with a fat `.venv`.
- **Event executemany**: insert an overlapping batch twice, assert `events_added`
  counts only new rows.
- **cleanup batch**: N missing paths produce one DELETE (spy on execute), survivors
  untouched, exists()-semantics preserved.
- **get_schema views/fts**: in-memory schema, assert the three views and `repos_fts`
  present, shadow tables and `sqlite_%` absent.
- **get_manifest aggregates**: seed known dirty/unpushed/published/DOI/stale rows,
  assert exact counts.
- **query_string guard**: CliRunner test that the positional now errors with the
  migration message; flag-only path still resolves the filtered set; update existing
  `tests/test_ops*.py` that expect the old signature.
- **timespec**: full unit matrix incl `m`=months, `min`=minutes, `M` alias, raise on
  invalid; re-point existing events/digest/refresh/flag_query parser tests.
- **readme_content**: non-NULL truncated content, FTS MATCH hit, arkiv export body.
- **set-\* confirmation**: bulk prompts and aborts on "no", `--yes` bypasses,
  single-repo and `--json`/non-tty paths do not hang.
- **apply_schema preserve**: build a v9 DB with seeded external events (github_release,
  pr, star) and refresh_log, run migration to v10, assert those rows survive.
- **Zenodo concept_doi**: additive v9 to v10 migration with no data loss; a
  ZenodoRecord with both DOIs persists `doi`=version and `concept_doi`=concept via
  both the zenodo.py and repository_service.py paths.
- **Python floor / deps / version sync**: `python3.10 -c 'import repoindex.mcp.server'`
  passes; installed metadata has no `pathlib`/`tweepy`/`Jinja2`; version-equality
  check passes; CI matrix green on 3.10/3.11/3.12.
- **Docs / plugin**: `mkdocs build --strict` passes; grep guards assert no
  `repoindex query`/`repoindex init`/`claude-code-marketplace`/`gitea_forks`/
  `name ==` strings remain; `marketplace.json` version updated.

Owner-witnessed check: a timed `repoindex refresh` on the real ~200-repo collection
before and after the language-detection fix.

Baseline: 1848 tests passing today; this bundle must end green with new tests added.

## Non-Goals (explicitly deferred)

- Full ALTER migration ladder (architecture pass).
- `ops generate --name/--path` per-repo selector and the dependent repo-polish.md
  workflow rewrite (feature request).
- `cleanup_missing_repos` set-difference pruning (behavior change, not a free win).
- `tomli_w` swap to drop the `toml` dependency (unrelated cleanup).
- The four larger directions from the landscape (MCP self-teaching beyond the
  cheap surface wins, never-lose-work safety net, portfolio-as-graph, architecture
  honesty beyond the migration fix). These remain on the board for later brainstorms.

## Out-of-Grain Reminders (do not let the bundle drift into these)

- No writable SQL, no broad MCP mutation. The MCP changes here are read-surface only.
- `forge_id` stays single-valued in 2.x.
- No long-lived server, no second heavyweight UI.
- No query DSL revival; new expressiveness goes to SQL or additive columns/views.
- Notes/snapshots/forge fields remain enrichment, never the sole source of truth.
