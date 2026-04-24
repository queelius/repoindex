# Collection Operations

The `ops` command group provides write operations across your repository
collection.

**Safety**: always preview with `--dry-run` first. Git push / pull require
confirmation (skip with `--yes`).

## Subcommands

```
repoindex ops
├── git              # Multi-repo push / pull / status
├── generate         # Boilerplate file generation (license, codemeta, ...)
├── github           # GitHub write ops (topics, description) via gh CLI
├── audit            # Metadata completeness audit
├── mirror           # Push every branch and tag to configured redundancy targets
└── wip-snapshot     # Snapshot dirty working trees to origin wip/ branches
```

Each subcommand accepts the four filter flags (`--dirty`, `--language`,
`--tag`, `--recent`). For filtering that does not fit the flags, query
the database via SQL first and pipe repo names in as needed.

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
missing `.gitignore`, no CI config, no description, no GitHub topics,
missing citation files, author not listed in `pyproject.toml`, and so
on.

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
repoindex ops generate gh-pages --dry-run
```

All generation commands support the filter flags and `--force` to
overwrite existing files.

## GitHub Operations

Set GitHub topics and descriptions across repos. Requires the `gh` CLI
installed and authenticated.

```bash
# Sync pyproject.toml keywords as GitHub topics
repoindex ops github set-topics --from-pyproject --language python --dry-run

# Set specific topics
repoindex ops github set-topics --topics python,cli,tools --dry-run

# Set description from pyproject.toml
repoindex ops github set-description --from-pyproject --dry-run
```

## Mirror

Push every branch and tag (`git push --mirror`) to one or more named
redundancy targets defined in `~/.repoindex/config.yaml`:

```yaml
mirrors:
  - name: codeberg
    url_template: "https://codeberg.org/queelius/{repo}.git"
  - name: gitea-gdrive
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
