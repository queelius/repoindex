# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**repoindex is a collection-aware metadata index for git repositories.**

It provides a unified view across all your repositories, enabling queries, organization, and integration with LLM tools like Claude Code.

**Key Philosophy**: repoindex knows *about* your repos (metadata, tags, status), while Claude Code works *inside* them (editing, generating). Together they provide full portfolio awareness.

**Current Version**: 0.8.2

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
         ├── /repos/...     → what exists
         ├── /tags/...      → organization
         ├── /stats/...     → aggregations
         └── /events/...    → what happened
```

### Core Principles
1. **Collection, not content** - know *about* repos, not *inside* them
2. **Metadata, not manipulation** - track state, don't edit files
3. **Index, not IDE** - we're the catalog, not the workbench
4. **Complement Claude Code** - provide context, not compete
5. **VFS interface** - navigable, queryable structure
6. **MCP server** - LLM integration endpoint

### Core Capabilities
1. **Repository Discovery** - Find and track repos across directories
2. **Tag-Based Organization** - Hierarchical tags for categorization
3. **Registry Awareness** - PyPI, CRAN publication status
4. **Event Tracking** - New tags, releases, publishes (28 event types)
5. **Statistics** - Aggregations across the collection
6. **Query Language** - Filter and search with expressions

## Using repoindex with Claude Code

Claude Code can run repoindex CLI commands directly. This is often more powerful than MCP since you can compose with Unix tools.

### Common Patterns

```bash
# Dashboard overview
repoindex status

# Repos with uncommitted changes
repoindex query --dirty --pretty

# Find Python repos with stars
repoindex query --language python --starred --pretty

# What happened recently?
repoindex events --since 7d --pretty

# What got released this week?
repoindex events --type git_tag --since 7d --pretty

