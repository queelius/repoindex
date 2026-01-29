#!/usr/bin/env python3

import os
import json
import tomllib
from pathlib import Path

import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr) # Default to stderr
    ]
)
logger = logging.getLogger("repoindex")

# Global stats dictionary (minimal - most operations are read-only)
stats = {
    "repos_scanned": 0,
    "repos_with_docs": 0,
    "repos_with_packages": 0,
}

def get_config_path():
    """Get the path to the configuration file.

    Checks in order:
    1. REPOINDEX_CONFIG environment variable
    2. ~/.repoindex/ directory (YAML preferred)
    3. ~/.ghops/ directory (legacy location for backward compatibility)

    Note: JSON/TOML configs are auto-migrated to YAML on first load.
    """
    # Check for environment variable override
    if 'REPOINDEX_CONFIG' in os.environ:
        path = Path(os.environ['REPOINDEX_CONFIG'])
        if path.exists():
            return path

    # Check ~/.repoindex/ directory (YAML preferred)
    repoindex_dir = Path.home() / '.repoindex'
    # Prefer YAML, then check legacy formats
    for filename in ['config.yaml', 'config.yml', 'config.json', 'config.toml']:
        path = repoindex_dir / filename
        if path.exists() and path.stat().st_size > 10:  # Not empty/trivial
            return path

    # Check ~/.ghops/ directory (legacy location for backward compatibility)
    ghops_dir = Path.home() / '.ghops'
    for filename in ['config.yaml', 'config.yml', 'config.json', 'config.toml']:
        path = ghops_dir / filename
        if path.exists():
            logger.debug(f"Using legacy config from {path}")
            return path

    # If no file exists, return default YAML path for saving
    return repoindex_dir / 'config.yaml'


