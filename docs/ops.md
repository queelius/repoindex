# Collection Operations

The `ops` command group provides write operations across your repository collection.

**Safety**: Always preview with `--dry-run` first. Git push/pull require confirmation (skip with `--yes`).

## Git Operations

Push, pull, and check status across multiple repos. Supports the same query flags as `query`.

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
**Severity**: critical, recommended, suggested

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

The audit checks for things like: missing license, missing README, no remote, no .gitignore, missing CI config, no description, no topics, missing citation files, etc.

## File Generation

Generate boilerplate files across repos. Uses author info from config (`repoindex config get author`).

```bash
# Generate codemeta.json
repoindex ops generate codemeta --language python --dry-run

# Generate LICENSE files
repoindex ops generate license --license mit --no-license --dry-run
repoindex ops generate license --license apache-2.0 --dry-run

# Generate .gitignore
repoindex ops generate gitignore --lang python --dry-run
repoindex ops generate gitignore --lang node --dry-run

# Generate community files
repoindex ops generate code-of-conduct --dry-run
repoindex ops generate contributing --dry-run

# Generate citation and documentation
repoindex ops generate citation --language python --dry-run
repoindex ops generate zenodo --has-citation --dry-run
repoindex ops generate mkdocs --language python --dry-run
repoindex ops generate gh-pages --dry-run
```

All generation commands support query flags (`--language`, `--tag`, `--dirty`, etc.) and `--force` to overwrite existing files.

## GitHub Operations

Set GitHub topics and descriptions across repos. Requires the `gh` CLI installed and authenticated.

```bash
# Sync pyproject.toml keywords as GitHub topics
repoindex ops github set-topics --from-pyproject --language python --dry-run

# Set specific topics
repoindex ops github set-topics --topics python,cli,tools --dry-run

# Set description from pyproject.toml
repoindex ops github set-description --from-pyproject --dry-run
```

## Query Integration

All ops subcommands support the same query flags as `query`:

```bash
repoindex ops audit --language python --starred
repoindex ops git push --tag "work/*"
repoindex ops generate license --no-license --language rust
```

Or use a query expression as positional argument:

```bash
repoindex ops audit "language == 'Python' and github_stars > 0"
```
