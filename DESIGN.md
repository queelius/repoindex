# ghops Design Philosophy

**Version**: 0.9.0 (proposed)
**Status**: Living Document

This document describes the design principles, architecture, and concrete abstractions for ghops.

## Vision

**ghops is a collection-aware metadata index for git repositories.**

It provides a unified view across all your repositories, enabling queries, organization, and integration with LLM tools like Claude Code.

```
┌─────────────────────────────────────────────────────────────────┐
│                         Claude Code                             │
│              (deep work on ONE repo at a time)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ "What else do I have?"
                              │ "Which repos need X?"
                              │ "Show me my portfolio"
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                           ghops                                 │
│              (collection awareness, metadata layer)             │
│                                                                 │
│   • What repos exist and where                                  │
│   • Tags and organization                                       │
│   • Registry status (PyPI, CRAN, npm, ...)                      │
│   • Cross-repo queries                                          │
│   • Event detection (new tags, releases, publishes)             │
│   • Statistics and aggregations                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Core Principles

### 1. Collection, Not Content

ghops knows *about* repositories, not *inside* them.

- ✓ "You have 45 Python repos"
- ✓ "12 are published on PyPI"
- ✓ "ghops was last tagged 2 days ago"
- ✗ "This function has a bug on line 42"
- ✗ "Here's a refactored version of your code"

### 2. Metadata, Not Manipulation

We track state; we don't edit files.

- ✓ Query repository status
- ✓ Track tags and organization
- ✓ Detect events (new releases)
- ✗ Edit source code
- ✗ Generate documentation content
- ✗ Write README files

### 3. Index, Not IDE

We're the catalog, not the workbench.

- ✓ "Find all repos with MIT license"
- ✓ "Show unpublished Python packages"
- ✗ "Build the documentation"
- ✗ "Run the test suite"

### 4. Complement Claude Code

Don't duplicate what Claude Code already does well.

| Claude Code Does | ghops Does |
|------------------|------------|
| Read/write files in a repo | Know about ALL repos |
| Run git commands | Track events across repos |
| Generate docs, READMEs | Provide context for generation |
| Understand one codebase | Query across the collection |

### 5. VFS as Primary Interface

The virtual filesystem is the natural interface for both humans and LLMs.

```
/repos/                     → all repositories
/repos/{name}/              → metadata for one repo
/by-tag/{tag}/              → repos with this tag
/by-language/{lang}/        → repos by language
/stats/                     → aggregations
/stats/languages            → count by language
/stats/published            → published vs unpublished
/events/                    → recent activity
/events/recent              → last N events
/events/repo/{name}/        → events for one repo
```

### 6. MCP Server for LLM Integration

ghops exposes itself as an MCP (Model Context Protocol) server:

- **Resources**: VFS paths providing read-only data
- **Tools**: Actions like `tag()`, `query()`, `refresh()`

This allows Claude Code (or any MCP client) to query the collection and take actions.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Interface                            │
│                   (Resources + Tools)                           │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      VFS Layer                                  │
│        /repos/  /tags/  /stats/  /events/                       │
└─────────────────────────────────────────────────────────────────┘
                              │
┌──────────────┬──────────────┬──────────────┬───────────────────┐
│   Metadata   │    Tags      │    Stats     │     Events        │
│    Store     │   System     │   Engine     │      Log          │
└──────────────┴──────────────┴──────────────┴───────────────────┘
                              │
┌──────────────┬──────────────┬──────────────┬───────────────────┐
│     Git      │    PyPI      │    CRAN      │     GitHub        │
│   Scanner    │   Client     │   Client     │      API          │
└──────────────┴──────────────┴──────────────┴───────────────────┘
```

### Core Components

| Component | Purpose |
|-----------|---------|
| **Metadata Store** | Persistent cache of repo metadata |
| **Tags System** | Hierarchical organization layer |
| **Stats Engine** | Aggregations and counts |
| **Event Log** | Track changes over time |
| **Registry Clients** | PyPI, CRAN, npm status |
| **VFS Layer** | Unified path-based interface |
| **MCP Server** | LLM integration endpoint |

## What's In Scope

### Keep and Enhance

- `core.py` - Pure business logic
- `tags.py` - Tag management
- `query.py`, `simple_query.py` - Query language
- `metadata.py` - Metadata store
- `analytics_store.py` - Statistics
- `events.py` - Stateless event scanning
- `pypi.py`, `cran.py` - Registry clients
- `shell/` - VFS interface (becomes central)
- `config.py`, `utils.py` - Infrastructure

### Out of Scope (Remove or Extract)

