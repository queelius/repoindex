# Future Plans for repoindex

## Vision: From GitHub Operations to Digital Legacy Platform

repoindex has evolved from a simple GitHub operations tool into a comprehensive repository and digital presence management system. This document outlines our vision, planned features, and development roadmap.

## Core Philosophy

**Local-first with remote awareness**: Your local git repositories are the ground truth, and remote platforms (GitHub, GitLab, PyPI, social media) are services that enrich and distribute your work.

## 🎉 v0.6.0 - Major Milestone Completed ✅

### Architecture & Quality Overhaul
- ✅ **Complete Modular Redesign**: Separated all functionality into dedicated command modules
- ✅ **Comprehensive Testing**: 138 tests achieving 86% code coverage
- ✅ **Robust Error Handling**: Graceful handling of network failures and edge cases
- ✅ **Performance Optimizations**: Optional API checks with performance flags
- ✅ **Enhanced Documentation**: Complete rewrite of README, usage guide, and API docs

### Enhanced Feature Set
- ✅ **Advanced Configuration**: JSON/TOML support with environment variable overrides
- ✅ **License Management**: Full GitHub API integration with template customization
- ✅ **Social Media Automation**: Multi-platform support with template-driven content
- ✅ **GitHub Pages Detection**: Multi-method detection for documentation sites
- ✅ **Improved PyPI Integration**: Enhanced package detection and version tracking

## Previously Implemented ✅

### PyPI Package Detection and Management
- ✅ **Package Detection**: Scan repositories for `pyproject.toml`, `setup.py`, `setup.cfg`
- ✅ **PyPI Status Check**: Query PyPI API to verify packages and get version info
- ✅ **Status Integration**: Include PyPI package and version columns in status output
- ✅ **Statistics Tracking**: Track repos with packages, published packages, outdated packages
- ✅ **Performance Options**: `--no-pypi-check` flag for faster results

### Configuration System
- ✅ **Config File Support**: `~/.repoindexrc` with JSON/TOML format support
- ✅ **Example Generation**: `repoindex config generate` command
- ✅ **Environment Override**: `REPOINDEX_CONFIG` and per-setting environment variables

### Social Media Framework
- ✅ **Platform Support**: Framework for Twitter/X, LinkedIn, Mastodon
- ✅ **Smart Sampling**: Random repository selection for content with filtering
- ✅ **Template System**: Configurable post templates for different content types
- ✅ **Preview Mode**: `--dry-run` flag to preview posts before publishing
- ✅ **Rate Limiting**: Daily limits and time-based posting controls

### GitHub Integration

- ✅ **Visibility & Presence**: Status table now shows if a repo exists on GitHub and its visibility (Public/Private).

## 🚀 Next Release Goals (v0.7.0)

### Priority 1: Core Usability & Automation 🎯

#### GitHub Remote Management

**Motivation**: Many local repositories are not yet tracked on GitHub. `repoindex` should streamline the process of creating and linking remote repositories.

**Features**:

- **Auto-Create Remotes**: A new command, `repoindex remote create`, will create a GitHub repository for a local-only repo using the `gh` CLI.
- **Interactive Prompts**: The command will prompt for repository name, visibility (public/private), and description.
- **Status Integration**: The `repoindex status` command will highlight local-only repositories and suggest running the `remote create` command.

#### Automated Homepage URL Update

**Motivation**: When a GitHub Pages site is detected, the project's metadata (`pyproject.toml` or `package.json`) should be updated to reflect the live URL.

**Features**:

- **Homepage Update Command**: A new command, `repoindex pages update-homepage`, will automatically find the `homepage` or `urls.Homepage` key in `pyproject.toml` and set it to the detected GitHub Pages URL.
- **Dry-Run Support**: The command will include a `--dry-run` flag to show the proposed changes without writing to the file.

#### Single Repository Operations

**Motivation**: Fix the critical usability gap where `repoindex` does nothing when run inside a git repository.

**Current Problem**:

```bash
cd ~/my-awesome-project  # This is a git repo
repoindex status             # Does nothing - very confusing!
repoindex update            # Does nothing - breaks user expectations
```

**Expected Behavior**:

```bash
cd ~/my-awesome-project  # This is a git repo  
repoindex status             # Shows detailed status of THIS repo
repoindex update            # Updates THIS repo with enhanced output
repoindex license add mit   # Adds license to THIS repo
```

**Implementation Features**:

- **Smart Mode Detection**: Auto-detect if current directory is a git repository
- **Single vs Batch Modes**:
  - Single repo mode: Detailed output, repo-specific operations
  - Batch mode: Summary tables, multi-repo operations
- **Unified Command Interface**:
  - `repoindex status` - Auto-detects mode based on current directory
  - `repoindex status --batch` - Force batch mode even in git directory
  - `repoindex status --single` - Force single mode even outside git directory
