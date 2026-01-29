# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**"repoindex is a filesystem git catalog."**

It indexes **local git directories** accessible via standard filesystem operations. The **filesystem path IS the canonical identity** of a repository — each local path is an independent entity regardless of remotes.

External platforms (GitHub, PyPI, CRAN) provide **optional enrichment metadata**, but repoindex has **no dependency on any single platform**. Platform-specific fields are namespaced (`github_stars`, `pypi_published`) to maintain clear provenance.

**Current Version**: 0.10.0

**See also**: [DESIGN.md](DESIGN.md) for detailed design principles and architecture.

## Vision

```
Claude Code (deep work on ONE repo)
         │
         │ "What else do I have?"
         │ "Which repos need X?"
         ▼
    repoindex (collection awareness)
         │
         ├── query       → filter and search
         ├── status      → health dashboard
         ├── events      → what happened
         ├── tags        → organization
         └── ops         → collection operations (push/pull, citations)
```

### Core Principles (v0.10.0)
1. **Path is Identity** - filesystem path defines a repo, not remote URL
2. **Local-First** - works fully offline; external APIs are opt-in
3. **Platforms are Enrichment** - GitHub, PyPI add metadata but don't define identity
4. **Explicit Provenance** - platform fields are namespaced (`github_*`, `pypi_*`)
5. **No Platform Lock-in** - no dependency on any single external system
6. **CLI first** - compose with Unix tools via pipes

### Core Capabilities
1. **Repository Discovery** - Find and track repos across directories
2. **Tag-Based Organization** - Hierarchical tags for categorization
3. **Registry Awareness** - PyPI, CRAN publication status
4. **Event Tracking** - New tags, releases, publishes (28 event types)
5. **Statistics** - Aggregations across the collection
6. **Query Language** - Filter and search with expressions
7. **Collection Operations** - Multi-repo git push/pull, metadata generation

## Using repoindex with Claude Code

Claude Code can run repoindex CLI commands directly. Compose with Unix tools via pipes.

### Common Patterns

```bash
# Dashboard overview
repoindex status

# Repos with uncommitted changes (pretty table by default)
repoindex query --dirty

# Find Python repos with GitHub stars
repoindex query --language python --starred

# What happened recently?
repoindex events --since 7d

# What got released this week?
repoindex events --type git_tag --since 7d

# JSONL output for piping/scripting
repoindex query --json --language python | jq '.name'

# Raw SQL access
repoindex sql "SELECT name, github_stars FROM repos ORDER BY github_stars DESC LIMIT 10"
```

### Query Convenience Flags

**Local flags** (no prefix - these are about the local git directory):
```bash
repoindex query --dirty              # Uncommitted changes
repoindex query --clean              # No uncommitted changes
repoindex query --language python    # Python repos (detected locally)
repoindex query --recent 7d          # Recent local commits
repoindex query --tag "work/*"       # By tag
repoindex query --no-license         # Missing license file
repoindex query --no-readme          # Missing README
repoindex query --has-citation       # Has citation files (CITATION.cff, .zenodo.json)
repoindex query --has-doi            # Has DOI in citation metadata
repoindex query --has-remote         # Has any remote URL
```

**GitHub flags** (requires `--github` during refresh):
```bash
repoindex query --starred            # Has GitHub stars
repoindex query --private            # Private on GitHub
repoindex query --public             # Public on GitHub
repoindex query --fork               # Is a fork on GitHub
repoindex query --no-fork            # Non-forked repos only
repoindex query --archived           # Archived on GitHub
```

### Event Types

Events are populated by `refresh` and stored in the SQLite database:
- `git_tag`, `commit`, `branch`, `merge`

Query events from the database:
```bash
repoindex events --since 7d              # Pretty table (default)
repoindex events --type commit --since 30d
repoindex events --repo myproject
repoindex events --stats
repoindex events --json --since 7d       # JSONL for piping
```

### Output Formats

`query` and `events` output pretty tables by default. Use `--json` for JSONL:
```bash
# Default: pretty tables
repoindex query --language python
repoindex events --since 7d

# JSONL for piping/scripting
repoindex query --json --language python | jq '.name'
repoindex events --json --since 7d | jq '.type' | sort | uniq -c

# Brief output (just repo names)
repoindex query --brief --dirty
```

## CRITICAL DESIGN PRINCIPLES

