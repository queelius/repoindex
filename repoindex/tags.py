"""
Tag management utilities for repoindex.

Tags are key:value pairs or simple strings that provide flexible metadata.
Examples:
  - org:torvalds
  - lang:python
  - status:active
  - deprecated (simple tag without value)
"""

from typing import Dict, List, Tuple, Optional, Any
import re


def parse_tag(tag: str) -> Tuple[str, Optional[str]]:
    """
    Parse a tag into key and optional value.
    
    Args:
        tag: Tag string (e.g., "org:torvalds" or "deprecated")
        
    Returns:
        Tuple of (key, value) where value may be None
    """
    if ':' in tag:
        parts = tag.split(':', 1)
        return (parts[0], parts[1])
    return (tag, None)


def format_tag(key: str, value: Optional[str] = None) -> str:
    """
    Format a tag from key and optional value.
    
    Args:
        key: Tag key
        value: Optional tag value
        
    Returns:
        Formatted tag string
    """
    if value is not None:
        return f"{key}:{value}"
    return key


def parse_tags(tags: List[str]) -> Dict[str, Optional[str]]:
    """
    Parse a list of tags into a dictionary.
    
    Args:
        tags: List of tag strings
        
    Returns:
        Dictionary mapping keys to values (or None for simple tags)
    """
    result = {}
    for tag in tags:
        key, value = parse_tag(tag)
        result[key] = value
    return result


def format_tags(tag_dict: Dict[str, Optional[str]]) -> List[str]:
    """
    Format a tag dictionary into a list of tag strings.
    
    Args:
        tag_dict: Dictionary of tags
        
    Returns:
        List of formatted tag strings
    """
    return [format_tag(k, v) for k, v in tag_dict.items()]


def merge_tags(existing: List[str], new: List[str]) -> List[str]:
    """
    Merge two lists of tags, with new tags overriding existing ones.
    
    Args:
        existing: Existing tags
        new: New tags to merge
        
    Returns:
        Merged list of tags
    """
    existing_dict = parse_tags(existing)
    new_dict = parse_tags(new)
    
    # Merge dictionaries (new overrides existing)
    merged = {**existing_dict, **new_dict}
    
    return format_tags(merged)


def filter_tags(tags: List[str], pattern: str) -> List[str]:
    """
    Filter tags by pattern.
    
    Args:
        tags: List of tags
        pattern: Pattern to match (e.g., "org:*", "lang:python")
        
    Returns:
        Filtered list of tags
    """
    if '*' in pattern:
        # Convert wildcard to regex
        regex_pattern = pattern.replace('*', '.*')
        regex = re.compile(f"^{regex_pattern}$")
        return [tag for tag in tags if regex.match(tag)]
    else:
        # Exact match
        return [tag for tag in tags if tag == pattern]


def get_tag_value(tags: List[str], key: str) -> Optional[str]:
    """
    Get the value of a specific tag key.
    
    Args:
        tags: List of tags
        key: Tag key to look for
        
    Returns:
        Tag value or None if not found
    """
    tag_dict = parse_tags(tags)
    return tag_dict.get(key)


def has_tag(tags: List[str], key: str, value: Optional[str] = None) -> bool:
    """
    Check if a tag exists.
    
    Args:
        tags: List of tags
        key: Tag key to check
        value: Optional specific value to match
        
    Returns:
        True if tag exists (and matches value if specified)
    """
    tag_dict = parse_tags(tags)
    if key not in tag_dict:
        return False
    
    if value is not None:
        return tag_dict[key] == value
    
    return True


def is_hierarchical_tag(tag_value: str) -> bool:
    """
    Check if a tag value represents a hierarchy.
    
    Args:
        tag_value: The tag value to check
        
    Returns:
        True if the value contains hierarchy separators
    """
    return '/' in tag_value if tag_value else False


def parse_hierarchical_tag(tag: str) -> Tuple[str, List[str]]:
    """
    Parse a hierarchical tag into key and hierarchy levels.
    
    Args:
        tag: Tag string (e.g., "topic:scientific/engineering/ai")
        
    Returns:
        Tuple of (key, hierarchy_levels)
    """
    key, value = parse_tag(tag)
    if value and '/' in value:
        levels = value.split('/')
        return (key, levels)
    return (key, [value] if value else [])


def match_hierarchical_tag(tag: str, pattern: str) -> bool:
    """
    Check if a hierarchical tag matches a pattern.
    
    Args:
        tag: Tag to check (e.g., "topic:scientific/engineering/ai")
        pattern: Pattern to match (e.g., "topic:scientific/*" or "topic:scientific")
        
    Returns:
        True if tag matches the pattern
    """
    tag_key, tag_levels = parse_hierarchical_tag(tag)
    pattern_key, pattern_levels = parse_hierarchical_tag(pattern)
    
    # Keys must match
    if tag_key != pattern_key:
        return False
    
    # If pattern has no value, it matches any value with that key
    if not pattern_levels or pattern_levels == [None]:
        return True
    
    # Check each level
    for i, pattern_level in enumerate(pattern_levels):
        if pattern_level == '*':
            # Wildcard matches rest of hierarchy
            return True
        if i >= len(tag_levels):
            # Pattern has more levels than tag
            return False
        if pattern_level != tag_levels[i]:
            return False
    
    # Exact match if pattern has same or fewer levels
    return True


