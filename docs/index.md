# repoindex Documentation

Welcome to the documentation for **repoindex** - a comprehensive repository orchestration platform that helps developers manage, analyze, and automate their projects across multiple platforms with advanced clustering, workflow orchestration, and intelligent integrations.

## What is repoindex?

`repoindex` is a powerful repository orchestration platform that treats your local git repositories as the source of truth, with remote platforms (GitHub, GitLab, PyPI, etc.) serving as enrichment and distribution services. It provides advanced repository analysis, intelligent clustering, workflow automation, and comprehensive export capabilities for managing projects at scale.

## 🚀 What's New in Version 0.8.0

- **🧠 Repository Clustering**: Advanced machine learning algorithms for grouping similar projects
  - Multiple clustering algorithms: K-means, DBSCAN, Hierarchical, Network-based
  - Code duplication detection at function and class level
  - Intelligent consolidation advisor with confidence scoring
  - Support for Python, JavaScript, Java, and Go code analysis
- **🔄 Workflow Orchestration**: YAML-based workflow automation with DAG execution
  - Parallel and sequential step execution with dependency resolution
  - Multiple action types: shell, python, http, git, repoindex
  - Conditional execution and retry mechanisms
  - Built-in actions library and extensible custom actions
- **📊 Data Visualization**: Interactive charts and graphs for repository analytics
- **🎓 Tutorial Notebooks**: 5 comprehensive Jupyter notebooks for hands-on learning
- **🔌 Plugin Architecture**: Extensible integration system for custom features

## 🎯 Core Philosophy

- **Local-First**: Your local git repositories are the ground truth
- **JSONL by Default**: All commands output newline-delimited JSON for Unix pipeline composition
- **Tag-Based Organization**: Powerful tagging system with implicit tags from metadata
- **Query Language**: Fuzzy search with simple boolean expressions
- **Multi-Platform**: Works with GitHub, GitLab, Bitbucket, and more (coming soon)

## ✨ Key Features

### 🧠 **Advanced Repository Analysis**
- **Intelligent Clustering**: Automatically group similar repositories using machine learning
  - K-means clustering with automatic optimal cluster detection
  - DBSCAN for density-based clustering of arbitrary shapes
  - Hierarchical clustering with dendrogram visualization
  - Network-based clustering using repository relationships
  - Ensemble methods combining multiple algorithms
- **Code Duplication Detection**: Find duplicate code blocks across repositories
  - Function and class-level code extraction
  - Cross-repository similarity scoring
  - Multi-language support: Python, JavaScript, Java, Go
  - Actionable recommendations with confidence levels
- **Consolidation Advisor**: Get intelligent suggestions for merging similar repositories
  - Confidence scoring (0.0 to 1.0) for consolidation recommendations
  - Effort estimation: low, medium, high complexity
  - Detailed rationale and expected benefits
  - Consideration of shared dependencies and code patterns
- **Technology Stack Analysis**: Deep insights into languages, frameworks, and dependencies

### 🔄 **Workflow Orchestration**
- **YAML Workflows**: Define complex multi-step workflows in human-readable YAML
  - Clear workflow definitions with variables and templating
  - Support for workflow composition and reuse
  - Schedule workflows with cron expressions
  - Version control friendly format
- **DAG Execution**: Directed Acyclic Graph execution with dependency management
  - Automatic dependency resolution and topological sorting
  - Parallel execution of independent steps
  - Sequential execution for dependent operations
  - Dynamic step generation based on runtime conditions
- **Multiple Action Types**: Rich variety of built-in and custom actions
  - **shell**: Execute shell commands with timeout and retry
  - **python**: Run Python code with context access
  - **http**: Make HTTP requests with authentication
  - **git**: Git operations (clone, pull, push, commit)
  - **repoindex**: Integrate all repoindex commands seamlessly
  - **custom**: Extensible custom action support
