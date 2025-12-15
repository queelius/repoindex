# Changelog

All notable changes to repoindex will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.2] - 2025-12-15

### Added
- **Expanded Event System**: 28 total event types across multiple categories
  - Local metadata events: `license_change`, `ci_config_change`, `docs_change`, `readme_change`
  - GitHub repo events: `repo_rename`, `repo_transfer`, `repo_visibility`, `repo_archive`
  - Registry events: `gem_publish` (RubyGems), `nuget_publish` (NuGet), `maven_publish` (Maven)
- **Config-driven event defaults**: Set `events.default_types` in config
- **Improved event limits**: Default increased to 100, `--limit 0` for unlimited

### Changed
- Default event types now only include fast local events (no API calls by default)
- Event system optimized for speed-first operation

### Fixed
- Test suite improvements (625 tests passing)

## [0.8.1] - 2025-12-14

### Added
- **Additional registry events**: `npm_publish`, `cargo_publish`, `docker_publish`
- **Local metadata events**: `version_bump`, `deps_update`
- GitHub security alerts: `security_alert` event type

### Changed
- Event scanning now uses stateless time-based filtering
- Improved JSONL streaming for large event sets

## [0.8.0] - 2025-12-01

### Added
- **Comprehensive Event System**: Stateless event detection across repositories
  - Local git events: `git_tag`, `commit`, `branch`, `merge`
  - GitHub events: `github_release`, `pr`, `issue`, `workflow_run`
  - Registry events: `pypi_publish`, `cran_publish`
- **Event command**: `repoindex events` with time-based filtering
- **Watch mode**: Continuous event monitoring with `--watch`
- **Statistics**: Event summaries with `--stats`
- **MCP Server**: Model Context Protocol server for LLM integration
- **CRAN package detection**: R package registry support

### Changed
- Refocused on core functionality: metadata index, events, queries
- Simplified architecture following Unix philosophy
- All commands output JSONL by default

### Removed
- Clustering integration (repository clustering algorithms)
- Workflow orchestration engine
- Jupyter notebook tutorials
- Social media automation
- LLM content generation
- Export components (HTML, PDF, LaTeX generation)

## [0.7.x] - Previous Releases

See git history for older releases. The project underwent significant refactoring in 0.8.0 to focus on core metadata indexing and event detection functionality.

---

## Migration Notes

### From 0.7.x to 0.8.x

The 0.8.0 release represents a significant refocus of the project:

**Removed features:**
- `repoindex cluster` commands (clustering, consolidation)
- `repoindex workflow` commands
- `repoindex social` commands
- `repoindex export` (HTML, PDF generation)
- Jupyter notebook tutorials

**New focus:**
- Event-driven awareness across repository collections
- Fast local scanning by default
- JSONL output for Unix pipeline composition
- MCP server for LLM integration

**Configuration changes:**
- Config location: `~/.repoindex/config.json`
- New `events.default_types` option
- Removed clustering, workflow, social media config sections
