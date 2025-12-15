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

# Global stats dictionary
stats = {
    "cloned": 0,
    "skipped": 0,
    "updated": 0,
    "committed": 0,
    "pulled": 0,
    "pushed": 0,
    "conflicts": 0,
    "conflicts_resolved": 0,
    "licenses_added": 0,
    "licenses_skipped": 0,
    "repos_with_pages": 0,
    "repos_with_packages": 0,
    "published_packages": 0,
    "outdated_packages": 0,
    "social_posts": 0,
}

def get_config_path():
    """Get the path to the configuration file.

    Checks in order:
    1. REPOINDEX_CONFIG environment variable
    2. ~/.repoindex/ directory (new location)
    3. ~/.ghops/ directory (legacy location for backward compatibility)
    """
    # Check for environment variable override
    if 'REPOINDEX_CONFIG' in os.environ:
        path = Path(os.environ['REPOINDEX_CONFIG'])
        if path.exists():
            return path

    # Check ~/.repoindex/ directory (new location)
    repoindex_dir = Path.home() / '.repoindex'
    for filename in ['config.json', 'config.toml', 'config.yaml', 'config.yml']:
        path = repoindex_dir / filename
        if path.exists() and path.stat().st_size > 10:  # Not empty/trivial
            return path

    # Check ~/.ghops/ directory (legacy location for backward compatibility)
    ghops_dir = Path.home() / '.ghops'
    for filename in ['config.json', 'config.toml', 'config.yaml', 'config.yml']:
        path = ghops_dir / filename
        if path.exists():
            logger.debug(f"Using legacy config from {path}")
            return path

    # If no file exists, return default path for saving
    return repoindex_dir / 'config.json'

def migrate_config_to_tags(config: dict) -> dict:
    """
    Migrate old metadata structure to new tag-based structure.
    
    Old structure:
        repository_metadata: {
            "path": {"organization": "x", "category": "y", "tags": ["a", "b"]}
        }
    
    New structure:
        repository_tags: {
            "path": ["org:x", "category:y", "a", "b"]
        }
    """
    # Check if we have old-style metadata
    if "repository_metadata" in config and "repository_tags" not in config:
        config["repository_tags"] = {}
        
        # Convert each metadata entry to tags
        for path, metadata in config["repository_metadata"].items():
            tags = []
            
            # Convert organization to org: tag
            if org := metadata.get("organization"):
                tags.append(f"org:{org}")
            
            # Convert category to category: tag
            if category := metadata.get("category"):
                tags.append(f"category:{category}")
            
            # Add existing tags
            if existing_tags := metadata.get("tags"):
                tags.extend(existing_tags)
            
            config["repository_tags"][path] = tags
        
        # Remove old metadata
        del config["repository_metadata"]
        
        # Rebuild catalogs from tags
        rebuild_catalogs_from_tags(config)
    
    return config


def rebuild_catalogs_from_tags(config: dict) -> None:
    """Rebuild catalog structure from repository tags."""
    from .tags import parse_tag
    
    config["catalogs"] = {}
    repo_tags = config.get("repository_tags", {})
    
    for path, tags in repo_tags.items():
        for tag in tags:
            key, value = parse_tag(tag)
            
            # Add to by_tag catalog
            if "by_tag" not in config["catalogs"]:
                config["catalogs"]["by_tag"] = {}
            if tag not in config["catalogs"]["by_tag"]:
                config["catalogs"]["by_tag"][tag] = []
            if path not in config["catalogs"]["by_tag"][tag]:
                config["catalogs"]["by_tag"][tag].append(path)
            
            # Add to by_key catalogs for key:value tags
            if value is not None:
                catalog_key = f"by_{key}"
                if catalog_key not in config["catalogs"]:
                    config["catalogs"][catalog_key] = {}
                if value not in config["catalogs"][catalog_key]:
                    config["catalogs"][catalog_key][value] = []
                if path not in config["catalogs"][catalog_key][value]:
                    config["catalogs"][catalog_key][value].append(path)


def load_config():
    """Load configuration from file."""
    config_path = get_config_path()
    
    # Start with default config
    config = get_default_config()
    
    # Load from file if it exists
    if config_path.exists():
        try:
            if config_path.suffix.lower() in ['.toml']:
                with open(config_path, 'rb') as f:
                    file_config = tomllib.load(f)
            elif config_path.suffix.lower() in ['.yaml', '.yml']:
                try:
                    import yaml
                    with open(config_path, 'r') as f:
                        file_config = yaml.safe_load(f)
                except ImportError:
                    logger.warning("PyYAML not installed. Install with 'pip install pyyaml' for YAML support.")
                    # Fall back to JSON
                    with open(config_path, 'r') as f:
                        file_config = json.load(f)
            else:
                # Default to JSON format
                with open(config_path, 'r') as f:
                    file_config = json.load(f)
            
            # Merge file config with defaults
            config = merge_configs(config, file_config)
        except Exception as e:
            logger.error(f"Error loading config from {config_path}: {e}")
    
    # Apply environment variable overrides
    config = apply_env_overrides(config)
    
    # Migrate old config format to new tag-based format
    config = migrate_config_to_tags(config)
    
    return config