### 1. Unix Philosophy First
- **Do one thing well**: Each command has a single, clear purpose
- **Compose via pipes**: Output of one command feeds into another
- **Text streams are the universal interface**: JSONL is our text stream format

### 2. Output Format Rules
- **Read commands** (`query`, `events`): Pretty tables by default, `--json` for JSONL
- **Write/ops commands** (`export`, `copy`, `link`, `ops`): Simple text to stderr, `--pretty` for rich formatting, `--json` for JSONL
- **Stream, don't collect**: Output each object as it's processed
- **Errors go to stderr**: Keep stdout clean for piping
- **Brief mode**: Use `--brief` for just repo names (one per line)

### 3. Architecture Layers
```
Commands (CLI) → Services → Infrastructure → Domain
     ↓              ↓            ↓             ↓
   Parse args    Business    External      Pure data
   Handle I/O    logic       systems       Immutable
   Format output Orchestrate Clients       Dataclasses
```

### 4. Layered Architecture
- **Domain Layer**: Immutable dataclasses (Repository, Tag, Event)
- **Infrastructure Layer**: External system clients (GitClient, GitHubClient, FileStore)
- **Service Layer**: Business logic (RepositoryService, TagService, EventService)
- **Command Layer**: Thin CLI wrappers that use services

### 5. Command Implementation Pattern
```python
@click.command()
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
def query_handler(output_json):
    """Query repositories."""
    # Get data as generator from service
    repos = repo_service.query_repos()

    if output_json:
        # Stream JSONL for piping
        for repo in repos:
            print(json.dumps(repo), flush=True)
    else:
        # Pretty table (default for interactive commands)
        render.repos_table(list(repos))
```

### 6. Error Handling
- **Structured errors**: Errors are JSON objects: `{"error": "message", "context": {...}}`
- **Continue on error**: Don't stop the stream, output error objects
- **stderr for fatal errors**: Only use stderr for unrecoverable errors

### 7. Standard Data Models

#### Repository Domain Object
```python
@dataclass(frozen=True)
class Repository:
    path: str
    name: str
    branch: str = "main"
    clean: bool = True
    remote_url: Optional[str] = None
    language: Optional[str] = None
    description: Optional[str] = None
```

#### Error Object
```json
{
  "error": "string describing error",
  "type": "git_error|file_error|api_error|...",
  "context": {
    "path": "/path/to/repo",
    "command": "git status",
    "stderr": "detailed error output"
  }
}
```

## Development Commands

### Essential Commands
```bash
make install          # Create .venv, install dependencies and package in dev mode
make test            # Run test suite using pytest (requires .venv activation)
make build           # Build wheel and sdist packages
make clean           # Remove build artifacts, cache files, and .venv
```

**IMPORTANT**: All `make` commands automatically use `.venv/` virtual environment. The Makefile handles activation internally. You don't need to manually activate the venv before running make commands.

### Documentation
```bash
make docs            # Build documentation using mkdocs
make serve-docs      # Serve documentation at http://localhost:8000
make gh-pages        # Deploy documentation to GitHub Pages
```

### Publishing
```bash
make build-pypi      # Build packages for PyPI distribution
make publish-pypi    # Upload to PyPI (requires twine and credentials)
```

### Testing
```bash
# Run all tests via make (uses .venv automatically)
make test

# Or activate .venv and run pytest directly:
source .venv/bin/activate

# Run all tests with verbose output
pytest --maxfail=3 --disable-warnings -v

# Run specific test file
pytest tests/test_core.py -v

# Run tests matching pattern
pytest -k "test_status" -v

# Run with coverage (RECOMMENDED after changes)
pytest --cov=repoindex --cov-report=html

# Run with coverage and open report
pytest --cov=repoindex --cov-report=html && open htmlcov/index.html
```

**Test Coverage Requirements**:
- Test suite contains 810+ tests
- Tests located in `tests/` directory, using `pyfakefs` for filesystem mocking
- **ALWAYS run coverage after adding new features**: `pytest --cov=repoindex --cov-report=html`
- Coverage report available in `htmlcov/index.html` after running coverage

**IMPORTANT - `run_command` return values**:
The `run_command()` function in `utils.py` returns a tuple `(stdout, returncode)`. When mocking or using this function:
```python
# Correct usage:
output, returncode = run_command("git status", cwd=repo_path, capture_output=True)

# When mocking in tests:
mock_run_command.return_value = ("output string", 0)  # Success
mock_run_command.return_value = (None, 1)  # Failure
mock_run_command.side_effect = [("output1", 0), ("output2", 0)]  # Multiple calls
```