def migrate_config_to_yaml(config_path: Path) -> Path:
    """
    Migrate JSON/TOML config to YAML format.

    Creates a backup of the original file (e.g., config.json.bak)
    and writes a new config.yaml file.

    Args:
        config_path: Path to existing JSON/TOML config file

    Returns:
        Path to the new YAML config file
    """
    if config_path.suffix.lower() in ['.yaml', '.yml']:
        return config_path  # Already YAML

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed, cannot migrate to YAML")
        return config_path

    # Load the existing config
    try:
        if config_path.suffix.lower() == '.toml':
            with open(config_path, 'rb') as f:
                config_data = tomllib.load(f)
        else:
            with open(config_path, 'r') as f:
                config_data = json.load(f)
    except Exception as e:
        logger.warning(f"Could not read config for migration: {e}")
        return config_path

    # Create backup
    backup_path = config_path.with_suffix(config_path.suffix + '.bak')
    try:
        import shutil
        shutil.copy2(config_path, backup_path)
        logger.info(f"Backed up config to {backup_path}")
    except Exception as e:
        logger.warning(f"Could not create backup: {e}")
        return config_path

    # Write new YAML config
    yaml_path = config_path.parent / 'config.yaml'
    try:
        with open(yaml_path, 'w') as f:
            yaml.safe_dump(config_data, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Migrated config to YAML: {yaml_path}")

        # Remove old config file (backup exists)
        try:
            config_path.unlink()
            logger.debug(f"Removed old config file: {config_path}")
        except Exception:
            pass  # Non-critical

        return yaml_path
    except Exception as e:
        logger.warning(f"Could not write YAML config: {e}")
        return config_path

def load_config():
    """Load configuration from file.

    Automatically migrates JSON/TOML configs to YAML format.
    """
    config_path = get_config_path()

    # Auto-migrate non-YAML configs
    if config_path.exists() and config_path.suffix.lower() not in ['.yaml', '.yml']:
        config_path = migrate_config_to_yaml(config_path)

    # Start with default config
    config = get_default_config()

    # Load from file if it exists
    if config_path.exists():
        try:
            if config_path.suffix.lower() in ['.toml']:
                # TOML is deprecated but still readable
                with open(config_path, 'rb') as f:
                    file_config = tomllib.load(f)
            elif config_path.suffix.lower() in ['.yaml', '.yml']:
                import yaml
                with open(config_path, 'r') as f:
                    file_config = yaml.safe_load(f) or {}
            else:
                # JSON is deprecated but still readable
                with open(config_path, 'r') as f:
                    file_config = json.load(f)

            # Merge file config with defaults
            config = merge_configs(config, file_config)
        except Exception as e:
            logger.error(f"Error loading config from {config_path}: {e}")

    # Apply environment variable overrides
    config = apply_env_overrides(config)

    return config

def save_config(config):
    """Save configuration to file.

    Always saves as YAML (the only supported format for writing).
    """
    config_path = get_config_path()

    # Always use YAML for new saves
    if config_path.suffix.lower() not in ['.yaml', '.yml']:
        config_path = config_path.parent / 'config.yaml'

    try:
        import yaml
    except ImportError:
        logger.error("PyYAML not installed. Install with 'pip install pyyaml'")
        return

    try:
        # Create directory if it doesn't exist
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Configuration saved to {config_path}")
    except Exception as e:
        logger.error(f"Error saving config to {config_path}: {e}")

def get_default_config():
    """
    Get default configuration.

    The config is intentionally minimal. repoindex is a read-only metadata index.
    The SQLite database serves as the cache - no in-memory caching needed.

    If no repository_directories are configured and no --dir is provided,
    repoindex will use the current directory.
    """
    return {
        # Where to find repositories
        # Empty by default - use --dir or configure explicitly
        # Supports glob patterns: ~/github/** for recursive
        "repository_directories": [],

        # Directories to exclude from repository discovery
        # Paths are matched as prefixes after ~ expansion
        # Example: ["~/github/archived", "~/github/forks"]
        "exclude_directories": [],

        # Author identity for operations (citation generation, etc.)
        # Used by `repoindex ops generate` commands as defaults
        "author": {
            "name": "",           # Full name: "Alexander Towell"
            "alias": "",          # Preferred/short name: "Alex Towell"
            "email": "",          # Email address
            "orcid": "",          # ORCID identifier: "0000-0001-6443-9897"
            "github": "",         # GitHub username
            "affiliation": "",    # Institution/organization
            "url": "",            # Personal website
            # API tokens for external services
            "zenodo_token": "",   # Zenodo API token (for future integration)
        },

        # GitHub API access (optional, for richer metadata)
        # Can also use GITHUB_TOKEN environment variable
        "github": {
            "token": "",
            "rate_limit": {
                "max_retries": 3,
                "max_delay_seconds": 60,
                "respect_reset_time": True
            }
        },

        # User-defined tags (managed by `repoindex tag` commands)
        "repository_tags": {},

        # Refresh command defaults for external sources
        # These slow operations are opt-in by default
        "refresh": {
            "external_sources": {
                "github": False,   # GitHub API (stars, topics) - moderate speed
                "pypi": False,     # PyPI package status - slow
                "cran": False,     # CRAN package status - slow
                "zenodo": False,   # Zenodo DOI enrichment (requires author.orcid)
            }
        },

        # NOTE: Legacy keys (registries, cache) are ignored if present in old configs
        # The SQLite database is now the canonical cache
    }

def generate_config_example():
    """Generate an example configuration file."""
    config_path = Path.home() / '.repoindex' / 'config.example.yaml'
    config_path.parent.mkdir(parents=True, exist_ok=True)

    example_content = """# repoindex Configuration
# A filesystem git catalog for repository collection management
# The SQLite database serves as the cache - run 'repoindex refresh' to populate

# Where to find repositories
# Use glob patterns for recursive: ~/github/**
# Leave empty to use current directory or --dir flag
repository_directories:
  - ~/github/**
  # - ~/projects
  # - /work/repos

# Directories to exclude from repository discovery
# Paths are matched as prefixes after ~ expansion
# exclude_directories:
#   - ~/github/archived
#   - ~/github/forks

# Author identity for operations (citation generation, etc.)
# Used by `repoindex ops generate` commands as defaults
# Can also use environment variables: REPOINDEX_AUTHOR_NAME, etc.
author:
  name: ""           # Full name: "Alexander Towell"
  alias: ""          # Preferred/short name: "Alex Towell"
  email: ""          # Email address
  orcid: ""          # ORCID identifier: "0000-0001-6443-9897"
  github: ""         # GitHub username
  affiliation: ""    # Institution/organization
  url: ""            # Personal website
  zenodo_token: ""   # Zenodo API token (for future integration)

# GitHub API (optional, for richer metadata)
# Alternatively, set GITHUB_TOKEN environment variable
github:
  token: ""
  rate_limit:
    max_retries: 3
    max_delay_seconds: 60
    respect_reset_time: true

# User-defined tags (managed by `repoindex tag` commands)
# repository_tags:
#   /path/to/repo: [tag1, tag2]

# Refresh command defaults for external sources
# These slow operations are opt-in by default
# Use --external flag to enable all, or individual flags
refresh:
  external_sources:
    github: false   # GitHub API (stars, topics) - moderate speed
    pypi: false     # PyPI package status - slow
    cran: false     # CRAN package status - slow
"""
    config_path.write_text(example_content)
    logger.info(f"Example configuration saved to {config_path}")


def generate_default_config():
    """Generate a minimal default configuration file (YAML)."""
    config_path = Path.home() / '.repoindex' / 'config.yaml'
    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import yaml
    except ImportError:
        logger.error("PyYAML not installed. Install with 'pip install pyyaml'")
        return

    minimal_config = {
        "repository_directories": [],
        "exclude_directories": [],
        "repository_tags": {}
    }

    with open(config_path, 'w') as f:
        yaml.safe_dump(minimal_config, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Configuration file created at {config_path}")
    logger.info("Add your repository directories or use --dir flag.")

def merge_configs(base_config, override_config):
    """
    Recursively merge two configuration dictionaries.
    
    Args:
        base_config (dict): Base configuration
        override_config (dict): Configuration to merge/override with
        
    Returns:
        dict: Merged configuration
    """
    merged = base_config.copy()
    
    for key, value in override_config.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            # Recursively merge nested dictionaries
            merged[key] = merge_configs(merged[key], value)
        else:
            # Override or add new key
            merged[key] = value
    
    return merged


def apply_env_overrides(config):
    """
    Apply environment variable overrides to configuration.

    Supports:
    - GITHUB_TOKEN: GitHub API token (standard convention)
    - REPOINDEX_AUTHOR_NAME: Author full name
    - REPOINDEX_AUTHOR_EMAIL: Author email
    - REPOINDEX_AUTHOR_ORCID: Author ORCID identifier
    - REPOINDEX_AUTHOR_GITHUB: Author GitHub username
    - REPOINDEX_ZENODO_TOKEN: Zenodo API token
    """
    # Handle GITHUB_TOKEN (standard convention)
    github_token = os.environ.get('GITHUB_TOKEN')
    if github_token:
        if 'github' not in config:
            config['github'] = {}
        config['github']['token'] = github_token

    # Handle author-related environment variables
    if 'author' not in config:
        config['author'] = {}

    author_env_mappings = [
        ('REPOINDEX_AUTHOR_NAME', 'name'),
        ('REPOINDEX_AUTHOR_ALIAS', 'alias'),
        ('REPOINDEX_AUTHOR_EMAIL', 'email'),
        ('REPOINDEX_AUTHOR_ORCID', 'orcid'),
        ('REPOINDEX_AUTHOR_GITHUB', 'github'),
        ('REPOINDEX_AUTHOR_AFFILIATION', 'affiliation'),
        ('REPOINDEX_AUTHOR_URL', 'url'),
        ('REPOINDEX_ZENODO_TOKEN', 'zenodo_token'),
    ]

    for env_var, config_key in author_env_mappings:
        value = os.environ.get(env_var)
        if value:
            config['author'][config_key] = value

    return config


def get_repository_directories(config: dict) -> list:
    """
    Get repository directories from config.

    Args:
        config: Configuration dictionary

    Returns:
        List of directory paths/patterns (empty if not configured)
    """
    return config.get('repository_directories', [])


def get_exclude_directories(config: dict) -> list:
    """
    Get exclude directories from config.

    Args:
        config: Configuration dictionary

    Returns:
        List of directory paths/patterns to exclude (empty if not configured)
    """
    return config.get('exclude_directories', [])



