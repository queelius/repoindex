"""
Handles the 'clone' command for cloning GitHub repositories.

This command follows our design principles:
- Default output is JSONL streaming
- --pretty flag for human-readable table output
- Core logic returns generators for streaming
- No side effects in core functions
"""

import click
import json
import os
from pathlib import Path
from typing import Generator, Dict, Any, List, Optional

from ..config import load_config, save_config
from ..render import render_get_table
from ..utils import run_command, parse_repo_url
from ..cli_utils import standard_command, add_common_options
from ..exit_codes import NoReposFoundError


def is_path_covered(path: str, repo_dirs: List[str]) -> bool:
    """
    Check if a path is already covered by existing repository directories.
    
    Args:
        path: Path to check
        repo_dirs: List of repository directories from config
        
    Returns:
        True if the path is already covered
    """
    import glob
    path = os.path.abspath(os.path.expanduser(path))
    
    for repo_dir in repo_dirs:
        repo_dir = os.path.abspath(os.path.expanduser(repo_dir))
        
        # Check if it's a glob pattern
        if '*' in repo_dir or '?' in repo_dir or '[' in repo_dir:
            # Check if path matches the glob pattern
            if glob.glob(repo_dir):
                for matched_dir in glob.glob(repo_dir):
                    if path.startswith(os.path.abspath(matched_dir)):
                        return True
        else:
            # Direct path comparison
            if path.startswith(repo_dir):
                return True
    
    return False


def add_directory_to_config(directory: str, config: Dict[str, Any], 
                           tags: List[str] = None,
                           dry_run: bool = False) -> bool:
    """
    Add a directory to the repository directories in config with optional tags.
    
    Args:
        directory: Directory to add
        config: Current configuration
        tags: Optional list of tags for the directory
        dry_run: Whether to simulate the action
        
    Returns:
        True if directory was added (or would be added in dry-run)
    """
    repo_dirs = config.get("general", {}).get("repository_directories", [])
    
    # Check if already covered
    if is_path_covered(directory, repo_dirs):
        return False
    
    if not dry_run:
        # Add the directory
        repo_dirs.append(directory)
        config["general"]["repository_directories"] = repo_dirs
        
        # Add tags if provided
        if tags:
            if "repository_tags" not in config:
                config["repository_tags"] = {}
            config["repository_tags"][directory] = tags
            
            # Update catalogs
            update_catalogs(config, directory, tags)
        
        save_config(config)
    
    return True


def update_catalogs(config: Dict[str, Any], directory: str, tags: List[str]) -> None:
    """
    Update repository catalogs based on tags.
    
    Catalogs organize repositories by tag keys and values.
    """
    from ..tags import parse_tag
    
    if "catalogs" not in config:
        config["catalogs"] = {}
    
    # Build catalogs from tags
    for tag in tags:
        key, value = parse_tag(tag)
        
        # Catalog by full tag
        if "by_tag" not in config["catalogs"]:
            config["catalogs"]["by_tag"] = {}
        if tag not in config["catalogs"]["by_tag"]:
            config["catalogs"]["by_tag"][tag] = []
        if directory not in config["catalogs"]["by_tag"][tag]:
            config["catalogs"]["by_tag"][tag].append(directory)
        
        # Catalog by tag key (for tags with values)
        if value is not None:
            catalog_key = f"by_{key}"
            if catalog_key not in config["catalogs"]:
                config["catalogs"][catalog_key] = {}
            if value not in config["catalogs"][catalog_key]:
                config["catalogs"][catalog_key][value] = []
            if directory not in config["catalogs"][catalog_key][value]:
                config["catalogs"][catalog_key][value].append(directory)


