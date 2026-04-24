# repoindex: Design

> **The filesystem is where your work lives. repoindex is where your work becomes legible.**

**Version**: 1.0 (design). Last refreshed 2026-04-24 for the v1.0 cut.

This document describes what repoindex is, why its pieces fit together the way
they do, and where to extend it. For the operational surface (commands,
flags, tables, configuration), see `CLAUDE.md`. For the backward-compatibility
contract at v1.0, see `STABILITY.md`.

---

## 1. What repoindex Is

repoindex is a catalog of the git repositories on your filesystem plus a
disciplined set of external enrichment sources (GitHub, PyPI, CRAN, Zenodo, and
several other registries). It exists so that an LLM (or a terminal user) can
answer questions like:

- Which of my Python repos have uncommitted changes?
- What did I tag or release in the last 30 days?
- Which repos are published on PyPI but have no CITATION.cff?
- What repos have GitHub stars above 10 but no license file?
- Show me everything tagged `work/active` that is not archived on GitHub.

It does not index the contents of repositories. It answers collection-level
questions about them. Claude Code works inside one repo at a time; repoindex
provides the awareness layer above that, so the assistant can decide which
repo to open, notice which ones are neglected, and surface what moved.

repoindex is deliberately not: a CI system, a GitHub mirror, a code search
tool, a project management tool, or a replacement for `gh`. It observes. The
only write operations it performs are on its own SQLite database, on symlink
trees it explicitly owns, or through explicit `ops` subcommands (mirror,
push/pull, generate boilerplate) that the user triggered.

---

## 2. The Central Decision: Path is Identity

Most tools that model collections of repositories key on a remote URL: they
treat `github.com/queelius/repoindex` as the canonical identity and the clone
on your disk as a cached pointer to it. repoindex inverts that model. The
identity of a repository is its **absolute filesystem path**. A second clone
at a different path is a separate entity. A repo with no remote is just as
first-class as one with a remote. A repo whose remote is unreachable, renamed,
or deleted does not break anything.

This reflects the reality of a working developer:

- Private, experimental, or archived work does not live on a hosting platform.
- The same remote can be cloned twice, intentionally, for parallel work.
- Ownership of a remote can change without your checkout moving.
- A repo can move or be renamed on disk (`git mv`) without any remote changing.
- You work from paths: `cd ~/github/foo`, not `cd remote:origin:...`.

Once the filesystem path is the primary key, several consequences cascade
through the rest of the design:

1. **Platform metadata is enrichment, not identity.** GitHub data,
   PyPI records, and DOI assignments attach to the path-keyed record, not the
   other way around. They are allowed to be missing. They are allowed to be
   stale. They are allowed to disagree with local reality, and when they do,
   local wins.

2. **Platform fields are namespaced.** `stars` is not a field on a repo.
   `github_stars` is. `version` is not a field. `pypi_version` and
   `cran_version` and `citation_version` are. Provenance is visible at the
   column level so it cannot be forgotten.

3. **No deduplication by remote.** Two paths are two repos. If the user
   wants them merged, they can write a SQL `GROUP BY remote_url`.

4. **Refresh is a one-way enrichment.** The local filesystem and the local
   git state are the ground truth. Refresh reads the filesystem, then reads
   external APIs, and merges their output into the database as namespaced
   columns. It never writes back to the filesystem or the remotes.

5. **Offline works.** Without network access or any configured platform
   token, repoindex still answers every local question: what exists, what is
   dirty, what has a README, what is Python. External enrichment simply
   becomes NULL.

This inversion is the reason repoindex is useful at all. It is what makes
the tool correct for private work, for archaeology across years of
directories, and for users who maintain anywhere from one to a thousand
repositories without wanting a single platform's metadata to define their
collection.

---

## 3. Architecture

repoindex is a layered CLI over a SQLite database, with external APIs and git
treated as infrastructure. The layers are strict; higher layers depend on
lower layers, never the other way.

