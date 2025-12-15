# Export Command

The `repoindex export` command generates portfolio exports from your repositories in various formats, perfect for creating documentation sites, portfolios, and reports.

## Overview

Export your repository data as:
- **Markdown** - Clean, readable documentation
- **Hugo** - Complete Hugo site structure with taxonomies
- **HTML** - Interactive portfolio with search and filtering
- **JSON** - Structured data for further processing
- **CSV** - Tabular data for spreadsheets
- **LaTeX/PDF** - Professional printed portfolios

## Usage

```bash
repoindex export generate [OPTIONS]
```

## Key Options

- `-f, --format FORMAT` - Output format (markdown, hugo, html, json, csv, pdf, latex)
- `-o, --output DIR` - Output directory
- `--single-file` - Export to single file instead of multiple
- `--group-by PREFIX` - Group repositories by tag prefix
- `--template NAME` - Use custom template
- `-t, --tag TAG` - Filter by tags
- `-q, --query EXPR` - Filter by query expression
- `--pretty` - Display export progress

## Export Formats

### Markdown Export

Simple, clean markdown suitable for any documentation system.

```bash
# Export all repos to markdown
repoindex export generate -f markdown -o ./portfolio

# Export Python projects only
repoindex export generate -f markdown -t "lang:python" -o ./python-projects

# Single file export
repoindex export generate -f markdown --single-file -o ./output
```

### Hugo Export

Creates a complete Hugo content structure with front matter.

```bash
# Generate Hugo site content
repoindex export generate -f hugo -o ./my-site/content/projects

# Group by language
repoindex export generate -f hugo --group-by lang -o ./my-site/content/projects

# Export work projects
repoindex export generate -f hugo -t "dir:work" -o ./my-site/content/work
```

Generated structure:
```
content/projects/
├── _index.md          # Section index with statistics
├── python/
│   ├── _index.md      # Language group index
│   ├── project1.md    # Individual project page
│   └── project2.md
└── javascript/
    ├── _index.md
    └── project3.md
```

### HTML Export

Interactive portfolio with JavaScript-powered search and filtering.

```bash
# Create interactive portfolio
repoindex export generate -f html -o ./portfolio

# Single-page application
repoindex export generate -f html --single-file -o ./portfolio

# Group by directory
repoindex export generate -f html --group-by dir -o ./portfolio
```

Features:
- Live search filtering
- Language dropdown filter
- Sort by name, stars, or update date
- Responsive design
- No external dependencies

### JSON Export

Clean JSON for API consumption or further processing.

```bash
# Export all metadata
repoindex export generate -f json -o ./data

# Single file with all repos
repoindex export generate -f json --single-file -o ./data

# Filter high-star projects
repoindex export generate -f json -q "stars > 10" -o ./popular
```

### CSV Export

Tabular format for spreadsheet analysis.

```bash
# Export to CSV
repoindex export generate -f csv -o ./reports

# Group by language
repoindex export generate -f csv --group-by lang -o ./reports
```

Columns included:
- name, description, language
- stars, forks, license
- created_at, updated_at
- homepage, repository_url
- topics (comma-separated)

### LaTeX/PDF Export

Professional document format for printed portfolios.

```bash
# Generate LaTeX document
repoindex export generate -f latex -o ./portfolio

# Compile to PDF (requires pdflatex)
repoindex export generate -f latex -o ./portfolio
cd ./portfolio && pdflatex repositories.tex
```

## Grouping and Organization

Use `--group-by` to organize repositories by tag prefix:

```bash
# Group by directory
repoindex export generate -f hugo --group-by dir

# Group by language
repoindex export generate -f html --group-by lang

# Group by organization
repoindex export generate -f markdown --group-by org
```

## Templates

Custom templates allow you to control the export format:

```bash
# List available templates
repoindex export templates --list

# Use a template
repoindex export generate -f markdown --template my-template

# Show template content
repoindex export templates --show my-template
```

## Pipeline Integration

Export commands output JSONL by default for progress tracking:

```bash
# Monitor export progress
repoindex export generate -f hugo -o ./site | jq -r '.file'

# Count exported files
repoindex export generate -f html | jq -s 'length'

# Get export summary
repoindex export generate -f markdown | jq -s '{
  total_files: length,
  total_repos: [.[] | .repositories // 0] | add
}'
```

## Examples

### Complete Portfolio Website

```bash
# Generate full Hugo site for all projects
repoindex export generate -f hugo \
  --group-by lang \
  -o ./my-portfolio/content/projects

# Add to Hugo config.yaml:
# menu:
#   main:
#     - name: "Projects"
#       url: "/projects/"
#       weight: 10
```

### Work vs Personal Projects

```bash
# Export work projects
repoindex export generate -f html \
  -t "dir:work" \
  -o ./portfolios/work \
  --single-file

# Export personal projects
repoindex export generate -f html \
  -t "dir:personal" \
  -o ./portfolios/personal \
  --single-file
```

### Language-Specific Portfolios

```bash
# Python portfolio
repoindex export generate -f markdown \
  -t "lang:python" \
  -o ./python-portfolio \
  --single-file

# JavaScript portfolio
repoindex export generate -f markdown \
  -t "lang:javascript" \
  -o ./js-portfolio \
  --single-file
```

### Executive Summary

```bash
# High-level PDF report of popular projects
repoindex export generate -f latex \
  -q "stars > 5 or forks > 2" \
  -o ./executive-summary \
  --single-file

cd ./executive-summary
pdflatex repositories.tex
```

### API Documentation

```bash
# Export all repos with docs to JSON
repoindex export generate -f json \
  -t "has:docs" \
  -o ./api/data \
  --single-file

# Serve with any static server
cd ./api && python -m http.server
```

## Integration with Static Site Generators

### Hugo

```bash
# Export directly to Hugo content directory
repoindex export generate -f hugo -o ./my-site/content/projects

# Build and serve
cd ./my-site
hugo serve
```

### Jekyll

```bash
# Export as markdown to Jekyll collections
repoindex export generate -f markdown -o ./my-site/_projects

# Add to _config.yml:
# collections:
#   projects:
#     output: true
```

### Next.js / Gatsby

```bash
# Export as JSON for static generation
repoindex export generate -f json \
  --single-file \
  -o ./my-app/data/projects.json

# Import in your app
# import projects from '../data/projects.json'
```