## Architecture

### Layered Module Structure

**Domain Layer** (`repoindex/domain/`):
- `models.py` - Immutable dataclasses: Repository, Tag, Event
- Pure data objects with no dependencies
- Frozen dataclasses for immutability

**Infrastructure Layer** (`repoindex/infrastructure/`):
- `git_client.py` - Git operations (status, remotes, tags)
- `github_client.py` - GitHub API client
- `file_store.py` - JSON file persistence
- `output.py` - JSONL streaming output

**Service Layer** (`repoindex/services/`):
- `repository_service.py` - Repository discovery and metadata
- `tag_service.py` - Tag management
- `event_service.py` - Event scanning
- `export_service.py` - ECHO format export

**Command Layer** (`repoindex/commands/`):
- Individual CLI command implementations
- Parse arguments with Click
- Use services for business logic
- Format output: Pretty tables (default), `--json` for JSONL

### Core Modules
- `repoindex/cli.py` - Main CLI entry point using Click framework
- `repoindex/config.py` - Configuration management with JSON/TOML support
- `repoindex/utils.py` - Shared utility functions
- `repoindex/simple_query.py` - Query language with fuzzy matching
- `repoindex/citation.py` - Citation file parsing (CITATION.cff, .zenodo.json)
- `repoindex/pypi.py` - PyPI package detection and API integration
- `repoindex/cran.py` - CRAN package detection
- `repoindex/events.py` - Stateless event scanning (git tags, commits)
- `repoindex/tags.py` - Tag management and implicit tag generation

### Key Design Patterns
- **Layered Architecture**: Domain → Infrastructure → Services → Commands
- **Dependency Injection**: Services receive clients via constructor
- **Immutable Domain Objects**: Frozen dataclasses for thread safety
- **JSONL Streaming**: `--json` flag enables JSONL for Unix pipelines
- **Configuration Cascading**: Defaults → config file → environment variables

### Dependencies
- `rich>=13.0.0` - Enhanced terminal output and progress bars
- `requests>=2.25.0` - HTTP requests for API integration
- `packaging>=21.0` - Package version handling
- `click` - CLI framework
- `rapidfuzz` - Fuzzy string matching for query language
- `pyyaml` - YAML configuration files

### Commands Implemented (14 commands)

```
repoindex
├── status              # Dashboard: health overview
├── query               # Human-friendly repo search with flags
├── events              # Query events from database
├── sql                 # Raw SQL queries + database management
├── refresh             # Database sync (repos + events)
├── export              # ECHO format export (durable, self-describing)
├── copy                # Copy repositories with filtering (backup/redundancy)
├── link                # Symlink tree management
│   ├── tree            # Create symlink trees organized by metadata
│   ├── refresh         # Update existing tree (remove broken links)
│   └── status          # Show tree health status
├── ops                 # Collection-level operations
│   ├── git             # Multi-repo git operations
│   │   ├── push        # Push repos with unpushed commits
│   │   ├── pull        # Pull updates from remotes
│   │   └── status      # Multi-repo git status summary
│   └── generate        # Boilerplate file generation
│       ├── codemeta        # Generate codemeta.json files
│       ├── license         # Generate LICENSE files
│       ├── gitignore       # Generate .gitignore files
│       ├── code-of-conduct # Generate CODE_OF_CONDUCT.md
│       └── contributing    # Generate CONTRIBUTING.md
├── tag                 # Organization (add/remove/list/tree)
├── view                # Curated views (list/show/create/delete)
├── config              # Settings (show/repos/init)
├── claude              # Skill management (install/uninstall/show)
└── shell               # Interactive mode
```

## Configuration

Configuration is managed through `~/.repoindex/config.yaml` (YAML is the only supported format for new configurations; existing JSON configs are auto-migrated). Use `REPOINDEX_CONFIG` environment variable to override location.

Key configuration sections:
- `repository_directories` - List of repo directories (supports ** glob patterns)
- `github.token` - GitHub API token (or use GITHUB_TOKEN env var)
- `github.rate_limit` - Retry configuration with exponential backoff
- `repository_tags` - Manual tag assignments for repos
- `author` - Author identity for metadata generation (see below)

