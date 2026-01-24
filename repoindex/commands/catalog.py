"""
Catalog management commands for repoindex.

Provides virtual organization of repositories through metadata-based catalogs.
Supports creating symlink directories, searching, and filtering repositories.
"""

import click
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Generator, Optional
from collections import defaultdict

from ..config import load_config, save_config
from ..utils import find_git_repos_from_config, is_git_repo
from ..pypi import extract_pypi_tags
from ..cli_utils import standard_command, add_common_options
from rich.console import Console
from rich import box

console = Console()


def get_repository_tags(repo_path: str, repo_info: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Get all tags for a repository (explicit and implicit).
    
    Args:
        repo_path: Path to the repository
        repo_info: Optional repository metadata (from status command)
        
    Returns:
        Combined list of explicit and implicit tags
    """
    config = load_config()
    
    # Get explicit tags from config
    explicit_tags = config.get("repository_tags", {}).get(repo_path, [])
    
    # Get implicit tags
    implicit_tags = get_implicit_tags(repo_path, repo_info)
    
    # Combine and deduplicate
    all_tags = list(set(explicit_tags + implicit_tags))
    
    return sorted(all_tags)


def get_implicit_tags(repo_path: str, repo_info: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Generate implicit tags for a repository based on its path and metadata.
    
    Args:
        repo_path: Path to the repository
        repo_info: Optional repository metadata (e.g., from status command)
        
    Returns:
        List of implicit tags
    """
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


def get_repo_metadata_tags(repo_path: str) -> List[str]:
    """
    Get implicit tags based on repository metadata.
    This fetches actual repo status to generate tags like has:license, pypi, etc.
    
    Args:
        repo_path: Path to the repository
        
    Returns:
        List of metadata-based implicit tags
    """
    from ..core import _get_repository_status_for_path
    
    try:
        # Get repository status (this includes license, package, github info, etc.)
        # _get_repository_status_for_path is a generator, so we need to get the first result
        for repo_info in _get_repository_status_for_path(repo_path):
            # Get all implicit tags including metadata-based ones
            return get_implicit_tags(repo_path, repo_info)
        
        # If no results, return path-based tags
        return get_implicit_tags(repo_path)
    except Exception as e:
        # If we can't get metadata, just return path-based tags
        import sys
        print(f"Debug: Error getting metadata for {repo_path}: {e}", file=sys.stderr)
        return get_implicit_tags(repo_path)


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


def get_repositories_by_tags(tag_filters: List[str], config: Dict[str, Any], 
                            match_all: bool = False) -> Generator[Dict[str, Any], None, None]:
    """
    Get repositories that match tag filters.
    
    Args:
        tag_filters: List of tag filters (e.g., "org:*", "lang:python", "deprecated")
        config: Configuration dictionary
        match_all: If True, repository must match all filters; if False, match any
        
    Yields:
        Repository info dictionaries with path, name, and tags
    """
    from ..tags import filter_tags
    
    # Get repository tags from config
    repo_tags = config.get("repository_tags", {})
    
    # If no filters, return all repositories
    if not tag_filters:
        repo_dirs = config.get("general", {}).get("repository_directories", [])
        for repo_path in find_git_repos_from_config(repo_dirs):
            # Try to find tags using both absolute and relative paths
            tags = repo_tags.get(repo_path, [])
            if not tags:
                # Try with home directory collapsed
                home = os.path.expanduser("~")
                if repo_path.startswith(home):
                    relative_path = "~" + repo_path[len(home):]
                    tags = repo_tags.get(relative_path, [])
            
            # If still no tags, check parent directories for inherited tags
            if not tags:
                # Check each tagged path to see if it's a parent of this repo
                for tagged_path, parent_tags in repo_tags.items():
                    expanded_tagged_path = os.path.expanduser(tagged_path)
                    # Check if this repo is inside the tagged directory
                    if (repo_path.startswith(expanded_tagged_path + "/") and 
                        not is_git_repo(expanded_tagged_path)):
                        # Tagged path is a parent directory (not a git repo itself)
                        tags = parent_tags
                        break
            
            # Add implicit tags - always use metadata store for completeness
            from ..metadata import MetadataStore
            store = MetadataStore()
            metadata = store.get(repo_path)
            if metadata:
                implicit_tags = get_implicit_tags(repo_path, metadata)
            else:
                # If no metadata, just use path-based tags
                implicit_tags = get_implicit_tags(repo_path)
            all_tags = list(set(tags + implicit_tags))
            
            yield {
                "path": repo_path,
                "name": os.path.basename(repo_path),
                "tags": all_tags
            }
        return
    
    # Find repositories matching filters
    repo_dirs = config.get("general", {}).get("repository_directories", [])
    for repo_path in find_git_repos_from_config(repo_dirs):
        # Try to find tags using both absolute and relative paths
        tags = repo_tags.get(repo_path, [])
        if not tags:
            # Try with home directory collapsed
            home = os.path.expanduser("~")
            if repo_path.startswith(home):
                relative_path = "~" + repo_path[len(home):]
                tags = repo_tags.get(relative_path, [])
        
        # If still no tags, check parent directories for inherited tags
        if not tags:
            # Check each tagged path to see if it's a parent of this repo
            for tagged_path, parent_tags in repo_tags.items():
                expanded_tagged_path = os.path.expanduser(tagged_path)
                # Check if this repo is inside the tagged directory
                if (repo_path.startswith(expanded_tagged_path + "/") and 
                    not is_git_repo(expanded_tagged_path)):
                    # Tagged path is a parent directory (not a git repo itself)
                    tags = parent_tags
                    break
        
        # Add implicit tags - always use metadata store for completeness
        from ..metadata import MetadataStore
        store = MetadataStore()
        metadata = store.get(repo_path)
        if metadata:
            implicit_tags = get_implicit_tags(repo_path, metadata)
        else:
            # If no metadata, just use path-based tags
            implicit_tags = get_implicit_tags(repo_path)
        all_tags = list(set(tags + implicit_tags))
        
        # Check if tags match filters
        matches = []
        for tag_filter in tag_filters:
            matching_tags = filter_tags(all_tags, tag_filter)
            matches.append(bool(matching_tags))
        
        # Apply match logic
        if match_all and all(matches):
            yield {
                "path": repo_path,
                "name": os.path.basename(repo_path),
                "tags": all_tags
            }
        elif not match_all and any(matches):
            yield {
                "path": repo_path,
                "name": os.path.basename(repo_path),
                "tags": all_tags
            }


def create_symlink_directory(target_dir: str, repo_paths: List[str], 
                           dry_run: bool = False) -> Dict[str, Any]:
    """
    Create a directory with symlinks to repositories.
    
    Args:
        target_dir: Directory to create with symlinks
        repo_paths: List of repository paths to link
        dry_run: Whether to simulate the operation
        
    Returns:
        Operation result dictionary
    """
    result = {
        "target_dir": target_dir,
        "created": False,
        "linked_count": 0,
        "errors": [],
        "details": {}
    }
    
    try:
        if not dry_run:
            # Create target directory
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            result["created"] = True
            
            # Create symlinks
            for repo_path in repo_paths:
                repo_name = os.path.basename(repo_path)
                link_path = os.path.join(target_dir, repo_name)
                
                # Check if link already exists
                if os.path.exists(link_path):
                    if os.path.islink(link_path):
                        # Update existing link if it points elsewhere
                        if os.readlink(link_path) != repo_path:
                            os.unlink(link_path)
                            os.symlink(repo_path, link_path)
                    else:
                        result["errors"].append(f"{repo_name}: Path exists and is not a symlink")
                        continue
                else:
                    os.symlink(repo_path, link_path)
                
                result["linked_count"] += 1
        else:
            result["created"] = True
            result["linked_count"] = len(repo_paths)
            result["details"]["message"] = "[DRY RUN] Would create symlinks"
            
    except Exception as e:
        result["error"] = str(e)
        
    return result


@click.group("catalog")
def catalog_cmd():
    """Manage repository catalogs for virtual organization."""
    pass


@catalog_cmd.command("import-github")
@click.option("-t", "--tag", "tag_filters", multiple=True, help="Only import for repos matching these tags")
@click.option("--all", "match_all", is_flag=True, help="Match all tags (default: match any)")
@add_common_options('verbose', 'quiet', 'dry_run')
@standard_command(streaming=True)
def catalog_import_github(tag_filters, match_all, dry_run, quiet, progress, **kwargs):
    """
    Import GitHub metadata as tags for repositories.
    
    Fetches repository information from GitHub and adds tags like:
    
    \b
    - github:topic:security (from GitHub topics)
    - github:lang:python (primary language)
    - github:stars:100+ (star count buckets)
    - github:fork:true (if it's a fork)
    - github:archived:true (if archived)
    
    Examples:
    
    \b
        repoindex catalog import-github  # Import for all repos
        repoindex catalog import-github -t org:torvalds  # Only for specific org
        repoindex catalog import-github --dry-run  # Preview changes
        repoindex catalog import-github -q  # Progress only, no JSON output
    """
    from ..tags import github_metadata_to_tags
    from ..utils import get_github_repo_info
    from ..exit_codes import NoReposFoundError, APIError, PartialSuccessError
    import time
    
    config = load_config()
    
    # Get repositories to process
    progress("Discovering repositories...")
    repos = list(get_repositories_by_tags(tag_filters, config, match_all))
    
    if not repos:
        raise NoReposFoundError("No repositories found to import GitHub metadata")
    
    # Track changes
    updated_count = 0
    error_count = 0
    skipped_count = 0
    
    progress(f"Found {len(repos)} repositories to process")
    
    # Use progress bar for processing
    with progress.task("Importing GitHub metadata", total=len(repos)) as update:
        for i, repo in enumerate(repos, 1):
            repo_path = repo["path"]
            repo_name = repo["name"]
            existing_tags = repo["tags"]
            
            # Update progress
            update(i, repo_name)
            
            result = {
                "path": repo_path,
                "name": repo_name,
                "status": "pending"
            }
            
            try:
                # Get GitHub info from remote URL
                remote_url = None
                from ..utils import get_remote_url
                remote_url = get_remote_url(repo_path)
                
                if not remote_url or "github.com" not in remote_url:
                    result["status"] = "skipped"
                    result["reason"] = "Not a GitHub repository"
                    skipped_count += 1
                    if not quiet:
                        yield result
                    continue
                
                # Extract owner and repo name from URL
                import re
                match = re.search(r'github.com[:/]([^/]+)/([^/\.]+)', remote_url)
                if not match:
                    result["status"] = "error"
                    result["error"] = "Could not parse GitHub URL"
                    error_count += 1
                    if not quiet:
                        yield result
                    continue
                
                owner, repo = match.groups()
                
                # Fetch from GitHub API
                repo_data = get_github_repo_info(owner, repo)
                
                if not repo_data:
                    result["status"] = "error"
                    result["error"] = "Failed to fetch from GitHub API"
                    error_count += 1
                    if not quiet:
                        yield result
                    continue
                
                # Convert to tags with github: prefix
                github_tags = []
                for tag in github_metadata_to_tags(repo_data):
                    # Add github: prefix to distinguish from user tags
                    if ":" in tag:
                        key, value = tag.split(":", 1)
                        github_tags.append(f"github:{key}:{value}")
                    else:
                        github_tags.append(f"github:{tag}")
                
                # Remove old github: tags and add new ones
                # Keep only non-github tags from existing
                non_github_tags = [t for t in existing_tags if not t.startswith("github:")]
                
                # Combine non-github tags with new github tags
                new_tags = non_github_tags + github_tags
                
                # Check if anything changed
                if set(new_tags) != set(existing_tags):
                    result["status"] = "updated"
                    result["old_tags"] = existing_tags
                    result["new_tags"] = new_tags
                    result["added_tags"] = list(set(new_tags) - set(existing_tags))
                    
                    if not dry_run:
                        # Update repository tags in config
                        if "repository_tags" not in config:
                            config["repository_tags"] = {}
                        config["repository_tags"][repo_path] = new_tags

                    updated_count += 1
                else:
                    result["status"] = "unchanged"
                
                # Yield result immediately for streaming
                if not quiet:
                    yield result
                
                # Be nice to GitHub API
                time.sleep(0.1)
                
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
                error_count += 1
                if not quiet:
                    yield result
                progress.error(f"Error processing {repo_name}: {e}")
    
    # Save config if not dry run
    if not dry_run and updated_count > 0:
        save_config(config)
        progress.success(f"Configuration saved with {updated_count} updates")
    
    # Show summary
    unchanged_count = len(repos) - updated_count - error_count - skipped_count
    progress("")  # Empty line
    progress("Summary:")
    progress(f"  Total repositories: {len(repos)}")
    if updated_count > 0:
        progress.success(f"  Updated: {updated_count}")
    if unchanged_count > 0:
        progress(f"  Unchanged: {unchanged_count}")
    if skipped_count > 0:
        progress(f"  Skipped: {skipped_count}")
    if error_count > 0:
        progress.error(f"  Errors: {error_count}")
    
    if dry_run:
        progress.warning("DRY RUN - no changes were saved")
    
    # Raise appropriate error if there were failures
    if error_count > 0 and updated_count == 0:
        # Complete failure
        raise APIError(f"Failed to import GitHub metadata for all {error_count} repositories")
    elif error_count > 0:
        # Partial success
        raise PartialSuccessError(
            f"Imported metadata for {updated_count} repos, but {error_count} failed",
            succeeded=updated_count,
            failed=error_count
        )


@catalog_cmd.command("tag")
@click.option("-t", "--tag", "new_tags", multiple=True, required=True, help="Tags to add (e.g., type:work, lang:python)")
@click.option("--remove", "remove_tags", multiple=True, help="Tags to remove")
@click.option("-d", "--dir", "directory", help="Tag all repos in this directory")
@click.option("-f", "--filter", "tag_filters", multiple=True, help="Only tag repos matching these filters")
@click.option("--all", "match_all", is_flag=True, help="Match all filters (default: match any)")
@click.option("--sync-pypi", is_flag=True, help="Sync applicable tags to PyPI metadata")
@click.option("--dry-run", is_flag=True, help="Preview changes without saving")
@click.option("--pretty", is_flag=True, help="Display results in formatted output")
def catalog_tag(new_tags, remove_tags, directory, tag_filters, match_all, sync_pypi, dry_run, pretty):
    """
    Add or remove tags from repositories.
    
    Examples:
        # Tag all repos in a directory
        repoindex catalog tag -t type:work -t priority:high -d ~/work
        
        # Tag repos matching a filter
        repoindex catalog tag -t deprecated -f lang:perl
        
        # Remove tags
        repoindex catalog tag --remove deprecated -f lang:perl
        
        # Tag specific repos by combining filters
        repoindex catalog tag -t needs:review -f org:mycompany -f "stars:0" --all
    """
    from ..tags import merge_tags
    
    config = load_config()
    
    # Determine which repos to tag
    repos_to_tag = []
    
    if directory:
        # Tag all repos in the specified directory
        expanded_dir = os.path.expanduser(directory)
        if not os.path.exists(expanded_dir):
            error_msg = {"error": f"Directory not found: {directory}"}
            if pretty:
                console.print(f"[red]✗[/red] {error_msg['error']}")
            else:
                print(json.dumps(error_msg), flush=True)
            return
        
        # Find all git repos in directory
        for root, dirs, _ in os.walk(expanded_dir):
            if '.git' in dirs:
                repos_to_tag.append({
                    "path": root,
                    "name": os.path.basename(root),
                    "tags": config.get("repository_tags", {}).get(root, [])
                })
                dirs[:] = [d for d in dirs if d != '.git']
    else:
        # Tag repos matching filters
        repos_to_tag = list(get_repositories_by_tags(tag_filters, config, match_all))
    
    if not repos_to_tag:
        error_msg = {"error": "No repositories found to tag"}
        if pretty:
            console.print(f"[red]✗[/red] {error_msg['error']}")
        else:
            print(json.dumps(error_msg), flush=True)
        return
    
    # Check for protected tags
    protected_tags_to_add = [tag for tag in new_tags if is_protected_tag(tag)]
    if protected_tags_to_add and not dry_run:
        error_msg = {
            "error": f"Cannot manually assign protected tags: {', '.join(protected_tags_to_add)}",
            "protected_tags": protected_tags_to_add
        }
        if pretty:
            console.print(f"[red]✗[/red] {error_msg['error']}")
            console.print("\n[yellow]Protected tags are automatically assigned based on repository attributes.[/yellow]")
        else:
            print(json.dumps(error_msg), flush=True)
        return
    
    # Process each repository
    results = []
    updated_count = 0
    
    for repo in repos_to_tag:
        repo_path = repo["path"]
        current_tags = repo["tags"]
        
        # Filter out implicit tags from current tags (they'll be re-added automatically)
        current_tags = [t for t in current_tags if not is_protected_tag(t)]
        
        # Apply tag changes
        if remove_tags:
            # Remove specified tags (but not protected ones)
            new_tag_list = [t for t in current_tags if t not in remove_tags]
        else:
            new_tag_list = current_tags
        
        # Add new tags (excluding protected ones)
        if new_tags:
            tags_to_add = [t for t in new_tags if not is_protected_tag(t)]
            new_tag_list = merge_tags(new_tag_list, tags_to_add)
        
        # Check if anything changed
        if set(new_tag_list) != set(current_tags):
            result = {
                "path": repo_path,
                "name": repo["name"],
                "old_tags": current_tags,
                "new_tags": new_tag_list,
                "added": list(set(new_tag_list) - set(current_tags)),
                "removed": list(set(current_tags) - set(new_tag_list)),
                "updated": True,
                "pypi_sync": {}
            }
            
            if not dry_run:
                # Update repository tags in config
                if "repository_tags" not in config:
                    config["repository_tags"] = {}
                config["repository_tags"][repo_path] = new_tag_list

                # Sync to PyPI if requested
                if sync_pypi:
                    from ..pypi import sync_pypi_tags, find_packaging_files
                    # Only sync if this is a Python package
                    if find_packaging_files(repo_path):
                        # Sync added tags to PyPI
                        tags_to_sync = result["added"]
                        sync_results = sync_pypi_tags(repo_path, tags_to_sync)
                        result["pypi_sync"] = sync_results
            
            updated_count += 1
        else:
            result = {
                "path": repo_path,
                "name": repo["name"],
                "tags": current_tags,
                "updated": False
            }
        
        results.append(result)
    
    # Save config if not dry run
    if not dry_run and updated_count > 0:
        save_config(config)
    
    # Output results
    if pretty:
        # Show what we're doing
        action_desc = []
        if new_tags:
            action_desc.append(f"Adding: {', '.join(new_tags)}")
        if remove_tags:
            action_desc.append(f"Removing: {', '.join(remove_tags)}")
        
        console.print(f"[bold]{' | '.join(action_desc)}[/bold]")
        
        if directory:
            console.print(f"Directory: {directory}")
        elif tag_filters:
            filter_desc = " AND ".join(tag_filters) if match_all else " OR ".join(tag_filters)
            console.print(f"Filters: {filter_desc}")
        
        console.print("\n[bold]Results:[/bold]")
        console.print(f"  Total repositories: {len(repos_to_tag)}")
        console.print(f"  [green]Updated: {updated_count}[/green]")
        console.print(f"  Unchanged: {len(repos_to_tag) - updated_count}")
        
        if dry_run:
            console.print("\n[yellow]DRY RUN - no changes were saved[/yellow]")
        
        # Show updated repos
        updated_results = [r for r in results if r.get("updated")]
        if updated_results and len(updated_results) <= 10:
            console.print("\n[bold]Updated repositories:[/bold]")
            for result in updated_results:
                console.print(f"\n  {result['name']}:")
                if result.get("added"):
                    console.print(f"    [green]Added:[/green] {', '.join(result['added'])}")
                if result.get("removed"):
                    console.print(f"    [red]Removed:[/red] {', '.join(result['removed'])}")
                if sync_pypi and result.get("pypi_sync"):
                    synced = [tag for tag, success in result["pypi_sync"].items() if success]
                    failed = [tag for tag, success in result["pypi_sync"].items() if not success]
                    if synced:
                        console.print(f"    [blue]Synced to PyPI:[/blue] {', '.join(synced)}")
                    if failed:
                        console.print(f"    [yellow]Failed to sync:[/yellow] {', '.join(failed)}")
        elif updated_results:
            console.print("\n[bold]Updated repositories:[/bold]")
            for result in updated_results:
                console.print(f"\n  {result['name']}:")
                if result.get("added"):
                    console.print(f"    [green]Added:[/green] {', '.join(result['added'])}")
                if result.get("removed"):
                    console.print(f"    [red]Removed:[/red] {', '.join(result['removed'])}")
        elif updated_results:
            console.print(f"\n[dim]Updated {len(updated_results)} repositories (too many to show individually)[/dim]")
    else:
        # Output as JSONL
        for result in results:
            print(json.dumps(result, ensure_ascii=False), flush=True)


@catalog_cmd.command("link")
@click.option("-t", "--tag", "tag_filters", multiple=True, help="Tag filters (e.g., org:torvalds, lang:python)")
@click.option("--all", "match_all", is_flag=True, help="Match all tags (default: match any)")
@click.argument("target_dir")
@click.option("--dry-run", is_flag=True, help="Preview without creating links")
@click.option("--pretty", is_flag=True, help="Display results in formatted table")
def catalog_link(tag_filters, match_all, target_dir, dry_run, pretty):
    """
    Create directory with symlinks to repositories matching tag filters.
    
    Examples:
        repoindex catalog link -t lang:python ~/organized/python-projects
        repoindex catalog link -t org:torvalds ~/organized/torvalds
        repoindex catalog link -t type:work -t lang:go --all ~/organized/go-work
        repoindex catalog link -t "org:*" ~/organized/by-org  # Wildcard matching
    """
    config = load_config()
    
    # Get matching repositories
    repos = list(get_repositories_by_tags(tag_filters, config, match_all))
    repo_paths = [r["path"] for r in repos]
    
    if not repo_paths:
        filter_desc = " AND ".join(tag_filters) if match_all else " OR ".join(tag_filters)
        error_msg = {
            "error": f"No repositories found matching: {filter_desc}",
            "type": "catalog_error"
        }
        if pretty:
            console.print(f"[red]✗[/red] {error_msg['error']}")
        else:
            print(json.dumps(error_msg), flush=True)
        return
    
    # Create symlink directory
    result = create_symlink_directory(target_dir, repo_paths, dry_run)
    
    # Add catalog info to result
    result["tag_filters"] = tag_filters
    result["match_all"] = match_all
    result["total_repos"] = len(repo_paths)
    
    if pretty:
        # Display formatted output
        if result.get("created"):
            console.print(f"[green]✓[/green] Created catalog link directory: {target_dir}")
            filter_desc = " AND ".join(tag_filters) if match_all else " OR ".join(tag_filters)
            console.print(f"  Filters: {filter_desc}")
            console.print(f"  Linked repositories: {result['linked_count']}/{result['total_repos']}")
            
            if result.get("errors"):
                console.print("\n[red]Errors:[/red]")
                for error in result["errors"]:
                    console.print(f"  [red]✗[/red] {error}")
        else:
            console.print(f"[red]✗[/red] Failed to create directory: {result.get('error', 'Unknown error')}")
    else:
        print(json.dumps(result, ensure_ascii=False), flush=True)


@catalog_cmd.command("list")
@click.option("--pretty", is_flag=True, help="Display as formatted table")
def catalog_list(pretty):
    """
    List all unique tags and their statistics.
    
    Shows tag keys and values with repository counts.
    """
    from ..tags import parse_tag
    from collections import Counter
    
    config = load_config()
    repo_tags = config.get("repository_tags", {})
    
    if not repo_tags:
        if pretty:
            console.print("[yellow]No repositories have tags. Use 'repoindex get --tag' or 'repoindex catalog tag' to add tags.[/yellow]")
        else:
            print(json.dumps({"tags": {}}), flush=True)
        return
    
    # Collect tag statistics
    tag_counts = Counter()
    tag_key_counts = Counter()
    
    for path, tags in repo_tags.items():
        for tag in tags:
            tag_counts[tag] += 1
            key, value = parse_tag(tag)
            if value is not None:
                tag_key_counts[key] += 1
    
    # Build catalog statistics
    catalog_stats = []
    
    # Add individual tags
    for tag, count in sorted(tag_counts.items()):
        key, value = parse_tag(tag)
        catalog_stats.append({
            "type": "tag",
            "key": key,
            "value": value,
            "tag": tag,
            "repositories": count
        })
    
    if pretty:
        # Create a custom table for tags
        from rich.table import Table
        table = Table(
            title="Repository Tags",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta"
        )
        
        table.add_column("Tag", style="cyan")
        table.add_column("Repositories", style="magenta", justify="right")
        
        # Group by key for better display
        by_key = defaultdict(list)
        for stat in catalog_stats:
            by_key[stat["key"]].append(stat)
        
        for key in sorted(by_key.keys()):
            # Add entries for this key
            for stat in sorted(by_key[key], key=lambda x: x["tag"]):
                table.add_row(stat["tag"], str(stat["repositories"]))
        
        console.print(table)
        
        # Print summary
        console.print("\n[bold]Summary:[/bold]")
        console.print(f"  Total tags: {len(tag_counts)}")
        console.print(f"  Total repositories with tags: {len(repo_tags)}")
        console.print(f"  Tag keys: {', '.join(sorted(tag_key_counts.keys()))}")
    else:
        # Output as JSONL
        for stat in catalog_stats:
            print(json.dumps(stat, ensure_ascii=False), flush=True)


@catalog_cmd.command("show")
@click.option("-t", "--tag", "tag_filters", multiple=True, help="Tag filters (e.g., org:torvalds, lang:python)")
@click.option("--all", "match_all", is_flag=True, help="Match all tags (default: match any)")
@click.option("--pretty", is_flag=True, help="Display as formatted table")
def catalog_show(tag_filters, match_all, pretty):
    """
    Show repositories matching tag filters.
    
    Examples:
        repoindex catalog show -t lang:python
        repoindex catalog show -t org:torvalds
        repoindex catalog show -t type:work -t has:tests --all
        repoindex catalog show -t "topic:*"  # Show all repos with any topic
    """
    config = load_config()
    
    # Default to showing all if no filters
    if not tag_filters:
        tag_filters = ["*"]
    
    # Get matching repositories
    repos = list(get_repositories_by_tags(tag_filters, config, match_all))
    
    if not repos:
        filter_desc = " AND ".join(tag_filters) if match_all else " OR ".join(tag_filters)
        error_msg = {
            "error": f"No repositories found matching: {filter_desc}",
            "type": "catalog_error"
        }
        if pretty:
            console.print(f"[red]✗[/red] {error_msg['error']}")
        else:
            print(json.dumps(error_msg), flush=True)
        return
    
    if pretty:
        # Create table
        from rich.table import Table
        table = Table(
            title=f"Repositories matching: {' AND '.join(tag_filters) if match_all else ' OR '.join(tag_filters)}",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta"
        )
        
        table.add_column("Repository", style="cyan")
        table.add_column("Path", style="dim")
        table.add_column("Tags", style="green")
        
        # Sort by name
        for repo in sorted(repos, key=lambda x: x["name"]):
            table.add_row(
                repo["name"],
                repo["path"],
                ", ".join(repo["tags"]) if repo["tags"] else ""
            )
        
        console.print(table)
        console.print(f"\n[bold]Total repositories:[/bold] {len(repos)}")
    else:
        # Output as JSONL
        for repo in repos:
            print(json.dumps(repo, ensure_ascii=False), flush=True)


@catalog_cmd.command("search")
@click.option("-t", "--tag", "tag_filters", multiple=True, help="Tag filters to search (wildcards supported)")
@click.option("--all", "match_all", is_flag=True, help="Match all tags (default: match any)")
@click.option("--pretty", is_flag=True, help="Display as formatted table")
def catalog_search(tag_filters, match_all, pretty):
    """
    Search for repositories using complex tag queries.
    
    This is an alias for 'catalog show' with the same functionality.
    
    Examples:
        repoindex catalog search -t lang:python -t has:tests
        repoindex catalog search -t org:torvalds -t "stars:100+" --all
        repoindex catalog search -t "topic:*security*"  # Wildcard search
    """
    # Just delegate to catalog show
    from click import Context
    ctx = Context(catalog_show)
    ctx.invoke(catalog_show, tag_filters=tag_filters, match_all=match_all, pretty=pretty, full=False)


@catalog_cmd.command("purge")
@click.option("--dry-run", is_flag=True, help="Show what would be removed without making changes")
@click.option("--yes", is_flag=True, help="Automatically confirm all removals")
@click.option("-t", "--tag", "tag_filters", multiple=True, help="Only purge entries matching these tags")
@click.option("--older-than", type=str, help="Only purge entries older than specified time (e.g., 30d, 1w)")
@click.option("--pretty", is_flag=True, help="Display results in a formatted table")
def catalog_purge(dry_run, yes, tag_filters, older_than, pretty):
    """
    Remove tags for repositories that no longer exist.
    
    This command scans all tagged paths and checks if they still exist as git repositories.
    For missing repositories, it can either prompt for removal or auto-remove with --yes.
    
    Examples:
        repoindex catalog purge                    # Interactive removal
        repoindex catalog purge --dry-run          # Show what would be removed
        repoindex catalog purge --yes              # Remove all without prompting
        repoindex catalog purge -t "project:*"     # Only purge specific tags
    """
    from ..config import load_config, save_config
    from ..utils import is_git_repo
    import click
    
    config = load_config()
    repo_tags = config.get("repository_tags", {})
    
    if not repo_tags:
        if pretty:
            console.print("[yellow]No tagged repositories found.[/yellow]")
        else:
            print(json.dumps({"status": "no_tags", "message": "No tagged repositories found"}), flush=True)
        return
    
    # Find orphaned entries
    orphaned = []
    checked_count = 0
    
    for path, tags in repo_tags.items():
        checked_count += 1
        expanded_path = os.path.expanduser(path)
        
        # Check if it's a git repository
        if not is_git_repo(expanded_path):
            # Check if it's a directory that might contain repos
            if os.path.isdir(expanded_path):
                # Skip directories (they might be parent dirs for tagging)
                continue
            
            # It's missing or not a git repo
            orphaned_entry = {
                "path": path,
                "expanded_path": expanded_path,
                "tags": tags,
                "exists": os.path.exists(expanded_path),
                "is_dir": os.path.isdir(expanded_path) if os.path.exists(expanded_path) else False
            }
            
            # Apply tag filters if specified
            if tag_filters:
                from ..tags import filter_tags
                matches = False
                for tag_filter in tag_filters:
                    if filter_tags(tags, tag_filter):
                        matches = True
                        break
                if not matches:
                    continue
            
            orphaned.append(orphaned_entry)
    
    if not orphaned:
        if pretty:
            console.print("[green]✓[/green] All tagged repositories exist. Nothing to purge.")
        else:
            print(json.dumps({
                "status": "all_exist",
                "checked": checked_count,
                "orphaned": 0
            }), flush=True)
        return
    
    # Display orphaned entries
    if pretty:
        console.print(f"\n[bold]Found {len(orphaned)} orphaned entries:[/bold]\n")
        
        for entry in orphaned:
            status = "[red]Missing[/red]" if not entry["exists"] else "[yellow]Not a git repo[/yellow]"
            console.print(f"{status} {entry['path']}")
            if entry["tags"]:
                console.print(f"  Tags: {', '.join(entry['tags'])}")
            console.print()
    
    if dry_run:
        if pretty:
            console.print(f"[yellow]Dry run:[/yellow] Would remove {len(orphaned)} entries")
        else:
            print(json.dumps({
                "status": "dry_run",
                "would_remove": len(orphaned),
                "entries": [{"path": e["path"], "tags": e["tags"]} for e in orphaned]
            }), flush=True)
        return
    
    # Process removals
    removed_count = 0
    skipped_count = 0
    
    for entry in orphaned:
        path = entry["path"]
        
        # Prompt for confirmation unless --yes is specified
        if not yes:
            if pretty:
                response = click.confirm(f"Remove tags for {path}?", default=True)
            else:
                # In non-pretty mode, skip interactive prompts
                response = True
        else:
            response = True
        
        if response:
            # Remove from config
            del repo_tags[path]
            removed_count += 1
            
            if not pretty:
                print(json.dumps({
                    "action": "removed",
                    "path": path,
                    "tags": entry["tags"]
                }), flush=True)
        else:
            skipped_count += 1
            if not pretty:
                print(json.dumps({
                    "action": "skipped",
                    "path": path,
                    "tags": entry["tags"]
                }), flush=True)
    
    # Save config if changes were made
    if removed_count > 0:
        config["repository_tags"] = repo_tags
        save_config(config)
    
    # Summary
    if pretty:
        console.print("\n[bold]Summary:[/bold]")
        console.print(f"  Checked: {checked_count}")
        console.print(f"  [green]Removed: {removed_count}[/green]")
        console.print(f"  Skipped: {skipped_count}")
        if removed_count > 0:
            console.print("\n[green]✓[/green] Configuration updated")
    else:
        print(json.dumps({
            "status": "complete",
            "checked": checked_count,
            "removed": removed_count,
            "skipped": skipped_count
        }), flush=True)


@catalog_cmd.command("explain")
@click.argument('namespace', required=False)
def catalog_explain(namespace):
    """
    Explain how tags are generated and used.
    
    Without arguments, shows general tag documentation.
    With a namespace argument, shows details for that namespace.
    
    Examples:
        repoindex catalog explain
        repoindex catalog explain lang
        repoindex catalog explain status
    """
    TAG_NAMESPACE_DOCS = {
        "lang": "Programming language detected in the repository",
        "dir": "Parent directory of the repository", 
        "repo": "Repository name",
        "owner": "Repository owner (from remote URL)",
        "host": "Git hosting platform (github, gitlab, etc.)",
        "license": "License type of the repository",
        "topic": "GitHub topics or similar platform topics",
        "status": "Development status (from PyPI classifiers)",
        "audience": "Intended audience (from PyPI classifiers)",
        "environment": "Environment (from PyPI classifiers)",
        "framework": "Framework used (from PyPI classifiers)",
        "natural-language": "Natural language of documentation",
        "os": "Operating system support",
        "programming-language": "Programming language (from PyPI classifiers)",
        "year": "Year of last update or creation",
        "has": "Binary flags (readme, tests, docs, ci, etc.)",
        "package": "Package manager or registry (pypi, npm, etc.)",
        "org": "Organization tag (user-defined)",
        "category": "Category tag (user-defined)",
        "project": "Project grouping (user-defined)",
        "client": "Client association (user-defined)",
        "priority": "Priority level (user-defined)",
        "github": "GitHub-specific metadata",
    }
    
    if namespace:
        # Show specific namespace documentation
        if namespace in TAG_NAMESPACE_DOCS:
            console.print(f"\n[bold]Namespace: {namespace}[/bold]")
            console.print("=" * 50)
            console.print(TAG_NAMESPACE_DOCS[namespace])
            console.print("")
            
            # Add specific examples based on namespace
            if namespace == "lang":
                console.print("[bold]Common values:[/bold]")
                console.print("  - lang:python")
                console.print("  - lang:javascript") 
                console.print("  - lang:rust")
                console.print("  - lang:go")
                console.print("\n[dim]Generated from: Primary language detection in repository files[/dim]")
                
            elif namespace == "status":
                console.print("[bold]Possible values (from PyPI classifiers):[/bold]")
                console.print("  - status:planning")
                console.print("  - status:pre-alpha")
                console.print("  - status:alpha")
                console.print("  - status:beta")
                console.print("  - status:production-stable")
                console.print("  - status:mature")
                console.print("  - status:inactive")
                console.print("\n[dim]Generated from: setup.py or pyproject.toml classifiers[/dim]")
                
            elif namespace == "license":
                console.print("[bold]Common values:[/bold]")
                console.print("  - license:mit")
                console.print("  - license:apache-2.0")
                console.print("  - license:gpl-3.0")
                console.print("  - license:bsd-3-clause")
                console.print("\n[dim]Generated from: LICENSE file in repository[/dim]")
                
            elif namespace == "has":
                console.print("[bold]Binary flags:[/bold]")
                console.print("  - has:readme - Repository has a README file")
                console.print("  - has:tests - Repository has a tests directory")
                console.print("  - has:docs - Repository has documentation")
                console.print("  - has:ci - Repository has CI configuration")
                console.print("  - has:package - Repository is a package")
                console.print("  - has:license - Repository has a license")
                console.print("\n[dim]Generated from: File and directory detection[/dim]")
                
            elif namespace == "github":
                console.print("[bold]GitHub metadata tags:[/bold]")
                console.print("  - github:has:issues - Issues are enabled")
                console.print("  - github:has:wiki - Wiki is enabled")
                console.print("  - github:has:pages - GitHub Pages is enabled")
                console.print("  - github:archived:true - Repository is archived")
                console.print("  - github:fork:true - Repository is a fork")
                console.print("  - github:language:* - Primary language from GitHub")
                console.print("  - github:visibility:* - public/private visibility")
                console.print("\n[dim]Generated from: GitHub API via 'catalog import-github'[/dim]")
                
        else:
            console.print(f"\n[yellow]Namespace '{namespace}' not documented.[/yellow]")
            console.print("\nThis might be a user-defined namespace.")
            console.print("\n[bold]Known namespaces:[/bold]")
            for ns in sorted(TAG_NAMESPACE_DOCS.keys()):
                console.print(f"  - {ns}")
    else:
        # Show general documentation
        console.print("\n[bold]Ghops Tag System[/bold]")
        console.print("=" * 50)
        console.print("""
Tags are generated from multiple sources:

[bold]1. Automatic Tags[/bold] (generated from repository analysis):
   - [cyan]lang:*[/cyan] - Primary programming language
   - [cyan]dir:*[/cyan] - Parent directory name
   - [cyan]repo:*[/cyan] - Repository name
   - [cyan]owner:*[/cyan] - Repository owner from git remote
   - [cyan]host:*[/cyan] - Git hosting platform
   - [cyan]year:*[/cyan] - Year of last modification
   - [cyan]has:readme[/cyan], [cyan]has:tests[/cyan], [cyan]has:docs[/cyan] - Feature detection

[bold]2. License Tags[/bold] (from LICENSE file):
   - [cyan]license:mit[/cyan], [cyan]license:apache-2.0[/cyan], etc.

[bold]3. PyPI Classifier Tags[/bold] (from setup.py/pyproject.toml):
   - [cyan]status:*[/cyan] - Development status
   - [cyan]audience:*[/cyan] - Intended audience  
   - [cyan]environment:*[/cyan] - Environment
   - [cyan]framework:*[/cyan] - Framework
   - [cyan]natural-language:*[/cyan] - Natural language
   - [cyan]os:*[/cyan] - Operating system
   - [cyan]programming-language:*[/cyan] - Language version

[bold]4. Platform Tags[/bold] (from GitHub/GitLab API):
   - [cyan]topic:*[/cyan] - Topics/labels from the platform
   - [cyan]github:*[/cyan] - GitHub-specific metadata

[bold]5. User-Defined Tags[/bold] (from config or catalog):
   - Custom tags without namespaces
   - [cyan]org:*[/cyan], [cyan]category:*[/cyan], [cyan]project:*[/cyan] - Organization tags
   - [cyan]client:*[/cyan], [cyan]priority:*[/cyan] - Custom namespaces
""")
        
        console.print("\n[bold]Available Namespaces:[/bold]")
        console.print("-" * 50)
        for ns, doc in sorted(TAG_NAMESPACE_DOCS.items()):
            console.print(f"  [cyan]{ns:20}[/cyan] - {doc}")
        
        console.print("\n[bold]Using Tags:[/bold]")
        console.print("-" * 50)
        console.print("  Filter by tags:     [dim]repoindex list --tag lang:python[/dim]")
        console.print("  Multiple tags:      [dim]repoindex list --tag lang:python --tag license:mit[/dim]")
        console.print("  Exclude tags:       [dim]repoindex list --tag '!status:inactive'[/dim]")
        console.print("  Wildcard matching:  [dim]repoindex list --tag 'topic:web*'[/dim]")
        console.print("  Query language:     [dim]repoindex list --query \"'python' in tags\"[/dim]")
        console.print("  Catalog commands:   [dim]repoindex catalog show -t lang:python[/dim]")
        
        console.print("\n[dim]For details on a specific namespace:[/dim]")
        console.print("  repoindex catalog explain <namespace>")