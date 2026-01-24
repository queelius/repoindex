# Tags and Query Language

repoindex provides powerful tools for organizing and finding repositories through its tagging system and query language.

## Tag System

The tag system allows you to organize repositories with hierarchical tags, both explicit (user-defined) and implicit (auto-generated).

### Adding Tags

```bash
# Add tags to a repository
repoindex tag add myproject python ml research

# Add hierarchical tags
repoindex tag add myproject work/active
repoindex tag add myproject topic:ml/research

# Add to multiple repos
repoindex tag add project1 client-work urgent
repoindex tag add project2 client-work completed
```

### Viewing Tags

```bash
# List all tags
repoindex tag list

# List repositories with a specific tag
repoindex tag list -t python

# List repositories matching tag pattern
repoindex tag list -t "work/*"

# Show tags for a specific repository
repoindex tag list -r myproject

# Show tag hierarchy as tree
repoindex tag tree

# Show subtree
repoindex tag tree -t work
```

### Removing Tags

```bash
# Remove specific tags
repoindex tag remove myproject urgent

# Remove hierarchical tag
repoindex tag remove myproject work/active
```

### Moving Between Tags

```bash
# Move from one tag to another (removes old, adds new)
repoindex tag move myproject work/active work/completed
```

### Tag Formats

**Simple tags:**
```bash
repoindex tag add myproject python ml research
```

**Hierarchical tags:**
```bash
repoindex tag add myproject work/active
repoindex tag add myproject client/acme/backend
```

**Key:value tags:**
```bash
repoindex tag add myproject topic:ml
repoindex tag add myproject status:maintained
repoindex tag add myproject topic:scientific/engineering/ai
```

### Implicit Tags

The system automatically generates implicit tags from repository metadata:

| Tag Pattern | Description | Example |
|-------------|-------------|---------|
| `repo:NAME` | Repository name | `repo:repoindex` |
| `lang:LANGUAGE` | Primary language | `lang:python` |
| `dir:PARENT` | Parent directory | `dir:work` |
| `org:OWNER` | GitHub organization | `org:facebook` |
| `has:LICENSE` | Has license file | `has:license` |
| `has:README` | Has README file | `has:readme` |
| `has:DOCS` | Has documentation | `has:docs` |
| `tool:TOOL` | Documentation tool | `tool:mkdocs` |
| `license:TYPE` | License type | `license:mit` |
| `topic:TOPIC` | GitHub topics | `topic:machine-learning` |

## Query Language

The query command provides fuzzy matching and complex boolean expressions.

### Citation Metadata Fields

Repositories with CITATION.cff or .zenodo.json files have these queryable fields:

| Field | Description |
|-------|-------------|
| `citation_doi` | DOI identifier (e.g., "10.5281/zenodo.1234567") |
| `citation_title` | Software title from citation file |
| `citation_authors` | JSON array of author objects |
| `citation_version` | Version from citation file |
| `citation_repository` | Repository URL from citation file |
| `citation_license` | License from citation file |

**Query examples:**
```bash
# Repos with DOI
repoindex query --has-doi
repoindex query "citation_doi != ''"

# SQL queries for citation data
repoindex sql "SELECT name, citation_doi, citation_title FROM repos WHERE citation_doi IS NOT NULL"
```

### Basic Syntax

```bash
# Simple equality
repoindex query "language == 'Python'"

# Fuzzy matching with ~=
repoindex query "language ~= 'pyton'"  # Matches Python

# Comparisons
repoindex query "stars > 10"
repoindex query "forks >= 5"
repoindex query "created_at < '2023-01-01'"

# Contains operator
repoindex query "'machine-learning' in topics"
repoindex query "topics contains 'ml'"

# Not equal
repoindex query "license.key != 'proprietary'"
```

### Complex Expressions

```bash
# AND operations
repoindex query "stars > 10 and language == 'Python'"

# OR operations
repoindex query "language == 'Python' or language == 'JavaScript'"

# Parentheses for grouping
repoindex query "(stars > 5 or forks > 2) and language ~= 'python'"

# Nested field access
repoindex query "license.name contains 'MIT'"
repoindex query "remote.owner == 'myorg'"
```

### Fuzzy Matching

