# Changelog

All notable changes to repoindex will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2025-10-16

### Added - Major Integration Features

#### Repository Clustering Integration
- **Multiple Clustering Algorithms**: Support for K-means, DBSCAN, Hierarchical, and Network-based clustering
  - K-means with automatic optimal cluster detection using silhouette scoring
  - DBSCAN for density-based clustering and outlier detection
  - Hierarchical clustering with dendrogram visualization
  - Network-based clustering using repository dependencies and relationships
  - Ensemble clustering combining multiple algorithms for consensus results
- **Code Duplication Detection**: Advanced code similarity analysis
  - Function and class-level code block extraction
  - Cross-repository duplicate detection
  - Multi-language support: Python, JavaScript, Java, Go
  - Similarity scoring with configurable thresholds
  - Actionable recommendations based on duplication levels
- **Consolidation Advisor**: Intelligent repository consolidation suggestions
  - Confidence scoring (0.0 to 1.0) for merge recommendations
  - Effort estimation: low, medium, high complexity
  - Detailed rationale and expected benefits
  - Migration step suggestions
  - Risk assessment and mitigation strategies
- **Feature Extraction**: Comprehensive repository feature analysis
  - Technology stack features (languages, frameworks, dependencies)
  - Size metrics (LOC, file count, repository size)
  - Activity patterns (commit frequency, contributors, last update)
  - Complexity metrics (cyclomatic complexity, dependency depth)
  - Documentation and quality scores
- **CLI Commands**: New clustering command group
  - `repoindex cluster analyze`: Analyze and cluster repositories
  - `repoindex cluster find-duplicates`: Detect duplicate code
  - `repoindex cluster suggest-consolidation`: Get consolidation recommendations
  - `repoindex cluster export`: Export results in multiple formats (JSON, HTML, GraphML)
- **JSONL Output**: Streaming output for all clustering operations
  - Compatible with Unix pipelines and jq
  - Progress updates and error reporting
  - Detailed result schemas with comprehensive metadata

#### Workflow Orchestration Engine
- **YAML-Based Workflows**: Human-readable workflow definitions
  - Clear syntax for multi-step automation
  - Variable templating with Jinja2-style expressions
  - Workflow composition and reuse
  - Version control friendly format
- **DAG Execution**: Directed Acyclic Graph execution engine
  - Automatic dependency resolution
  - Topological sorting for optimal execution order
  - Parallel execution of independent steps
  - Sequential execution for dependent operations
  - Cycle detection and validation
- **Multiple Action Types**: Rich variety of built-in actions
  - `shell`: Execute shell commands with timeout and retry
  - `python`: Run Python code with context access
  - `http`: Make HTTP requests with authentication
  - `git`: Git operations (clone, pull, push, commit)
  - `repoindex`: Integrate all repoindex commands seamlessly
  - `custom`: Extensible custom action support
- **Conditional Execution**: Advanced control flow
  - If/else conditions using template expressions
  - Access to step outputs and workflow context
  - Complex boolean expressions
  - Skip steps based on previous results
- **Error Handling**: Robust retry and recovery mechanisms
  - Configurable retry with exponential backoff
  - Continue on error or stop on failure options
  - Error recovery steps and fallback actions
  - Comprehensive error reporting and logging
- **CLI Commands**: Workflow management
  - `repoindex workflow run`: Execute workflows with variables
  - `repoindex workflow validate`: Syntax and semantic validation
  - `repoindex workflow list`: List available workflows
  - `repoindex workflow history`: Execution history and logs
- **Example Workflows**: Production-ready workflow templates
  - Morning routine: Daily repository maintenance
  - Release pipeline: Automated release process
  - Security audit: Vulnerability scanning workflow
  - Dependency updates: Automated dependency management

#### Tutorial Notebooks
- **5 Comprehensive Jupyter Notebooks**: Interactive learning materials
  - `01_getting_started.ipynb`: Introduction to repoindex basics
  - `02_clustering_analysis.ipynb`: Repository clustering tutorial
  - `03_workflow_orchestration.ipynb`: Building automated workflows
  - `04_advanced_integrations.ipynb`: Combining features and custom integrations
  - `05_data_visualization.ipynb`: Visualizing repository data
- **Hands-On Exercises**: Practical exercises in each notebook
- **Sample Data**: Example repositories and datasets for learning
- **Visualization Examples**: Chart and graph templates using matplotlib, seaborn, plotly
- **Best Practices**: Recommended patterns and workflows

