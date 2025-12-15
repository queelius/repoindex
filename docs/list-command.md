# Enhanced repoindex list Command

The `repoindex list` command now provides rich metadata about repositories, including GitHub statistics when available.

## Output Format

Each repository is output as a single JSON object (JSONL format) containing:

```json
{
  "name": "repository-name",
  "path": "/full/path/to/repository",
  "remote_url": "https://github.com/user/repo",
  "github": {
    "stars": 42,
    "forks": 7,
    "description": "A cool repository",
    "language": "Python",
    "is_private": false,
    "is_fork": false
  }
}
```

## GitHub Metadata

When a repository is hosted on GitHub and the GitHub CLI (`gh`) is available, the command automatically fetches:

- **stars**: Number of stargazers
- **forks**: Number of forks
- **description**: Repository description
- **language**: Primary programming language
- **is_private**: Whether the repository is private
- **is_fork**: Whether the repository is a fork

For local-only repositories or when GitHub CLI is unavailable, the `github` field will be `null`.

## Command Options

- `--dir TEXT`: Directory to search (overrides config)
- `--recursive`: Search subdirectories for git repos
- `--dedup`: Deduplicate repos by remote origin URL (⚠️ Memory intensive)
- `--dedup-details`: Show all paths for each unique remote (⚠️ Memory intensive)

## Memory Warnings

When using `--dedup` or `--dedup-details`, the command warns about memory usage since it must track seen repositories to avoid duplicates.

## Example Use Cases

### 1. Basic Repository Discovery
```bash
repoindex list --dir ~/projects
```

### 2. Find Popular Projects
```bash
repoindex list --dir ~/projects | jq 'select(.github.stars > 10)'
```

### 3. Language Analysis
```bash
repoindex list --dir ~/projects | jq -s 'group_by(.github.language) | map({language: .[0].github.language, count: length})'
```

### 4. Generate Reports
```bash
# CSV format
echo "name,stars,language" > repos.csv
repoindex list --dir ~/projects | jq -r '[.name, .github.stars, .github.language] | @csv' >> repos.csv

# Markdown format
repoindex list --dir ~/projects | jq -r '"## " + .name + "\n- **Language:** " + .github.language + "\n- **Stars:** " + (.github.stars | tostring)'
```

### 5. Repository Health Assessment
```bash
repoindex list --dir ~/projects | jq '{
  name: .name,
  health_score: (
    (if .github.stars > 0 then 1 else 0 end) +
    (if .github.description != "" then 1 else 0 end) +
    (if .github.language then 1 else 0 end)
  )
}'
```

### 6. Combine with Status Command
```bash
# Get comprehensive repository analysis
repoindex list --dir ~/projects > repos.jsonl
repoindex status --dir ~/projects > status.jsonl

# Join and analyze
jq -s 'map({name: .name, github_stars: .github.stars, language: .github.language})' repos.jsonl
```

## Integration with jq

The JSONL output format makes it easy to:
- Filter repositories by any criteria
- Transform data into different formats (CSV, Markdown, HTML)
- Aggregate statistics across repositories
- Generate reports and dashboards
- Integrate with other tools and scripts

See `examples/enhanced_list_examples.sh` for comprehensive usage examples.
