# Repository Organization with Catalog and Query

repoindex provides powerful tools for organizing and finding repositories through its tagging system and query language.

## Catalog System

The catalog system allows you to organize repositories with tags, both explicit (user-defined) and implicit (auto-generated).

### Adding Tags

```bash
# Tag a single repository
repoindex catalog add myproject python ml research

# Tag multiple repos
repoindex catalog add project1 client-work urgent
repoindex catalog add project2 client-work completed
```

### Viewing Tagged Repositories

```bash
# Show all tagged repos
repoindex catalog show --pretty

# Filter by specific tags
repoindex catalog show -t python --pretty

# Require multiple tags (AND operation)
repoindex catalog show -t python -t ml --all-tags --pretty

# JSONL output for processing
repoindex catalog show -t client-work | jq -r '.name'
```

### Removing Tags

```bash
# Remove specific tags
repoindex catalog remove myproject urgent

# Remove all tags from a repo
repoindex catalog clear myproject
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

## Combining Catalog and Query

Use both systems together for powerful filtering:

```bash
# Tag-based pre-filtering with query refinement
repoindex list -t "lang:python" | jq -r '.path' | \
  xargs -I {} repoindex query "stars > 5" --path {}

# Find untagged repos
repoindex query "true" | jq -r '.name' > all-repos.txt
repoindex catalog show | jq -r '.name' > tagged-repos.txt
comm -23 <(sort all-repos.txt) <(sort tagged-repos.txt)
```

## Common Patterns

### Project Organization

```bash
# Tag by project status
repoindex catalog add project1 active in-development
repoindex catalog add project2 completed archived
repoindex catalog add project3 active needs-review

# Find active projects needing review
repoindex catalog show -t active -t needs-review --all-tags
```

### Client Work

```bash
# Tag by client
repoindex catalog add webapp client:acme web
repoindex catalog add api client:acme backend
repoindex catalog add report client:bigco analysis

# All work for a client
repoindex catalog show -t "client:acme"
```

### Technology Stacks

```bash
# Tag by stack
repoindex catalog add frontend react typescript webpack
repoindex catalog add backend python django postgresql
repoindex catalog add mobile flutter dart

# Find all TypeScript projects
repoindex catalog show -t typescript
# Or use implicit tags
repoindex list -t "lang:typescript"
```

### Maintenance Status

```bash
# Tag by maintenance needs
repoindex catalog add oldproject needs:update needs:tests
repoindex catalog add newproject well-maintained has:ci

# Find projects needing attention
repoindex catalog show -t "needs:update"
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

## Integration with Other Commands

### Audit Filtered Repos

```bash
# Audit all client work
repoindex audit all -t "client:*" --pretty

# Audit Python projects without docs
repoindex audit docs -q "language == 'Python' and not has_docs"
```

### Export Filtered Repos

```bash
# Export active projects to Hugo
repoindex export generate -t active -f hugo -o ./site/content/active

# Export popular repos to PDF
repoindex export generate -q "stars > 5 or forks > 2" -f pdf
```

### Bulk Operations

```bash
# Update all work repos
repoindex update -t "dir:work"

# Build docs for all documented Python projects
repoindex docs build -q "language == 'Python' and has_docs == true"
```

## Best Practices

1. **Use Namespaces**: Prefix related tags (e.g., `client:*`, `project:*`, `status:*`)

2. **Combine Systems**: Use tags for stable categorization, queries for dynamic filtering

3. **Document Tags**: Keep a README of your tagging conventions

4. **Regular Cleanup**: Remove obsolete tags periodically
   ```bash
   repoindex catalog show -t obsolete | jq -r '.name' | \
     xargs -I {} repoindex catalog remove {} obsolete
   ```

5. **Export Tag Documentation**:
   ```bash
   # Generate tag documentation
   repoindex catalog show | jq -r '.tags[]' | sort | uniq -c | \
     sort -rn > tag-usage.txt
   ```