The `~=` operator uses fuzzy string matching:

```bash
# Typos are forgiven
repoindex query "name ~= 'djago'"  # Matches django

# Partial matches
repoindex query "description ~= 'web framework'"

# Case insensitive
repoindex query "language ~= 'PYTHON'"
```

### Tag Queries

```bash
# Check if tag exists
repoindex query "'python' in tags"

# Check for hierarchical tag
repoindex query "'work/active' in tags"

# Combine with other conditions
repoindex query "'ml' in tags and stars > 5"
```

## Combining Tags and Queries

Use both systems together for powerful filtering:

```bash
# Tag-based filtering with query refinement
repoindex query --json --tag "lang:python" | jq 'select(.stars > 5)'

# Query with tag conditions
repoindex query "'work' in tags and language == 'Python'"

# Find repos with specific tag and status
repoindex query "'client:acme' in tags and not archived"
```

## Common Patterns

### Project Organization

```bash
# Tag by project status
repoindex tag add project1 status/active in-development
repoindex tag add project2 status/completed archived
repoindex tag add project3 status/active needs-review

# Find active projects needing review
repoindex query "'status/active' in tags and 'needs-review' in tags"
```

### Client Work

```bash
# Tag by client
repoindex tag add webapp client/acme web
repoindex tag add api client/acme backend
repoindex tag add report client/bigco analysis

# All work for a client
repoindex tag list -t "client/acme"
```

### Technology Stacks

```bash
# Tag by stack
repoindex tag add frontend react typescript webpack
repoindex tag add backend python django postgresql
repoindex tag add mobile flutter dart

# Find all TypeScript projects (using implicit tag)
repoindex query --json --tag "lang:typescript"

# Or explicit tag
repoindex tag list -t typescript
```

### Maintenance Status

```bash
# Tag by maintenance needs
repoindex tag add oldproject needs/update needs/tests
repoindex tag add newproject well-maintained has-ci

# Find projects needing attention
repoindex tag list -t "needs/*"
```

## Query Examples

### Finding Repositories

```bash
# Popular Python projects
repoindex query "language == 'Python' and stars > 10"

# Recently updated
repoindex query "updated_at > '2024-01-01'"

# Projects without licenses
repoindex query "not has_license"

# Large projects
repoindex query "file_count > 1000 or total_size > 10000000"

# ML projects
repoindex query "'machine-learning' in topics or 'ml' in topics or name contains 'learn'"
```

### Complex Queries

```bash
# Active web projects
repoindex query "(language == 'JavaScript' or language == 'TypeScript') and updated_at > '2023-06-01' and ('web' in topics or description contains 'web')"

# Python packages on PyPI
repoindex query "language == 'Python' and has_package == true and package.registry == 'pypi'"

# Documentation sites
repoindex query "has_docs == true and (has_pages == true or homepage contains 'github.io')"
```

## Integration with Events

Combine tags with event monitoring:

```bash
# Events for tagged repos
repoindex events --since 7d -t "work/active" --pretty

# Find repos with recent releases
repoindex events --type git_tag --since 30d | jq -r '.repo' | sort -u
```

## Best Practices

1. **Use Namespaces**: Prefix related tags (e.g., `client/*`, `project/*`, `status/*`)

2. **Hierarchical Organization**: Use paths for related concepts
   ```bash
   repoindex tag add myproject work/client/acme/backend
   ```

3. **Combine Systems**: Use tags for stable categorization, queries for dynamic filtering

4. **Regular Cleanup**: Remove obsolete tags periodically
   ```bash
   # Find and remove obsolete tags
   repoindex tag list -t obsolete | jq -r '.name' | \
     xargs -I {} repoindex tag remove {} obsolete
   ```

5. **Document Conventions**: Keep a README of your tagging conventions

## Shell VFS Integration

The interactive shell provides a filesystem view of your tags:

```bash
repoindex shell

# Navigate tag hierarchy
> cd /by-tag/work/active
> ls

# Add tags via filesystem operations
> cp /repos/myproject /by-tag/work/active

# Move between tags
> mv /by-tag/work/active/myproject /by-tag/work/completed

# Remove tags
> rm /by-tag/work/active/myproject
```

See [Shell & VFS](shell-vfs.md) for details.