- **Enhanced Single-Repo Output**: More detailed information when focusing on one repository

#### Programmatic API

**Motivation**: Enable `repoindex` integration into Python scripts, automation systems, and provide better developer experience.

**API Design Goals**:

- **Clean Python Interface**: Full programmatic access to all `repoindex` functionality
- **Type Safety**: Complete type hints for IDE support and better developer experience
- **Async Support**: For operations involving network calls and batch processing
- **Documentation**: Auto-generated API docs via docstrings and MkDocs

**Example API Usage**:

```python
from repoindex import api
from pathlib import Path

# Single repository operations
repo = api.repository(Path.cwd())
status = repo.get_status()
pypi_info = repo.get_pypi_info()
pages_url = repo.get_pages_url()

# Batch operations
results = api.scan_repositories(
    directory="~/projects",
    recursive=True,
    filters={"language": "python", "has_pyproject": True}
)

# Social media operations
posts = api.create_social_posts(
    repositories=results.with_packages(),
    template="pypi_release",
    dry_run=True
)
```

**Implementation Strategy**:

- **CLI as Thin Wrapper**: Refactor CLI to use the programmatic API internally
- **Result Objects**: Structured returns instead of console output
- **Error Handling**: Proper exception hierarchy for programmatic error handling
- **Testing**: API makes comprehensive testing much easier

### Priority 2: Enhanced Functionality ⚡

#### Auto-Package Generation

**Motivation**: Make it easy to convert existing repositories into publishable Python packages.

- **New command**: `repoindex package init` to bootstrap packaging for repositories
- **Smart defaults**:
  - Package name from repository directory name
  - Version starts at `0.1.0`
  - Author/email from `git config`
  - Dependencies from `requirements.txt` if available
- **Template generation**: Create minimal but complete `pyproject.toml`
- **Interactive mode**: Prompt for key metadata when auto-detection isn't sufficient

#### Publishing Automation

- **New command**: `repoindex package publish` for automated PyPI uploads
- **Version management**: Integration with version bumping
- **Build automation**: Automatic wheel and sdist generation
- **Safety checks**: Verify package before upload
- **Batch publishing**: Publish multiple packages with version updates

### Repository Filtering and Selection

#### Smart Filtering System

**Motivation**: When managing hundreds of repositories, you need fine-grained control over which repositories to operate on.

- **`.repoindexignore` files**: Similar to `.gitignore`, but for excluding repositories from operations
  - **Base directory**: Place `.repoindexignore` in the root directory to set global exclusions
  - **Subdirectory filtering**: `.repoindexignore` in subdirectories excludes repos in that subtree
  - **Self-exclusion**: If a repository directory contains `.repoindexignore`, it excludes itself
  - **Pattern matching**: Support glob patterns, regex, and path-based exclusions
- **Command-line filters**: One-off filtering for specific operations
  - `--include` and `--exclude` flags with glob patterns
  - `--filter` for complex expressions (e.g., `--filter "language:python AND has:pyproject.toml"`)
  - `--limit N` to operate on only N repositories (useful for testing)
- **Whitelist mode**: Invert the filtering logic
  - `--whitelist-only` mode where only explicitly included repositories are processed
  - Useful for focusing on specific projects while ignoring everything else
  - Can be combined with `.repoindexinclude` files for persistent whitelist configuration
- **Smart selection**:
  - `--changed-only`: Only repositories with uncommitted changes
  - `--outdated-only`: Only repositories behind their remote
  - `--python-only`: Only repositories with Python code
  - `--has-issues`: Only repositories with open GitHub issues

#### Filter Configuration

- **Filter profiles**: Named filter configurations for different use cases
  - `repoindex config filter create work --include "work/*" --exclude "*/archive/*"`
  - `repoindex config filter create python --filter "language:python"`
  - `repoindex status --filter-profile python`
- **Interactive selection**: TUI for selecting repositories visually
- **Filter testing**: `repoindex filter test` to see which repositories match current filters

## Medium-term Goals (v0.7.0 - v0.8.0)

### Enhanced Repository Intelligence

#### Language and Framework Detection

- **Programming language detection**: Beyond just Python, detect Go, Rust, JavaScript, etc.
- **Framework identification**: Detect React, Django, FastAPI, etc.
- **Dependency analysis**: Parse `requirements.txt`, `package.json`, `Cargo.toml`, etc.
- **Technology stack visualization**: Show the full tech stack for each repository

#### Repository Health Metrics

- **Code quality indicators**: Last commit date, test presence, documentation coverage
- **Community metrics**: Star count, fork count, issue count, contributor count
- **Maintenance status**: Detect abandoned or actively maintained projects
- **Security analysis**: Check for known vulnerabilities in dependencies