def save_config(config):
    """Save configuration to file."""
    config_path = get_config_path()
    
    try:
        # Create directory if it doesn't exist
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        if config_path.suffix.lower() in ['.toml']:
            # For TOML we need toml library for writing (tomllib is read-only)
            try:
                import toml
                with open(config_path, 'w') as f:
                    toml.dump(config, f)
            except ImportError:
                logger.warning("toml library not installed. Saving as JSON instead.")
                config_path = config_path.with_suffix('.json')
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
        elif config_path.suffix.lower() in ['.yaml', '.yml']:
            try:
                import yaml
                with open(config_path, 'w') as f:
                    yaml.safe_dump(config, f, default_flow_style=False)
            except ImportError:
                logger.warning("PyYAML not installed. Saving as JSON instead.")
                config_path = config_path.with_suffix('.json')
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
        else:
            # Default to JSON format
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
        
        logger.info(f"Configuration saved to {config_path}")
    except Exception as e:
        logger.error(f"Error saving config to {config_path}: {e}")

def get_default_config():
    """Get default configuration."""
    return {
        "general": {
            "repository_directories": ["~/github"],  # List of directories or glob patterns
            "git_user_name": "",
            "git_user_email": "",
            "github_username": "",
            "max_concurrent_operations": 5,
            "progress_bar": True
        },
        "language_detection": {
            "skip_directories": [".git", "node_modules", "vendor", "venv", ".venv"],
            "skip_hidden_directories": True,
            "skip_file_extensions": [".min.js", ".min.css", ".map"],
            "max_file_size_kb": 1024
        },
        "pypi": {
            "check_by_default": True,
            "timeout_seconds": 10,
            "include_test_pypi": False
        },
        "github": {
            "token": "",
            "rate_limit": {
                "max_retries": 3,
                "max_delay_seconds": 60,
                "respect_reset_time": True
            }
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s"
        },
        "social_media": {
            "platforms": {
                "twitter": {
                    "enabled": False,
                    "api_key": "",
                    "api_secret": "",
                    "access_token": "",
                    "access_token_secret": "",
                    "templates": {
                        "pypi_release": "🚀 New release: {package_name} v{version} is now available on PyPI! {pypi_url} #{package_name} #python #opensource",
                        "github_pages": "📖 Updated documentation for {repo_name}: {pages_url} #docs #opensource",
                        "random_highlight": "✨ Working on {repo_name}: {description} {repo_url} #{language} #coding"
                    }
                },
                "linkedin": {
                    "enabled": False,
                    "access_token": "",
                    "templates": {
                        "pypi_release": "I'm excited to announce the release of {package_name} v{version}! This Python package {description}. Check it out on PyPI: {pypi_url}",
                        "github_pages": "Updated the documentation for my {repo_name} project. You can view it here: {pages_url}",
                        "random_highlight": "Currently working on {repo_name} - {description}. You can find the source code here: {repo_url}"
                    }
                },
                "mastodon": {
                    "enabled": False,
                    "instance_url": "",
                    "access_token": "",
                    "templates": {
                        "pypi_release": "🐍 {package_name} v{version} is live on PyPI! {pypi_url} #Python #OpenSource",
                        "github_pages": "📚 Fresh docs for {repo_name}: {pages_url} #Documentation",
                        "random_highlight": "🛠️ {repo_name}: {description} {repo_url} #{language}"
                    }
                }
            },
            "posting": {
                "random_sample_size": 3,
                "daily_limit": 5,
                "min_hours_between_posts": 2,
                "exclude_private": True,
                "exclude_forks": True,
                "minimum_stars": 0,
                "hashtag_limit": 5
            }
        },
        "service": {
            "enabled": False,
            "interval_minutes": 120,
            "start_time": "09:00",
            "reporting": {
                "enabled": True,
                "interval_hours": 24,
                "include_stats": True,
                "include_status": True,
                "include_recent_activity": True
            },
            "notifications": {
                "email": {
                    "enabled": False,
                    "smtp_server": "",
                    "smtp_port": 587,
                    "username": "",
                    "password": "",
                    "from_email": "",
                    "to_email": "",
                    "use_tls": True,
                    "daily_summary": True,
                    "error_alerts": True
                }
            }
        },
        "filters": {
            "default_ignore_patterns": [
                ".git",
                "node_modules",
                "__pycache__",
                "*.egg-info",
                ".venv",
                "venv"
            ],
            "profiles": {}
        },
        "analytics": {
            "google_analytics": {
                "tracking_id": "",
                "auto_setup_github_pages": False
            }
        }
    }