def filter_hierarchical_tags(tags: List[str], pattern: str) -> List[str]:
    """
    Filter tags by hierarchical pattern.
    
    Args:
        tags: List of tags
        pattern: Pattern to match (e.g., "topic:scientific/*", "topic:scientific")
        
    Returns:
        Filtered list of tags
    """
    return [tag for tag in tags if match_hierarchical_tag(tag, pattern)]


def github_metadata_to_tags(repo_data: Dict[str, Any]) -> List[str]:
    """
    Convert GitHub repository metadata to tags.
    
    Args:
        repo_data: GitHub repository data
        
    Returns:
        List of tags
    """
    tags = []
    
    # Owner/organization
    if owner := repo_data.get('owner'):
        if isinstance(owner, dict):
            owner = owner.get('login')
        if owner:
            tags.append(f"org:{owner}")
    
    # Visibility
    if 'private' in repo_data:
        visibility = 'private' if repo_data['private'] else 'public'
        tags.append(f"visibility:{visibility}")
    
    # Fork status
    if repo_data.get('fork'):
        tags.append("fork:true")
    
    # Archived status
    if repo_data.get('archived'):
        tags.append("archived:true")
    
    # Primary language
    if language := repo_data.get('language'):
        tags.append(f"language:{language.lower()}")
    
    # License
    if license_info := repo_data.get('license'):
        if isinstance(license_info, dict) and (key := license_info.get('key')):
            tags.append(f"license:{key}")
    
    # Stars (bucketed for easier querying)
    if 'stargazers_count' in repo_data:
        stars = repo_data['stargazers_count']
        if stars >= 1000:
            tags.append("stars:1000+")
        elif stars >= 100:
            tags.append("stars:100+")
        elif stars >= 10:
            tags.append("stars:10+")
        elif stars >= 1:
            tags.append("stars:1+")
        else:
            tags.append("stars:0")
    
    # Topics (GitHub's tags)
    if topics := repo_data.get('topics'):
        for topic in topics:
            tags.append(f"topic:{topic}")
    
    # Has issues/wiki/pages
    if repo_data.get('has_issues'):
        tags.append("has:issues")
    if repo_data.get('has_wiki'):
        tags.append("has:wiki")
    if repo_data.get('has_pages'):
        tags.append("has:pages")
    
    return tags


def auto_detect_tags(repo_path: str) -> List[str]:
    """
    Auto-detect tags from repository content.

    Args:
        repo_path: Path to repository

    Returns:
        List of detected tags
    """
    from pathlib import Path
    tags = []

    repo_path_obj = Path(repo_path)

    # Detect fork status from directory structure
    # Repos in directories containing "fork" are likely forks
    path_parts = [p.lower() for p in repo_path_obj.parts]
    if 'fork' in path_parts or 'forks' in path_parts:
        tags.append("source:fork")
    
    # Detect languages by file extensions
    language_extensions = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.go': 'go',
        '.rs': 'rust',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.r': 'r',
        '.jl': 'julia',
        '.sh': 'shell',
        '.ps1': 'powershell',
    }
    
    detected_langs = set()
    for ext, lang in language_extensions.items():
        if list(repo_path_obj.rglob(f"*{ext}")):
            detected_langs.add(lang)

    for lang in detected_langs:
        tags.append(f"lang:{lang}")

    # Detect project types
    if (repo_path_obj / 'package.json').exists():
        tags.append("type:node")
    if (repo_path_obj / 'requirements.txt').exists() or (repo_path_obj / 'setup.py').exists() or (repo_path_obj / 'pyproject.toml').exists():
        tags.append("type:python")
    if (repo_path_obj / 'go.mod').exists():
        tags.append("type:go")
    if (repo_path_obj / 'Cargo.toml').exists():
        tags.append("type:rust")
    if (repo_path_obj / 'pom.xml').exists() or (repo_path_obj / 'build.gradle').exists():
        tags.append("type:java")
    if (repo_path_obj / 'Gemfile').exists():
        tags.append("type:ruby")
    if (repo_path_obj / 'composer.json').exists():
        tags.append("type:php")

    # Detect documentation
    if (repo_path_obj / 'docs').exists() or (repo_path_obj / 'documentation').exists():
        tags.append("has:docs")
    if (repo_path_obj / 'README.md').exists() or (repo_path_obj / 'README.rst').exists():
        tags.append("has:readme")

    # Detect CI/CD
    if (repo_path_obj / '.github' / 'workflows').exists():
        tags.append("ci:github-actions")
    if (repo_path_obj / '.travis.yml').exists():
        tags.append("ci:travis")
    if (repo_path_obj / '.circleci').exists():
        tags.append("ci:circleci")
    if (repo_path_obj / 'Jenkinsfile').exists():
        tags.append("ci:jenkins")

    # Detect testing
    if (repo_path_obj / 'tests').exists() or (repo_path_obj / 'test').exists():
        tags.append("has:tests")

    # Detect containerization
    if (repo_path_obj / 'Dockerfile').exists():
        tags.append("has:dockerfile")
    if (repo_path_obj / 'docker-compose.yml').exists() or (repo_path_obj / 'docker-compose.yaml').exists():
        tags.append("has:docker-compose")

    return tags


