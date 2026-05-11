# Collection Operations

The `ops` command group provides write operations across your repository
collection.

**Safety**: always preview with `--dry-run` first. Git push / pull require
confirmation (skip with `--yes`).

## Subcommands

```
repoindex ops
├── audit               Metadata completeness audit
├── git                 Multi-repo push / pull / status
├── generate            Boilerplate file generation (license, codemeta, ...)
├── mirror              Push --mirror to forges with role: mirror
├── sync                Clone repos you own on enumerable forges
├── wip-snapshot        Snapshot dirty working trees to origin wip/ branches
├── set-topics          Set topics on the repo's forge (cross-platform)
├── set-description     Set the forge-side description
├── set-archived        Archive / unarchive on the forge
├── set-visibility      Toggle public / private on the forge
├── set-default-branch  Change the forge's default branch
└── set-pages           Enable Pages (where supported by the forge)
```

Each subcommand accepts the four filter flags (`--dirty`, `--language`,
`--tag`, `--recent`). For filtering that does not fit the flags, query
the database via SQL first and pipe repo names in as needed.

## Metadata Audit

Check repositories across 4 categories with 3 severity levels.

**Categories**: essentials, development, discoverability, documentation
(plus identity when author is configured).
**Severity**: critical, recommended, suggested.

```bash
# Audit all repos (rich table by default)
repoindex ops audit

# Filter by category and severity
repoindex ops audit --category essentials
repoindex ops audit --severity critical

# Audit subset
repoindex ops audit --language python
repoindex ops audit --tag "work/*"

# Machine-readable output
repoindex ops audit --json
```

Typical audit findings: missing license, missing README, no remote,
missing `.gitignore`, no CI config, no description, no forge topics,
missing citation files, author not listed in `pyproject.toml`, and so
on.

## Git Operations

Push, pull, and check status across multiple repos.

```bash
# Push repos with unpushed commits
repoindex ops git push --dry-run
repoindex ops git push --language python
repoindex ops git push --yes              # Skip confirmation

# Pull updates
repoindex ops git pull
repoindex ops git pull --dirty --dry-run

# Multi-repo status
repoindex ops git status
repoindex ops git status --dirty --json
```

## File Generation

Generate boilerplate files across repos. Uses author info from config;
set it with `repoindex config set author.name "..."` etc.

```bash
# codemeta.json
repoindex ops generate codemeta --language python --dry-run

# LICENSE
repoindex ops generate license --license mit --dry-run
repoindex ops generate license --license apache-2.0 --dry-run

# .gitignore
repoindex ops generate gitignore --lang python --dry-run
repoindex ops generate gitignore --lang node --dry-run

# Community files
repoindex ops generate code-of-conduct --dry-run
repoindex ops generate contributing --dry-run

# Citation and documentation
repoindex ops generate citation --language python --dry-run
repoindex ops generate zenodo --dry-run
repoindex ops generate mkdocs --language python --dry-run
```

All generation commands support the filter flags and `--force` to
overwrite existing files.

The v1.x `ops generate gh-pages` command was removed in v2.0. Use
`repoindex ops set-pages <repo> --branch <b> --path <p>` instead,
which dispatches through the appropriate `GitForge` for each repo.

## Cross-Platform Forge Actions (`ops set-*`)

These commands change forge-side metadata (topics, description,
archived flag, visibility, default branch, Pages) on whichever
hosting platform owns each repo. They look up `forge_id` from
`remote_url` during refresh, then dispatch through the matching
`GitForge`. GitHub and Gitea (which drives Codeberg and Forgejo) are
supported today; adding GitLab or Sourcehut is a single new file
under `~/.repoindex/sources/forges/`.

Single-repo mode (positional `REPO`):

```bash
repoindex ops set-topics dreamlog python logic prolog
repoindex ops set-description dreamlog "Prolog with S-expressions"
repoindex ops set-archived old-experiment true
repoindex ops set-visibility private-thoughts private
repoindex ops set-default-branch repoindex main
repoindex ops set-pages metafunctor --branch gh-pages --path /
```

Bulk mode requires `--all` plus the standard filter flags:

```bash
repoindex ops set-topics --all --language python python cli
repoindex ops set-archived --all --tag legacy/* true --dry-run
```

If a forge does not implement a capability (Gitea's `enable_pages`
varies per instance), the per-repo row reports `skipped` with the
reason. Other failures stay isolated per-repo and do not poison the
batch.

## Sync

Clone repos you own on configured `GitForge` instances that aren't
present locally. Read-side complement to `ops mirror`. Strictly
additive: never deletes, never modifies existing repos.

```bash
# Preview what would be cloned from every enumerable forge
repoindex ops sync --all --dry-run

# Sync from a specific forge
repoindex ops sync --from codeberg

# Override destination root
repoindex ops sync --all --into ~/imports/

# Include archived repos
repoindex ops sync --all --include-archived

# Filter by name pattern
repoindex ops sync --all --filter "tools-*"
```

Destination resolution:

1. `--into PATH` (CLI override): `PATH/forge_id/repo_name`.
2. `forges.<name>.sync_into` from config: `<sync_into>/repo_name`.
3. Default: `~/github/imported/<forge_id>/<repo_name>`.

After sync completes, run `repoindex refresh` to index the new clones.

## Mirror

Push every branch and tag (`git push --mirror`) to one or more redundancy
targets configured under `forges:` with `role: mirror`:

```yaml
forges:
  codeberg:
    source_id: gitea
    host: codeberg.org
    role: mirror
    token_env: CODEBERG_TOKEN
    url_template: "https://codeberg.org/queelius/{repo}.git"
  gitea-gdrive:
    source_id: gitea
    role: mirror
    url_template: "file:///mnt/gdrive/git-mirrors/{repo}.git"
```

For each (repo, mirror) pair, the URL is resolved from an existing git
remote of the same name if present (user override wins), else added from
`url_template`. Fast-forward is enforced by default; use `--force` to
overwrite. `--init` creates missing bare repos for `file://` targets.

```bash
# Preview pushing every repo to Codeberg
repoindex ops mirror --to codeberg --dry-run

# Push all Python repos to every configured mirror
repoindex ops mirror --all --language python

# Mirror dirty repos to a local Gitea, initializing bare repos
repoindex ops mirror --to gitea-gdrive --dirty --init

# Force-push (overwrites diverged mirror branches)
repoindex ops mirror --to nas-backup --force
```

The top-level `mirrors:` config from v1.x is no longer read; if present
and non-empty, `ops mirror` prints a one-line migration hint and exits.

## WIP Snapshot

Snapshot dirty working trees to `wip/<hostname>/<date>` branches on
`origin`. Remote-recoverable, does not modify the working tree or main
branches. Safe to run anytime.

```bash
# Snapshot all dirty repos
repoindex ops wip-snapshot

# Preview first
repoindex ops wip-snapshot --dry-run

# Only Python repos
repoindex ops wip-snapshot --language python
```

Recovery:

```bash
git fetch origin wip/<hostname>/<date>
git checkout -b recovered FETCH_HEAD
```

## Combining Filters

Every `ops` subcommand supports the same four shorthand flags. Compose
them naturally:

```bash
repoindex ops audit --language python --severity critical
repoindex ops git push --tag "work/*" --dry-run
repoindex ops generate license --language rust --dry-run
repoindex ops mirror --to codeberg --recent 7d
```

For questions the flags cannot express, query the database:

```bash
# Find repos without license files via SQL, then operate
repoindex sql "SELECT name FROM repos WHERE has_license = 0"
```

The SQL surface is documented in `CLAUDE.md` and is part of the stable
contract; see `STABILITY.md`.