| Module | Reason |
|--------|--------|
| `integrations/clustering/` | Content analysis, not metadata |
| `integrations/templates/` | Reads source files |
| `integrations/timemachine/` | Content-focused |
| `llm/content_generator.py` | LLM generates, not us |
| `hugo_export.py` | Content generation |
| `export_components*.py` | Portfolio generation |

These should either be removed or extracted into separate tools that *consume* ghops data.

### Gray Areas

| Module | Decision |
|--------|----------|
| `docs.py` | Keep detection, remove building |
| `audit.py` | Keep (health checks are metadata queries) |
| `tui/` | Keep for direct human use (optional) |
| License detection | Keep (metadata extraction is okay) |

## Event Model

Events answer "what happened?" across the collection.

**Key principle**: ghops is read-only. It scans and reports events; external tools act on them.

### Event Types

```
git_tag         - New tag created
commit          - New commits pushed
```

Future (when registry clients are enhanced):
```
pypi_publish    - Package published to PyPI
cran_publish    - Package published to CRAN
github_release  - GitHub release created
```

### Event Flow (Stateless)

```
1. User runs: ghops events --since 7d
2. ghops scans git repos for tags/commits
3. Events streamed as JSONL to stdout
4. External tools consume the stream
5. External tools decide what action to take

Example pipeline:
$ ghops events --since 1d --type git_tag | ./notify-releases.sh
$ ghops events --watch | jq 'select(.type == "git_tag")' | ./post-to-slack.sh
```

### Design Rationale

- **No dispatch mechanism**: ghops observes, doesn't act
- **No state tracking**: Each scan is independent
- **Time-based filtering**: `--since` and `--until` replace "last seen" state
- **Composable output**: JSONL enables Unix pipelines

## MCP Server Interface

### Resources (Read-Only)

```
repo://list                    → all repos with basic metadata
repo://{name}                  → full metadata for one repo
repo://{name}/status           → git status
repo://{name}/package          → package info (PyPI/CRAN)

tags://list                    → all tags
tags://tree                    → hierarchical view
tags://{tag}/repos             → repos with this tag

stats://summary                → overall statistics
stats://languages              → count by language
stats://published              → registry publication status

events://recent                → recent events
events://repo/{name}           → events for one repo
events://type/{type}           → events by type
```

### Tools (Actions)

```
ghops_tag(repo, tag)           → add tag to repo
ghops_untag(repo, tag)         → remove tag
ghops_query(expression)        → run query, return matching repos
ghops_refresh(repo?)           → refresh metadata (one or all)
ghops_stats(groupby)           → get statistics
```

## Example LLM Workflows

### "Which Python repos aren't on PyPI?"

```
1. LLM calls: ghops_query("language == 'Python' and not published")
2. ghops returns: [{name: "my-tool", path: "/home/..."}, ...]
3. LLM presents results to user
```

### "Post about my latest release"

```
1. LLM reads: events://recent
2. Sees: {type: "git_tag", repo: "ghops", tag: "v2.0.0", ...}
3. LLM reads: repo://ghops (gets full context)
4. LLM generates post text (Claude Code does this, not ghops)
5. LLM calls external tool to post (or user copies text)
```

### "Organize my ML projects"

```
1. LLM reads: repo://list
2. LLM identifies ML-related repos from descriptions/topics
3. LLM calls: ghops_tag("repo1", "topic:ml")
4. LLM calls: ghops_tag("repo2", "topic:ml")
5. User can now query: tags://topic:ml/repos
```

## Migration Path

### Phase 1: Document & Clean
- Document design principles (this file)
- Remove out-of-scope modules
- Update CLAUDE.md

### Phase 2: Enhance Core
- Strengthen VFS layer
- Add statistics engine
- Improve event tracking

### Phase 3: MCP Server
- Implement MCP protocol
- Expose resources
- Implement tools

### Phase 4: Integration
- Test with Claude Code
- Iterate on interface
- Document for users

---

## Refined Architecture

### Design Invariants

These are non-negotiable constraints that every component must respect:

1. **JSONL is the universal interface** - Default output is newline-delimited JSON
2. **Generators over collections** - Stream data, don't buffer in memory
3. **Pure core, thin commands** - Business logic in services, CLI is orchestration
4. **Fail gracefully, continue processing** - One bad repo doesn't stop the scan
5. **Explicit over magic** - No hidden behavior, clear flags for options