# Raw SQL access
repoindex sql "SELECT name, stars FROM repos ORDER BY stars DESC LIMIT 10"
```

### Query Convenience Flags

```bash
repoindex query --dirty              # Uncommitted changes
repoindex query --language python    # Python repos
repoindex query --recent 7d          # Recent commits
repoindex query --tag "work/*"       # By tag
repoindex query --no-license         # Missing license
repoindex query --starred            # Has stars
```

### Event Types

Events are populated by `refresh` and stored in the SQLite database:
- `git_tag`, `commit`, `branch`, `merge`

Query events from the database:
```bash
repoindex events --since 7d --pretty
repoindex events --type commit --since 30d
repoindex events --repo myproject
repoindex events --stats
```

### Output Formats

All commands output JSONL by default:
```bash
repoindex events --since 7d | jq '.type' | sort | uniq -c
```

Use `--pretty` for human-readable tables:
```bash
repoindex events --since 7d --pretty
```

## CRITICAL DESIGN PRINCIPLES

### 1. Unix Philosophy First
- **Do one thing well**: Each command has a single, clear purpose
- **Compose via pipes**: Output of one command feeds into another
- **Text streams are the universal interface**: JSONL is our text stream format

### 2. Output Format Rules
- **DEFAULT is JSONL**: Every command outputs newline-delimited JSON by default
- **Stream, don't collect**: Output each object as it's processed
- **NO --json flag**: JSONL is already JSON (one object per line)
- **Human output is opt-in**: Use --pretty or --table for human-readable tables
- **Errors go to stderr**: Keep stdout clean for piping

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
@click.option('--pretty', is_flag=True, help='Display as formatted table')
def status_handler(pretty):
    """Show repository status."""
    # Get data as generator from service
    repos = repo_service.get_repository_status(path)

    if pretty:
        # Collect and render as table
        render.status_table(list(repos))
    else:
        # Stream JSONL (default)
        for repo in repos:
            print(json.dumps(repo), flush=True)
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
- Test suite contains 604+ tests
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

**Command Layer** (`repoindex/commands/`):
- Individual CLI command implementations
- Parse arguments with Click
- Use services for business logic
- Format output: JSONL (default) or --pretty

### Core Modules
- `repoindex/cli.py` - Main CLI entry point using Click framework
- `repoindex/config.py` - Configuration management with JSON/TOML support
- `repoindex/utils.py` - Shared utility functions
- `repoindex/simple_query.py` - Query language with fuzzy matching
- `repoindex/pypi.py` - PyPI package detection and API integration
- `repoindex/cran.py` - CRAN package detection
- `repoindex/events.py` - Stateless event scanning (git tags, commits)
- `repoindex/tags.py` - Tag management and implicit tag generation

### MCP Server
- `repoindex/mcp/server.py` - MCP server implementation
- Uses MCPContext for shared state
- Exposes resources and tools for LLM integration

### Key Design Patterns
- **Layered Architecture**: Domain → Infrastructure → Services → Commands
- **Dependency Injection**: Services receive clients via constructor
- **Immutable Domain Objects**: Frozen dataclasses for thread safety
- **JSONL Streaming**: Default output format for Unix pipelines
- **Configuration Cascading**: Defaults → config file → environment variables

### Dependencies
- `rich>=13.0.0` - Enhanced terminal output and progress bars
- `requests>=2.25.0` - HTTP requests for API integration
- `packaging>=21.0` - Package version handling
- `click` - CLI framework
- `rapidfuzz` - Fuzzy string matching for query language
- `mcp` - Model Context Protocol server

### Commands Implemented (11 commands)

```
repoindex
├── status              # Dashboard: health overview
├── query               # Human-friendly repo search with flags
├── events              # Query events from database
├── sql                 # Raw SQL queries + database management
├── refresh             # Database sync (repos + events)
├── tag                 # Organization (add/remove/list/tree)
├── view                # Curated views (list/show/create/delete)
├── config              # Settings (show/repos/init)
├── mcp                 # LLM integration server
├── claude              # Skill management (install/uninstall/show)
└── shell               # Interactive mode with VFS navigation
```

## Configuration

Configuration is managed through `~/.repoindex/config.json` (or YAML). Use `REPOINDEX_CONFIG` environment variable to override location.

Key configuration sections:
- `repository_directories` - List of repo directories (supports ** glob patterns)
- `github.token` - GitHub API token (or use GITHUB_TOKEN env var)
- `github.rate_limit` - Retry configuration with exponential backoff
- `repository_tags` - Manual tag assignments for repos

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
- Path-based access to nested fields (e.g., `license.key`, `package.version`)
- Operators: `==`, `!=`, `~=` (fuzzy), `>`, `<`, `contains`, `in`
- Examples:
  - `"language ~= 'pyton'"` - fuzzy match Python
  - `"'ml' in topics"` - check if 'ml' in topics list
  - `"stars > 10 and language == 'Python'"` - multiple conditions

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
from ..config import load_config
from ..services.repository_service import RepositoryService

@click.command('your-command')
@click.option('--pretty', is_flag=True, help='Display as formatted table')
def your_command_handler(pretty):
    """Brief description of your command."""
    # Get data from service
    service = RepositoryService(config=load_config())
    results = service.your_method()

    if pretty:
        # Render as table for humans
        from ..render import render_table
        render_table(list(results), columns=['key1', 'key2'])
    else:
        # Stream JSONL (default)
        import json
        for result in results:
            print(json.dumps(result), flush=True)
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

**Default JSONL output**:
```python
# Stream one JSON object per line
for item in items:
    print(json.dumps(item), flush=True)
```

**Optional pretty output**:
```python
if pretty:
    from ..render import render_table
    render_table(list(items), columns=['col1', 'col2'])
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
- Default: `~/.repoindex/config.json`
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

### MCP Server
- Start with `repoindex mcp serve`
- Exposes resources: `repo://list`, `tags://list`, `stats://summary`
- Exposes tools: `repoindex_tag`, `repoindex_untag`, `repoindex_query`, `repoindex_refresh`, `repoindex_stats`

### Events Command Usage
```bash
# Query events from database (default: last 7 days)
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

# Human-readable output
repoindex events --pretty
```

### Refresh Command
```bash
repoindex refresh              # Smart refresh (changed repos only)
repoindex refresh --full       # Force full refresh
repoindex refresh --github     # Include GitHub metadata
repoindex refresh --since 30d  # Events from last 30 days
repoindex sql --reset          # Reset database (then refresh --full)
```