### Enhanced GitHub Integration

#### Issues and Pull Requests

- **Issue management**: List open issues across all repositories
- **PR status**: Track open pull requests and their status
- **Review assignments**: See which PRs need your attention
- **Milestone tracking**: Monitor progress toward repository milestones

#### GitHub Actions Integration

- **Workflow status**: See the status of CI/CD pipelines across repositories
- **Failed builds**: Quickly identify repositories with failing tests
- **Deployment status**: Track which repositories have pending deployments
- **Action summaries**: Aggregate build success rates and performance metrics

## Long-term Goals (v0.9.0 - v1.0.0)

### Analytics and SEO Enhancement

#### Google Analytics Integration

**Motivation**: Improve discoverability and track the impact of your open source projects.

- **Analytics setup automation**:
  - **GitHub Pages**: Auto-configure Google Analytics for GitHub Pages sites
  - **Documentation sites**: Add analytics to MkDocs, Sphinx, GitBook, etc.
  - **README badges**: Generate analytics-enabled badges for repository READMEs
  - **Custom domains**: Handle analytics for repositories with custom domain GitHub Pages
- **SEO optimization**:
  - **Meta tag generation**: Auto-generate SEO-friendly meta tags for GitHub Pages
  - **Sitemap generation**: Create and update sitemaps for better search indexing
  - **Schema markup**: Add structured data for better search result presentation
  - **Open Graph tags**: Optimize social media sharing with proper OG tags
- **Content optimization**:
  - **README analysis**: Suggest improvements for better search visibility
  - **Keyword optimization**: Analyze and suggest keywords based on repository content
  - **Description optimization**: Improve repository descriptions for search engines
  - **Topic suggestions**: Recommend GitHub topics to improve discoverability
- **Performance tracking**:
  - **Traffic analysis**: Aggregate analytics across all your repositories
  - **Conversion tracking**: Track downloads, clones, stars from different sources
  - **Search ranking**: Monitor how your repositories rank for relevant keywords
  - **Referrer analysis**: Understand where your traffic is coming from

#### Analytics Reporting

- **Dashboard generation**: Create unified analytics dashboards across all repositories
- **Trend analysis**: Track growth patterns and identify successful strategies
- **Goal tracking**: Set and monitor specific objectives (downloads, stars, contributors)
- **Competitive analysis**: Compare your repositories against similar projects

### Advanced GitHub Operations

#### Repository Management

- **Repository creation**: Create new repositories with templates and best practices
- **Branch management**: Bulk operations on branches across repositories
- **Webhook management**: Set up and manage webhooks for automation
- **Settings synchronization**: Keep repository settings consistent across projects

#### Team Collaboration

- **Team management**: Manage collaborators and permissions across repositories
- **Organization tools**: Tools for managing repositories at the organization level
- **Access auditing**: Review and audit access permissions
- **Compliance reporting**: Generate reports for security and compliance requirements

### Enterprise Features

#### Performance and Scalability

- **Parallel processing**: Optimize for handling hundreds of repositories
- **Caching strategies**: Cache GitHub API responses for better performance
- **Incremental updates**: Only process changed repositories
- **Background processing**: Queue long-running operations

#### Integration and Extensibility

- **Plugin system**: Allow third-party extensions and customizations
- **API endpoints**: Provide REST API for integration with other tools
- **Webhook support**: React to external events and trigger repoindex operations
- **IDE integration**: Plugins for VS Code, PyCharm, etc.

#### Enterprise Management

- **Multi-user support**: Support for teams and organizations
- **Role-based access**: Different permission levels for different users
- **Audit logging**: Comprehensive logging for enterprise compliance
- **Backup and restore**: Backup configurations and restore operations

## 🔧 Future Repository Operations

### Core Repository Operations

**Philosophy**: `repoindex` should focus on repository-level operations while maintaining composability with other tools through streaming JSONL output.

#### Sync Operations
```bash
repoindex sync --dry-run      # Show what would be synchronized
repoindex sync --pull-only    # Only pull changes, don't push
repoindex sync --force        # Force sync even with conflicts
```

**Features**:
- Bulk pull/push operations across multiple repositories
- Conflict detection and resolution strategies
- Branch synchronization with upstream remotes
- Streaming progress output for large repository sets

#### Backup and Archive
```bash
repoindex backup --format tar.gz --include-lfs    # Create compressed backups
repoindex backup --format git-bundle              # Create git bundles
repoindex archive --to-storage s3://bucket/path   # Archive to cloud storage
```

**Features**:
- Multiple backup formats (tar, zip, git bundle)
- Git LFS support for large files
- Incremental backup strategies
- Cloud storage integration (S3, Google Cloud, Azure)
- Restore operations with verification