### Layered Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Layer                            │
│  ghops/commands/*.py                                    │
│  - Parse arguments (Click)                              │
│  - Call services                                        │
│  - Format output (JSONL or pretty)                      │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                  Service Layer                          │
│  ghops/services/*.py                                    │
│  - RepositoryService: discover, status, filter          │
│  - TagService: add, remove, query tags                  │
│  - EventService: scan events                            │
│  - MetadataService: persist, refresh metadata           │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                  Domain Layer                           │
│  ghops/domain/*.py                                      │
│  - Repository, Tag, Event dataclasses                   │
│  - Pure functions for filtering, transformation         │
│  - No I/O, no side effects                              │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│               Infrastructure Layer                      │
│  ghops/infra/*.py                                       │
│  - GitClient: shell out to git                          │
│  - GitHubClient: GitHub API with rate limiting          │
│  - FileStore: JSON/YAML persistence                     │
│  - Config: configuration loading                        │
└─────────────────────────────────────────────────────────┘
```

### Key Abstractions

#### Repository (Domain Object)

```python
@dataclass(frozen=True)
class Repository:
    """Immutable representation of a git repository."""
    path: str
    name: str

    # Git state
    branch: str
    clean: bool
    remote_url: Optional[str] = None

    # Derived metadata
    owner: Optional[str] = None
    language: Optional[str] = None
    license: Optional[str] = None

    # Organization
    tags: FrozenSet[Tag] = frozenset()

    # External state (optional, fetched on demand)
    github: Optional[GitHubMetadata] = None
    package: Optional[PackageMetadata] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON output."""

    @classmethod
    def from_path(cls, path: str) -> 'Repository':
        """Construct from filesystem path."""
```

#### Tag (Value Object)

```python
@dataclass(frozen=True)
class Tag:
    """Structured tag with optional hierarchy."""
    value: str                    # Full tag string: "topic:ml/research"
    key: Optional[str] = None     # Namespace: "topic"
    segments: Tuple[str] = ()     # Path segments: ("ml", "research")
    source: TagSource = TagSource.EXPLICIT

    @classmethod
    def parse(cls, tag_string: str) -> 'Tag':
        """Parse 'topic:ml/research' into structured Tag."""

    def matches(self, pattern: str) -> bool:
        """Check if tag matches pattern like 'topic:*' or 'ml/*'."""

class TagSource(Enum):
    EXPLICIT = "explicit"      # User-assigned
    IMPLICIT = "implicit"      # Auto-generated (lang:python, repo:name)
    PROVIDER = "provider"      # From GitHub topics, etc.
```

#### Event (Domain Object)

```python
@dataclass
class Event:
    """An event that occurred in or related to a repository."""
    type: str                     # git_tag, commit
    timestamp: datetime
    repo_name: str
    repo_path: str
    data: Dict[str, Any]

    @property
    def id(self) -> str:
        """Stable unique identifier."""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON output."""

    def to_jsonl(self) -> str:
        """Single-line JSON for streaming."""
```

#### Result (Output Wrapper)

```python
@dataclass
class Result:
    """Unified command result for consistent output."""
    success: bool
    data: List[Dict[str, Any]]
    errors: List[Dict[str, Any]] = field(default_factory=list)
    count: int = 0

    def to_jsonl(self) -> Generator[str, None, None]:
        """Yield JSONL lines."""
        for item in self.data:
            yield json.dumps(item)
        for error in self.errors:
            yield json.dumps({"error": error})
```

### Service Contracts

#### RepositoryService

```python
class RepositoryService:
    """Discovers and queries repositories."""

    def discover(self, paths: Optional[List[str]] = None) -> Generator[Repository]:
        """Discover repositories from paths or config."""

    def get_status(self, repo: Repository, fetch_github: bool = False) -> Repository:
        """Enrich repository with current status."""

    def filter(self, repos: Iterable[Repository], query: Query) -> Generator[Repository]:
        """Filter repositories by query expression."""
```

#### TagService

```python
class TagService:
    """Manages repository tags."""

    def add(self, repo: Repository, tag: Tag) -> None:
        """Add tag to repository."""

    def remove(self, repo: Repository, tag: Tag) -> None:
        """Remove tag from repository."""

    def get_tags(self, repo: Repository) -> Set[Tag]:
        """Get all tags for repository (explicit + implicit)."""

    def query(self, pattern: str) -> Generator[Repository]:
        """Find repositories matching tag pattern."""
```

#### EventService

```python
class EventService:
    """Scans repositories for events (stateless)."""

    def scan(
        self,
        repos: Iterable[Repository],
        types: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> Generator[Event]:
        """Scan repositories for events."""
```

### Infrastructure Contracts

#### GitClient

```python
class GitClient:
    """Abstraction over git commands."""

    def status(self, path: str) -> GitStatus:
        """Get repository status (branch, clean, ahead/behind)."""

    def remote_url(self, path: str, remote: str = "origin") -> Optional[str]:
        """Get remote URL."""

    def tags(self, path: str, since: Optional[datetime] = None) -> List[GitTag]:
        """List git tags."""

    def log(self, path: str, limit: int = 50) -> List[GitCommit]:
        """Get commit log."""
```

#### GitHubClient

```python
class GitHubClient:
    """GitHub API with rate limiting and caching."""

    def get_repo(self, owner: str, name: str) -> Optional[GitHubRepo]:
        """Fetch repository metadata."""

    def get_topics(self, owner: str, name: str) -> List[str]:
        """Fetch repository topics."""

    def check_published(self, owner: str, name: str) -> bool:
        """Check if repo exists and is public."""
```

### Command Pattern

Every command follows this structure:

```python
@click.command('status')
@click.option('--pretty', '-p', is_flag=True, help='Human-readable output')
@click.option('--github/--no-github', default=None, help='Fetch GitHub metadata')
@click.argument('path', default='/', required=False)
def status_handler(pretty: bool, github: Optional[bool], path: str):
    """Show repository status."""
    # 1. Load configuration
    config = load_config()

    # 2. Create services (dependency injection)
    repo_service = RepositoryService(GitClient(), config)

    # 3. Get data as generator
    repos = repo_service.discover(path)

    # 4. Enrich if needed
    if github:
        repos = (repo_service.get_status(r, fetch_github=True) for r in repos)

    # 5. Output (JSONL default, --pretty for tables)
    output.emit(repos, pretty=pretty)
```

### Output Module

```python
# ghops/output.py

def emit(items: Iterable[Any], pretty: bool = False):
    """Emit items as JSONL or pretty table."""
    if pretty:
        items = list(items)
        if items:
            render_table(items)
        else:
            click.echo("No results found")
    else:
        for item in items:
            if hasattr(item, 'to_dict'):
                item = item.to_dict()
            print(json.dumps(item), flush=True)

def emit_error(error: str, context: Dict = None):
    """Emit error to stderr as JSON."""
    obj = {"error": error}
    if context:
        obj["context"] = context
    print(json.dumps(obj), file=sys.stderr)
```

---

## Proposed File Structure

```
ghops/
├── __init__.py
├── cli.py                    # Click entry point (thin)
├── output.py                 # JSONL/pretty output helpers
├── config.py                 # Configuration loading
│
├── domain/                   # Pure domain objects
│   ├── __init__.py
│   ├── repository.py         # Repository dataclass
│   ├── tag.py                # Tag dataclass
│   ├── event.py              # Event dataclass (moved from events.py)
│   └── query.py              # Query parsing and execution
│
├── services/                 # Business logic
│   ├── __init__.py
│   ├── repository_service.py # Discovery, status, filtering
│   ├── tag_service.py        # Tag management
│   ├── event_service.py      # Event scanning
│   └── metadata_service.py   # Persistence, refresh
│
├── infra/                    # External integrations
│   ├── __init__.py
│   ├── git_client.py         # Git operations
│   ├── github_client.py      # GitHub API
│   ├── pypi_client.py        # PyPI API
│   ├── cran_client.py        # CRAN API
│   └── file_store.py         # JSON/YAML persistence
│
├── commands/                 # CLI commands (thin wrappers)
│   ├── __init__.py
│   ├── status.py
│   ├── events.py
│   ├── tag.py
│   ├── query.py
│   └── ...
│
├── shell/                    # Interactive shell
│   └── shell.py
│
└── mcp/                      # MCP server
    ├── __init__.py
    └── server.py
```

---

## Known Technical Debt

Issues to address during refactoring:

| Issue | Location | Fix |
|-------|----------|-----|
| Duplicate `get_remote_url()` | utils.py (lines 65, 290) | Keep git command version, remove parser version |
| Circular imports | core.py ↔ commands/ | Move shared logic to services layer |
| Monolithic function | core.py `get_repository_status()` | Split into RepositoryService methods |
| Tag logic scattered | tags.py, catalog.py, core.py | Consolidate into TagService |
| Language detection duplicated | metadata.py, tags.py | Single implementation in domain/repository.py |
| Inconsistent return types | Various | All services return generators |
| Global state | `_store` in metadata.py | Inject MetadataService as dependency |

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| Output format | Mixed | JSONL default, `--pretty` opt-in |
| Return types | Dict, List, Generator | Always Generator from services |
| Side effects | Scattered | Isolated in infra layer |
| Tag system | Fragmented | Unified TagService |
| Repository data | Dict with path string | Repository dataclass |
| Error handling | Mixed | Yield errors, continue processing |
| Configuration | Loaded everywhere | Injected via services |
| Testing | Hard to mock | Pure domain, mockable infra |