- **Conditional Logic**: Support for if/else conditions and dynamic branching
  - Jinja2-style template expressions
  - Access to step outputs and workflow context
  - Complex boolean expressions
  - Skip steps based on previous results
- **Error Handling**: Robust retry and recovery mechanisms
  - Configurable retry with exponential backoff
  - Continue on error or stop on failure options
  - Error recovery steps and fallback actions
  - Comprehensive error reporting

### 🔍 **Repository Discovery & Organization**
- **Tag-Based Catalogs**: Organize repos with explicit tags and auto-generated implicit tags
- **Powerful Query Language**: Find repos with fuzzy matching: `repoindex query "language ~= 'pyton'"`
- **Metadata Store**: Local database of all repository information for fast queries
- **Implicit Tags**: Automatic tags like `repo:name`, `lang:python`, `has:docs`, `dir:parent`

### 🛡️ **Repository Auditing**
- **Comprehensive Health Checks**: Audit repos for licenses, READMEs, security issues, and more
- **Auto-Fix Capabilities**: Automatically fix common issues with `--fix` flag
- **Security Scanning**: Detect hardcoded secrets and security vulnerabilities
- **Dependency Auditing**: Check for missing or outdated dependency management
- **Documentation Health**: Verify documentation setup and configuration

### 📄 **Portfolio Export**
- **Multiple Formats**: Export to Markdown, Hugo, HTML, JSON, CSV, LaTeX, and PDF
- **Interactive HTML**: Generated HTML includes live search, filtering, and sorting
- **Hugo Integration**: Create complete Hugo site structure with taxonomies
- **Grouping & Organization**: Group exports by language, directory, or custom tags
- **Template Support**: Customizable export templates for all formats

### 📚 **Documentation Management**
- **Multi-Tool Support**: Works with MkDocs, Sphinx, Jekyll, Hugo, and more
- **Status Checking**: See documentation health across all repos
- **Build & Serve**: Build and preview documentation locally
- **Deploy to GitHub Pages**: One-command deployment to GitHub Pages
- **Bulk Operations**: Manage docs across multiple repos simultaneously

### 🚀 **Repository Management**
- Clone all your GitHub repositories with a single command
- Update multiple repositories simultaneously with smart conflict resolution
- Track status across all your projects with detailed reporting and progress bars
- Flexible repository discovery with configurable ignore patterns

### 📦 **PyPI Integration**
- Automatically detect Python packages from `pyproject.toml`, `setup.py`, and `setup.cfg`
- Track PyPI publishing status and version information with real-time checking
- Identify outdated packages that need updates
- Performance optimized with optional checking for faster operations

### 📱 **Social Media Automation**
- Template-driven content generation for Twitter, LinkedIn, and Mastodon
- Smart sampling of repositories with configurable filters
- Dry-run support to preview posts before publishing
- Rate limiting and posting frequency controls

### 🌐 **GitHub Pages Detection**
- Multi-method detection for Jekyll, MkDocs, Sphinx, and custom configurations
- Automatically build GitHub Pages URLs from repository metadata
- Track which repositories have active documentation sites

### 📄 **License Management**
- GitHub API integration for license template fetching
- Bulk license addition across multiple repositories
- Template customization with automatic placeholder replacement
- Support for all major open source licenses

### ⚙️ **Configuration Management**
- Support for both JSON and TOML configuration formats
- Environment variable overrides for all settings
- Intelligent merging of defaults, file settings, and overrides
- Built-in configuration template generation

### ⚡ **Performance & Quality**
- Fast operations with real-time progress indicators
- Configurable filtering and performance options
- Clean console output with detailed statistics
- Comprehensive error handling and logging

### 🔧 **Unix Philosophy & JSONL Output**
- All commands output newline-delimited JSON (JSONL) by default
- Stream-friendly format for processing millions of repos
- Compose with standard Unix tools (jq, grep, awk)
- Human-readable tables available with `--pretty` flag

## 🚀 Quick Start