```
Commands (CLI, Click)
  repoindex/commands/*.py, repoindex/cli.py
         |
         v
Services (business logic)
  repoindex/services/*.py
         |
         +---> Database (SQLite abstraction, schema migrations, queries)
         |       repoindex/database/*.py
         |
         +---> Infrastructure (git subprocess, GitHub API, Zenodo API, files)
         |       repoindex/infra/*.py
         |
         +---> Domain (frozen dataclasses: Repository, Tag, Event, ...)
                 repoindex/domain/*.py
```

**Domain** is the only layer allowed to have no I/O. Every dataclass is
frozen. The layer holds the shape of the system: what a `Repository`, an
`Event`, an `AuditCheck`, an `OperationDetail` are. Tests at this level need
no mocks and no filesystem.

**Database** wraps SQLite behind a `Database` context manager with a
schema-version migration system and typed query helpers. The database file
lives at `~/.repoindex/index.db`. Read-only connections are enforced at the
SQLite level (via `mode=ro` URI parameter) so read paths cannot accidentally
mutate. The schema is documented in `CLAUDE.md` and, more authoritatively,
lives in `repoindex/database/schema.py`.

**Infrastructure** holds git subprocess wrappers, the GitHub client, the
Zenodo client, PyPI metadata fetch, and file-store helpers. Everything that
reaches outside the process lives here. Services depend on these through
their interfaces so tests mock exactly one layer.

**Services** hold business logic: repository discovery, tag manipulation,
event scanning, auditing, git operations, copy, link tree maintenance,
boilerplate generation, mirror coordination, WIP snapshots. A service takes
a `config` object in its constructor, yields progress strings, and stores
results on `self.last_*` attributes. Commands import services; services
never import from commands.

**Commands** are thin Click wrappers. They parse arguments, call a service,
and render output. Two rules:

- Pretty output is the default for interactive human use.
- `--json` produces newline-delimited JSON (JSONL) on stdout. Errors always
  go to stderr as structured JSON: `{"error": "...", "type": "...", "context": {...}}`.

Because the command layer is thin, a new feature almost always lives in a
service; the command is a 50-line wrapper on top. This is deliberate: the
MCP server is also a thin wrapper that reuses the same underlying code (it
mostly calls services directly, or shells out to the CLI when the CLI
formatting is what the user wants).

---

## 4. The Database as Materialized View

repoindex uses a CQRS pattern. One command writes; all the others read.

- `refresh` is the writer. It walks the configured `repository_directories`,
  updates every repo's row, runs each enabled `MetadataSource` in parallel,
  scans events out of the reflog and working tree, and populates the
  `publications` and `scan_errors` and `refresh_log` tables. It is the
  expensive operation, and it is the only one that costs real time.
- Every other command reads from the database only. `status`, `show`,
  `events`, `digest`, `export`, `copy`, `link`, `ops audit`, and the MCP
  server's `run_sql`, `get_manifest`, `get_schema`, `export`, `tag` tools
  all open the database in read-only mode.

The database is therefore a **materialized view** of the filesystem and
external state. Like any materialized view, it is:

- **Stale by design**, between refreshes. The trade-off is fast reads. A
  `repoindex status` or `repoindex sql "..."` returns in milliseconds
  against a local SQLite file, not against GitHub rate limits.
- **Reproducible**. Two refreshes of the same tree converge on the same
  state (minus event append-only history and external platform drift).
- **Replaceable**. `repoindex sql --reset` drops it. `refresh --full`
  rebuilds it. Nothing is ever stored only in the database that cannot be
  recovered from the filesystem plus external APIs.

Events are the one table with append-only semantics. Events are scanned by
stable `event_id` and deduplicated via `INSERT OR IGNORE`. Old events are
kept even if the source branch or ref is gone. This makes `events` and
`digest` function as a historical log, not a snapshot.

The `refresh_log` table records each refresh run, what sources were enabled,
and how long it took, which is what `digest` and `status` use to tell the
user whether their data is fresh.

---

## 5. Extension Points