#### Health and Maintenance
```bash
repoindex health --check-corruption     # Check repository integrity
repoindex clean --dry-run              # Show what would be cleaned
repoindex clean --cache --temp          # Clean caches and temporary files
repoindex optimize --gc --repack        # Optimize repository storage
```

**Features**:
- Repository corruption detection using `git fsck`
- Cleanup of temporary files, caches, and build artifacts
- Git optimization (garbage collection, repacking)
- Disk usage analysis and reporting
- Broken symlink detection and cleanup

#### Migration and Export
```bash
repoindex migrate github-to-gitlab --input repos.jsonl    # Migrate between services
repoindex export --format json --include-history          # Export metadata
repoindex export --clone-bundle --mirror                  # Create mirror bundles
```

**Features**:
- Service migration (GitHub ↔ GitLab ↔ Bitbucket)
- Metadata preservation during migration
- History preservation options
- Authentication handling for different services
- Progress tracking for large migrations

### Export and Integration Operations

#### Dashboard and Monitoring Export
```bash
repoindex export dashboard --format prometheus    # Metrics for monitoring
repoindex export grafana --datasource json        # Grafana dashboard data
repoindex export json --schema v2                 # Structured data export
```

**Features**:
- Prometheus metrics export for monitoring
- JSON schema for external tool integration
- Real-time monitoring data streams
- Custom metric definitions
- Alert threshold configurations

#### Documentation Generation
```bash
repoindex export readme --template detailed       # Generate README files
repoindex export inventory --format markdown      # Repository inventory
repoindex export changelog --since-tag v1.0       # Generate changelogs
```

**Features**:
- Automated README generation from repository metadata
- Repository inventory for documentation sites
- Changelog generation from git history
- Template-based documentation generation
- Integration with static site generators

### NOT in repoindex Operations

**These belong in separate tools to maintain focus**:

- **Documentation Site Generation**: Use dedicated tools like `repodocs` or `gitdocs`
- **GitHub API Data Mining**: Use specialized tools like `ghj` for comprehensive GitHub analysis
- **Code Analysis**: Use language-specific tools (pylint, eslint, etc.)
- **Deployment**: Use CI/CD tools and deployment platforms
- **Issue/PR Management**: Use GitHub CLI or web interface

### Plugin Architecture for Extensions

```python
# repoindex/plugins/export/custom.py
@repoindex_plugin("export", "custom-format")
def export_custom_format(repos: Iterator[dict], **options):
    """Custom export plugin example."""
    for repo in repos:
        yield transform_repo_data(repo, options)
```

**Plugin Types**:
- **Export plugins**: New output formats and destinations
- **Health check plugins**: Custom repository health metrics
- **Migration plugins**: Support for additional services
- **Integration plugins**: Custom external tool integrations

### Design Principles for Future Operations

1. **Repository-Focused**: Operations should act on git repositories, not external services
2. **Streaming First**: All operations should support streaming JSONL input/output
3. **Composable**: Work well with Unix pipes and external tools
4. **Safe by Default**: Destructive operations require explicit confirmation
5. **Progressive**: Show progress for long-running operations
6. **Configurable**: Support configuration files and environment variables

## Implementation Roadmap

### Phase 1: Core Usability (v0.7.0)

- Single repository operation mode with smart detection
- Programmatic API with full type hints and async support
- Enhanced single-repo output and error handling
- CLI refactoring to use the API internally

### Phase 2: Package Management & Filtering (v0.8.0)

- Auto-package generation (`repoindex package init`)
- Publishing automation (`repoindex package publish`)
- `.repoindexignore` file support
- Command-line filtering options
- Filter profiles and testing

### Phase 3: Repository Intelligence (v0.9.0)

- Language and framework detection
- Repository health metrics
- Enhanced GitHub integration (issues, PRs, actions)

### Phase 4: Advanced Social Media (v1.0.0)

- Real API integrations for all platforms
- Content intelligence and optimization
- Automated campaign management

### Phase 5: Analytics and SEO (v1.1.0)

- Google Analytics automation
- SEO optimization tools
- Traffic analysis and reporting

### Phase 6: Enterprise Features (v1.2.0)

- Performance optimizations
- Advanced GitHub operations
- Team collaboration features
- Plugin system and extensibility

## Contributing to These Goals

We welcome contributions in all these areas! If you're interested in working on any of these features:

1. **Check existing issues**: Many of these are tracked as GitHub issues
2. **Start a discussion**: Open an issue to discuss your approach
3. **Small PRs**: Start with small, focused pull requests
4. **Documentation**: Help improve docs and examples
5. **Testing**: Add tests for new features and edge cases

The future of `repoindex` is exciting, and we're building it together with the community!