```bash
# Install repoindex
pip install repoindex

# Generate configuration with examples
repoindex config generate

# Clone all your repositories
repoindex get

# Check status of all repositories (outputs JSONL)
repoindex status -r

# Pretty-print status as a table
repoindex status -r --pretty

# Analyze repository clusters using K-means
repoindex cluster analyze --algorithm kmeans --n-clusters 5

# Find duplicate code across repositories
repoindex cluster find-duplicates --min-similarity 0.7 -r

# Get consolidation suggestions
repoindex cluster suggest-consolidation --confidence 0.8 --pretty

# Run a workflow
repoindex workflow run examples/workflows/morning-routine.yaml

# Run workflow with variables
repoindex workflow run release-pipeline.yaml --var version=1.0.0

# Filter repos with jq
repoindex status | jq 'select(.status.uncommitted_changes == true)'

# Sample repositories for social media (dry run)
repoindex social sample --size 3
repoindex social post --dry-run
```

## Use Cases

### **Open Source Maintainers**
- Track all your projects in one place
- Automate social media promotion of releases
- Monitor PyPI package status across projects
- Keep licenses up to date

### **Development Teams**
- Synchronize repository updates across team members
- Track project health and activity
- Maintain consistent licensing and documentation

### **Individual Developers**
- Organize and monitor personal projects
- Automate promotion of your work
- Track your open source contributions

## Getting Started