There are two places where repoindex is designed to be extended by users.
Both discover Python modules from fixed directories at import time.

### MetadataSource (read-side enrichment)

`repoindex/sources/__init__.py` defines a single abstract base class,
`MetadataSource`, with two concrete methods:

- `detect(repo_path, repo_record)` returns True if the source applies to
  this repo.
- `fetch(repo_path, repo_record, config)` returns a dict of metadata.

Each source declares a `target`: either `"repos"` (merge fields into the
repos table as namespaced columns, for platform enrichment like GitHub, or
local file parsing like CITATION.cff) or `"publications"` (upsert into the
publications table for registry discovery like PyPI, CRAN, npm, Cargo,
Zenodo). Sources may also declare `batch = True`, which causes a one-shot
`prefetch(config)` to run before per-repo iteration (Zenodo's ORCID search
uses this).

Built-in sources live in `repoindex/sources/`:

- target=repos: `citation_cff`, `keywords`, `local_assets`, `gitea`, `github`
- target=publications: `pypi`, `cran`, `zenodo`, `npm`, `cargo`, `conda`,
  `docker`, `rubygems`, `go`

User-provided sources are discovered from `~/.repoindex/sources/*.py` and
must export a module-level `source` attribute that is a `MetadataSource`
instance. The discovery function accepts an `only` filter, which is how the
refresh command selects sources via `--source <id>` or `--external`.

Source failures never kill a refresh. An error on one source for one repo
logs and continues; the `scan_errors` table records what went wrong.

### Exporter (write-side rendering)

`repoindex/exporters/__init__.py` defines `Exporter` with one method:
`export(repos, output, config)`. Each exporter declares a `format_id`, a
`name`, and a default file `extension`.

Built-in exporters: `bibtex`, `csv`, `markdown`, `opml`, `jsonld`, `arkiv`.
The default `repoindex export -o <dir>` command produces a
longecho-compliant arkiv archive: a directory with JSONL data, a schema
file, a queryable SQLite copy, and an interactive HTML browser based on
sql.js.

User-provided exporters are discovered from `~/.repoindex/exporters/*.py`
and must export a module-level `exporter` attribute.

### Why exactly two ABCs

The previous design had three: `PlatformProvider`, `RegistryProvider`, and
`Exporter`, where platforms enriched repos and registries detected
publications. That split was incidental, not essential: both sides
fundamentally answered "is this relevant, and if so what data do I
contribute?" Collapsing them into a single `MetadataSource` with a `target`
discriminator removed a parallel implementation and let the refresh
dispatcher treat them uniformly. The split exists now only where it
matters, inside `fetch`, which returns a dict shaped for its target table.

---

## 6. Two Query Layers

repoindex used to have three query layers: filter flags, a DSL, and raw
SQL. The DSL has been removed. There are now two.

### Filter flags (for humans at a terminal)

Four flags, the common ones, available on every operation command:

- `--dirty` : repos with uncommitted or unpushed changes.
- `--language <name>` : repos whose detected primary language matches.
- `--tag <pattern>` : repos with a tag matching the glob pattern.
- `--recent <duration>` : repos with commits within a `7d`/`30d`/`2w` window.

These exist because they are the questions a human types frequently enough
that having to write SQL for them is friction.

### SQL (for everything else)

Anything more expressive uses `repoindex sql "..."` at the CLI, or
`run_sql` on the MCP server. The database schema is documented and stable
(see `STABILITY.md`), FTS5 is available on repo name/description/readme,
and all the GitHub, PyPI, CRAN, and citation fields are namespaced and
queryable.

### Why the DSL was removed

A DSL that is not SQL is almost always a worse SQL. The previous one
parsed expressions like `language == 'Python' and github_stars > 10`,
compiled them to SQL, and added fuzzy matching and view references on top.
In practice:

- LLMs write SQL much better than they write a one-project DSL.
- Users who wanted power used SQL directly.
- Users who did not want power used the filter flags.
- Maintaining the compiler, the fuzzy matcher, and the views system was
  substantial weight for a narrow middle group.