### Author Configuration
The `author` section stores identity information for metadata generation:
```yaml
author:
  name: "Alexander Towell"     # Full name for citations
  alias: "Alex Towell"          # Short/preferred name
  email: "alex@example.com"
  orcid: "0000-0001-6443-9897"  # ORCID identifier
  github: "queelius"            # GitHub username
  affiliation: "University"
  url: "https://example.com"
  zenodo_token: ""              # For future Zenodo integration
```

Environment variable overrides: `REPOINDEX_AUTHOR_NAME`, `REPOINDEX_AUTHOR_EMAIL`, `REPOINDEX_AUTHOR_ORCID`, `REPOINDEX_AUTHOR_GITHUB`

The SQLite database (`~/.repoindex/repoindex.db`) is the canonical cache. Run `repoindex refresh` to populate.

### Rate Limiting
GitHub API calls use intelligent rate limiting:
- Configurable max_retries and max_delay_seconds
- Respects GitHub's rate limit reset time
- Exponential backoff between retries

## Important Design Decisions

### Layered Architecture (v0.9.0)
We refactored to a clean layered architecture:
- **Domain**: Pure data objects (Repository, Tag, Event)
- **Infrastructure**: External system clients (GitClient, GitHubClient, FileStore)
- **Services**: Business logic orchestration
- **Commands**: Thin CLI wrappers

### Tag System
- **Explicit tags**: User-assigned tags stored in config
- **Implicit tags**: Auto-generated (repo:name, dir:parent, lang:python)
- **Provider tags**: From GitHub topics, etc.
- **Protected namespaces**: Some prefixes reserved for system use

### Query Language
- Simple boolean expressions with fuzzy matching via `rapidfuzz`
- Path-based access to nested fields (e.g., `license.key`, `pypi_version`)
- Platform fields are namespaced: `github_stars`, `github_is_private`, `pypi_published`
- Operators: `==`, `!=`, `~=` (fuzzy), `>`, `<`, `contains`, `in`
- Examples:
  - `"language ~= 'pyton'"` - fuzzy match Python
  - `"'ml' in github_topics"` - check if 'ml' in GitHub topics list
  - `"github_stars > 10 and language == 'Python'"` - multiple conditions
  - `"github_is_private"` - repos that are private on GitHub
  - `"pypi_published"` - repos published to PyPI
  - `"citation_doi != ''"` - repos with DOI in citation metadata

### Citation Metadata
Repos with CITATION.cff or .zenodo.json files have parsed metadata:
- `citation_doi` - DOI identifier (e.g., "10.5281/zenodo.1234567")
- `citation_title` - Software title from citation file
- `citation_authors` - JSON array of author objects
- `citation_version` - Version from citation file
- `citation_repository` - Repository URL from citation file
- `citation_license` - License from citation file

Query examples:
```bash
repoindex query --has-doi                    # Repos with DOI
repoindex query "citation_doi != ''"          # Same as above
repoindex sql "SELECT name, citation_doi, citation_title FROM repos WHERE citation_doi IS NOT NULL"
```

### SQL Data Model

The SQLite database (`~/.repoindex/repoindex.db`) is the canonical cache. Use `repoindex sql` for direct access.

**repos table** (main repository data):
```
-- Core identity
id, name, path (UNIQUE), branch, remote_url, owner

-- Git status
is_clean, ahead, behind, has_upstream, uncommitted_changes, untracked_files

-- Metadata
language, languages (JSON array), description, readme_content

-- License
license_key (SPDX), license_name, license_file

-- File presence
has_readme, has_license, has_ci, has_citation, citation_file

-- Citation metadata (from CITATION.cff/.zenodo.json)
citation_doi, citation_title, citation_authors (JSON), citation_version,
citation_repository, citation_license

-- GitHub metadata (all github_ prefixed)
github_owner, github_name, github_description,
github_stars, github_forks, github_watchers, github_open_issues,
github_is_fork, github_is_private, github_is_archived,
github_has_issues, github_has_wiki, github_has_pages, github_pages_url,
github_topics (JSON array),
github_created_at, github_updated_at, github_pushed_at

-- Operational
scanned_at, git_index_mtime
```

**events table** (git activity):
```
id, repo_id (FK→repos), event_id (UNIQUE), type, timestamp, ref, message, author, metadata (JSON)
-- Types: git_tag, commit, branch, merge
```

**tags table** (repo organization):
```
repo_id (FK→repos), tag, source ('user'|'implicit'|'github'), created_at
-- Primary key: (repo_id, tag)
```

