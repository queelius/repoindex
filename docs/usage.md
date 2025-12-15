# Usage Guide

This guide covers all the features and commands available in `repoindex`.

## Installation and Setup

### Install repoindex
```bash
pip install repoindex
```

### Initial Configuration
```bash
# Generate an example configuration file
repoindex config generate

# Edit the configuration (opens ~/.repoindexrc)
nano ~/.repoindexrc

# View current configuration
repoindex config show
```

## Core Commands

### Repository Operations

#### Clone Repositories
```bash
# Clone all your GitHub repositories
repoindex get

# Clone to a specific directory
repoindex get --dir ~/projects

# Clone and add MIT license
repoindex get --license mit --license-name "Your Name" --license-email "you@example.com"
```

#### Update Repositories
```bash
# Update all repositories in current directory
repoindex update

# Update recursively (search subdirectories)
repoindex update -r

# Update repositories in specific directory
repoindex update --dir ~/projects -r

# Update and add/update licenses
repoindex update -r --license mit --license-name "Your Name"
```

#### Check Status
```bash
# Show comprehensive status
repoindex status -r

# Fast status (skip PyPI and Pages checks)
repoindex status --no-pypi-check --no-pages-check

# JSON output for scripts
repoindex status --json

# Status for specific directory
repoindex status --dir ~/projects -r
```

### Configuration Management

#### Generate Configuration
```bash
# Create example config file
repoindex config generate
```

This creates `~/.repoindexrc` with documented examples for all configuration options.

#### View Configuration
```bash
# Show current configuration
repoindex config show
```

### PyPI Integration

The PyPI integration is automatically enabled and provides:

- **Package Detection**: Scans for `pyproject.toml`, `setup.py`, `setup.cfg`
- **PyPI Status**: Checks if packages exist on PyPI
- **Version Tracking**: Shows current PyPI version vs local version
- **Statistics**: Counts published packages, outdated packages

#### PyPI Status Information

The `status` command shows:
- **PyPI Package**: Package name (linked if published)
- **Version**: Current version on PyPI or "Not published"
- **Statistics**: Summary of package status across all repositories

#### Configuration Options
```toml
[pypi]
check_by_default = true         # Include PyPI info in status
timeout_seconds = 10            # API request timeout
include_test_pypi = false       # Also check test.pypi.org
```

### Social Media Automation

#### Sample Repositories
```bash
# Sample 3 repositories randomly
repoindex social sample

# Sample 5 repositories
repoindex social sample --size 5

# Sample from specific directory
repoindex social sample --dir ~/projects --size 3
```

#### Create and Post Content
```bash
# Preview what would be posted
repoindex social post --dry-run

# Preview with custom sample size
repoindex social post --dry-run --size 2

# Actually post to configured platforms
repoindex social post --size 3
```

#### Platform Configuration

Configure social media platforms in your `~/.repoindexrc`:

```toml
[social_media.platforms.twitter]
enabled = true
api_key = "your_twitter_api_key"
api_secret = "your_twitter_api_secret"
access_token = "your_access_token"
access_token_secret = "your_access_token_secret"

[social_media.platforms.linkedin]
enabled = true
access_token = "your_linkedin_access_token"

[social_media.platforms.mastodon]
enabled = true
instance_url = "https://mastodon.social"
access_token = "your_mastodon_access_token"
```

#### Post Templates

Customize post templates for different content types:

```toml
[social_media.platforms.twitter.templates]
pypi_release = "🚀 New release: {package_name} v{version} is now available on PyPI! {pypi_url} #{package_name} #python #opensource"
github_pages = "📖 Updated documentation for {repo_name}: {pages_url} #docs #opensource"
random_highlight = "✨ Working on {repo_name}: {description} {repo_url} #{language} #coding"
```

Available template variables:
- `{repo_name}` - Repository name
- `{repo_url}` - GitHub repository URL
- `{description}` - Repository description
- `{language}` - Primary language
- `{license}` - License type
- `{package_name}` - PyPI package name
- `{version}` - PyPI package version
- `{pypi_url}` - PyPI package URL
- `{pages_url}` - GitHub Pages URL

#### Posting Rules

Control when and what to post:

