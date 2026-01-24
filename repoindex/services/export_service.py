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
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Generator, List, Optional

from ..config import load_config
from ..database import Database
from ..database.repository import get_all_repos, get_repos_with_tags

logger = logging.getLogger(__name__)


@dataclass
class ExportOptions:
    """Options for export operation."""
    output_dir: Path
    include_readmes: bool = False
    include_git_summary: int = 0  # Number of commits per repo
    include_events: bool = False
    archive_repos: bool = False
    dry_run: bool = False


@dataclass
class ExportResult:
    """Result of export operation."""
    repos_exported: int = 0
    events_exported: int = 0
    readmes_exported: int = 0
    git_summaries_exported: int = 0
    archives_created: int = 0
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

        try:
            # Tier 1: Core exports (always included)
            yield "Exporting database..."
            self._export_database(output_dir, options.dry_run)

            yield "Exporting repos.jsonl..."
            result.repos_exported = self._export_repos_jsonl(output_dir, options.dry_run)

            if options.include_events:
                yield "Exporting events.jsonl..."
                result.events_exported = self._export_events_jsonl(output_dir, options.dry_run)

            yield "Generating README.md..."
            self._generate_readme(output_dir, result, options)

            yield "Generating manifest.json..."
            self._generate_manifest(output_dir, result, options)

            # Tier 2: Optional enhanced exports
            if options.include_readmes:
                yield "Exporting repository READMEs..."
                result.readmes_exported = self._export_repo_readmes(output_dir, options.dry_run)

            if options.include_git_summary > 0:
                yield f"Exporting git summaries (last {options.include_git_summary} commits)..."
                result.git_summaries_exported = self._export_git_summaries(
                    output_dir, options.include_git_summary, options.dry_run
                )

            # Tier 3: Archive repos (heavy operation)
            if options.archive_repos:
                yield "Creating repository archives..."
                result.archives_created = self._create_archives(output_dir, options.dry_run)

        except Exception as e:
            logger.error(f"Export failed: {e}")
            result.errors.append(str(e))

        return result

    def _export_database(self, output_dir: Path, dry_run: bool) -> None:
        """Copy SQLite database to export directory."""
        db_path = Path(self.config.get('database', {}).get(
            'path',
            Path.home() / '.repoindex' / 'repoindex.db'
        ))

        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

        if not dry_run:
            dest = output_dir / 'index.db'
            shutil.copy2(db_path, dest)
            logger.debug(f"Copied database to {dest}")

    def _export_repos_jsonl(self, output_dir: Path, dry_run: bool) -> int:
        """Export all repositories to JSONL."""
        count = 0

        if dry_run:
            with Database(config=self.config, read_only=True) as db:
                for _ in get_repos_with_tags(db):
                    count += 1
            return count

        dest = output_dir / 'repos.jsonl'
        with Database(config=self.config, read_only=True) as db:
            with open(dest, 'w', encoding='utf-8') as f:
                for repo in get_repos_with_tags(db):
                    # Clean up record for export
                    record = self._clean_record(repo)
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
                    count += 1

        logger.debug(f"Exported {count} repos to {dest}")
        return count

    def _export_events_jsonl(self, output_dir: Path, dry_run: bool) -> int:
        """Export all events to JSONL."""
        count = 0

        with Database(config=self.config, read_only=True) as db:
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

        if options.include_readmes:
            readme_content += "| `readmes/` | README snapshots from each repo |\n"

        if options.include_git_summary > 0:
            readme_content += f"| `git-summaries/` | Last {options.include_git_summary} commits per repo |\n"

        if options.archive_repos:
            readme_content += "| `archives/` | Full repository archives (.tar.gz) |\n"

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
        """Generate ECHO manifest."""
        if options.dry_run:
            return

        # Get language distribution
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

        manifest: Dict[str, Any] = {
            "echo_version": "1.0",
            "toolkit": "repoindex",
            "toolkit_version": self._version,
            "exported_at": datetime.now().isoformat(),
            "contents": {
                "index.db": {
                    "type": "sqlite3",
                    "description": "Full database with schema"
                },
                "repos.jsonl": {
                    "type": "jsonl",
                    "count": result.repos_exported,
                    "description": "Repository records"
                }
            },
            "stats": {
                "total_repos": result.repos_exported,
                "languages": languages
            },
            "options": {
                "include_readmes": options.include_readmes,
                "include_events": options.include_events,
                "include_git_summary": options.include_git_summary,
                "archive_repos": options.archive_repos
            }
        }

        if options.include_events:
            manifest["contents"]["events.jsonl"] = {
                "type": "jsonl",
                "count": result.events_exported,
                "description": "Git event history"
            }

        dest = output_dir / 'manifest.json'
        dest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        logger.debug(f"Generated manifest at {dest}")

    def _export_repo_readmes(self, output_dir: Path, dry_run: bool) -> int:
        """Export README files from each repository."""
        if dry_run:
            return 0

        readmes_dir = output_dir / 'readmes'
        readmes_dir.mkdir(exist_ok=True)
        count = 0

        readme_names = ['README.md', 'README.rst', 'README.txt', 'README']

        with Database(config=self.config, read_only=True) as db:
            for repo in get_all_repos(db):
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

    def _export_git_summaries(self, output_dir: Path, n_commits: int, dry_run: bool) -> int:
        """Export git log summaries for each repo."""
        if dry_run:
            return 0

        summaries_dir = output_dir / 'git-summaries'
        summaries_dir.mkdir(exist_ok=True)
        count = 0

        with Database(config=self.config, read_only=True) as db:
            for repo in get_all_repos(db):
                repo_path = Path(repo['path'])
                if not repo_path.exists():
                    continue

                # Get recent commits from events table
                db.execute("""
                    SELECT timestamp, message, author
                    FROM events
                    WHERE repo_id = ? AND type = 'commit'
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (repo['id'], n_commits))
                commits = [dict(row) for row in db.fetchall()]

                if commits:
                    summary = {
                        "repo": repo['name'],
                        "path": repo['path'],
                        "commits": commits
                    }
                    dest = summaries_dir / (self._safe_filename(repo['name']) + '.json')
                    dest.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
                    count += 1

        logger.debug(f"Exported {count} git summaries to {summaries_dir}")
        return count

    def _create_archives(self, output_dir: Path, dry_run: bool) -> int:
        """Create tar.gz archives of repositories."""
        if dry_run:
            return 0

        archives_dir = output_dir / 'archives'
        archives_dir.mkdir(exist_ok=True)
        count = 0

        with Database(config=self.config, read_only=True) as db:
            for repo in get_all_repos(db):
                repo_path = Path(repo['path'])
                if not repo_path.exists():
                    continue

                archive_name = self._safe_filename(repo['name']) + '.tar.gz'
                archive_path = archives_dir / archive_name

                try:
                    with tarfile.open(archive_path, 'w:gz') as tar:
                        tar.add(repo_path, arcname=repo['name'])
                    count += 1
                    logger.debug(f"Created archive: {archive_path}")
                except (IOError, OSError, tarfile.TarError) as e:
                    logger.debug(f"Failed to archive {repo['name']}: {e}")

        logger.debug(f"Created {count} archives in {archives_dir}")
        return count

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
