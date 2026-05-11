# repoindex: Design

> **The filesystem is where your work lives. repoindex is where your work becomes legible.**

**Version**: 2.0 (design). Refreshed 2026-05-11 for the v2.0 cut.

This document describes what repoindex is, why its pieces fit together the way
they do, and where to extend it. For the operational surface (commands,
flags, tables, configuration), see `CLAUDE.md`. For the backward-compatibility
contract at v2.0, see `STABILITY.md`.

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

2. **Forge metadata is unified, with provenance carried in `forge_id`.**
   A repo has one `stars` column, one `topics` column, one `is_archived`
   flag, populated by whichever GitForge owns its `remote_url`. Provenance
   is carried in `forge_id` (and `forge_host` for self-hosted instances).
   Registry-side fields stay namespaced: `pypi_version`, `cran_version`,
   `citation_version`, because a single repo can publish to many registries
   simultaneously while it can only live on one canonical forge.

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
  updates every repo's row, resolves each repo's `forge_id` from its remote
  URL, runs each enabled `Source` in parallel, scans events out of the
  reflog and working tree, and populates the `publications`, `scan_errors`,
  and `refresh_log` tables. It is the expensive operation, and it is the
  only one that costs real time.
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

There are two extension points: `Source` (read-side enrichment, plus
write actions on git forges) and `Exporter` (write-side rendering). Both
discover Python modules from fixed directories at import time.

### The Source hierarchy

`repoindex/sources/__init__.py` defines a three-level type tree:

```
Source                              abstract base; declares detect() and fetch()
├── LocalScanner                    no network, no auth; output to repos table
└── RemoteSource                    network-backed, has auth
    ├── GitForge                    hosts the git repo; output to repos table
    └── Registry                    publishes packaged artifacts; output to publications
```

Every concrete source overrides two methods:

- `detect(repo_path, repo_record)` returns True if the source applies to
  this repo. (For batch sources, this returns True unconditionally; the
  actual matching happens inside `fetch`.)
- `fetch(repo_path, repo_record, config)` returns a dict of metadata, or
  `None` when there is nothing to contribute.

Where the data lands is determined by the subclass, not by a discriminator
field. `LocalScanner` and `GitForge` populate the `repos` table; `Registry`
populates the `publications` table. The refresh dispatcher uses `isinstance`
to route the dict to the right writer.

Built-in sources live in three subdirectories:

- `sources/scanners/`: `citation_cff`, `keywords`, `local_assets`.
- `sources/forges/`: `github`, `gitea` (also drives Codeberg, Forgejo).
- `sources/registries/`: `pypi`, `cran`, `zenodo`, `npm`, `cargo`, `conda`,
  `docker`, `rubygems`, `go`.

`Registry` carries a `batch` flag for sources that prefetch in bulk; Zenodo
sets it. Their `prefetch(config)` runs once before per-repo iteration.

User extensions follow the same shape:
`~/.repoindex/sources/scanners/*.py`,
`~/.repoindex/sources/forges/*.py`,
`~/.repoindex/sources/registries/*.py`. Each module exports a module-level
`source` attribute that is an instance of the appropriate subclass.

Source failures never kill a refresh. An error on one source for one repo
logs and continues; the `scan_errors` table records what went wrong.

### GitForge optional capabilities

`GitForge` declares optional write methods that default to raising
`NotImplementedError`. Each implementation overrides whichever methods the
platform supports:

- `enumerate_user_repos(config)`: paginated listing of the user's repos.
- `set_topics(repo_record, topics, config)`: replace the topic list.
- `set_description(repo_record, description, config)`
- `set_archived(repo_record, archived, config)`
- `set_visibility(repo_record, public, config)`
- `set_default_branch(repo_record, branch, config)`
- `enable_pages(repo_record, branch, path, config)`

The `ops set-*` commands look up a repo's `forge_id`, find the GitForge
with the matching `source_id`, and dispatch. Gitea (which drives Codeberg)
declines `enable_pages` because Pages support varies per Gitea instance.
The CLI surfaces the `NotImplementedError` cleanly: "this forge does not
support enable_pages".

`ops sync` is the read-side dual of `ops mirror`. It calls
`enumerate_user_repos` on each forge configured in `forges:`, then clones
any repos not already present locally.

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

### Why a hierarchy instead of a flat ABC

The v1.0 design had a single `MetadataSource` ABC with a `target: str`
discriminator. Three different concerns (read-only file scanners, git
hosting platforms, package registries) were collapsed into one shape, and
the differences leaked through `target` checks and conditional branches.

Git forges have write capabilities (topics, archived flag, visibility) that
registries and scanners do not. The flat ABC could not express that without
stub methods raising on every non-forge source. v2.0 promotes the
distinction into the type system: `GitForge` carries the cross-platform
write surface as proper methods, scanners stay simple, registries stay
narrow.

The schema benefits too. v1.0 had `github_*` and `gitea_*` per-platform
columns. v2.0 has `forge_id` plus generic `topics`, `is_archived`, `stars`,
`pages_url`, populated by whichever GitForge owns the repo. Adding GitLab
or Sourcehut is now a single new file in `sources/forges/`, with no schema
churn and no special cases.

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

### Forge config and mirrors

Forge auth, host overrides, and redundancy targets all live in one
top-level config section, `forges:`. Each entry has a `role`:

- `primary` (default): the canonical forge for repos whose `remote_url`
  resolves to its host. `forge_id` resolution discovers these passively
  from the URL.
- `mirror`: a redundancy destination. `ops mirror` walks these, fetches,
  fast-forward-checks, then pushes `--mirror` to each.

Both roles share the same configuration shape (token_env, host,
url_template, source_id). A forge entry can serve as both a metadata
source and a mirror target; the role is orthogonal to read ability.

`url_template` is a `str.format()` template with a single `{repo}`
placeholder. Mirror push uses it to compute the destination URL when the
local repo doesn't already have a remote with the forge's name; if it
does, the existing remote URL wins and the template is informational.

This collapses what used to be two parallel config sections (`mirrors:`
and per-source auth blocks) into one. It also future-proofs `role:
archive` for read-only snapshots without needing yet another section.

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

At v2.0 repoindex commits to a backward-compatibility contract over:

- The **SQL schema v9** enumerated in `STABILITY.md` (repos with unified
  `forge_*` columns, events, tags, publications, scan_errors,
  refresh_log, repos_fts).
- The **MCP tool names and argument shapes** (six tools, unchanged from
  v1.x).
- The **CLI commands and filter flags** currently documented, including
  the cross-platform `ops set-*` and `ops sync` surface added in v2.0.
- The **config file top-level keys**, including the unified `forges:`
  section.
- The **Source / LocalScanner / GitForge / Registry ABC signatures** and
  the **Exporter ABC signature**. `GitForge` optional capability methods
  have stable signatures; `NotImplementedError` is a valid response from
  a forge that doesn't support a given capability.
- The **user-directory discovery contract** for
  `~/.repoindex/sources/{scanners,forges,registries}/*.py` and
  `~/.repoindex/exporters/*.py`.

It does not commit to:

- The Python API of `repoindex.services.*`. Services are internal.
- Indexes, triggers, and FTS internals on top of the documented tables.
- The exact text of log messages, warning text, or pretty (non-JSON) output.
- Tag derivation heuristics. The set of implicit tags is expected to evolve.

Additions to any stable surface are minor releases. Removals are major
bumps and will be preceded by at least one 2.x release with a runtime
deprecation warning. See `STABILITY.md` for the details.

---

## Appendix: Design Anti-Patterns to Keep Avoiding

A short list, written down so future changes do not regress:

- **Do not make remote URL the identity.** It is tempting when writing a
  merge strategy. Resist it. Two paths with the same remote are two repos.
- **Do not re-namespace forge fields by platform.** v2.0 collapsed the
  parallel `github_*` and `gitea_*` columns into unified `forge_*` columns
  with `forge_id` carrying provenance. Adding a third platform should be
  a new GitForge subclass, not a new column family. Registry fields stay
  namespaced (one repo can publish to many registries simultaneously); the
  forge analog does not apply (one repo lives on one canonical forge).
- **Do not add a new DSL.** If SQL is awkward for a specific use case, add
  a view or a computed column to the schema, or a filter flag if it is
  common enough. Do not invent a sublanguage.
- **Do not split the schema into per-platform tables.** `github_metadata`,
  `gitlab_metadata`, and so on would make joins for common queries
  ("stars + recent commits") harder for no real gain. The one wide `repos`
  table with unified forge columns is the right shape.
- **Do not add write operations to MCP without strong justification.**
  `refresh`, `tag`, and `export` are the current carve-outs. Read-only SQL
  is the main channel.
- **Do not regress on offline operation.** Every read command must work
  with no network and no tokens configured; external fields simply become
  NULL.
- **Do not hardcode a GitForge implementation in command logic.** All
  cross-platform actions dispatch through `forge_id` and the GitForge ABC.
  `ops github` was the v1.x violation of this; v2.0 deleted it.