**publications table** (package registries):
```
repo_id (FK→repos), registry ('pypi'|'npm'|'cran'|'cargo'|'docker'),
package_name, current_version, published, url, downloads_total, downloads_30d
-- Unique: (repo_id, registry)
```

**Example SQL queries**:
```bash
# Top starred repos
repoindex sql "SELECT name, github_stars FROM repos WHERE github_stars > 0 ORDER BY github_stars DESC LIMIT 10"

# Missing license
repoindex sql "SELECT name, path FROM repos WHERE has_license = 0"

# Recent commits by repo
repoindex sql "SELECT r.name, COUNT(*) as n FROM events e JOIN repos r ON e.repo_id = r.id WHERE e.type = 'commit' AND e.timestamp > datetime('now', '-30 days') GROUP BY r.id ORDER BY n DESC"

# Published packages
repoindex sql "SELECT r.name, p.registry, p.package_name FROM publications p JOIN repos r ON p.repo_id = r.id WHERE p.published = 1"

# Repos by language
repoindex sql "SELECT language, COUNT(*) as n FROM repos GROUP BY language ORDER BY n DESC"
```

### Export Command
Export repository index in ECHO-compliant format (durable, self-describing, offline-capable).
READMEs and a browsable site/ directory are always included (they are metadata).
Supports the same query flags as `query` to export a subset.
```bash
# Basic export (database + JSONL + READMEs + site + manifest)
repoindex export ~/backups/repos-2026-01

# Include full event history
repoindex export ~/backups/repos --include-events

# Export subset using query flags
repoindex export ~/backups/python-repos --language python
repoindex export ~/backups/starred --starred
repoindex export ~/backups/work --tag "work/*"

# DSL query expression
repoindex export ~/backups/popular "language == 'Python' and github_stars > 10"

# Preview without writing
repoindex export ~/backups/test --dry-run --pretty
```

Output structure:
```
output-dir/
├── README.md           # Human-readable documentation
├── manifest.json       # ECHO manifest (standard schema)
├── index.db            # SQLite database copy (full snapshot)
├── repos.jsonl         # Repository records (with publications)
├── readmes/            # README from each repo (always included)
│   ├── my-project.md
│   └── other-repo.md
├── site/               # Browsable HTML dashboard (always included)
│   └── index.html
└── events.jsonl        # Optional: --include-events
```

ECHO manifest schema (`manifest.json`):
```json
{
  "version": "1.0",
  "name": "Repository Index",
  "description": "Git repository collection (N repos, top languages: ...)",
  "type": "database",
  "icon": "code",
  "_repoindex": {
    "toolkit_version": "0.10.0",
    "exported_at": "2026-01-28T...",
    "stats": {"total_repos": 120, "languages": {...}}
  }
}
```

### Copy Command
Copy repositories to a destination directory with filtering (useful for backups):
```bash
# Copy all repos to backup directory
repoindex copy ~/backups/repos-2026-01

# Copy with query filters (same flags as query command)
repoindex copy ~/backups/python-repos --language python
repoindex copy ~/backups/uncommitted --dirty
repoindex copy ~/backups/work-repos --tag "work/*"
repoindex copy ~/backups/popular "language == 'Python' and github_stars > 10"

# Options
repoindex copy ~/backups --exclude-git          # Skip .git directories
repoindex copy ~/backups --preserve-structure   # Keep parent dir hierarchy
repoindex copy ~/backups --collision rename     # rename/skip/overwrite
repoindex copy ~/backups --dry-run --pretty     # Preview
```

### Link Command
Create and manage symlink trees organized by metadata:
```bash
# Create symlink tree organized by tags
repoindex link tree ~/links/by-tag --by tag

# Create symlink tree organized by language
repoindex link tree ~/links/by-language --by language

# Other organization options
repoindex link tree ~/links/by-year --by modified-year
repoindex link tree ~/links/by-owner --by owner

# With query filtering (same flags as query command)
repoindex link tree ~/links/python --by tag --language python

# Preview without creating
repoindex link tree ~/links/test --by tag --dry-run --pretty

# Check tree status
repoindex link status ~/links/by-tag

# Refresh tree (remove broken symlinks)
repoindex link refresh ~/links/by-tag --prune
```

