# repoindex Query Cookbook

This cookbook shows common search and analysis patterns using `repoindex` with `jq`.

## Basic Searches

### Find repositories by language
```bash
repoindex query --json | jq 'select(.language == "Python")'
repoindex query --json | jq 'select(.language | test("Java"; "i"))'  # Case-insensitive
```

### Find popular repositories
```bash
repoindex query --json | jq 'select(.github_stars > 10)'
repoindex query --json | jq 'select(.github_stars != null and .github_stars > 5)'
```

### Find repositories with issues
```bash
repoindex status | jq 'select(.status | contains("modified") or contains("untracked"))'
```

## Complex Queries

### Multi-criteria search
```bash
# Python repos with PyPI packages
repoindex query --json | jq 'select(
  .language == "Python" and
  .pypi_published == true and
  .github_stars > 0
)'
```

### Repository health assessment
```bash
repoindex query --json | jq '{
  name: .name,
  health_score: (
    ((.github_stars != null) | if . then 2 else 0 end) +
    ((.license != null and .license != "") | if . then 1 else 0 end) +
    ((.pypi_published == true) | if . then 2 else 0 end) +
    ((.has_readme == true) | if . then 1 else 0 end) +
    ((.github_stars > 0) | if . then 1 else 0 end)
  )
} | select(.health_score >= 4)'
```

## Aggregations

### Language distribution
```bash
repoindex query --json | jq -s 'group_by(.language) |
  map({language: .[0].language, count: length}) |
  sort_by(.count) | reverse'
```

### Deployment statistics
```bash
repoindex query --json | jq -s '{
  total: length,
  with_github: map(select(.github_stars != null)) | length,
  with_pypi: map(select(.pypi_published == true)) | length,
  with_license: map(select(.license != null and .license != "")) | length,
  with_readme: map(select(.has_readme == true)) | length
}'
```

## Output Formatting

### CSV export
```bash
echo "name,stars,language,has_pypi" > repos.csv
repoindex query --json | jq -r '[.name, .github_stars, .language, .pypi_published] | @csv' >> repos.csv
```

### Markdown report
```bash
repoindex query --json | jq -r '"## " + .name + " (" + (.language // "Unknown") + ")\n" +
  "Stars: " + ((.github_stars // 0) | tostring) + "\n" +
  (.description // "No description") + "\n"'
```

### HTML table
```bash
echo "<table><tr><th>Name</th><th>Stars</th><th>Language</th></tr>"
repoindex query --json | jq -r '"<tr><td>" + .name + "</td><td>" + ((.github_stars // 0) | tostring) + "</td><td>" + (.language // "") + "</td></tr>"'
echo "</table>"
```

## Performance Tips

### Streaming for large datasets
```bash
# Process results as they come in (don't wait for all repos)
repoindex query --json | jq 'select(.github_stars > 100)' | head -10
```

### Combine commands efficiently
```bash
# Use process substitution for complex joins
join -t$'\t' \
  <(repoindex query --json | jq -r '[.name, .github_stars] | @tsv' | sort) \
  <(repoindex query --json | jq -r '[.name, .pypi_published] | @tsv' | sort)
```

## Common Patterns

### Find "todo" repositories
```bash
# Repos that need attention
repoindex query --json | jq 'select(
  (.clean == false) or
  (.license == null or .license == "") or
  (.github_stars == null) or
  (.description == null or .description == "")
)' | jq '{name: .name, issues: [
  (if .clean == false then "uncommitted changes" else empty end),
  (if .license == null or .license == "" then "no license" else empty end),
  (if .github_stars == null then "not on github" else empty end),
  (if .description == null or .description == "" then "no description" else empty end)
]}'
```

### Portfolio analysis
```bash
# Your coding portfolio stats
repoindex query --json | jq -s '{
  total_repos: length,
  languages: [group_by(.language) | .[] | {lang: .[0].language, count: length}],
  total_stars: map(.github_stars // 0) | add,
  original_projects: map(select(.github_is_fork != true)) | length
}'
```

### Maintenance dashboard
```bash
# Repos with uncommitted changes
repoindex query --json | jq 'select(.clean == false)' | jq '{
  name: .name,
  branch: .branch,
  action: "git commit needed"
}'
```

## Advanced Techniques

### Custom scoring function
```bash
repoindex_score() {
  repoindex query --json | jq --arg weight_stars "$1" --arg weight_pypi "$2" '{
    name: .name,
    score: (
      ((.github_stars // 0) * ($weight_stars | tonumber)) +
      ((.pypi_published == true) | if . then ($weight_pypi | tonumber) else 0 end) +
      ((.license != null and .license != "") | if . then 5 else 0 end)
    )
  } | select(.score > 10)'
}

# Usage: repoindex_score 2 10  (2 points per star, 10 for PyPI)
```

### Real-time monitoring
```bash
# Watch for dirty repos (requires `watch` command)
watch -n 30 'repoindex query --json | jq "select(.clean == false)" | jq -r ".name + \": uncommitted changes\""'
```
