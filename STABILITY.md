# repoindex: Stability and Compatibility

This document is the backward-compatibility contract for repoindex 1.x. It
defines what is guaranteed to keep working across 1.x releases, what is
explicitly reserved for change, and how deprecations and removals are
handled.

See `DESIGN.md` for the rationale behind each surface. See `CLAUDE.md` for
the currently documented shape of commands, tables, and configuration.

---

## What "Stable" Means in 1.x

A **stable surface** may be extended in a minor release (1.1, 1.2, ...).
Extensions are additive and backward-compatible: new columns, new tools,
new flags, new config keys, new exporters. If you wrote a query, a script,
or a tool against the 1.0 surface and follow the rules in the relevant
section below, that query or script continues to work on any 1.x release.

Surfaces not listed below are **internal** and may change at any time.
This document is the definitive list. If something is not mentioned here,
assume it is internal.

---

## 1. SQL Schema (Stable)

The following tables and their currently documented columns are stable:

- `repos`
- `events`
- `tags`
- `publications`
- `scan_errors`
- `refresh_log`
- `repos_fts` (FTS5 virtual table over `repos`)

The exact columns, types, and constraints as of v1.0 are defined in
`repoindex/database/schema.py` and summarized in `CLAUDE.md`.

**Allowed in a 1.x minor release:**

- Adding a new column to any of the above tables. New columns will be
  nullable or have a sensible default, so existing `SELECT *` and
  explicit-column queries keep working.
- Adding a new table.
- Adding indexes, triggers, or additional FTS tokenizers as internal
  optimizations.
- Incrementing the schema version and running an additive migration.

**Not allowed in 1.x (requires 2.0):**

- Removing a documented column.
- Changing a column type in a way that breaks existing reads (for
  example, changing `github_stars` from INTEGER to TEXT).
- Renaming a documented column.
- Removing or renaming any of the seven documented tables.

Indexes, triggers, and FTS internals beyond the existence of `repos_fts`
are internal and may be reorganized. If you rely on a specific index for
query performance, your query is still correct across releases, but its
plan may change.

---

## 2. MCP Tool Contract (Stable)

The MCP server exposes exactly these six tools at v1.0:

- `get_manifest()`
- `get_schema(table: str | None = None)`
- `run_sql(query: str)`
- `refresh(github: bool = False, pypi: bool = False, cran: bool = False, external: bool = False, full: bool = False)`
- `tag(repo: str, action: str, tag: str = "")`
- `export(output_dir: str, language: str = "", dirty: bool = False, tag: str = "", recent: str = "")`

**Allowed in a 1.x minor release:**

- Adding a new tool to the server.
- Adding a new **optional** parameter with a default value to any tool.
- Adding new keys to response dictionaries. Consumers must tolerate unknown
  keys.
- Tightening input validation in ways that reject previously malformed
  input (for example, clearer error messages for invalid SQL).

**Not allowed in 1.x:**

- Removing a tool.
- Removing or renaming a parameter.
- Changing the semantics of an existing parameter (for example, redefining
  what `full=True` means for `refresh`).
- Removing documented keys from response envelopes.
- Making a previously optional parameter required.

Error responses use the envelope `{"status": "error", "error": "..."}`.
The `error` value is a string and its exact wording is not stable. The
`status` key and the contract of "success returns structured data,
failure returns an object with `status: error`" are stable.

---

## 3. CLI Command Surface (Stable)

At v1.0, these commands exist and accept their currently documented flags:

- `repoindex status`
- `repoindex events`
- `repoindex sql`
- `repoindex refresh`
- `repoindex show`
- `repoindex digest`
- `repoindex export`
- `repoindex copy`
- `repoindex link` (with subcommands `tree`, `refresh`, `status`)
- `repoindex ops` (with subcommands `git`, `generate`, `github`, `audit`,
  `mirror`, `wip-snapshot`)
- `repoindex tag` (with subcommands `add`, `remove`, `list`, `tree`, `move`)
- `repoindex config` (with subcommands `show`, `get`, `set`, `unset`,
  `init`, `repos`)
- `repoindex mcp`

The hidden `db` command is a deprecated alias for `sql` and will remain
available in 1.x.

**Allowed in a 1.x minor release:**

- Adding a new command.
- Adding a new subcommand to `ops`, `tag`, `link`, or `config`.
- Adding a new flag to any command. New flags have sensible defaults so
  that existing invocations behave unchanged.
- Adding new columns to pretty table output (non-`--json` rendering).
- Adding new fields to JSONL output. Consumers must tolerate unknown
  keys in the JSON.

**Not allowed in 1.x:**

- Removing a command or subcommand.
- Removing a documented flag.
- Changing the semantics of a flag (for example, redefining what
  `--language python` selects).
- Removing documented fields from JSONL output.

Pretty (non-`--json`) output formatting is **not stable**. Column order,
column width, colors, and prose are free to change across minor releases.
Scripts that parse human output are not supported; use `--json`.

---

## 4. Filter Flags on Operation Commands (Stable)

The four filter flags available on operation commands (`copy`, `export`,
`ops audit`, `ops git`, `ops generate`, `ops mirror`, `ops wip-snapshot`,
`ops github`, `link tree`) are stable:

- `--dirty`
- `--language <name>`
- `--tag <pattern>` (supports glob wildcards like `work/*`)
- `--recent <duration>` (for example `7d`, `30d`, `2w`)

The semantics of each flag, as documented in `CLAUDE.md` and each
command's `--help`, will not change in 1.x.

Additional filter flags may be added. Removals require a major bump.

---

## 5. Configuration File (Stable)