Output structure for tag-organized tree:
```
by-tag/
├── topic/
│   ├── ml/
│   │   └── my-project → /path/my-project
│   └── web/
│       └── webapp → /path/webapp
├── work/
│   └── active/
│       └── my-project → /path/my-project
└── .repoindex-links.json   # Manifest for refresh
```

### Ops Command
Collection-level operations: git push/pull across multiple repos, metadata generation.

```bash
# Git operations - push repos with unpushed commits
repoindex ops git push                          # Push all unpushed repos
repoindex ops git push --dry-run                # Preview without pushing
repoindex ops git push --language python        # Push only Python repos
repoindex ops git push --tag "work/*"           # Push repos with work/* tags
repoindex ops git push --yes                    # Skip confirmation prompt

# Git operations - pull updates
repoindex ops git pull                          # Pull all repos
repoindex ops git pull --dry-run                # Preview (fetches first)

# Git status across repos
repoindex ops git status                        # Status summary
repoindex ops git status --json                 # JSONL output

# Generate codemeta.json files
repoindex ops generate codemeta                 # All repos
repoindex ops generate codemeta --language python

# Generate LICENSE files
repoindex ops generate license --license mit    # MIT license
repoindex ops generate license --license apache-2.0
repoindex ops generate license --license gpl-3.0

# Generate .gitignore files by language
repoindex ops generate gitignore --lang python
repoindex ops generate gitignore --lang node

# Generate CODE_OF_CONDUCT.md
repoindex ops generate code-of-conduct

# Generate CONTRIBUTING.md
repoindex ops generate contributing
```

**Safety Model**:
- `--dry-run`: Preview changes without writing
- Confirmation prompt for git push/pull (skip with `--yes`)
- `--force`: Required to overwrite existing files

**Query Integration**: All ops subcommands support the same query flags as `query`:
- `--dirty`, `--clean`, `--language`, `--tag`, `--starred`, etc.
- Or use a query expression as positional argument

## Project Structure Notes

- Entry point: `repoindex/cli.py:main()`
- Package metadata: `pyproject.toml` (uses hatchling build system)
- Build system: hatchling (not setuptools)
- Documentation: `docs/` directory with mkdocs (Material theme)
- Virtual environment: All make commands use `.venv/` for isolation

## Development Workflow

### Initial Setup
```bash
# Clone and set up development environment
git clone https://github.com/queelius/repoindex.git
cd repoindex
make install  # Creates .venv and installs dependencies

# Verify installation
source .venv/bin/activate
repoindex --version
pytest --version
```

### Development Cycle
1. **Make changes** to code in `repoindex/` directory
2. **Write tests** in `tests/` directory
3. **Run tests** with `make test` or `pytest`
4. **Check coverage** with `pytest --cov=repoindex --cov-report=html`
5. **Build docs** with `make docs` if updating documentation
6. **Commit** changes following conventional commits style

### Before Committing
```bash
# 1. Run full test suite
pytest --maxfail=3 --disable-warnings -v

# 2. Check test coverage (aim for >86%)
pytest --cov=repoindex --cov-report=html

# 3. Build package to verify no build issues
make build

# 4. Build docs to verify documentation builds
make docs
```

## Working with the Codebase

### Adding New Commands

1. **Create command file** in `repoindex/commands/your_command.py`:
```python
import click
import json
from ..config import load_config
from ..services.repository_service import RepositoryService

@click.command('your-command')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
def your_command_handler(output_json):
    """Brief description of your command."""
    # Get data from service
    service = RepositoryService(config=load_config())
    results = service.your_method()

    if output_json:
        # Stream JSONL for piping
        for result in results:
            print(json.dumps(result), flush=True)
    else:
        # Pretty table (default for read commands)
        from ..render import render_table
        render_table(list(results), columns=['key1', 'key2'])
```

2. **Add service method** in `repoindex/services/`:
```python
def your_method(self) -> Generator[Dict[str, Any], None, None]:
    """
    Business logic that uses infrastructure clients.

    Yields:
        Dict with consistent schema
    """
    for repo in self.discover_repos():
        yield {
            "key1": value1,
            "key2": value2,
            "status": "success"
        }
```

3. **Register command** in `repoindex/cli.py`:
```python
from repoindex.commands.your_command import your_command_handler

# In the cli() function setup:
cli.add_command(your_command_handler)
```

