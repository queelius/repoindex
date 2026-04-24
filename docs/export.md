# Export

The `export` command produces a **longecho-compliant arkiv archive** by
default: a self-contained directory with JSONL data, metadata schema, a
SQLite database, and an interactive HTML browser. Format-based exports
(CSV, BibTeX, Markdown, OPML, JSON-LD) are available via the exporter
plugin system.

## Quick Start

```bash
# Default: longecho-compliant arkiv archive with HTML browser
repoindex export -o ~/archives/repos/

# Filtered archive
repoindex export -o ~/archives/python/ --language python
repoindex export -o ~/archives/dirty/ --dirty
repoindex export -o ~/archives/work/ --tag "work/*"
repoindex export -o ~/archives/recent/ --recent 30d

# Format-based exports (via exporter plugins)
repoindex export csv -o repos.csv
repoindex export bibtex --language python > refs.bib
repoindex export --list-formats
```

## Default Archive Output

When no format is specified, `export -o <dir>` produces:

```
archive/
├── README.md             # longecho self-description (YAML frontmatter)
├── schema.yaml           # arkiv spec: types, counts, values per key
├── repos.jsonl           # repository metadata (inode / directory records)
├── events.jsonl          # git events (text/plain records)
├── publications.jsonl    # package registry records (if any)
├── archive.db            # SQLite derived database (queryable)
└── site/
    └── index.html        # interactive SQL browser (sql.js)
```

The archive is:

- **longecho-compliant**: `longecho check <dir>` passes
- **arkiv-spec compliant**: proper schema discovery, universal record format
- **Queryable**: `sqlite3 archive.db "SELECT json_extract(metadata, '$.name') FROM records"`
- **Browsable**: open `site/index.html` in any browser

## Format Plugins

Stream-based exports for specific formats:

| Format | ID | Description |
|--------|----|-------------|
| BibTeX | `bibtex` | Citation entries for LaTeX / academic use |
| CSV | `csv` | Comma-separated values for spreadsheets |
| Markdown | `markdown` | Markdown table of repositories |
| OPML | `opml` | Outline format (feed readers, outliners) |
| JSON-LD | `jsonld` | Linked data / structured metadata |
| Arkiv | `arkiv` | Arkiv universal records (JSONL stream to stdout) |

Use `repoindex export --list-formats` to list the currently available
format IDs, including any user-installed exporters.

## Filter Flags

Four shorthands, same as the other operation commands:

```bash
repoindex export -o out/ --language python
repoindex export -o out/ --dirty
repoindex export -o out/ --tag "work/*"
repoindex export -o out/ --recent 7d
```

For anything more expressive, query the database via SQL first, then
invoke export unfiltered and post-process. See `ops.md` for the general
pattern.

## Custom Exporters

Drop a Python file into `~/.repoindex/exporters/`:

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

Then use it:

```bash
repoindex export custom -o output.txt
```

The `Exporter` ABC signature is part of the stable surface; see
`STABILITY.md` section 6.

## MCP

The `export` tool on the MCP server produces the same longecho-compliant
arkiv archive:

```python
export(output_dir="/tmp/myarchive", language="python")
```

Arguments mirror the filter flags. For arbitrary filtering, run `run_sql`
first to find the repo names, then invoke `export` without filters and
post-process.
