# Tags & Queries

## Tags

Organize repositories with hierarchical tags.

```bash
repoindex tag add myproject work/active topic:ml
repoindex tag remove myproject work/active
repoindex tag move myproject work/active work/completed
repoindex tag list -t "work/*"
repoindex tag tree
```

**Formats**: simple (`python`), hierarchical (`work/client/acme`), key:value (`topic:ml/research`, `status:maintained`).

### Implicit Tags

Auto-generated from metadata:

| Pattern | Example |
|---------|---------|
| `repo:NAME` | `repo:repoindex` |
| `lang:LANGUAGE` | `lang:python` |
| `dir:PARENT` | `dir:github` |
| `has:FILE` | `has:license`, `has:readme` |
| `license:TYPE` | `license:mit` |
| `topic:TOPIC` | `topic:machine-learning` |

## Query DSL

```bash
# Equality and comparison
repoindex query "language == 'Python'"
repoindex query "github_stars > 10"

# Fuzzy matching (typo-tolerant)
repoindex query "language ~= 'pyton'"

# Boolean logic
repoindex query "language == 'Python' and github_stars > 10"
repoindex query "language == 'Python' or language == 'Rust'"

# Tags in DSL
repoindex query "tagged('work/*')"
repoindex query "'ml' in tags and github_stars > 5"

# Contains / membership
repoindex query "'machine-learning' in github_topics"
```

### Shorthand Flags

Four essential shorthands; everything else via DSL:

```bash
repoindex query --dirty              # Uncommitted changes
repoindex query --language python    # By language
repoindex query --tag "work/*"       # By tag
repoindex query --recent 7d          # Recent commits
```

### DSL for Everything Else

```bash
repoindex query "github_stars > 0"                    # Starred repos
repoindex query "has_doi"                             # Has DOI
repoindex query "not has_license"                     # Missing license
repoindex query "github_is_archived"                  # Archived repos
repoindex query "not github_is_private"               # Public repos
```

### Citation Fields

Repos with CITATION.cff or .zenodo.json expose: `citation_doi`, `citation_title`, `citation_authors`, `citation_version`.

```bash
repoindex query "has_doi"
repoindex sql "SELECT name, citation_doi FROM repos WHERE citation_doi IS NOT NULL"
```

## jq Cookbook

```bash
# Language distribution
repoindex query --json | jq -s 'group_by(.language) |
  map({language: .[0].language, count: length}) |
  sort_by(.count) | reverse'

# Portfolio stats
repoindex query --json | jq -s '{
  total_repos: length,
  total_stars: map(.github_stars // 0) | add
}'

# CSV export
echo "name,stars,language" > repos.csv
repoindex query --json | jq -r '[.name, .github_stars, .language] | @csv' >> repos.csv

# Find repos needing attention
repoindex query --json | jq 'select(.clean == false or .license == null)'
```
