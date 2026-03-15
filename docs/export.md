# Export

The `export` command produces a **longecho-compliant arkiv archive** by default — a self-contained directory with JSONL data, metadata schema, SQLite database, and an interactive HTML browser. Format-based exports (CSV, BibTeX, etc.) are available via the exporter plugin system.

## Quick Start

```bash
# Default: longecho-compliant arkiv archive with HTML browser
repoindex export -o ~/archives/repos/

# Filtered archive
repoindex export -o ~/archives/python/ --language python

# With DSL query
repoindex export -o ~/archives/starred/ "github_stars > 0"

# Format-based exports (via exporter plugins)
repoindex export csv > repos.csv
repoindex export bibtex --language python > refs.bib
repoindex export --list-formats
```

## Default Archive Output

When no format is specified, `export -o <dir>` produces:

```
archive/
├── README.md             # longecho self-description (YAML frontmatter)
├── schema.yaml           # arkiv spec: types, counts, values per key
├── repos.jsonl           # repository metadata (inode/directory records)
├── events.jsonl          # git events (text/plain records)
├── publications.jsonl    # package registry records (if any)
├── archive.db            # SQLite derived database (queryable)
└── site/
    └── index.html        # interactive SQL browser (sql.js)
```

The archive is:
- **longecho-compliant** — `longecho check <dir>` passes
- **arkiv-spec compliant** — proper schema discovery, universal record format
- **Queryable** — `sqlite3 archive.db "SELECT json_extract(metadata, '$.name') FROM records"`
- **Browsable** — open `site/index.html` in any browser

## Format Plugins

Stream-based exports for specific formats:

| Format | ID | Description |
|--------|----|-------------|
| BibTeX | `bibtex` | Citation entries for LaTeX/academic use |
| CSV | `csv` | Comma-separated values for spreadsheets |
| Markdown | `markdown` | Markdown table of repositories |
| OPML | `opml` | Outline format (feed readers, outliners) |
| JSON-LD | `jsonld` | Linked data / structured metadata |
| Arkiv | `arkiv` | Arkiv universal records (JSONL stream to stdout) |

Use `repoindex query` to preview which repos will be exported.

## Query Filtering

Four shorthand flags plus the full DSL:

```bash
repoindex export -o out/ --language python
repoindex export -o out/ --dirty
repoindex export -o out/ --tag "work/*"
repoindex export -o out/ --recent 7d
repoindex export -o out/ "has_doi and github_stars > 5"
repoindex export -o out/ @python-active
```

## Custom Exporters

Create custom formats by placing Python files in `~/.repoindex/exporters/`:

```python
# ~/.repoindex/exporters/my_format.py
from repoindex.exporters import Exporter

class MyExporter(Exporter):
    format_id = "custom"
    name = "My Custom Format"
    extension = ".txt"

    def export(self, repos, output, config=None):
        for repo in repos:
            output.write(f"{repo['name']}: {repo.get('description', '')}\n")
        return len(repos)

exporter = MyExporter()
```

Then use it: `repoindex export custom > output.txt`

## MCP Server

For LLM access to the database, use the MCP server instead:

```bash
repoindex mcp   # stdio transport, 4 tools: get_manifest, get_schema, run_sql, refresh
```

Requires: `pip install repoindex[mcp]`