4. **Write tests** in `tests/test_your_command.py`:
```python
import pytest
from unittest.mock import MagicMock
from repoindex.services.repository_service import RepositoryService

def test_your_method():
    mock_client = MagicMock()
    service = RepositoryService(config={}, git_client=mock_client)
    results = list(service.your_method())
    assert len(results) > 0
```

### Testing Patterns

**Service tests** (mock infrastructure):
```python
from unittest.mock import MagicMock
from repoindex.services.repository_service import RepositoryService

def test_discover_repos():
    mock_git_client = MagicMock()
    mock_git_client.get_status.return_value = {'branch': 'main', 'clean': True}

    service = RepositoryService(config={}, git_client=mock_git_client)
    repos = list(service.discover_repos())
    assert len(repos) > 0
```

**Domain tests** (no mocking needed):
```python
from repoindex.domain.models import Repository

def test_repository_immutable():
    repo = Repository(path="/test", name="test")
    assert repo.path == "/test"
    # Frozen dataclass - can't modify
```

### Configuration Changes

When adding new configuration options:

1. **Update defaults** in `repoindex/config.py`:
```python
def get_default_config():
    return {
        # ...existing...
        'your_section': {
            'your_option': default_value
        }
    }
```

2. **Add environment variable** in `apply_env_overrides()`:
```python
def apply_env_overrides(config):
    # ...existing...
    if 'REPOINDEX_YOUR_OPTION' in os.environ:
        config['your_section']['your_option'] = os.environ['REPOINDEX_YOUR_OPTION']
```

3. **Document in README.md** and `docs/` if it's user-facing

### Output Format Guidelines

**Default pretty output** (for interactive commands like `query`, `events`):
```python
# Pretty table by default
render.repos_table(list(repos))
```

**JSONL output** (for scripting/piping):
```python
if output_json:
    for item in items:
        print(json.dumps(item), flush=True)
```

**Error output**:
```python
# Errors go to stderr
import sys
error_obj = {
    "error": "Description",
    "type": "error_type",
    "context": {"path": "/some/path"}
}
print(json.dumps(error_obj), file=sys.stderr)
```

### Common Utilities

**Find repositories**:
```python
from repoindex.utils import find_git_repos, find_git_repos_from_config

repos = find_git_repos('/path/to/search', recursive=True)
config_repos = find_git_repos_from_config(config['general']['repository_directories'], recursive=False)
```

**Git operations** (use infrastructure client):
```python
from repoindex.infrastructure.git_client import GitClient

git_client = GitClient()
status = git_client.get_status('/path/to/repo')
remote = git_client.get_remote_url('/path/to/repo')
tags = git_client.get_tags('/path/to/repo')
```

### CLI Tag Management

```bash
# Add tags
repoindex tag add myproject alex/beta
repoindex tag add myproject topic:ml/research work/active

# Remove tags
repoindex tag remove myproject alex/beta

# List all tags
repoindex tag list

# List repositories with specific tag
repoindex tag list -t "alex/*"

# Show tag hierarchy as tree
repoindex tag tree
```

## Important Implementation Notes

### Config Store Location
- Default: `~/.repoindex/config.yaml`
- Set `REPOINDEX_CONFIG` to override

### Rate Limiting (GitHub API)
- Configured in `github.rate_limit` section
- Exponential backoff with max retries
- Respects GitHub's rate limit reset time
- Use `REPOINDEX_GITHUB_TOKEN` for higher limits

### Database-First Architecture
- `refresh` populates the SQLite database with repos and events
- `query`, `events`, `sql` all query from the database
- No live scanning in query commands - database is the cache

### Events Command Usage
```bash
# Query events from database (default: last 7 days, pretty table)
repoindex events

# Events since specific time
repoindex events --since 24h
repoindex events --since 7d

# Filter by type
repoindex events --type git_tag
repoindex events --type commit

# Filter by repository
repoindex events --repo myproject

# Summary statistics
repoindex events --stats

# JSONL output for scripting
repoindex events --json --since 7d | jq '.type'
```

### Refresh Command
```bash
repoindex refresh                  # Smart refresh (changed repos only)
repoindex refresh --full           # Force full refresh
repoindex refresh --github         # Include GitHub metadata
repoindex refresh --pypi           # Include PyPI package status
repoindex refresh --cran           # Include CRAN package status
repoindex refresh --external       # Include all external metadata
repoindex refresh --since 30d      # Events from last 30 days
repoindex sql --reset              # Reset database (then refresh --full)
```