def generate_config_example():
    """Generate an example configuration file."""
    config = get_default_config()
    config_path = Path.home() / '.repoindexrc.example'
    
    # Add helpful comments to the example
    if config_path.suffix.lower() in ['.toml']:
        example_content = """# repoindex Configuration File
# This file configures various aspects of repoindex behavior

[general]
default_directory = "~/github"  # Default directory for operations
git_user_name = ""              # Git user name (leave empty to use git config)
git_user_email = ""             # Git user email (leave empty to use git config)
github_username = ""            # GitHub username for API operations
max_concurrent_operations = 5   # Number of concurrent operations
progress_bar = true             # Show progress bars

[pypi]
check_by_default = true         # Check PyPI status in status command
timeout_seconds = 10            # Timeout for PyPI API requests
include_test_pypi = false       # Also check test.pypi.org

[social_media.platforms.twitter]
enabled = false
api_key = ""                    # Twitter API key
api_secret = ""                 # Twitter API secret
access_token = ""               # Twitter access token
access_token_secret = ""        # Twitter access token secret

[social_media.platforms.twitter.templates]
pypi_release = "🚀 New release: {package_name} v{version} is now available on PyPI! {pypi_url} #{package_name} #python #opensource"
github_pages = "📖 Updated documentation for {repo_name}: {pages_url} #docs #opensource"
random_highlight = "✨ Working on {repo_name}: {description} {repo_url} #{language} #coding"

[social_media.posting]
random_sample_size = 3          # Number of repos to randomly highlight
daily_limit = 5                 # Maximum posts per day
min_hours_between_posts = 2     # Minimum time between posts
exclude_private = true          # Don't post about private repos
exclude_forks = true            # Don't post about forked repos
minimum_stars = 0               # Minimum stars to post about a repo
hashtag_limit = 5               # Maximum hashtags per post

# Add more platform configurations as needed...
"""
        config_path.write_text(example_content)
    else:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
    
    logger.info(f"✅ An example configuration file has been saved to {config_path}")
    logger.info("Edit this file to configure repoindex for your needs.")

def generate_default_config():
    """Generate a default configuration file at ~/.repoindexrc."""
    config = get_default_config()
    config_path = Path.home() / '.repoindexrc'
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    logger.info(f"✅ Default configuration file has been saved to {config_path}")
    logger.info("Edit this file to configure repoindex for your needs.")

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
    Environment variables follow the pattern: REPOINDEX_SECTION_SUBSECTION_KEY
    For example: REPOINDEX_PYPI_CHECK_BY_DEFAULT=false
    """
    env_prefix = "REPOINDEX_"
    
    for env_key, value in os.environ.items():
        if not env_key.startswith(env_prefix):
            continue

        key_parts = env_key[len(env_prefix):].lower().split('_')
        
        # Convert value
        if value.lower() in ('true', '1', 'yes', 'on'):
            typed_value = True
        elif value.lower() in ('false', '0', 'no', 'off'):
            typed_value = False
        elif value.isdigit():
            typed_value = int(value)
        else:
            typed_value = value

        current_level = config
        i = 0
        while i < len(key_parts):
            # Find the longest key in current_level that is a prefix of the remaining key_parts
            best_match_len = 0
            matched_key = None

            for config_key in current_level.keys():
                config_key_parts_from_key = config_key.split('_')
                if key_parts[i : i + len(config_key_parts_from_key)] == config_key_parts_from_key:
                    if len(config_key_parts_from_key) > best_match_len:
                        best_match_len = len(config_key_parts_from_key)
                        matched_key = config_key
            
            if matched_key:
                # If we are at the end of the env var, we have found the key to set
                if i + best_match_len == len(key_parts):
                    current_level[matched_key] = typed_value
                    break
                
                # Otherwise, we descend into the dictionary
                if isinstance(current_level[matched_key], dict):
                    current_level = current_level[matched_key]
                    i += best_match_len
                else:
                    # Path conflict, e.g., env var is longer but we found a non-dict value
                    break 
            else:
                # No match found
                break
                
    return config