# ---------------------------------------------------------------------------
# Legacy helpers used by tag.py, shell.py, and vfs_utils.py
# ---------------------------------------------------------------------------
#
# These were previously in commands/catalog.py. They mix "derived from path"
# with "derived from metadata dict" inputs and predate the services-layer
# tag_derivation module. The tag command still uses them to render the
# repository-tag view, so they live here until a proper DB-driven rewrite.
#
# Prefer `repoindex.services.tag_derivation.derive_implicit_tags` for new
# code that already has a repos-table row — it produces a superset that
# lines up with what refresh persists. The helpers below are scoped to the
# "I only have a filesystem path plus an optional status dict" callers.


def get_implicit_tags(repo_path: str, repo_info: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Generate implicit tags for a repository based on its path and metadata.

    Args:
        repo_path: Path to the repository
        repo_info: Optional repository metadata (e.g., from status command)

    Returns:
        List of implicit tags
    """
    import os
    from .pypi import extract_pypi_tags

    implicit_tags = []

    # Add repo name tag
    repo_name = os.path.basename(repo_path)
    implicit_tags.append(f"repo:{repo_name}")

    # Add parent directory tag
    parent_dir = os.path.basename(os.path.dirname(repo_path))
    if parent_dir:
        implicit_tags.append(f"dir:{parent_dir}")

    # If we have repo metadata, add more tags
    if repo_info:
        # GitHub hosting
        if repo_info.get("remote", {}).get("url", ""):
            remote_url = repo_info["remote"]["url"]
            if "github.com" in remote_url:
                implicit_tags.append("github")

        # PyPI publishing
        if repo_info.get("package", {}).get("published"):
            implicit_tags.append("pypi")

        # License info
        license_info = repo_info.get("license")
        if license_info:
            if isinstance(license_info, dict):
                license_type = license_info.get("type", "").lower()
            else:
                license_type = str(license_info).lower()

            if license_type and license_type != "none":
                implicit_tags.append("has:license")
                implicit_tags.append(f"license:{license_type}")

        # Package info
        if repo_info.get("package"):
            implicit_tags.append("has:package")

        # GitHub Pages
        if repo_info.get("github", {}).get("pages_url"):
            implicit_tags.append("has:pages")

        # Repository visibility
        github_info = repo_info.get("github", {})
        if github_info.get("is_private") is True:
            implicit_tags.append("type:private")
        elif github_info.get("is_private") is False:
            implicit_tags.append("type:public")

        # Git status
        status = repo_info.get("status", {})
        if status.get("clean"):
            implicit_tags.append("status:clean")
        elif status.get("uncommitted_changes") or status.get("unpushed_commits"):
            implicit_tags.append("status:dirty")

        # Documentation info
        if repo_info.get("has_docs"):
            implicit_tags.append("has:docs")
            docs_tool = repo_info.get("docs_tool")
            if docs_tool:
                implicit_tags.append(f"tool:{docs_tool}")

    # Extract PyPI classifier tags if this is a Python package
    if repo_info and repo_info.get("package"):
        # Only extract if we have packaging files
        pypi_tags = extract_pypi_tags(repo_path)
        implicit_tags.extend(pypi_tags)

    return implicit_tags


def get_repository_tags(repo_path: str, repo_info: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Get all tags for a repository (explicit and implicit).

    Args:
        repo_path: Path to the repository
        repo_info: Optional repository metadata (from status command)

    Returns:
        Combined list of explicit and implicit tags
    """
    from .config import load_config

    config = load_config()

    # Get explicit tags from config
    explicit_tags = config.get("repository_tags", {}).get(repo_path, [])

    # Get implicit tags
    implicit_tags = get_implicit_tags(repo_path, repo_info)

    # Combine and deduplicate
    all_tags = list(set(explicit_tags + implicit_tags))

    return sorted(all_tags)


def is_protected_tag(tag: str) -> bool:
    """
    Check if a tag is protected (implicit/system tag that cannot be manually assigned).

    Args:
        tag: Tag to check

    Returns:
        True if the tag is protected
    """
    protected_prefixes = [
        "repo:",      # Repository name
        "dir:",       # Parent directory
        "license:",   # License type
        "has:",       # Feature flags (has:license, has:package, has:pages)
        "status:",    # Git status
        "type:",      # Repository type (private/public)
    ]

    protected_exact = [
        "github",     # Hosted on GitHub
        "pypi",       # Published on PyPI
    ]

    # Check prefixes
    for prefix in protected_prefixes:
        if tag.startswith(prefix):
            return True

    # Check exact matches
    if tag in protected_exact:
        return True

    return False