Removing it simplified the codebase by thousands of lines, eliminated two
command surfaces (`query` and `view`), and pushed every non-trivial
question to SQL, where the documentation already lived.

---

## 7. LLM Integration via MCP

The MCP server (`repoindex/mcp/server.py`) exposes six tools over stdio:

- `get_manifest` : tables, row counts, last refresh, languages summary.
- `get_schema(table?)` : SQL DDL for the whole database or one table, with
  column details when a table is specified.
- `run_sql(query)` : read-only SQL (SELECT and WITH only), returning up to
  500 rows as JSON. Read-only is enforced by the SQLite connection mode.
- `refresh(github?, pypi?, cran?, external?, full?)` : trigger a refresh.
  Holds a file lock so concurrent refreshes cannot clobber each other.
- `tag(repo, action, tag)` : add, remove, or list user tags on a repo.
- `export(output_dir, language?, dirty?, tag?, recent?)` : produce a
  longecho-compliant arkiv archive.

The design choice driving this surface is: **SQL is the API.** Rather than
expose dozens of narrow tools ("list repos by language", "get repos with
DOIs", "count events this week"), the MCP exposes schema introspection
plus raw read-only SQL. This lets the assistant:

- Discover what tables exist without the server pre-deciding what matters.
- Compose queries the tool designer did not anticipate.
- Explain its work in a language (SQL) the user can verify.

The narrow tools (`refresh`, `tag`, `export`) exist only because their
effect is a state change, which SQL by itself cannot express, or because
the output (a full arkiv directory) is too large to return inline.

This makes the MCP server the dominant consumer of repoindex in practice.
Every design decision should ask: can an LLM, with only schema and SQL,
answer this? If yes, that is the shape. If no, add a tool.

---

## 8. Commitments and Non-Commitments

At v1.0 repoindex commits to a backward-compatibility contract over:

- The **SQL schema** enumerated in `STABILITY.md` (repos, events, tags,
  publications, scan_errors, refresh_log, repos_fts).
- The **MCP tool names and argument shapes**.
- The **CLI commands and filter flags** currently documented.
- The **config file top-level keys**.
- The **MetadataSource and Exporter ABC signatures**.
- The **user-directory discovery contract** (`~/.repoindex/sources/*.py`,
  `~/.repoindex/exporters/*.py`).

It does not commit to:

- The Python API of `repoindex.services.*`. Services are internal.
- Indexes, triggers, and FTS internals on top of the documented tables.
- The exact text of log messages, warning text, or pretty (non-JSON) output.
- Tag derivation heuristics. The set of implicit tags is expected to evolve.

Additions to any stable surface are minor releases. Removals are major
bumps and will be preceded by at least one 1.x release with a runtime
deprecation warning. See `STABILITY.md` for the details.

---

## Appendix: Design Anti-Patterns to Keep Avoiding

A short list, written down so future changes do not regress:

- **Do not make remote URL the identity.** It is tempting when writing a
  merge strategy. Resist it. Two paths with the same remote are two repos.
- **Do not un-namespace platform fields.** Keep the `github_`, `pypi_`,
  `cran_`, `gitea_`, `citation_` prefixes. Provenance at the column is
  worth the extra characters.
- **Do not add a new DSL.** If SQL is awkward for a specific use case, add
  a view or a computed column to the schema, or a filter flag if it is
  common enough. Do not invent a sublanguage.
- **Do not split the schema into per-platform tables.** `github_metadata`,
  `pypi_metadata`, and so on would make joins for common queries
  ("stars + recent commits") harder for no real gain. The one wide `repos`
  table with namespaced columns is the right shape.
- **Do not add write operations to MCP without strong justification.**
  `refresh`, `tag`, and `export` are the current carve-outs. Read-only SQL
  is the main channel.
- **Do not regress on offline operation.** Every read command must work
  with no network and no tokens configured; external fields simply become
  NULL.