The configuration file at `~/.repoindex/config.yaml` has these stable
top-level keys:

- `repository_directories`
- `exclude_directories`
- `github`
- `mirrors`
- `author`
- `repository_tags`
- `refresh`

The shape of each section as documented in `CLAUDE.md` and the example
config generated by `repoindex config init` is stable.

**Allowed in a 1.x minor release:**

- Adding new top-level keys.
- Adding new sub-keys under any existing section.
- Adding new environment variables that override config values.

**Not allowed in 1.x:**

- Removing a documented top-level key or sub-key.
- Changing the type of a documented key (for example, making a list into a
  string).
- Changing the semantics of a documented key.

The legacy JSON config format is still auto-migrated to YAML on first
read. This migration path is stable for the life of 1.x.

The `REPOINDEX_CONFIG` environment variable for overriding the config
path is stable.

---

## 6. Extension ABCs (Stable)

### MetadataSource

Defined in `repoindex.sources`. Stable surface:

- Class name: `MetadataSource`
- Attributes: `source_id`, `name`, `target`, `batch`
- Abstract methods: `detect(repo_path, repo_record)`,
  `fetch(repo_path, repo_record, config)`
- Optional method: `prefetch(config)` for `batch = True` sources
- Valid values of `target`: `"repos"`, `"publications"`
- Discovery: user sources loaded from `~/.repoindex/sources/*.py`, each
  exporting a module-level `source` attribute

`discover_sources(user_dir=None, only=None)` is the stable discovery API.

### Exporter

Defined in `repoindex.exporters`. Stable surface:

- Class name: `Exporter`
- Attributes: `format_id`, `name`, `extension`
- Abstract method: `export(repos, output, config)`
- Discovery: user exporters loaded from `~/.repoindex/exporters/*.py`, each
  exporting a module-level `exporter` attribute

`discover_exporters(user_dir=None, only=None)` is the stable discovery
API.

**Allowed in a 1.x minor release:**

- Adding new optional methods to either ABC (with default implementations).
- Adding new attributes with defaults.
- Adding new values to `target` (with dispatcher support).

**Not allowed in 1.x:**

- Removing an abstract method.
- Changing the signature of `detect`, `fetch`, or `export`.
- Removing attributes.
- Changing the discovery directory or the `source` / `exporter`
  module-attribute contract.

User-provided source and exporter modules written against the 1.0 ABCs
will keep loading under any 1.x release.

---

## 7. What Is Explicitly Not Stable

The following may change at any point within 1.x without a deprecation
cycle:

- **Services package (`repoindex.services.*`).** These are internal.
  Classes, method signatures, and their division of responsibilities may
  change. Do not import from `repoindex.services` in third-party code.
- **Infrastructure package (`repoindex.infra.*`).** Internal.
- **Domain package (`repoindex.domain.*`).** The dataclass shapes are used
  within the service and command layers but are not a public API. Field
  names may change; new frozen fields may be added.
- **Database indexes, triggers, FTS tokenizers.** These are performance and
  internal-consistency concerns. The presence of the documented tables and
  columns is stable; everything else around them is not.
- **Pretty output.** Column order, column widths, row formatting, colors,
  and wording in non-JSON output may change across minor releases.
- **Log messages, warning text, error message wording.** Strings printed
  to stderr are for humans; their exact content is not stable.
- **Tag derivation heuristics.** The set of implicit tags emitted from
  `source='implicit'` or `source='github'` during refresh (for example,
  `lang:python`, `dir:github`, `topic:machine-learning`) may grow or
  shrink. Explicit user tags (`source='user'`) are stable: a tag the user
  added continues to be present.
- **Digest output shape.** The `digest` command may add or reorganize
  sections across minor releases.

---

## 8. Deprecation Policy

Anything documented in sections 1 through 6 above is removed only after a
deprecation cycle. The cycle is:

1. A 1.x release introduces a runtime deprecation warning (on stderr for
   CLI use; in the response envelope for MCP tools) and documents the
   replacement in `CHANGELOG.md` under that version's notes.
2. The deprecation warning persists for at least one more 1.x release.
3. Removal happens no earlier than the next major version (2.0), or in a
   later 1.x release explicitly noted in the changelog.

This applies to:

- CLI commands, subcommands, and flags.
- Config keys.
- MCP tools and tool parameters.
- Schema columns.
- ABC methods and attributes.

The hidden `db` command alias is an example of the pattern already in
place: it is kept available but marked deprecated, with `sql` as the
supported name.

---

## 9. Version Policy

repoindex follows semantic versioning with the surfaces above as the
contract.

- **Patch releases (1.0.x)**: bug fixes, no surface changes.
- **Minor releases (1.x.0)**: additive changes to any stable surface.
  Deprecation warnings may begin here. Internal surfaces may change
  freely.
- **Major releases (2.0, 3.0)**: may remove deprecated surfaces, change
  documented types, reorganize tables, or redefine flag semantics. The
  changelog will explicitly list every breaking change and its migration
  path.

If you want to pin to a known-good surface, pin to `repoindex>=1.0,<2.0`.
If you want only patch fixes, pin to `repoindex~=1.0.0`.

---

## 10. Reporting a Break

If you find that something documented here stopped working in a 1.x
release, that is a bug. Open an issue at
https://github.com/queelius/repoindex/issues with:

- The version you were running.
- The surface that broke (section number from this document).
- A minimal reproducer (a SQL query, a command line, an MCP call).
- What you expected to happen and what happened instead.

Backward-compatibility bugs in stable surfaces are treated as regressions
and fixed in the next patch release.