```toml
[social_media.posting]
random_sample_size = 3          # Default sample size
daily_limit = 5                 # Maximum posts per day
min_hours_between_posts = 2     # Minimum time between posts
exclude_private = true          # Don't post about private repos
exclude_forks = true            # Don't post about forked repos
minimum_stars = 0               # Minimum stars to post about a repo
hashtag_limit = 5               # Maximum hashtags per post
```

### License Management

#### List Available Licenses
```bash
repoindex license list
```

#### View License Template
```bash
repoindex license show mit
repoindex license show apache-2.0
repoindex license show gpl-3.0
```

#### Add Licenses During Operations
```bash
# Add license during cloning
repoindex get --license mit --license-name "Your Name" --license-email "you@example.com"

# Add/update licenses during update
repoindex update -r --license mit --license-name "Your Name"
```

## Performance and Optimization

### Speed Up Status Checks
```bash
# Skip time-consuming checks
repoindex status --no-pypi-check --no-pages-check

# For very large numbers of repositories
repoindex status --no-pypi-check  # PyPI check is usually the slowest
```

### Configuration for Performance
```toml
[general]
max_concurrent_operations = 10  # Increase for faster parallel operations
progress_bar = true             # Show progress for long operations

[pypi]
timeout_seconds = 5             # Reduce timeout for faster checks
```

## Common Workflows

### Daily Development Workflow
```bash
# Check status of all projects
repoindex status -r

# Update all repositories
repoindex update -r

# Post about recent work (dry run first)
repoindex social post --dry-run --size 2
repoindex social post --size 2
```

### New Project Setup
```bash
# Clone all repositories
repoindex get --dir ~/projects

# Add licenses to unlicensed repositories
repoindex update -r --license mit --license-name "Your Name" --license-email "you@example.com"

# Check final status
repoindex status -r
```

### Social Media Promotion
```bash
# Sample repositories to see what's available
repoindex social sample --size 5

# Create posts for PyPI releases and documentation updates
repoindex social post --dry-run

# Actually post when ready
repoindex social post --size 3
```

## Troubleshooting

### Configuration Issues
```bash
# Regenerate configuration if corrupted
repoindex config generate

# Check current configuration
repoindex config show
```

### Performance Issues
- Use `--no-pypi-check` if PyPI API is slow
- Use `--no-pages-check` if GitHub API is rate-limited
- Reduce `timeout_seconds` in configuration
- Increase `max_concurrent_operations` for faster parallel processing

### Social Media Issues
- Verify API credentials in configuration
- Check platform-specific rate limits
- Use `--dry-run` to test without actually posting
- Check that platforms are `enabled = true` in configuration

### PyPI Detection Issues
- Ensure `packaging` Python package is installed
- Check that packaging files (`pyproject.toml`, etc.) are valid
- Verify network connectivity to PyPI
- Check `timeout_seconds` configuration if requests are timing out

## Testing and Quality Assurance

### Test Coverage and Quality

`repoindex` maintains high quality standards with:

- **138 comprehensive tests** covering all major functionality
- **86% test coverage** across the entire codebase
- **Unit tests** for individual functions and classes
- **Integration tests** for end-to-end workflows
- **Mock testing** for external API interactions
- **Error condition testing** for robust error handling

### Running Tests (for Contributors)

```bash
# Install development dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run with coverage report
pytest --cov=repoindex --cov-report=html

# Run specific test modules
pytest tests/test_status.py
pytest tests/test_integration.py

# Run tests with verbose output
pytest -v
```

### Test Categories

#### Unit Tests

- **Command modules**: Test each command's core logic
- **Utility functions**: Test shared utilities and helpers
- **Configuration system**: Test config loading and merging
- **PyPI integration**: Test package detection and API calls
- **Social media**: Test content generation and platform integration

#### Integration Tests

- **End-to-end workflows**: Full command execution paths
- **File system operations**: Repository cloning and updating
- **API integration**: Real API calls with mocking for reliability
- **Error scenarios**: Network failures and edge cases

#### Quality Metrics

- **Code coverage**: 86% across all modules
- **Error handling**: Comprehensive exception testing  
- **Performance**: Benchmarks for large repository sets
- **Compatibility**: Python 3.7+ support testing