def clone_repository(repo_url: str, target_dir: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Clone a single repository.
    
    Returns a dictionary with clone results following standard schema.
    """
    # Extract repo name from URL
    repo_name = repo_url.split("/")[-1].replace(".git", "")
    repo_path = os.path.join(target_dir, repo_name)
    
    result = {
        "url": repo_url,
        "name": repo_name,
        "path": repo_path,
        "actions": {
            "cloned": False,
            "existed": False,
            "error": None
        },
        "details": {}
    }
    
    # Check if repo already exists
    if os.path.exists(repo_path) and os.path.isdir(os.path.join(repo_path, ".git")):
        result["actions"]["existed"] = True
        result["details"]["message"] = "Repository already exists"
        return result
    
    try:
        if not dry_run:
            # Ensure target directory exists
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            
            # Clone the repository
            clone_output, returncode = run_command(
                f'git clone "{repo_url}" "{repo_name}"',
                cwd=target_dir,
                capture_output=True,
                check=False
            )

            if returncode == 0 and clone_output is not None:
                result["actions"]["cloned"] = True
                result["details"]["clone_output"] = clone_output.strip() if clone_output else "Cloned successfully"
            else:
                result["actions"]["error"] = "Clone command failed"
        else:
            result["actions"]["cloned"] = True
            result["details"]["message"] = "[DRY RUN] Would clone repository"
            
    except Exception as e:
        result["actions"]["error"] = str(e)
        result["error"] = str(e)
        result["type"] = "clone_error"
        result["context"] = {
            "url": repo_url,
            "target_dir": target_dir
        }
    
    return result


def get_user_repositories(username: str, limit: int = 100, 
                         visibility: str = "all", topic_filters: List[str] = None) -> Generator[Dict[str, Any], None, None]:
    """
    Get repositories for a GitHub user or organization.
    
    Yields repository information dictionaries.
    """
    # Use empty string for authenticated user
    user_query = username if username else ""
    
    # Build visibility filter
    visibility_flag = ""
    if visibility != "all":
        visibility_flag = f"--visibility {visibility}"
    
    # Get repositories using gh CLI with topics
    repos_output, returncode = run_command(
        f'gh repo list {user_query} --limit {limit} {visibility_flag} --json nameWithOwner,isPrivate,isFork,description,repositoryTopics',
        capture_output=True,
        check=False
    )

    if returncode != 0 or not repos_output:
        return
    
    try:
        repos_data = json.loads(repos_output)
        for repo in repos_data:
            # Extract topics from repositoryTopics structure
            topics = []
            if repo_topics := repo.get("repositoryTopics"):
                if isinstance(repo_topics, dict) and "nodes" in repo_topics:
                    # New format: {"nodes": [{"topic": {"name": "python"}}]}
                    topics = [node["topic"]["name"] for node in repo_topics["nodes"] if "topic" in node and "name" in node["topic"]]
                elif isinstance(repo_topics, list):
                    # Old format: ["python", "cli"]
                    topics = repo_topics
            
            # Filter by topics if specified
            if topic_filters:
                # Check if repo has any of the requested topics
                has_matching_topic = False
                for filter_topic in topic_filters:
                    # Remove "topic:" prefix if present
                    filter_topic = filter_topic.replace("topic:", "")
                    if filter_topic in topics:
                        has_matching_topic = True
                        break
                
                if not has_matching_topic:
                    continue  # Skip this repo
            
            yield {
                "full_name": repo.get("nameWithOwner", ""),
                "name": repo.get("nameWithOwner", "").split("/")[-1],
                "url": f"https://github.com/{repo.get('nameWithOwner', '')}.git",
                "is_private": repo.get("isPrivate", False),
                "is_fork": repo.get("isFork", False),
                "description": repo.get("description", ""),
                "topics": topics
            }
    except json.JSONDecodeError:
        # Fall back to line-based parsing (can't filter by topics in this case)
        if topic_filters:
            return  # Can't filter without full data
        
        for line in repos_output.strip().split("\n"):
            if line:
                yield {
                    "full_name": line,
                    "name": line.split("/")[-1],
                    "url": f"https://github.com/{line}.git",
                    "is_private": None,
                    "is_fork": None,
                    "description": "",
                    "topics": []
                }


def clone_repositories(repos: List[Dict[str, Any]], target_dir: str, 
                      ignore_list: List[str] = None, dry_run: bool = False) -> Generator[Dict[str, Any], None, None]:
    """
    Clone multiple repositories.
    
    Yields clone results for each repository.
    """
    if ignore_list is None:
        ignore_list = []
    
    for repo in repos:
        repo_name = repo["name"]
        
        # Check ignore list
        if repo_name in ignore_list:
            yield {
                "url": repo["url"],
                "name": repo_name,
                "path": os.path.join(target_dir, repo_name),
                "actions": {
                    "cloned": False,
                    "existed": False,
                    "ignored": True,
                    "error": None
                },
                "details": {
                    "message": "Repository in ignore list"
                }
            }
            continue
        
        # Clone the repository
        result = clone_repository(repo["url"], target_dir, dry_run)
        
        # Add repository metadata
        result["is_private"] = repo.get("is_private")
        result["is_fork"] = repo.get("is_fork")
        result["description"] = repo.get("description")
        result["topics"] = repo.get("topics", [])
        
        yield result


@click.command("clone")
@click.argument("target", required=False)
@click.option("--users", multiple=True, help="GitHub usernames to clone from")
@click.option("-d", "--dir", "target_dir", default=".", help="Target directory for cloning")
@click.option("--ignore", multiple=True, help="Repository names to skip")
@click.option("--limit", default=100, help="Maximum repositories per user")
@click.option("--visibility", type=click.Choice(["all", "public", "private"]), default="all", help="Repository visibility filter")
@click.option("--dry-run", is_flag=True, help="Preview operations without making changes")
@click.option("--table/--no-table", default=None, help="Display as formatted table (auto-detected by default)")
@click.option("--add-to-config", is_flag=True, help="Add cloned directory to repoindex repository directories")
@click.option("--no-add-to-config", is_flag=True, help="Don't add to config (useful if it becomes default)")
@click.option("--tag", "-t", "tags", multiple=True, help="Tags for repositories (e.g., org:torvalds, lang:python)")
@click.option("--import-github-tags", is_flag=True, default=True, help="Import GitHub topics and metadata as tags")
@click.option("--no-import-github-tags", is_flag=True, help="Don't import GitHub metadata")
@add_common_options('verbose', 'quiet')
@standard_command(streaming=True)
def clone_handler(target, users, target_dir, ignore, limit, visibility, dry_run, table,
                 add_to_config, no_add_to_config, tags, import_github_tags, no_import_github_tags,
                 progress, quiet, **kwargs):
    """
    Clone repositories from GitHub.

    TARGET can be:
    - A repository URL to clone a single repo
    - A GitHub username to clone all their repos
    - Omitted to clone repos from the authenticated user

    \\b
    Output format:
    - Interactive terminal: Table format by default
    - Piped/redirected: JSONL streaming by default
    - Use --table to force table output
    - Use --no-table to force JSONL output

    Examples:

    \\b
        repoindex clone torvalds                          # Clone all repos from torvalds
        repoindex clone https://github.com/user/repo.git  # Clone single repo
        repoindex clone --users user1 user2               # Clone from multiple users
        repoindex clone -d ~/projects                     # Clone to specific directory
        repoindex clone --tag org:company --add-to-config # Clone and add to config with tags
    """
    # Auto-detect table mode if not specified
    if table is None:
        import sys
        table = sys.stdout.isatty()
    
    # Expand target directory
    target_dir = os.path.expanduser(target_dir)
    results = []
    all_results = []  # Track all results for config update
    
    # Resolve conflicting flags
    if add_to_config and no_add_to_config:
        raise click.BadParameter("Cannot use both --add-to-config and --no-add-to-config")
    
    # Determine whether to add to config (for now, only if explicitly requested)
    should_add_to_config = add_to_config
    
    # Determine what to clone
    if target and target.startswith(("http://", "https://", "git@")):
        # Single repository URL
        progress(f"Cloning repository from {target}...")
        
        with progress.task("Cloning repository", total=1) as update:
            result = clone_repository(target, target_dir, dry_run)
            all_results.append(result)
            update(1, result.get('name', 'repository'))
            
            if result.get('actions', {}).get('cloned'):
                progress.success(f"Cloned {result['name']} to {result['path']}")
            elif result.get('actions', {}).get('existed'):
                progress.warning(f"Repository {result['name']} already exists")
            elif result.get('error'):
                progress.error(f"Failed to clone: {result['error']}")
            
            if table:
                results.append(result)
            elif not quiet:
                yield result
    else:
        # Clone from users
        usernames = list(users)
        if target and not target.startswith(("http://", "https://", "git@")):
            usernames.append(target)
        
        # If no users specified, use authenticated user
        if not usernames:
            usernames = [""]
        
        # Process each user
        for username in usernames:
            user_display = username if username else "authenticated user"
            
            progress(f"Fetching repositories for {user_display}...")
            
            # Extract topic filters from tags
            topic_filters = [t for t in tags if t.startswith("topic:")]
            
            # Get repositories for user
            repos = list(get_user_repositories(username, limit, visibility, topic_filters))
            
            if not repos:
                error_result = {
                    "user": user_display,
                    "error": "No repositories found",
                    "type": "user_error"
                }
                progress.warning(f"No repositories found for {user_display}")
                if table:
                    results.append(error_result)
                elif not quiet:
                    yield error_result
                continue
            
            progress(f"Found {len(repos)} repositories for {user_display}")
            
            # Clone repositories
            cloned_count = 0
            existed_count = 0
            error_count = 0
            
            with progress.task(f"Cloning from {user_display}", total=len(repos)) as update:
                for i, result in enumerate(clone_repositories(repos, target_dir, ignore, dry_run), 1):
                    result["user"] = user_display
                    all_results.append(result)
                    
                    update(i, result.get('name', 'repository'))
                    
                    # Track stats
                    if result.get('actions', {}).get('cloned'):
                        cloned_count += 1
                    elif result.get('actions', {}).get('existed'):
                        existed_count += 1
                    elif result.get('actions', {}).get('error'):
                        error_count += 1
                        progress.error(f"Failed to clone {result['name']}: {result['actions']['error']}")
                    
                    if table:
                        results.append(result)
                    elif not quiet:
                        yield result
            
            # Show summary for this user
            if cloned_count > 0:
                progress.success(f"Cloned {cloned_count} repositories from {user_display}")
            if existed_count > 0:
                progress(f"Skipped {existed_count} existing repositories")
            if error_count > 0:
                progress.error(f"Failed to clone {error_count} repositories")
    
    # Render table if requested
    if table and results:
        render_get_table(results)
    
    # Resolve conflicting flags for GitHub tag import
    should_import_github = import_github_tags and not no_import_github_tags
    
    # Add to config if requested and we cloned something
    if should_add_to_config:
        # Check if we actually cloned anything
        cloned_any = any(r.get('actions', {}).get('cloned') and not r.get('error') for r in all_results)
        
        if cloned_any:
            config = load_config()
            
            # Build tags list
            final_tags = list(tags)  # Start with user-provided tags
            
            # Auto-detect organization from username if not provided
            first_user = None
            for r in all_results:
                if r.get('user') and r.get('user') != 'authenticated user':
                    first_user = r['user']
                    break
            
            # Add org tag if we have a username
            if first_user and not any(t.startswith('org:') for t in final_tags):
                final_tags.append(f"org:{first_user}")
            
            # Import GitHub topics as tags if enabled
            if should_import_github:
                # Collect all unique topics from cloned repos
                all_topics = set()
                for r in all_results:
                    if r.get('topics'):
                        all_topics.update(r['topics'])
                
                # Add topic tags
                for topic in all_topics:
                    topic_tag = f"topic:{topic}"
                    if topic_tag not in final_tags:
                        final_tags.append(topic_tag)
            
            # Add the target directory to config
            abs_target_dir = os.path.abspath(target_dir)
            added = add_directory_to_config(abs_target_dir, config, final_tags, dry_run)
            
            if added:
                config_msg = {
                    "action": "config_updated",
                    "directory": abs_target_dir,
                    "tags": final_tags,
                    "message": "[DRY RUN] Would add to config" if dry_run else "Added to config"
                }
                if not quiet and not table:
                    yield config_msg
                
                progress.success(f"{config_msg['message']}: {abs_target_dir}")
                if final_tags:
                    progress(f"  Tags: {', '.join(final_tags)}")