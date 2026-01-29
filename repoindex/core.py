"""
Core business logic for repoindex.

All functions in this module are pure and side-effect-free.
They take data, process it, and return data (usually dicts or lists).
No printing, no direct file system access (unless reading is the core function).
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Generator, Optional, Any

from repoindex.config import logger, load_config

from .pypi import detect_pypi_package, is_package_outdated
from .utils import find_git_repos, find_git_repos_from_config, get_remote_url, get_license_info, get_git_status, run_command, parse_repo_url, get_git_remote_url


def list_repos(source, directory, recursive, dedup, dedup_details):
    """
    Core logic for listing repositories.
    """
    repo_paths = []
    if source == "directory":
        if not directory:
            raise ValueError("Directory must be specified when source is 'directory'")
        search_path = os.path.expanduser(directory)
        repo_paths = find_git_repos(search_path, recursive)
    else:  # source == "config"
        config = load_config()
        config_dirs = config.get("repository_directories", [])
        for conf_dir in config_dirs:
            search_path = os.path.expanduser(conf_dir)
            # When using config, we search non-recursively by default, respecting the --recursive flag
            repo_paths.extend(find_git_repos(search_path, recursive))

    # Remove duplicates that might arise from overlapping config paths
    repos = sorted(list(set(repo_paths)))

    if not repos:
        return {"status": "no_repos_found", "repos": []}

    if dedup or dedup_details:
        return _deduplicate_repos(repos, dedup_details)
    else:
        return {"status": "success", "repos": repos}


def _deduplicate_repos(repos, dedup_details):
    # Deduplication logic (same as in the command handler)
    from collections import defaultdict
    remotes = defaultdict(list)
    
    for repo in repos:
        remote_url = get_remote_url(repo)
        if remote_url:
            remotes[remote_url].append(str(repo))
    
    if dedup_details:
        return {"status": "dedup_details", "remotes": dict(remotes)}
    else:
        unique_repos = [paths[0] for paths in remotes.values()]
        return {"status": "deduped", "repos": unique_repos}


def get_repositories_from_path(base_dir: str, recursive: bool = False) -> Generator[str, None, None]:
    """
    Generator that yields repository paths from a directory.
    
    Args:
        base_dir: Base directory to search (None means use config)
        recursive: Whether to search recursively
        
    Yields:
        Repository paths (absolute paths)
    """
    config = load_config()
    
    if base_dir is None:
        # Use configured directories if no base_dir specified
        repo_paths = find_git_repos_from_config(
            config.get('repository_directories', []),
            recursive,
            exclude_dirs_config=config.get('exclude_directories', [])
        )
        if repo_paths:
            # These are already absolute paths from find_git_repos_from_config
            for repo_path in repo_paths:
                yield repo_path
        else:
            # Fall back to current directory
            for repo_dir in find_git_repos('.', recursive):
                yield os.path.abspath(repo_dir)
    else:
        # User specified a directory - just use it directly
        from .utils import is_git_repo

        # Expand and normalize the path
        expanded_dir = os.path.expanduser(base_dir)
        expanded_dir = os.path.abspath(expanded_dir)
        
        # Check if the directory itself is a repo
        if is_git_repo(expanded_dir):
            if not recursive:
                # Just this directory
                yield expanded_dir
            else:
                # Include this directory and search inside
                yield expanded_dir
                # Also search subdirectories
                for repo_dir in find_git_repos(expanded_dir, recursive=True):
                    abs_path = os.path.abspath(repo_dir)
                    if abs_path != expanded_dir:  # Don't yield the same dir twice
                        yield abs_path
        else:
            # Directory is not a repo, search inside it
            for repo_dir in find_git_repos(expanded_dir, recursive):
                yield os.path.abspath(repo_dir)


def get_repository_status(base_dir: Optional[str] = None, recursive: bool = False, skip_pages_check: bool = False,
                         deduplicate: bool = True, tag_filters: Optional[List[Any]] = None, all_tags: bool = False,
                         use_github_api: bool = False) -> Generator[Dict[str, Any], None, None]:
    """
    Generator that yields repository status objects.

    This is a pure function that returns a generator of repository status dictionaries.
    It does not print, format, or interact with the terminal.

    Args:
        base_dir: Base directory to search for repositories
        recursive: Whether to search recursively
        skip_pages_check: Whether to skip GitHub Pages checking
        deduplicate: Whether to deduplicate by remote URL (default True)
        tag_filters: List of tag filters to apply
        all_tags: Whether to match all tags (True) or any (False)
        use_github_api: Whether to make GitHub API calls for visibility/fork info (default False for speed)

    Yields:
        Repository status dictionaries following the standard schema
    """
    # Apply tag filtering if specified
    if tag_filters:
        filtered_repos = _get_filtered_repositories(base_dir, recursive, tag_filters, all_tags)
        for repo in filtered_repos:
            if deduplicate:
                # Need to collect and deduplicate filtered repos
                # For now, just yield them without deduplication when filtering
                yield from _get_repository_status_for_path(repo, skip_pages_check, use_github_api)
            else:
                yield from _get_repository_status_for_path(repo, skip_pages_check, use_github_api)
    else:
        # Original behavior without filtering
        if deduplicate:
            # Collect all statuses and deduplicate
            yield from _get_deduplicated_status(base_dir, recursive, skip_pages_check, use_github_api)
        else:
            # Stream without deduplication
            yield from _get_repository_status_raw(base_dir, recursive, skip_pages_check, use_github_api)


def _get_filtered_repositories(base_dir: str, recursive: bool, tag_filters: list, all_tags: bool) -> List[str]:
    """Get repositories filtered by tags."""
    from .commands.catalog import get_repositories_by_tags
    config = load_config()
    
    # Get all repos based on base_dir or config
    if base_dir is not None:
        # If base_dir is specified (including "."), use it
        repos = list(get_repositories_from_path(base_dir, recursive))
    else:
        # Only use config if no base_dir specified
        repo_dirs = config.get("repository_directories", [])
        repos = list(find_git_repos_from_config(
            repo_dirs,
            exclude_dirs_config=config.get('exclude_directories', [])
        ))
    
    # Get filtered repos by tags
    filtered_repos = list(get_repositories_by_tags(tag_filters, config, all_tags))
    filtered_paths = {r["path"] for r in filtered_repos}
    
    # Filter the discovered repos
    return [r for r in repos if os.path.abspath(r) in filtered_paths]


def _get_repository_status_for_path(repo_path: str, skip_pages_check: bool = False, use_github_api: bool = False) -> Generator[Dict, None, None]:
    """Get status for a single repository path.

    Args:
        repo_path: Path to the repository
        skip_pages_check: Whether to skip GitHub Pages checking
        use_github_api: Whether to make GitHub API calls (default False for speed)
    """
    config = load_config()
    check_pypi = config.get('pypi', {}).get('check_by_default', True)

    try:
        # Get name from the repository path
        repo_name = os.path.basename(repo_path)

        # Get git status
        status_info = get_git_status(repo_path)

        # Check for uncommitted changes
        result, _ = run_command("git status --porcelain", cwd=repo_path, capture_output=True, check=False)
        has_uncommitted = bool(result and result.strip())

        # Check for unpushed commits (only if there's an upstream branch)
        has_unpushed = False
        has_upstream = False
        if status_info.get('current_branch') and status_info.get('current_branch') != 'N/A':
            # Try to check for upstream branch
            result, _ = run_command(
                f"git config --get branch.{status_info['current_branch']}.remote",
                cwd=repo_path,
                capture_output=True,
                check=False
            )
            if result and result.strip():
                has_upstream = True
                # Check for unpushed commits
                result, _ = run_command(
                    "git log @{upstream}..HEAD --oneline",
                    cwd=repo_path,
                    capture_output=True,
                    check=False
                )
                has_unpushed = bool(result and result.strip())

        # Build status object
        repo_status: Dict[str, Any] = {
            "path": repo_path,
            "name": repo_name,
            "status": {
                "branch": status_info.get('current_branch', 'N/A'),
                "clean": not has_uncommitted,
                "ahead": status_info.get('ahead', 0),
                "behind": status_info.get('behind', 0),
                "has_upstream": has_upstream,
                "uncommitted_changes": has_uncommitted,
                "unpushed_commits": has_unpushed
            }
        }

        # Get remote URL
        remote_url = get_remote_url(repo_path)
        if remote_url:
            repo_status["remote"] = {
                "url": remote_url
            }
            # Parse owner and name from URL
            owner, repo_parsed = parse_repo_url(remote_url)
            if owner:
                repo_status["remote"]["owner"] = owner
                repo_status["remote"]["name"] = repo_parsed

        # Get license info
        license_info = get_license_info(repo_path)
        if license_info:
            repo_status["license"] = license_info

        # Get package info if enabled
        if check_pypi:
            package_info = detect_pypi_package(repo_path)
            if package_info:
                if package_info.get('published'):
                    # Check if it's outdated
                    is_outdated = is_package_outdated(
                        package_info.get('name'),
                        package_info.get('version')
                    )
                    package_info['outdated'] = is_outdated
                repo_status["package"] = package_info

        # Get GitHub info - use metadata store by default for speed
        if remote_url and ("github.com" in remote_url or "github" in remote_url.lower()):
            from .utils import detect_github_pages_locally
            from .metadata import get_metadata_store

            github_info = {}
            owner, repo_parsed = parse_repo_url(remote_url)

            # Try metadata store first (fast)
            if owner and repo_parsed:
                store = get_metadata_store()
                stored_metadata = store.get(repo_path)

                if stored_metadata:
                    # Use cached GitHub info from metadata store
                    if stored_metadata.get("private") is not None:
                        github_info["is_private"] = stored_metadata.get("private", False)
                    if stored_metadata.get("fork") is not None:
                        github_info["is_fork"] = stored_metadata.get("fork", False)
                    if stored_metadata.get("has_pages"):
                        github_info["pages_url"] = f"https://{owner}.github.io/{repo_parsed}"

                # Only make API calls if explicitly requested (--github flag)
                if use_github_api:
                    try:
                        result, _ = run_command(
                            f"gh repo view {owner}/{repo_parsed} --json name,visibility,isFork",
                            capture_output=True,
                            check=False
                        )
                        if result:
                            data = json.loads(result)
                            github_info["is_private"] = data.get('visibility', '').lower() == 'private'
                            github_info["is_fork"] = data.get('isFork', False)
                    except (json.JSONDecodeError, Exception):
                        pass

            # Check for GitHub Pages (if not skipping)
            if not skip_pages_check:
                # Try local detection first (fast)
                pages_info = detect_github_pages_locally(repo_path)
                if pages_info and pages_info.get('likely_enabled'):
                    github_info["pages_url"] = pages_info.get('pages_url')
                # Only use API if explicitly requested
                elif use_github_api and owner and repo_parsed:
                    pages_result, _ = run_command(
                        f"gh api repos/{owner}/{repo_parsed}/pages --silent",
                        capture_output=True,
                        check=False
                    )
                    if pages_result:
                        try:
                            pages_data = json.loads(pages_result)
                            github_info["pages_url"] = pages_data.get('html_url')
                        except json.JSONDecodeError:
                            pass

            if github_info:
                repo_status["github"] = github_info

        # Add tags (both explicit and implicit)
        from .commands.catalog import get_repository_tags

        # Get all tags for this repository
        all_tags = get_repository_tags(repo_path, repo_info=repo_status)
        if all_tags:
            repo_status["tags"] = all_tags

        yield repo_status

    except Exception as e:
        # Return error object
        yield {
            "error": str(e),
            "type": "repository_error",
            "context": {
                "path": repo_path,
                "operation": "get_status"
            }
        }


def _get_repository_status_raw(base_dir: str, recursive: bool = False, skip_pages_check: bool = False, use_github_api: bool = False) -> Generator[Dict, None, None]:
    """Raw status generator without deduplication.

    Args:
        base_dir: Base directory to search
        recursive: Whether to search recursively
        skip_pages_check: Whether to skip GitHub Pages checking
        use_github_api: Whether to make GitHub API calls (default False for speed)
    """
    config = load_config()
    check_pypi = config.get('pypi', {}).get('check_by_default', True)

    for repo_path in get_repositories_from_path(base_dir, recursive):
        try:
            # Get name from the repository path
            repo_name = os.path.basename(repo_path)

            # Get git status
            status_info = get_git_status(repo_path)

            # Check for uncommitted changes
            result, _ = run_command("git status --porcelain", cwd=repo_path, capture_output=True, check=False)
            has_uncommitted = bool(result and result.strip())

            # Check for unpushed commits (only if there's an upstream branch)
            has_unpushed = False
            has_upstream = False
            if status_info.get('current_branch') and status_info.get('current_branch') != 'N/A':
                # Check if there's an upstream branch
                upstream_check, _ = run_command(
                    "git rev-parse --abbrev-ref @{u}",
                    cwd=repo_path,
                    capture_output=True,
                    check=False,
                    log_stderr=False
                )
                if upstream_check and not upstream_check.startswith("fatal:"):
                    has_upstream = True
                    result, _ = run_command(
                        "git cherry -v",
                        cwd=repo_path,
                        capture_output=True,
                        check=False,
                        log_stderr=False
                    )
                    has_unpushed = bool(result and result.strip())

            # Get remote information
            remote_url = get_git_remote_url(repo_path)
            owner, repo_name_parsed = parse_repo_url(remote_url) if remote_url else (None, None)

            # Build status object
            repo_status = {
                "path": os.path.abspath(repo_path),
                "name": repo_name,
                "status": {
                    "branch": status_info.get('current_branch', 'N/A'),
                    "clean": not has_uncommitted and not has_unpushed,
                    "ahead": status_info.get('ahead', 0),
                    "behind": status_info.get('behind', 0),
                    "has_upstream": has_upstream,
                    "uncommitted_changes": has_uncommitted,
                    "unpushed_commits": has_unpushed
                }
            }

            # Add remote information if available
            if remote_url:
                repo_status["remote"] = {
                    "url": remote_url,
                    "owner": owner,
                    "name": repo_name_parsed
                }

            # Add license information
            license_info = get_license_info(repo_path)
            if license_info:
                if isinstance(license_info, dict):
                    repo_status["license"] = license_info
                else:
                    # Convert string to dict format
                    repo_status["license"] = {
                        "type": license_info,
                        "file": "LICENSE"
                    }

            # Add package information if PyPI checking is enabled
            if check_pypi:
                pypi_data = detect_pypi_package(repo_path)
                if pypi_data and pypi_data.get('package_name'):
                    # Extract version from pypi_info if available
                    version = None
                    outdated = False
                    if pypi_data.get('pypi_info'):
                        version = pypi_data['pypi_info'].get('version')
                        # Check if outdated (simplified check)
                        local_version = pypi_data.get('local_version')
                        if local_version and version and local_version != version:
                            outdated = True

                    repo_status["package"] = {
                        "type": "python",
                        "name": pypi_data.get('package_name'),
                        "version": version,
                        "published": pypi_data.get('is_published', False),
                        "registry": "pypi",
                        "outdated": outdated
                    }

            # Add GitHub information if available - use metadata store by default
            if owner and repo_name_parsed:
                from .utils import detect_github_pages_locally
                from .metadata import get_metadata_store

                github_info = {}

                # Try metadata store first (fast)
                store = get_metadata_store()
                stored_metadata = store.get(repo_path)

                if stored_metadata:
                    # Use cached GitHub info from metadata store
                    if stored_metadata.get("private") is not None:
                        github_info["is_private"] = stored_metadata.get("private", False)
                    if stored_metadata.get("fork") is not None:
                        github_info["is_fork"] = stored_metadata.get("fork", False)
                    if stored_metadata.get("has_pages"):
                        github_info["pages_url"] = f"https://{owner}.github.io/{repo_name_parsed}"

                # Check for GitHub Pages
                if not skip_pages_check:
                    # Try local detection first (fast)
                    pages_info = detect_github_pages_locally(repo_path)
                    if pages_info and pages_info.get('likely_enabled'):
                        github_info["pages_url"] = pages_info.get('pages_url')
                    # Only use API if explicitly requested
                    elif use_github_api:
                        pages_result, _ = run_command(
                            f"gh api repos/{owner}/{repo_name_parsed}/pages",
                            capture_output=True,
                            check=False,
                            log_stderr=False
                        )
                        if pages_result:
                            try:
                                pages_data = json.loads(pages_result)
                                github_info["pages_url"] = pages_data.get('html_url')
                            except json.JSONDecodeError:
                                pass

                if github_info:
                    repo_status["github"] = github_info

            yield repo_status

        except Exception as e:
            # Yield error object
            yield {
                "error": str(e),
                "type": "processing_error",
                "context": {
                    "path": repo_path,
                    "base_dir": base_dir
                }
            }


def _get_deduplicated_status(base_dir: str, recursive: bool = False, skip_pages_check: bool = False, use_github_api: bool = False) -> Generator[Dict, None, None]:
    """Get deduplicated repository status with symlink detection.

    Args:
        base_dir: Base directory to search
        recursive: Whether to search recursively
        skip_pages_check: Whether to skip GitHub Pages checking
        use_github_api: Whether to make GitHub API calls (default False for speed)
    """
    from collections import defaultdict
    from pathlib import Path

    # Group repos by remote URL
    remotes = defaultdict(list)

    # First, collect all repos and their paths
    for repo_path in get_repositories_from_path(base_dir, recursive):
        remote_url = get_remote_url(repo_path)
        if remote_url:
            remotes[remote_url].append(repo_path)
        else:
            # No remote URL, treat as unique
            remotes[f"local:{repo_path}"].append(repo_path)

    # Process each group
    for remote_url, paths in remotes.items():
        if len(paths) == 1:
            # Single instance, just get status
            for status in _get_repository_status_raw(paths[0], False, skip_pages_check, use_github_api):
                yield status
        else:
            # Multiple paths - check if they're symlinks or duplicates
            # Group by inode to detect links
            inodes = {}
            for path_str in paths:
                try:
                    real_path = Path(path_str).resolve()
                    inode = real_path.stat().st_ino
                    if inode not in inodes:
                        inodes[inode] = {"primary": str(real_path), "links": []}
                    inodes[inode]["links"].append(path_str)
                except FileNotFoundError:
                    continue

            # Get status for each unique inode
            for inode, data in inodes.items():
                # Use the first path (sorted) for getting status
                sorted_links = sorted(data["links"])
                for status in _get_repository_status_raw(sorted_links[0], False, skip_pages_check, use_github_api):
                    # Add deduplication info
                    status["all_paths"] = sorted_links
                    status["primary_path"] = data["primary"]
                    status["is_linked"] = len(sorted_links) > 1
                    status["is_true_duplicate"] = len(inodes) > 1
                    yield status


def generate_and_run_report_service(service_config):
    """
    Generate reports and run as a daemon.
    """
    config = load_config()
    enabled_services = service_config.get('enabled_services', [])
    
    service_status = {
        'report': False,
        'social_media': False,
        'scheduled_tasks': []
    }
    
    # Check if report service is enabled
    if 'report' in enabled_services:
        report_config = service_config.get('report', {})
        report_frequency = report_config.get('frequency', 'daily')
        
        service_status['report'] = True
        service_status['scheduled_tasks'].append({
            'task': 'report',
            'frequency': report_frequency
        })
    
    # Check if social media service is enabled
    if 'social_media' in enabled_services:
        social_config = config.get('social_media', {})
        posting_config = social_config.get('posting', {})
        post_frequency = posting_config.get('frequency', 'daily')
        
        service_status['social_media'] = True
        service_status['scheduled_tasks'].append({
            'task': 'social_media',
            'frequency': post_frequency
        })
    
    return service_status




def get_available_licenses():
    """
    Get list of available licenses from GitHub API.
    
    Returns:
        List of license dictionaries or None on error
    """
    result, _ = run_command("gh api /licenses", capture_output=True, check=False)
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            logger.error("Failed to parse licenses JSON")
            return None
    return None


def get_license_template(license_key):
    """
    Get license template from GitHub API.
    
    Args:
        license_key: License identifier (e.g., 'mit', 'apache-2.0')
        
    Returns:
        License template dictionary or None on error
    """
    result, _ = run_command(f"gh api /licenses/{license_key}", capture_output=True, check=False)
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse license template for {license_key}")
            return None
    return None


def get_github_license_info(repo_path):
    """
    Get license info from GitHub API for a repository.
    
    Args:
        repo_path: Path to the repository
        
    Returns:
        Dictionary with license info or error
    """
    try:
        output, _ = run_command("gh repo view --json licenseInfo", cwd=repo_path, capture_output=True)
        if output:
            import json
            data = json.loads(output)
            license_info = data.get("licenseInfo", {})
            if license_info:
                return {
                    "spdx_id": license_info.get("spdxId"),
                    "name": license_info.get("name")
                }
        return {"error": "No license information found"}
    except Exception as e:
        return {"error": str(e)}


def add_license_to_repo(repo_path, license_key, author_name=None, author_email=None, 
                       year=None, force=False, dry_run=False):
    """
    Add a license file to a repository.
    
    Args:
        repo_path: Path to the repository
        license_key: License identifier (e.g., 'mit')
        author_name: Name for copyright
        author_email: Email for copyright
        year: Year for copyright (defaults to current year)
        force: Whether to overwrite existing license
        dry_run: Whether to simulate without writing
        
    Returns:
        Dictionary with status and details
    """
    repo_path = Path(repo_path)
    license_path = repo_path / "LICENSE"
    
    # Check if license already exists
    if license_path.exists() and not force:
        logger.info(f"License already exists in {repo_path}")
        return {
            "status": "skipped",
            "reason": "License file already exists",
            "path": str(license_path)
        }
    
    # Get license template
    template_data = get_license_template(license_key)
    if not template_data:
        logger.error(f"Failed to get template for license: {license_key}")
        return {
            "status": "error",
            "reason": f"Failed to get template for license: {license_key}"
        }
    
    # Prepare license content
    license_body = template_data.get('body', '')
    
    # Replace placeholders if present
    if not year:
        year = str(datetime.now().year)
    
    # Common placeholder replacements
    replacements = {
        '[year]': year,
        '[yyyy]': year,
        '<year>': year,
        '[fullname]': author_name or '',
        '[name of copyright owner]': author_name or '',
        '[email]': author_email or '',
        '<email>': author_email or '',
    }
    
    for placeholder, value in replacements.items():
        license_body = license_body.replace(placeholder, value)
    
    # Handle special copyright line format
    if author_name and '[year] [fullname]' in license_body:
        if author_email:
            copyright_line = f"{year} {author_name} <{author_email}>"
        else:
            copyright_line = f"{year} {author_name}"
        license_body = license_body.replace('[year] [fullname]', copyright_line)
    
    if dry_run:
        logger.info(f"[DRY RUN] Would write license to {license_path}")
        return {
            "status": "success_dry_run",
            "path": str(license_path),
            "license": license_key
        }
    
    # Write license file
    try:
        with open(license_path, 'w', encoding='utf-8') as f:
            f.write(license_body)
        
        logger.info(f"Added {license_key} license to {repo_path}")
        return {
            "status": "success",
            "path": str(license_path),
            "license": license_key
        }
    except Exception as e:
        logger.error(f"Failed to write license file: {e}")
        return {
            "status": "error",
            "reason": str(e)
        }


def update_repo(repo_path, auto_commit=False, commit_message="Auto commit", dry_run=False):
    """
    Update a single repository by pulling latest changes.
    
    Args:
        repo_path: Path to the repository
        auto_commit: Whether to auto-commit uncommitted changes
        commit_message: Message for auto-commit
        dry_run: Whether to simulate without executing
        
    Returns:
        Dictionary with update status
    """
    result = {
        "pulled": False,
        "committed": False,
        "pushed": False,
        "error": None
    }
    
    if dry_run:
        logger.info(f"[DRY RUN] Would update repository: {repo_path}")
        return result
    
    try:
        # Check for uncommitted changes
        status_output, _ = run_command("git status --porcelain", cwd=repo_path, capture_output=True)
        has_changes = bool(status_output and status_output.strip())
        
        if has_changes and auto_commit:
            # Commit changes
            run_command("git add -A", cwd=repo_path)
            run_command(f'git commit -m "{commit_message}"', cwd=repo_path)
            result["committed"] = True
            logger.info(f"Committed changes in {repo_path}")
        
        # Pull latest changes
        pull_output, _ = run_command("git pull", cwd=repo_path, capture_output=True)
        if pull_output and "Already up to date" not in pull_output:
            result["pulled"] = True
            logger.info(f"Pulled updates for {repo_path}")
        
        # Push if we committed
        if result["committed"]:
            run_command("git push", cwd=repo_path)
            result["pushed"] = True
            logger.info(f"Pushed changes from {repo_path}")
            
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error updating {repo_path}: {e}")
    
    return result


def create_social_media_posts(repo_paths, sample_size=3):
    """
    Create social media posts from repository paths.
    
    Args:
        repo_paths: List of repository paths
        sample_size: Number of repositories to sample
        
    Returns:
        List of post dictionaries with platform-specific content
    """
    from .metadata import get_metadata_store
    from .social import generate_social_content
    
    # Sample repositories if needed
    if len(repo_paths) > sample_size:
        # Get metadata to prioritize
        store = get_metadata_store()
        repo_metadata = []
        
        for repo_path in repo_paths:
            metadata = store.get(repo_path)
            if metadata:
                repo_metadata.append((repo_path, metadata))
        
        # Sort by stars and recent updates
        repo_metadata.sort(key=lambda x: (
            x[1].get('stargazers_count', 0),
            x[1].get('pushed_at', ''),
        ), reverse=True)
        
        # Take top repos
        selected_repos = [r[0] for r in repo_metadata[:sample_size]]
    else:
        selected_repos = repo_paths
    
    # Generate posts
    posts = []
    store = get_metadata_store()
    config = load_config()
    
    for repo_path in selected_repos:
        # Get metadata
        metadata = store.get(repo_path)
        if not metadata:
            # Skip if no metadata
            continue
        
        # Generate post content
        post_data = {
            'repo_name': metadata.get('name'),
            'repo_path': repo_path,
            'platforms': {}
        }
        
        # Generate content for each platform
        platforms = config.get('social_media', {}).get('platforms', {})
        for platform_name, platform_config in platforms.items():
            if platform_config.get('enabled', False):
                content = generate_social_content(metadata, platform_name, platform_config)
                if content:
                    post_data['platforms'][platform_name] = content
        
        if post_data['platforms']:
            posts.append(post_data)
    
    return posts


def execute_social_media_posts(posts, dry_run=False):
    """
    Execute social media posts to configured platforms.
    
    Args:
        posts: List of post dictionaries
        dry_run: Whether to simulate without posting
        
    Returns:
        Number of successful posts
    """
    config = load_config()
    platforms = config.get('social_media', {}).get('platforms', {})
    successful_posts = 0
    
    for post in posts:
        if dry_run:
            logger.info(f"[DRY RUN] Would post to platforms: {list(post.get('platforms', {}).keys())}")
            successful_posts += 1
            continue
            
        # Post to each platform
        for platform_name, content in post.get('platforms', {}).items():
            platform_config = platforms.get(platform_name, {})
            
            if not platform_config.get('enabled', False):
                logger.info(f"Skipping {platform_name} (disabled)")
                continue
                
            try:
                # Import posting functions from social module
                from .social import PLATFORM_POSTERS
                
                # Get the appropriate posting function
                poster_func = PLATFORM_POSTERS.get(platform_name)
                
                if poster_func:
                    # Call the platform-specific posting function
                    result = poster_func(content, platform_config, dry_run=False)
                    
                    if result['status'] == 'success':
                        logger.info(f"Successfully posted to {platform_name}")
                        successful_posts += 1
                    else:
                        logger.error(f"Failed to post to {platform_name}: {result.get('error', 'Unknown error')}")
                else:
                    logger.warning(f"No posting function available for {platform_name}")
            except Exception as e:
                logger.error(f"Failed to post to {platform_name}: {e}")
    
    return successful_posts