### Enhanced - Existing Features

#### Documentation Improvements
- **Comprehensive Integration Docs**: Detailed guides for clustering and workflows
  - Algorithm comparison and selection guide
  - Complete JSONL output schemas
  - Real-world use cases and examples
  - Performance considerations and optimization tips
- **API Reference**: Complete Python API documentation
  - Integration base classes and interfaces
  - Clustering API with examples
  - Workflow API with task types
  - Utility functions and helpers
- **Tutorial Documentation**: Getting started with Jupyter notebooks
  - Setup instructions for different environments
  - Learning paths for different skill levels
  - Troubleshooting guide
  - Contributing your own notebooks
- **Enhanced Getting Started**: Quick start examples for new features
  - Clustering quick start
  - Workflow quick start
  - Integration examples

#### Command Line Interface
- **New Command Groups**: Organized command structure
  - `repoindex cluster`: Clustering and analysis commands
  - `repoindex workflow`: Workflow management commands
- **Improved Output**: Better formatting and progress indicators
  - Streaming JSONL for all commands
  - Pretty-print tables for human readability
  - Progress bars for long-running operations
- **Better Error Messages**: Clearer error reporting
  - Structured error objects in JSONL
  - Detailed error context and suggestions
  - Recovery recommendations

#### Configuration System
- **Integration Configuration**: New integration settings
  - Clustering algorithm defaults
  - Workflow execution parameters
  - Feature extraction options
- **Environment Variables**: Additional environment variable support
  - `REPOINDEX_CLUSTERING_ENABLED`: Enable/disable clustering
  - `REPOINDEX_WORKFLOW_DIR`: Custom workflow directory
  - `REPOINDEX_MAX_PARALLEL`: Maximum parallel tasks

### Changed

- **Minimum Python Version**: Now requires Python 3.8+ (was 3.7+)
- **Optional Dependencies**: Clustering and workflow features require extra packages
  - Install with `pip install repoindex[clustering]` for clustering features
  - Install with `pip install repoindex[workflows]` for workflow features
  - Install with `pip install repoindex[all]` for all features
- **Output Format**: All commands now default to JSONL (was mixed)
  - Use `--pretty` flag for human-readable table output
  - Better Unix pipeline compatibility

### Fixed

- **Memory Usage**: Improved memory efficiency for large repository collections
  - Streaming processing instead of loading everything in memory
  - Generator-based iteration throughout
- **Performance**: Faster repository analysis
  - Parallel feature extraction
  - Cached repository metadata
  - Optimized clustering algorithms
- **Error Handling**: More robust error recovery
  - Better handling of corrupt repositories
  - Graceful degradation on partial failures
  - Detailed error context in JSONL output

### Dependencies

#### New Required Dependencies
- `pyyaml>=6.0`: YAML workflow parsing
- `jinja2>=3.0`: Template rendering in workflows

#### New Optional Dependencies
- `scikit-learn>=1.0.0`: Clustering algorithms
- `scipy>=1.7.0`: Scientific computing for clustering
- `numpy>=1.21.0`: Numerical operations
- `pandas>=1.3.0`: Data analysis in notebooks
- `matplotlib>=3.4.0`: Static visualizations
- `seaborn>=0.11.0`: Statistical visualizations
- `plotly>=5.0.0`: Interactive visualizations
- `networkx>=2.6.0`: Network analysis and visualization

### Migration Guide

#### From 0.7.x to 0.8.0

**Breaking Changes:**
1. **Python Version**: Upgrade to Python 3.8+
   ```bash
   # Check your Python version
   python --version
   # Upgrade if needed
   ```

2. **Optional Features**: Install extra dependencies
   ```bash
   # For clustering
   pip install repoindex[clustering]

   # For workflows
   pip install repoindex[workflows]

   # For everything
   pip install repoindex[all]
   ```

3. **Output Format**: All commands now output JSONL by default
   ```bash
   # Old way (might have mixed output)
   repoindex list

   # New way (JSONL output)
   repoindex list

   # For human-readable table
   repoindex list --pretty
   ```

**New Features to Try:**
1. **Clustering**: Organize your repositories
   ```bash
   repoindex cluster analyze --algorithm kmeans -r
   repoindex cluster find-duplicates --min-similarity 0.8
   ```

