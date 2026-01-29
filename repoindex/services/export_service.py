"""
Export service for repoindex.

Exports repository index in ECHO-compliant format:
- Durable formats (SQLite, JSONL)
- Self-describing (README.md, manifest.json)
- Works offline

ECHO philosophy: exports that remain useful decades from now.
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Generator, List, Optional

from ..config import load_config
from ..database import Database, get_db_path
from ..database.repository import get_all_repos, get_repos_with_tags

logger = logging.getLogger(__name__)


@dataclass
class ExportOptions:
    """Options for export operation."""
    output_dir: Path
    include_events: bool = False
    dry_run: bool = False
    query_filter: Optional[str] = None  # DSL query to filter repos


@dataclass
class ExportResult:
    """Result of export operation."""
    repos_exported: int = 0
    events_exported: int = 0
    readmes_exported: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class ExportService:
    """
    Service for exporting repository index.

    ECHO format exports are:
    - Durable: SQLite + JSONL survive format changes
    - Self-describing: README explains contents
    - Complete: Works without the original tool

    Example:
        service = ExportService()
        options = ExportOptions(output_dir=Path("/tmp/export"))

        for progress in service.export(options):
            print(progress)  # "Exporting repos.jsonl..."

        # Result includes stats
        result = service.last_result
        print(f"Exported {result.repos_exported} repos")
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize ExportService.

        Args:
            config: Configuration dict (loads default if None)
        """
        self.config = config or load_config()
        self.last_result: Optional[ExportResult] = None
        self._version = self._get_version()

    def _get_version(self) -> str:
        """Get repoindex version."""
        try:
            from .. import __version__
            return __version__
        except ImportError:
            return "unknown"

    def export(
        self,
        options: ExportOptions
    ) -> Generator[str, None, ExportResult]:
        """
        Export repository index.

        Yields progress messages, returns ExportResult.

        Args:
            options: Export options

        Yields:
            Progress messages

        Returns:
            ExportResult with stats and any errors
        """
        result = ExportResult()
        self.last_result = result

        # Prepare output directory
        output_dir = options.output_dir
        if not options.dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)

        # Get filtered repos if query specified
        filtered_repo_ids = None
        if options.query_filter:
            yield "Filtering repositories..."
            filtered_repo_ids = self._get_filtered_repo_ids(options.query_filter)

        try:
            # Core exports (always included)
            yield "Exporting database..."
            self._export_database(output_dir, options.dry_run)

            yield "Exporting repos.jsonl..."
            result.repos_exported = self._export_repos_jsonl(
                output_dir, options.dry_run, filtered_repo_ids
            )

            if options.include_events:
                yield "Exporting events.jsonl..."
                result.events_exported = self._export_events_jsonl(
                    output_dir, options.dry_run, filtered_repo_ids
                )

            # READMEs are metadata -- always included
            yield "Exporting repository READMEs..."
            result.readmes_exported = self._export_repo_readmes(
                output_dir, options.dry_run, filtered_repo_ids
            )

            yield "Generating site/..."
            self._generate_site(output_dir, result, options, filtered_repo_ids)

            yield "Generating README.md..."
            self._generate_readme(output_dir, result, options)

            yield "Generating manifest.json..."
            self._generate_manifest(output_dir, result, options)

        except Exception as e:
            logger.error(f"Export failed: {e}")
            result.errors.append(str(e))

        return result

    def _get_filtered_repo_ids(self, query_filter: str) -> set:
        """Get repo IDs matching the query filter."""
        from ..database import compile_query

        views = self.config.get('views', {})
        compiled = compile_query(query_filter, views=views)

        repo_ids = set()
        with Database(config=self.config, read_only=True) as db:
            db.execute(compiled.sql, compiled.params)
            for row in db.fetchall():
                repo_ids.add(row['id'])

        return repo_ids

    def _export_database(self, output_dir: Path, dry_run: bool) -> None:
        """Copy SQLite database to export directory."""
        db_path = get_db_path(self.config)

        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

        if not dry_run:
            dest = output_dir / 'index.db'
            shutil.copy2(db_path, dest)
            logger.debug(f"Copied database to {dest}")

    def _export_repos_jsonl(
        self, output_dir: Path, dry_run: bool, filtered_ids: Optional[set] = None
    ) -> int:
        """Export repositories to JSONL, including publication data."""
        count = 0

        if dry_run:
            with Database(config=self.config, read_only=True) as db:
                for repo in get_repos_with_tags(db):
                    if filtered_ids is not None and repo.get('id') not in filtered_ids:
                        continue
                    count += 1
            return count

        dest = output_dir / 'repos.jsonl'
        with Database(config=self.config, read_only=True) as db:
            # Pre-load publication data keyed by repo_id
            publications = self._get_publications(db)

            with open(dest, 'w', encoding='utf-8') as f:
                for repo in get_repos_with_tags(db):
                    if filtered_ids is not None and repo.get('id') not in filtered_ids:
                        continue

                    record = self._clean_record(repo)

                    # Merge publication data
                    repo_id = repo.get('id')
                    if repo_id in publications:
                        record['publications'] = publications[repo_id]

                    f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
                    count += 1

        logger.debug(f"Exported {count} repos to {dest}")
        return count

    def _get_publications(self, db: Database) -> Dict[int, list]:
        """Load all publication records grouped by repo_id."""
        publications: Dict[int, list] = {}
        db.execute("""
            SELECT repo_id, registry, package_name, current_version,
                   published, url, downloads_total, downloads_30d
            FROM publications
        """)
        for row in db.fetchall():
            record = dict(row)
            repo_id = record.pop('repo_id')
            publications.setdefault(repo_id, []).append(record)
        return publications

    def _export_events_jsonl(
        self, output_dir: Path, dry_run: bool, filtered_ids: Optional[set] = None
    ) -> int:
        """Export events to JSONL."""
        count = 0

        with Database(config=self.config, read_only=True) as db:
            if filtered_ids is not None:
                # Filter events to matching repos
                placeholders = ','.join('?' for _ in filtered_ids)
                sql = f"""
                    SELECT e.*, r.name as repo_name, r.path as repo_path
                    FROM events e
                    JOIN repos r ON r.id = e.repo_id
                    WHERE e.repo_id IN ({placeholders})
                    ORDER BY e.timestamp DESC
                """
                db.execute(sql, tuple(filtered_ids))
            else:
                db.execute("""
                    SELECT e.*, r.name as repo_name, r.path as repo_path
                    FROM events e
                    JOIN repos r ON r.id = e.repo_id
                    ORDER BY e.timestamp DESC
                """)
            rows = db.fetchall()

            if dry_run:
                return len(rows)

            dest = output_dir / 'events.jsonl'
            with open(dest, 'w', encoding='utf-8') as f:
                for row in rows:
                    record = dict(row)
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
                    count += 1

        logger.debug(f"Exported {count} events to {dest}")
        return count

    def _clean_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Clean a database record for export."""
        # Remove internal fields that aren't useful for export
        cleaned = {k: v for k, v in record.items() if v is not None}

        # Parse JSON fields
        for json_field in ['languages', 'github_topics', 'citation_authors']:
            if json_field in cleaned and isinstance(cleaned[json_field], str):
                try:
                    cleaned[json_field] = json.loads(cleaned[json_field])
                except json.JSONDecodeError:
                    pass

        return cleaned

    def _generate_readme(
        self,
        output_dir: Path,
        result: ExportResult,
        options: ExportOptions
    ) -> None:
        """Generate README.md for the export."""
        if options.dry_run:
            return

        readme_content = f"""# repoindex Export

**Exported**: {datetime.now().isoformat()}
**Version**: repoindex {self._version}
**Source**: {Path.home().name}'s repository collection

## Contents

| File | Description |
|------|-------------|
| `index.db` | SQLite database (full schema, queryable) |
| `repos.jsonl` | JSONL export ({result.repos_exported} repositories) |
"""

        if options.include_events:
            readme_content += "| `events.jsonl` | Git events (commits, tags, etc.) |\n"

        readme_content += "| `readmes/` | README snapshots from each repo |\n"
        readme_content += "| `site/` | Browsable HTML dashboard |\n"

        readme_content += """| `manifest.json` | ECHO manifest with metadata |

## Using the SQLite Database

The `index.db` file is a complete SQLite database that can be queried directly:

```bash
# Open with sqlite3
sqlite3 index.db

# List tables
.tables

# Query repos with DOI
SELECT name, citation_doi, citation_title
FROM repos
WHERE citation_doi IS NOT NULL;

# Find Python repos with most stars
SELECT name, github_stars, description
FROM repos
WHERE language = 'Python'
ORDER BY github_stars DESC
LIMIT 10;

# Find recently active repos
SELECT r.name, COUNT(*) as commits
FROM repos r
JOIN events e ON e.repo_id = r.id
WHERE e.type = 'commit'
  AND e.timestamp > datetime('now', '-30 days')
GROUP BY r.id
ORDER BY commits DESC;
```

## Using the JSONL Export

JSONL files can be processed line-by-line:

```bash
# Count repos by language
jq -r '.language // "unknown"' repos.jsonl | sort | uniq -c | sort -rn

# Find repos with DOIs
jq -r 'select(.citation_doi) | "\\(.name): \\(.citation_doi)"' repos.jsonl

# Export Python repo names
jq -r 'select(.language == "Python") | .name' repos.jsonl
```

## Schema Overview

### repos table
- `name`, `path` - Repository identity
- `language`, `languages` - Detected programming languages
- `branch`, `is_clean`, `ahead`, `behind` - Git status
- `github_*` - GitHub metadata (stars, forks, topics, etc.)
- `citation_*` - Citation metadata from CITATION.cff/.zenodo.json

### events table
- `type` - Event type (commit, git_tag, branch, merge)
- `timestamp` - When the event occurred
- `repo_id` - Foreign key to repos
- `message`, `author` - Event details

### tags table
- User-assigned and auto-generated tags for categorization

### publications table
- Package registry status (PyPI, CRAN, npm, etc.)
- `registry`, `package_name`, `current_version`, `published`

## ECHO Compliance

This export follows ECHO principles:
- **Durable formats**: SQLite and JSONL will be readable for decades
- **Self-describing**: This README and manifest.json explain everything
- **No dependencies**: Works without repoindex installed
- **Complete**: All data needed to reconstruct the index

Generated by [repoindex](https://github.com/queelius/repoindex)
"""

        dest = output_dir / 'README.md'
        dest.write_text(readme_content)
        logger.debug(f"Generated README at {dest}")

    def _generate_manifest(
        self,
        output_dir: Path,
        result: ExportResult,
        options: ExportOptions
    ) -> None:
        """Generate ECHO-compliant manifest."""
        if options.dry_run:
            return

        # Get language distribution for description
        languages = {}
        with Database(config=self.config, read_only=True) as db:
            db.execute("""
                SELECT language, COUNT(*) as count
                FROM repos
                WHERE language IS NOT NULL
                GROUP BY language
                ORDER BY count DESC
                LIMIT 20
            """)
            for row in db.fetchall():
                languages[row['language']] = row['count']

        # Build human-readable description
        top_langs = list(languages.keys())[:3]
        lang_str = ', '.join(top_langs) if top_langs else 'various'
        description = (
            f"Git repository collection "
            f"({result.repos_exported} repos, top languages: {lang_str})"
        )

        manifest: Dict[str, Any] = {
            "version": "1.0",
            "name": "Repository Index",
            "description": description,
            "type": "database",
            "icon": "code",
            "_repoindex": {
                "toolkit_version": self._version,
                "exported_at": datetime.now().isoformat(),
                "stats": {
                    "total_repos": result.repos_exported,
                    "events_exported": result.events_exported,
                    "readmes_exported": result.readmes_exported,
                    "languages": languages,
                },
                "options": {
                    "include_events": options.include_events,
                    "query_filter": options.query_filter,
                },
            }
        }

        dest = output_dir / 'manifest.json'
        dest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        logger.debug(f"Generated manifest at {dest}")

    def _export_repo_readmes(
        self, output_dir: Path, dry_run: bool, filtered_ids: Optional[set] = None
    ) -> int:
        """Export README files from each repository."""
        if dry_run:
            return 0

        readmes_dir = output_dir / 'readmes'
        readmes_dir.mkdir(exist_ok=True)
        count = 0

        readme_names = ['README.md', 'README.rst', 'README.txt', 'README']

        with Database(config=self.config, read_only=True) as db:
            for repo in get_all_repos(db):
                if filtered_ids is not None and repo.get('id') not in filtered_ids:
                    continue

                repo_path = Path(repo['path'])
                if not repo_path.exists():
                    continue

                for readme_name in readme_names:
                    readme_file = repo_path / readme_name
                    if readme_file.exists():
                        dest_name = self._safe_filename(repo['name']) + self._get_extension(readme_name)
                        dest = readmes_dir / dest_name
                        try:
                            shutil.copy2(readme_file, dest)
                            count += 1
                        except (IOError, OSError) as e:
                            logger.debug(f"Failed to copy README for {repo['name']}: {e}")
                        break

        logger.debug(f"Exported {count} READMEs to {readmes_dir}")
        return count

    def _generate_site(
        self,
        output_dir: Path,
        result: ExportResult,
        options: ExportOptions,
        filtered_ids: Optional[set] = None,
    ) -> None:
        """Generate a browsable site/ directory with an HTML dashboard."""
        if options.dry_run:
            return

        site_dir = output_dir / 'site'
        site_dir.mkdir(exist_ok=True)

        # Gather data for the dashboard
        repos_data = []
        languages: Dict[str, int] = {}

        with Database(config=self.config, read_only=True) as db:
            for repo in get_repos_with_tags(db):
                if filtered_ids is not None and repo.get('id') not in filtered_ids:
                    continue

                repos_data.append({
                    'name': repo.get('name', ''),
                    'language': repo.get('language', ''),
                    'branch': repo.get('branch', ''),
                    'description': repo.get('description') or repo.get('github_description') or '',
                    'stars': repo.get('github_stars') or 0,
                    'tags': repo.get('tags', []),
                })

                lang = repo.get('language')
                if lang:
                    languages[lang] = languages.get(lang, 0) + 1

        # Sort repos by name
        repos_data.sort(key=lambda r: r['name'].lower())

        # Sort languages by count descending
        sorted_langs = sorted(languages.items(), key=lambda x: -x[1])

        # Build the HTML
        html = self._build_site_html(repos_data, sorted_langs, options)
        (site_dir / 'index.html').write_text(html, encoding='utf-8')
        logger.debug(f"Generated site at {site_dir}")

    def _build_site_html(
        self,
        repos: list,
        languages: list,
        options: ExportOptions,
    ) -> str:
        """Build a self-contained HTML dashboard."""
        now = datetime.now().isoformat(timespec='seconds')
        total = len(repos)

        # Language stats rows
        lang_rows = ''.join(
            f'<tr><td>{lang}</td><td>{count}</td></tr>'
            for lang, count in languages
        )

        # Repo table rows
        repo_rows = ''
        for r in repos:
            tags_str = ', '.join(r['tags'][:5])
            if len(r['tags']) > 5:
                tags_str += f' (+{len(r["tags"]) - 5})'
            desc = _html_escape(r['description'][:120]) if r['description'] else ''
            repo_rows += (
                f'<tr>'
                f'<td>{_html_escape(r["name"])}</td>'
                f'<td>{_html_escape(r["language"])}</td>'
                f'<td>{r["stars"]}</td>'
                f'<td>{_html_escape(r["branch"])}</td>'
                f'<td class="desc">{desc}</td>'
                f'<td class="tags">{_html_escape(tags_str)}</td>'
                f'</tr>\n'
            )

        filter_note = ''
        if options.query_filter:
            filter_note = f'<p class="filter">Filtered by: <code>{_html_escape(options.query_filter)}</code></p>'

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Repository Index</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 2rem; color: #222; }}
  h1 {{ margin-bottom: .25rem; }}
  .meta {{ color: #666; font-size: .9rem; margin-bottom: 1.5rem; }}
  .filter {{ background: #fff3cd; padding: .5rem 1rem; border-radius: 4px; margin-bottom: 1rem; }}
  .stats {{ display: flex; gap: 2rem; margin-bottom: 2rem; flex-wrap: wrap; }}
  .stat-card {{ background: #f5f5f5; padding: 1rem 1.5rem; border-radius: 8px; }}
  .stat-card .num {{ font-size: 1.8rem; font-weight: bold; }}
  .stat-card .label {{ color: #666; font-size: .85rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
  th, td {{ text-align: left; padding: .5rem .75rem; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #f5f5f5; position: sticky; top: 0; }}
  td.desc {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  td.tags {{ max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #666; font-size: .85rem; }}
  .lang-table {{ max-width: 300px; margin-bottom: 2rem; }}
  .lang-table td:last-child {{ text-align: right; }}
  footer {{ margin-top: 2rem; color: #999; font-size: .8rem; }}
</style>
</head>
<body>
<h1>Repository Index</h1>
<p class="meta">Exported {now} &middot; repoindex {_html_escape(self._version)}</p>
{filter_note}

<div class="stats">
  <div class="stat-card"><div class="num">{total}</div><div class="label">Repositories</div></div>
  <div class="stat-card"><div class="num">{len(languages)}</div><div class="label">Languages</div></div>
</div>

<h2>Languages</h2>
<table class="lang-table">
<tr><th>Language</th><th>Count</th></tr>
{lang_rows}
</table>

<h2>Repositories</h2>
<table>
<tr><th>Name</th><th>Language</th><th>Stars</th><th>Branch</th><th>Description</th><th>Tags</th></tr>
{repo_rows}
</table>

<footer>Generated by repoindex &middot; ECHO-compliant export</footer>
</body>
</html>"""

    def _safe_filename(self, name: str) -> str:
        """Convert a name to a safe filename."""
        # Replace unsafe characters with underscores
        safe = name.replace('/', '_').replace('\\', '_').replace(':', '_')
        safe = safe.replace('<', '_').replace('>', '_').replace('"', '_')
        safe = safe.replace('|', '_').replace('?', '_').replace('*', '_')
        return safe

    def _get_extension(self, filename: str) -> str:
        """Get the extension for a README file."""
        if filename.endswith('.md'):
            return '.md'
        elif filename.endswith('.rst'):
            return '.rst'
        elif filename.endswith('.txt'):
            return '.txt'
        return '.txt'  # Default for plain README


def _html_escape(text: str) -> str:
    """Minimal HTML escaping for safe output."""
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )
