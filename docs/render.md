# Render Formats

The `render` command exports repository data in various formats. Output goes to stdout by default (pipe-friendly). Supports the same query flags as `query`.

## Quick Start

```bash
# List available formats
repoindex render --list-formats

# BibTeX for citations
repoindex render bibtex --language python > refs.bib

# CSV spreadsheet
repoindex render csv --starred > repos.csv

# Markdown table
repoindex render markdown --recent 30d > recent.md

# OPML outline (for feed readers)
repoindex render opml > repos.opml

# JSON-LD (structured data)
repoindex render jsonld --has-doi > repos.jsonld

# Write directly to file
repoindex render csv --language python -o python_repos.csv
```

## Built-in Formats

| Format | ID | Description |
|--------|----|-------------|
| BibTeX | `bibtex` | Citation entries for LaTeX/academic use |
| CSV | `csv` | Comma-separated values for spreadsheets |
| Markdown | `markdown` | Markdown table of repositories |
| OPML | `opml` | Outline format (feed readers, outliners) |
| JSON-LD | `jsonld` | Linked data / structured metadata |

## Query Filtering

All query flags work with render:

```bash
repoindex render csv --language python --starred
repoindex render bibtex --has-doi
repoindex render markdown --tag "work/*" --recent 30d
repoindex render csv "language == 'Python' and github_stars > 10"
```

## Custom Exporters

Create custom formats by placing Python files in `~/.repoindex/exporters/`:

```python
# ~/.repoindex/exporters/my_format.py
from repoindex.exporters import Exporter

class MyExporter(Exporter):
    name = "my-format"
    description = "My custom format"
    extension = ".txt"

    def export(self, repos, output, config):
        for repo in repos:
            output.write(f"{repo['name']}: {repo.get('description', '')}\n")

exporter = MyExporter()
```

Then use it: `repoindex render my-format > output.txt`