2. **Workflows**: Automate your tasks
   ```bash
   repoindex workflow run examples/workflows/morning-routine.yaml
   ```

3. **Notebooks**: Learn interactively
   ```bash
   cd notebooks/
   jupyter notebook
   ```

## [0.7.0] - 2025-10-01

### Added - Major Architecture Overhaul

#### Component-Based Export System
- **Multiple Export Formats**: Markdown, Hugo, HTML, JSON, CSV, LaTeX, PDF
- **Interactive HTML**: Live search, filtering, and sorting
- **Template Support**: Customizable export templates
- **Grouping Options**: Group by language, directory, or custom tags

#### Unified Progress System
- **Consistent Progress Bars**: All commands show progress
- **Proper Exit Codes**: Commands return appropriate exit codes
- **Error Aggregation**: Collect and report all errors

#### Comprehensive Tagging System
- **Explicit Tags**: User-assigned tags in catalog
- **Implicit Tags**: Auto-generated from metadata
- **Provider Tags**: From GitHub topics, GitLab labels
- **Protected Namespaces**: Reserved prefixes for system tags

#### Query Language Enhancement
- **Fuzzy Matching**: Typo-tolerant queries with `~=` operator
- **Nested Field Access**: Query nested objects with dot notation
- **Multiple Operators**: `==`, `!=`, `~=`, `>`, `<`, `contains`, `in`

#### Documentation Management
- **Multi-Tool Support**: MkDocs, Sphinx, Jekyll, Hugo, Docusaurus
- **Status Checking**: Documentation health across repos
- **Build & Serve**: Local documentation preview
- **Deploy to GitHub Pages**: One-command deployment

#### Repository Audit
- **Health Checks**: License, README, security, documentation
- **Auto-Fix**: Automatically fix common issues
- **Security Scanning**: Detect hardcoded secrets
- **Dependency Auditing**: Check for outdated dependencies

### Changed
- **Architecture**: Modular command structure in `repoindex/commands/`
- **Testing**: 138 tests with 86% coverage
- **Performance**: Optional API checks for faster operations

## [0.6.0] - 2025-09-15

### Added
- **PyPI Integration**: Package detection and tracking
- **Social Media Automation**: Twitter, LinkedIn, Mastodon
- **Configuration System**: JSON and TOML support
- **Progress Bars**: Real-time progress indicators
- **Enhanced Status**: Clean status reporting

## [0.5.0] - 2025-09-01

### Added
- **License Management**: Bulk license operations
- **GitHub Pages Detection**: Multi-method detection
- **Rate Limiting**: Intelligent GitHub API rate limiting
- **Bulk Operations**: Update multiple repositories

## [0.4.0] - 2025-08-15

### Added
- **Repository Listing**: Deduplicated repository discovery
- **Status Tracking**: Git status with upstream tracking
- **Basic Configuration**: JSON configuration file

## [0.3.0] - 2025-08-01

### Added
- **Repository Cloning**: Clone all GitHub repositories
- **Repository Updates**: Smart conflict resolution
- **GitHub Integration**: GitHub API integration

## [0.2.0] - 2025-07-15

### Added
- **Basic Commands**: list, status, update
- **Git Integration**: Local git repository management

## [0.1.0] - 2025-07-01

### Added
- **Initial Release**: Basic repository management
- **CLI Framework**: Click-based command line interface
- **Configuration**: Simple configuration system

---

## Upcoming in 0.9.0

### Planned Features
- **Time Machine**: Historical analysis and trend tracking
- **Container Analysis**: Docker and Kubernetes support
- **Security Integration**: Advanced vulnerability scanning
- **Code Quality**: Static analysis integration
- **Cloud Providers**: AWS, Azure, GCP integration
- **Issue Tracking**: Jira, Linear, Asana sync

### Improvements
- **Performance**: Further optimization for large collections
- **Documentation**: More examples and tutorials
- **Testing**: Increased test coverage
- **UI**: Optional web interface

---

## Support

- **Issues**: [GitHub Issues](https://github.com/queelius/repoindex/issues)
- **Discussions**: [GitHub Discussions](https://github.com/queelius/repoindex/discussions)
- **Documentation**: [repoindex.readthedocs.io](https://repoindex.readthedocs.io)
- **Contributing**: [CONTRIBUTING.md](contributing.md)
