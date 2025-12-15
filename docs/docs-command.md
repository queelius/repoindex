# repoindex docs Command

The `repoindex docs` command provides comprehensive documentation management for your repositories, including detection, building, serving, and deployment to GitHub Pages.

## Overview

The docs command can:
- Detect documentation tools (MkDocs, Sphinx, Jekyll, Hugo, etc.)
- Build documentation locally
- Serve documentation for preview
- Deploy to GitHub Pages
- Track documentation status across all repositories

## Commands

### docs status

Show documentation status for repositories:

```bash
# Show docs status for all repositories (JSONL output)
repoindex docs status

# Pretty table format
repoindex docs status --pretty

# Specific directory
repoindex docs status --dir /path/to/repos --recursive
```

Output includes:
- Documentation tool detected
- Configuration files found
- GitHub Pages status
- Build/serve commands available

### docs detect

Detect which documentation tool a repository uses:

```bash
# Detect docs tool for current directory
repoindex docs detect .

# Output (JSONL)
{
  "tool": "mkdocs",
  "config": "mkdocs.yml",
  "build_cmd": "mkdocs build",
  "serve_cmd": "mkdocs serve",
  "output_dir": "site",
  "detected_files": ["mkdocs.yml"]
}
```

### docs build

Build documentation for one or more repositories:

```bash
# Build docs for current repository
repoindex docs build .

# Build all repositories with docs (using tag filter)
repoindex docs build -t "repo:*"

# Build only MkDocs projects
repoindex docs build -t "tool:mkdocs"

# Build Python projects with docs
repoindex docs build -t "lang:python" -t "has:docs" --all-tags

# Dry run to see what would be built
repoindex docs build -t "has:docs" --dry-run
```

### docs serve

Serve documentation locally for preview:

```bash
# Serve current repository docs
repoindex docs serve .

# Custom port
repoindex docs serve . --port 8080

# Open browser automatically
repoindex docs serve . --open
```

### docs deploy

Deploy documentation to GitHub Pages:

```bash
# Deploy current repository
repoindex docs deploy .

# Custom branch (default: gh-pages)
repoindex docs deploy . --branch docs

# Custom commit message
repoindex docs deploy . --message "Update API docs"

# Dry run
repoindex docs deploy . --dry-run
```

## Supported Documentation Tools

The docs command automatically detects:

1. **MkDocs** - `mkdocs.yml` or `mkdocs.yaml`
2. **Sphinx** - `docs/conf.py` or `doc/conf.py`
3. **Jekyll** - `_config.yml`, `_posts`, `_layouts`
4. **Docusaurus** - `docusaurus.config.js`
5. **VuePress** - `.vuepress/config.js`
6. **Hugo** - `config.toml/yaml/json` with `content/` or `themes/`
7. **Generic Markdown** - Any `docs/` directory with `.md` files

## Examples

### Find all repos with documentation

```bash
# List repos with docs
repoindex docs status | jq 'select(.has_docs == true)'

# Count by documentation tool
repoindex docs status | jq -s 'group_by(.docs_tool) | map({tool: .[0].docs_tool, count: length})'

# Find repos without GitHub Pages
repoindex docs status | jq 'select(.has_docs == true and .pages_url == null)'
```

### Batch operations

```bash
# Build all MkDocs projects
repoindex docs status | \
  jq -r 'select(.docs_tool == "mkdocs") | .path' | \
  xargs -I {} repoindex docs build {}

# Deploy all repos with built docs
repoindex docs build --all --tool mkdocs
repoindex docs status | \
  jq -r 'select(.docs_tool == "mkdocs") | .path' | \
  xargs -I {} repoindex docs deploy {}
```

### Integration with other commands

```bash
# Find Python projects with docs
repoindex query "lang:python" | \
  jq -r '.path' | \
  xargs -I {} repoindex docs detect {} | \
  jq 'select(.tool != null)'

# Export repos with docs to Hugo
repoindex docs status | \
  jq 'select(.has_docs == true)' | \
  repoindex export --format hugo --stdin
```

## JSONL Output Schema

```json
{
  "path": "/absolute/path/to/repo",
  "name": "repo-name",
  "has_docs": true,
  "docs_tool": "mkdocs",
  "docs_config": "mkdocs.yml",
  "detected_files": ["mkdocs.yml"],
  "pages_url": "https://user.github.io/repo"
}
```

## Notes

- The deploy command requires either `ghp-import` or git to be installed
- Some documentation tools may require specific dependencies to be installed
- GitHub Pages detection works both locally and via API
- All commands output JSONL by default for pipeline composition