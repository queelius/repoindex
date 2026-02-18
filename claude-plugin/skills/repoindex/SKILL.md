---
name: repoindex
description: >-
  Use when you need to query, search, or understand the user's git repository
  collection. Provides CLI reference for repoindex — a local git catalog
  indexing ~170 repos with metadata from GitHub, PyPI, CRAN, and Zenodo.
  Trigger on: "which repos", "find repos", "what repos do I have",
  "repository collection", "repoindex", "repo query", "published packages",
  "dirty repos", "repos with stars".
---

# repoindex CLI Reference

Query and manage a local git repository collection. Database: `~/.repoindex/repoindex.db`.

## Quick Commands

```bash
repoindex status                        # Dashboard overview
repoindex show <name>                   # Detailed single-repo view
repoindex show <name> --json            # JSON output for scripting
repoindex query --language python       # Filter repos (pretty table)
repoindex query --dirty                 # Repos with uncommitted changes
repoindex query --json | jq '.name'     # JSONL for piping
repoindex events --since 7d             # Recent activity
repoindex sql "SELECT ..." --table      # Raw SQL access
```

## Query Flags

```bash
# Identity
--name dapple                # Substring match
--name "*api*"               # Wildcard

# Git status
--dirty / --clean            # Uncommitted changes
--recent 7d                  # Recent commits
--has-remote                 # Has remote URL

# Metadata
--language python            # By language (py, js, ts, rust, go, cpp)
--tag "work/*"               # By tag (wildcards)
--no-license / --no-readme   # Missing files
--has-citation / --has-doi   # Citation metadata

# GitHub (requires --github during refresh)
--starred / --public / --private / --fork / --no-fork / --archived

# Modifiers
--sort stars                 # Sort (stars, name, language, updated)
--count                      # Just the count
--limit 10                   # Limit results
--columns path,language      # Select display columns
--brief                      # Just repo names
```

## Show Command

```bash
repoindex show repoindex            # By name
repoindex show ~/github/go-tools    # By path
repoindex show repoindex --json     # Full JSON with tags, publications, events
```

Displays: core metadata, GitHub stats, publications, tags, recent events (10).

## SQL Data Model

### repos table
Core identity: `id`, `name`, `path` (UNIQUE), `branch`, `remote_url`, `owner`
Git status: `is_clean`, `ahead`, `behind`, `has_upstream`, `uncommitted_changes`, `untracked_files`
Metadata: `language`, `languages` (JSON), `description`, `readme_content`
License: `license_key` (SPDX), `license_name`, `license_file`
Files: `has_readme`, `has_license`, `has_ci`, `has_citation`, `citation_file`
Citation: `citation_doi`, `citation_title`, `citation_authors` (JSON), `citation_version`
GitHub: `github_stars`, `github_forks`, `github_is_private`, `github_is_archived`, `github_is_fork`, `github_topics` (JSON), `github_created_at`, `github_updated_at`

### publications table (source of truth for packages)
`repo_id` (FK), `registry` ('pypi'|'cran'|'zenodo'|'npm'|'cargo'|'docker'), `package_name`, `current_version`, `published` (0=detected, 1=confirmed), `url`, `doi`, `downloads_total`, `downloads_30d`

### events table
`repo_id` (FK), `type` ('commit'|'git_tag'|'branch'|'merge'), `timestamp`, `ref`, `message`, `author`

### tags table
`repo_id` (FK), `tag`, `source` ('user'|'implicit'|'github')

## Common SQL Queries

```bash
# Published packages by registry
repoindex sql "SELECT registry, COUNT(*) FROM publications WHERE published = 1 GROUP BY registry"

# Top starred repos
repoindex sql "SELECT name, github_stars FROM repos WHERE github_stars > 0 ORDER BY github_stars DESC"

# Recent commits by repo
repoindex sql "SELECT r.name, COUNT(*) as n FROM events e JOIN repos r ON e.repo_id = r.id WHERE e.type = 'commit' AND e.timestamp > datetime('now', '-30 days') GROUP BY r.id ORDER BY n DESC"

# Package name differs from repo name
repoindex sql "SELECT r.name as repo, p.package_name, p.registry FROM publications p JOIN repos r ON p.repo_id = r.id WHERE p.published = 1 AND r.name != p.package_name"
```

## Operations

```bash
# Multi-repo git
repoindex ops git push --dry-run       # Preview pushes
repoindex ops git pull --name foo      # Pull specific repo
repoindex ops git status --dirty       # Status of dirty repos

# Metadata audit
repoindex ops audit --language python  # Audit completeness
repoindex ops audit --json             # Machine-readable

# Generate boilerplate
repoindex ops generate citation --dry-run "name == 'foo'"
repoindex ops generate license --license mit --no-license --dry-run
repoindex ops generate codemeta --language python --dry-run

# GitHub settings
repoindex ops github set-topics --from-pyproject --dry-run
repoindex ops github set-description --from-pyproject --dry-run

# Export formats
repoindex render bibtex --language python > refs.bib
repoindex render csv --starred > repos.csv
```

## Refresh

```bash
repoindex refresh              # Smart (changed repos only)
repoindex refresh --full       # Force full
repoindex refresh --github     # GitHub metadata
repoindex refresh --external   # All external sources
repoindex sql --reset          # Reset database
```

## Tags

```bash
repoindex tag add myproject topic:ml work/active
repoindex tag remove myproject work/active
repoindex tag list
repoindex tag tree
```