1. **[Installation](getting-started.md)** - Quick start guide for new users
2. **[Tutorial Notebooks](tutorials/notebooks.md)** - Interactive Jupyter notebooks for learning
3. **[Basic Usage](usage.md)** - Learn the core commands
4. **[Configuration](usage.md#configuration-management)** - Set up your preferences
5. **[Advanced Features](usage.md#pypi-integration)** - Explore PyPI and social media features

## Documentation Sections

### 📖 Core Documentation
- **[Getting Started](getting-started.md)** - Quick installation and first steps
- **[Usage Guide](usage.md)** - Comprehensive command reference and examples
- **[Query Cookbook](query-cookbook.md)** - Advanced query examples and patterns
- **[Architecture & Vision](architecture-vision.md)** - System design and philosophy

### 🔌 Integrations
- **[Integration Overview](integrations/overview.md)** - Plugin architecture and available integrations
- **[Repository Clustering](integrations/clustering.md)** - Machine learning-based clustering
- **[Workflow Orchestration](integrations/workflow.md)** - YAML-based automation
- **[Network Analysis](integrations/network-analysis.md)** - Repository relationship analysis

### 📚 Tutorials & Guides
- **[Tutorial Notebooks](tutorials/notebooks.md)** - Interactive Jupyter notebooks
- **[Best Practices](guides/best-practices.md)** - Repository management best practices
- **[Migration Guide](guides/migration.md)** - Upgrading from older versions
- **[Troubleshooting](guides/troubleshooting.md)** - Common issues and solutions

### 🔧 Commands & API
- **[Catalog & Query](catalog-query.md)** - Organization and discovery
- **[Repository Audit](audit-command.md)** - Health checks and auto-fixes
- **[Portfolio Export](export-command.md)** - Export to multiple formats
- **[Documentation](docs-command.md)** - Documentation management
- **[API Reference](api/index.md)** - Complete API documentation

### 🚀 Development
- **[Contributing](contributing.md)** - How to contribute to the project
- **[Future Plans](future-plans.md)** - Roadmap and upcoming features
- **[Changelog](changelog.md)** - Version history and release notes

## Recent Updates

### Version 0.6.0 🎉

**Major Architecture & Quality Overhaul** - This release represents a complete transformation of `repoindex` into a robust, enterprise-ready tool.

#### 🏗️ **Complete Architecture Redesign**

- ✅ **Modular Command Structure**: Separated all commands into dedicated modules (`repoindex/commands/`)
- ✅ **Clean Separation of Concerns**: Utilities, configuration, and API integrations properly separated
- ✅ **Extensible Design**: Easy to add new commands and features without breaking existing functionality
- ✅ **Import Optimization**: Eliminated circular dependencies and improved startup time

#### 🧪 **Comprehensive Testing Framework**

- ✅ **138 Tests**: Complete test coverage for all functionality
- ✅ **86% Code Coverage**: Robust testing of edge cases and error conditions
- ✅ **Unit & Integration Tests**: Both isolated component testing and end-to-end workflows
- ✅ **Mock Testing**: Reliable testing of external API interactions
- ✅ **Error Condition Testing**: Comprehensive failure scenario coverage

#### ⚡ **Performance & Reliability Enhancements**

- ✅ **Optional API Checks**: `--no-pypi-check` and `--no-pages-check` for faster operations
- ✅ **Robust Error Handling**: Graceful handling of network failures and edge cases
- ✅ **Progress Indicators**: Real-time progress bars for long-running operations
- ✅ **Concurrent Operations**: Configurable parallel processing for better performance
- ✅ **JSONL Streaming**: Stream-friendly output for processing large repository sets
- ✅ **Unix Pipeline Integration**: Compose with jq, grep, and other standard tools

#### 📱 **Advanced Social Media Framework**

- ✅ **Template-Driven Content**: Customizable post templates for different content types
- ✅ **Multi-Platform Support**: Twitter, LinkedIn, and Mastodon integration
- ✅ **Smart Sampling**: Configurable repository filtering and random selection
- ✅ **Dry-Run Support**: Preview posts before publishing
- ✅ **Rate Limiting**: Built-in posting frequency controls and daily limits

#### ⚙️ **Enhanced Configuration System**

- ✅ **Multiple Formats**: Support for both JSON and TOML configuration files
- ✅ **Environment Overrides**: All settings controllable via environment variables
- ✅ **Intelligent Merging**: Proper precedence of defaults, files, and overrides
- ✅ **Example Generation**: `repoindex config generate` creates comprehensive examples

#### 📄 **Robust License Management**

- ✅ **GitHub API Integration**: Direct fetching of license templates from GitHub
- ✅ **Template Customization**: Automatic placeholder replacement for author details
- ✅ **Bulk Operations**: Add licenses to multiple repositories efficiently
- ✅ **All Major Licenses**: Support for MIT, Apache, GPL, and many others

#### 🌐 **Enhanced GitHub Pages Detection**

- ✅ **Multi-Method Detection**: Scans for Jekyll, MkDocs, Sphinx, and custom configurations
- ✅ **URL Construction**: Automatically builds Pages URLs from repository metadata
- ✅ **Documentation Tracking**: Monitor which projects have active documentation

#### 📦 **Improved PyPI Integration**

- ✅ **Smart Package Detection**: Enhanced scanning of `pyproject.toml`, `setup.py`, `setup.cfg`
- ✅ **Version Comparison**: Track local vs published version differences
- ✅ **Performance Options**: Optional PyPI checking for faster status operations
- ✅ **Error Resilience**: Graceful handling of PyPI API issues

### Version 0.5.x (Legacy)

- ✅ **PyPI Integration**: Automatic detection and tracking of Python packages
- ✅ **Social Media Framework**: Generate and post content about your projects
- ✅ **Configuration System**: Flexible configuration with example generation
- ✅ **Performance Improvements**: Progress bars and faster operations
- ✅ **Enhanced Status**: Clean status reporting with PyPI and GitHub Pages info

## Community and Support

- **GitHub Repository**: [github.com/queelius/repoindex](https://github.com/queelius/repoindex)
- **Issues and Bug Reports**: [GitHub Issues](https://github.com/queelius/repoindex/issues)
- **Feature Requests**: [GitHub Discussions](https://github.com/queelius/repoindex/discussions)

## License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/queelius/repoindex/blob/main/LICENSE) file for details.

---

Ready to streamline your GitHub workflow? [Get started with the installation guide](usage.md#installation-and-setup)!
