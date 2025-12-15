# repoindex Query Cookbook

This cookbook shows common search and analysis patterns using `repoindex` with `jq`.

## Basic Searches

### Find repositories by language
```bash
repoindex list | jq 'select(.github.language == "Python")'
repoindex list | jq 'select(.github.language | test("Java"; "i"))'  # Case-insensitive
```

### Find popular repositories
```bash
repoindex list | jq 'select(.github.stars > 10)'
repoindex status | jq 'select(.github.on_github and .github.stars > 5)'
```

### Find repositories with issues
```bash
repoindex status | jq 'select(.status | contains("modified") or contains("untracked"))'
```

## Complex Queries

### Multi-criteria search
```bash
# Python repos with PyPI packages
repoindex status | jq 'select(
  .github.language == "Python" and 
  .pypi_info != null and 
  .github.stars > 0
)'
```

### Repository health assessment
```bash
repoindex status | jq '{
  name: .name,
  health_score: (
    (.github.on_github | if . then 2 else 0 end) +
    ((.license.name != null) | if . then 1 else 0 end) +
    ((.pypi_info != null) | if . then 2 else 0 end) +
    ((.pages_url != null) | if . then 1 else 0 end) +
    ((.github.stars > 0) | if . then 1 else 0 end)
  )
} | select(.health_score >= 4)'
```

## Aggregations

### Language distribution
```bash
repoindex list | jq -s 'group_by(.github.language) | 
  map({language: .[0].github.language, count: length}) | 
  sort_by(.count) | reverse'
```

### Deployment statistics
```bash
repoindex status | jq -s '{
  total: length,
  on_github: map(select(.github.on_github)) | length,
  with_pypi: map(select(.pypi_info != null)) | length,
  with_pages: map(select(.pages_url != null)) | length,
  with_license: map(select(.license.name != null)) | length
}'
```

## Output Formatting

### CSV export
```bash
echo "name,stars,language,has_pypi" > repos.csv
repoindex list | jq -r '[.name, .github.stars, .github.language, (.pypi_info != null)] | @csv' >> repos.csv
```

### Markdown report
```bash
repoindex list | jq -r '"## " + .name + " (" + (.github.language // "Unknown") + ")\n" +
  "⭐ " + (.github.stars | tostring) + " stars\n" +
  (.github.description // "No description") + "\n"'
```

### HTML table
```bash
echo "<table><tr><th>Name</th><th>Stars</th><th>Language</th></tr>"
repoindex list | jq -r '"<tr><td>" + .name + "</td><td>" + (.github.stars | tostring) + "</td><td>" + (.github.language // "") + "</td></tr>"'
echo "</table>"
```

## Performance Tips

### Streaming for large datasets
```bash
# Process results as they come in (don't wait for all repos)
repoindex status --recursive | jq 'select(.github.stars > 100)' | head -10
```

### Combine commands efficiently
```bash
# Use process substitution for complex joins
join -t$'\t' \
  <(repoindex list | jq -r '[.name, .github.stars] | @tsv' | sort) \
  <(repoindex status | jq -r '[.name, (.pypi_info != null)] | @tsv' | sort)
```

## Common Patterns

### Find "todo" repositories
```bash
# Repos that need attention
repoindex status | jq 'select(
  (.status | contains("modified")) or
  (.license.name == null) or
  (.github.on_github == false) or
  (.github.description == null or .github.description == "")
)' | jq '{name: .name, issues: [
  (if .status | contains("modified") then "uncommitted changes" else empty end),
  (if .license.name == null then "no license" else empty end),
  (if .github.on_github == false then "not on github" else empty end),
  (if .github.description == null or .github.description == "" then "no description" else empty end)
]}'
```

### Portfolio analysis
```bash
# Your coding portfolio stats
repoindex list | jq -s '{
  total_repos: length,
  languages: [group_by(.github.language) | .[] | {lang: .[0].github.language, count: length}],
  total_stars: map(.github.stars) | add,
  original_projects: map(select(.github.is_fork == false)) | length
}'
```

### Maintenance dashboard
```bash
# Repos needing updates
repoindex status | jq 'select(.status | contains("behind"))' | jq '{
  name: .name,
  status: .status,
  action: "git pull needed"
}'
```

## Advanced Techniques

### Custom scoring function
```bash
repoindex_score() {
  repoindex status | jq --arg weight_stars "$1" --arg weight_pypi "$2" '{
    name: .name,
    score: (
      (.github.stars * ($weight_stars | tonumber)) +
      ((.pypi_info != null) | if . then ($weight_pypi | tonumber) else 0 end) +
      ((.license.name != null) | if . then 5 else 0 end)
    )
  } | select(.score > 10)'
}

# Usage: repoindex_score 2 10  (2 points per star, 10 for PyPI)
```

### Real-time monitoring
```bash
# Watch for changes (requires `watch` command)
watch -n 30 'repoindex status | jq "select(.status | contains(\"modified\"))" | jq -r ".name + \": \" + .status"'
```
