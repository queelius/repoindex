import click
from repoindex.config import load_config
from repoindex.utils import find_git_repos, find_git_repos_from_config, get_remote_url, run_command, get_license_info, parse_repo_url
from repoindex.pypi import detect_pypi_package
from repoindex.render import render_list_table
from repoindex.cli_utils import standard_command, add_common_options
from repoindex.exit_codes import NoReposFoundError
from repoindex.metadata import get_metadata_store
import json
import os
import sys
from pathlib import Path


def get_repo_metadata(repo_path, remote_url, skip_github_info=False, skip_pages_check=False, preserve_symlinks=False, use_metadata_store=True):
    """Get basic repository metadata for discovery and filtering."""
    # For the name, always use the resolved path to get consistent names
    repo_name = os.path.basename(str(Path(repo_path).resolve()))

    # For the path, optionally preserve symlinks
    if preserve_symlinks:
        display_path = str(Path(repo_path).absolute())
    else:
        display_path = str(Path(repo_path).resolve())

    # Try to use metadata store first for speed
    if use_metadata_store and not skip_github_info:
        store = get_metadata_store()
        # Try to get by exact path first
        stored_metadata = store.get(repo_path)

        # If not found, try with resolved path
        if not stored_metadata:
            resolved_path = str(Path(repo_path).resolve())
            if resolved_path != repo_path:
                stored_metadata = store.get(resolved_path)
        if stored_metadata:
            # Use stored metadata but adapt to list command format
            metadata = {
                "name": repo_name,
                "path": display_path,
                "remote_url": stored_metadata.get("remote_url") or remote_url,
                "has_license": bool(stored_metadata.get("license")),
                "has_package": False,  # Will check below
                "github": None
            }

            # Check for package indicators in metadata
            # The metadata store doesn't have "package_type", so we check for typical package files
            # that would have been detected during metadata refresh
            if (stored_metadata.get("has_readme") and
                any(pkg_indicator in stored_metadata.get("readme_content", "").lower()
                    for pkg_indicator in ["pypi", "npm", "crates.io", "packagist"])):
                metadata["has_package"] = True
            # Or check if it's a known language with typical package managers
            elif stored_metadata.get("language") in ["Python", "JavaScript", "TypeScript", "Rust", "Go", "PHP", "Ruby"]:
                # Assume repos in these languages likely have packages - this is a heuristic
                # The slow check would be to look at the filesystem, which we're avoiding
                pass

            # Add GitHub info if available (provider == 'github')
            if stored_metadata.get("provider") == "github":
                github_info = {
                    "is_private": stored_metadata.get("private", False),
                    "is_fork": stored_metadata.get("fork", False)
                }

                # Add pages URL if available
                if not skip_pages_check:
                    if stored_metadata.get("has_pages"):
                        # Construct GitHub Pages URL
                        owner = stored_metadata.get("owner")
                        repo = stored_metadata.get("repo")
                        if owner and repo:
                            github_info["pages_url"] = f"https://{owner}.github.io/{repo}"
                    else:
                        github_info["pages_url"] = None

                metadata["github"] = github_info

            return metadata

    # Fallback to original logic if metadata store not available or skipped
    metadata = {
        "name": repo_name,
        "path": display_path,
        "remote_url": remote_url,
        "has_license": False,
        "has_package": False,
        "github": None
    }
    
    # Quick license check (just existence)
    license_files = ['LICENSE', 'LICENSE.txt', 'LICENSE.md', 'LICENCE', 'LICENCE.txt', 'LICENCE.md']
    for lf in license_files:
        if (Path(repo_path) / lf).exists():
            metadata["has_license"] = True
            break
    
    # Quick package check (just existence)
    package_files = ['pyproject.toml', 'setup.py', 'setup.cfg', 'package.json', 'Cargo.toml', 'go.mod']
    for pf in package_files:
        if (Path(repo_path) / pf).exists():
            metadata["has_package"] = True
            break
    
    # If it's a GitHub repo, try to get basic info (unless skipped)
    if not skip_github_info and remote_url and ("github.com" in remote_url or "github" in remote_url.lower()):
        # Cache imports removed
        from ..utils import parse_repo_url
        
        owner, repo_name_parsed = parse_repo_url(remote_url) if remote_url else (None, None)
        
        # Cache removed - go directly to GitHub CLI
        if owner and repo_name_parsed:
            try:
                # Use GitHub CLI to get basic repo info
                repo_info, _ = run_command(
                    "gh repo view --json name,stargazerCount,description,primaryLanguage,isPrivate,isFork,forkCount", 
                    cwd=repo_path, 
                    capture_output=True, 
                    check=False,
                    log_stderr=False
                )
                if repo_info and repo_info.strip():
                    github_data = json.loads(repo_info)
                    primary_lang = github_data.get("primaryLanguage")
                    metadata["github"] = {
                        "is_private": github_data.get("isPrivate", False),
                        "is_fork": github_data.get("isFork", False)
                    }
                    
                    # Cache call removed
                
                # Check for GitHub Pages
                if not skip_pages_check:
                    if owner and repo_name_parsed:
                        # Cache removed - go directly to GitHub API
                            pages_result, _ = run_command(
                                f"gh api repos/{owner}/{repo_name_parsed}/pages",
                                capture_output=True,
                                check=False,
                                log_stderr=False
                            )
                            if pages_result:
                                try:
                                    pages_data = json.loads(pages_result)
                                    metadata["github"]["pages_url"] = pages_data.get('html_url')
                                    # Cache call removed
                                except json.JSONDecodeError:
                                    # Cache call removed
                                    pass
                            else:
                                # Cache call removed
                                pass
            except (json.JSONDecodeError, Exception):
                # If GitHub CLI fails, just mark as GitHub repo without details
                metadata["github"] = {
                    "is_private": None,
                    "is_fork": None
                }
    
    # If GitHub info was skipped or Pages check was not skipped, try local detection
    if skip_github_info or not skip_pages_check:
        from ..utils import detect_github_pages_locally
        pages_info = detect_github_pages_locally(repo_path)
        if pages_info and pages_info.get('likely_enabled'):
            if metadata.get("github") is None:
                metadata["github"] = {}
            # Only set pages_url if we don't already have it from API
            if not metadata["github"].get("pages_url"):
                metadata["github"]["pages_url"] = pages_info.get('pages_url')
    
    return metadata


@click.command("list")
@click.option("-d", "--dir", help="[DEPRECATED] Use: repoindex fs ls /repos or repoindex status /")
@click.option("--recursive", is_flag=True, help="Search subdirectories for git repos")
@click.option("--no-dedup", is_flag=True, help="Show all instances including duplicates and soft links")
@click.option("--no-github", is_flag=True, help="Skip GitHub API calls for faster listing")
@click.option("--no-pages", is_flag=True, help="Skip GitHub Pages check for faster results")
@click.option("-t", "--tag", "tag_filters", multiple=True, help="[DEPRECATED] Use VFS paths like: repoindex fs ls /by-tag/work")
@click.option("--all-tags", is_flag=True, help="Match all tags (default: match any)")
@click.option("--table/--no-table", default=None, help="Display as formatted table (auto-detected by default)")
@add_common_options('verbose', 'quiet', 'format', 'fields')
@standard_command(streaming=True)
def list_repos_handler(dir, recursive, no_dedup, no_github, no_pages, tag_filters, all_tags, table, format, fields, progress, quiet, **kwargs):
    """
    [DEPRECATED] List available repositories.

    ⚠️  This command is deprecated. Use instead:
    - repoindex fs ls -l /            For list with metadata
    - repoindex status /              For comprehensive status
    - repoindex fs ls /by-tag/work    For tagged repos

    \b
    This command still works but will be removed in a future version.

    Examples:

    \b
        # OLD (deprecated):
        repoindex list
        repoindex list -t lang:python
        repoindex list -d ~/projects

        # NEW (recommended):
        repoindex fs ls -l /
        repoindex fs ls /by-language/Python
        repoindex status /
    """
    import sys
    print("⚠️  Warning: 'repoindex list' is deprecated.", file=sys.stderr)
    print("   Use 'repoindex fs ls -l /' for fast listing with metadata", file=sys.stderr)
    print("   Or 'repoindex status /' for comprehensive status", file=sys.stderr)
    print(file=sys.stderr)
    config = load_config()
    
    # Auto-detect table mode if not specified
    if table is None:
        import sys
        table = sys.stdout.isatty()  # Use table format for interactive terminals
    
    progress("Discovering repositories...")
    
    # Get repository paths
    repo_paths = []
    if dir:
        # Use specified directory (same logic as status command)
        from ..utils import is_git_repo
        expanded_dir = os.path.expanduser(dir)
        expanded_dir = os.path.abspath(expanded_dir)
        
        if is_git_repo(expanded_dir) and not recursive:
            # Directory itself is a repo
            repo_paths = [expanded_dir]
        else:
            # Search in directory
            repo_paths = find_git_repos(expanded_dir, recursive)
    else:
        # Use config
        config_dirs = config.get("general", {}).get("repository_directories", ["~/github"])
        repo_paths = find_git_repos_from_config(config_dirs, recursive)

    # Remove duplicates that might arise from overlapping config paths
    repos = sorted(list(set(repo_paths)))

    if not repos:
        raise NoReposFoundError("No repositories found in specified directories")
    
    progress(f"Found {len(repos)} repositories")

    # Check metadata store coverage and warn if low
    if not no_github:
        try:
            store = get_metadata_store()
            in_store = sum(1 for r in repos if store.get(r) or store.get(str(Path(r).resolve())))
            coverage = (in_store / len(repos)) * 100 if repos else 0

            if coverage < 50:
                import sys
                print(f"⚠️  Metadata coverage: {coverage:.0f}% ({in_store}/{len(repos)} repos)", file=sys.stderr)
                print(f"   For faster results, refresh metadata: repoindex metadata refresh --github", file=sys.stderr)
                print(f"   Or skip GitHub info: repoindex list --no-github", file=sys.stderr)
        except Exception:
            pass  # Don't fail if metadata check fails

    # Apply tag filtering if specified
    if tag_filters:
        from ..tags import filter_tags
        from ..commands.catalog import get_repositories_by_tags
        
        progress("Applying tag filters...")
        
        # Get filtered repos
        filtered_repos = list(get_repositories_by_tags(tag_filters, config, all_tags))
        filtered_paths = {str(Path(r["path"]).resolve()) for r in filtered_repos}
        
        # Filter the discovered repos
        repos = [r for r in repos if str(Path(r).resolve()) in filtered_paths]
        
        if not repos:
            filter_desc = " AND ".join(tag_filters) if all_tags else " OR ".join(tag_filters)
            raise NoReposFoundError(f"No repositories found matching: {filter_desc}")
        
        progress(f"Filtered to {len(repos)} repositories")

    # Handle table format (either explicit --table or --format table)
    if table or format == 'table':
        # Collect all repos and render as table
        all_repos = []
        with progress.task("Gathering repository information", total=len(repos)) as update:
            if no_dedup:
                # Show all instances without deduplication
                for i, repo_path in enumerate(repos, 1):
                    update(i, os.path.basename(repo_path))
                    remote_url = get_remote_url(repo_path)
                    metadata = get_repo_metadata(repo_path, remote_url, skip_github_info=no_github, skip_pages_check=no_pages, preserve_symlinks=True)
                    all_repos.append(metadata)
            else:
                # Default: Collect deduplicated repos with detail
                for i, repo_data in enumerate(_collect_deduplicated_repos(repos, include_details=True, skip_github_info=no_github, skip_pages_check=no_pages), 1):
                    update(i, repo_data.get('name', ''))
                    all_repos.append(repo_data)
        
        # Render as table (not suppressed by quiet)
        render_list_table(all_repos)
    else:
        # Stream JSONL output (default)
        with progress.task("Gathering repository information", total=len(repos)) as update:
            repo_count = 0
            if no_dedup:
                # Stream all instances without deduplication
                for repo_path in repos:
                    repo_count += 1
                    update(repo_count, os.path.basename(repo_path))
                    remote_url = get_remote_url(repo_path)
                    metadata = get_repo_metadata(repo_path, remote_url, skip_github_info=no_github, skip_pages_check=no_pages, preserve_symlinks=True)
                    if not quiet:
                        yield metadata
            else:
                # Default: Stream deduplicated repos with details
                for repo_data in _collect_deduplicated_repos(repos, include_details=True, skip_github_info=no_github, skip_pages_check=no_pages):
                    repo_count += 1
                    update(repo_count, repo_data.get('name', ''))
                    if not quiet:
                        yield repo_data


def _collect_deduplicated_repos(repo_paths, include_details, skip_github_info=False, skip_pages_check=False):
    """Collect deduplicated repositories with basic metadata (generator)."""
    remotes = {}
    for repo_path in repo_paths:
        remote_url = get_remote_url(repo_path)
        if remote_url:
            if remote_url not in remotes:
                remotes[remote_url] = []
            remotes[remote_url].append(repo_path)

    if not include_details:
        # Yield unique repos (first occurrence of each remote) with metadata
        for remote_url, paths in remotes.items():
            primary_path = paths[0]
            metadata = get_repo_metadata(primary_path, remote_url, skip_github_info, skip_pages_check)
            metadata["duplicate_count"] = len(paths)
            metadata["duplicate_paths"] = [str(Path(p).resolve()) for p in paths[1:]] if len(paths) > 1 else []
            yield metadata
    else:
        # Yield detailed deduplication info with metadata
        for remote_url, paths in remotes.items():
            # Group paths by inode to detect links vs true duplicates
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

            # Yield each inode group with metadata
            for inode, data in inodes.items():
                sorted_links = sorted(data["links"])
                is_duplicate = len(inodes) > 1  # True duplicate if multiple inodes for same remote
                
                metadata = get_repo_metadata(sorted_links[0], remote_url, skip_github_info, skip_pages_check)
                metadata.update({
                    "primary_path": data["primary"],
                    "all_paths": sorted_links,
                    "is_linked": len(sorted_links) > 1,
                    "is_true_duplicate": is_duplicate
                })
                yield metadata


def _stream_deduplicated_repos(repo_paths, include_details, skip_github_info=False, skip_pages_check=False):
    """Stream deduplicated repositories as JSONL with basic metadata."""
    remotes = {}
    for repo_path in repo_paths:
        remote_url = get_remote_url(repo_path)
        if remote_url:
            if remote_url not in remotes:
                remotes[remote_url] = []
            remotes[remote_url].append(repo_path)

    if not include_details:
        # Stream unique repos (first occurrence of each remote) with metadata
        for remote_url, paths in remotes.items():
            primary_path = paths[0]
            metadata = get_repo_metadata(primary_path, remote_url, skip_github_info, skip_pages_check)
            metadata["duplicate_count"] = len(paths)
            metadata["duplicate_paths"] = [str(Path(p).resolve()) for p in paths[1:]] if len(paths) > 1 else []
            print(json.dumps(metadata), flush=True)
    else:
        # Stream detailed deduplication info with metadata
        for remote_url, paths in remotes.items():
            # Group paths by inode to detect links vs true duplicates
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

            # Stream each inode group with metadata
            for inode, data in inodes.items():
                sorted_links = sorted(data["links"])
                is_duplicate = len(inodes) > 1  # True duplicate if multiple inodes for same remote
                
                metadata = get_repo_metadata(sorted_links[0], remote_url, skip_github_info, skip_pages_check)
                metadata.update({
                    "primary_path": data["primary"],
                    "all_paths": sorted_links,
                    "is_linked": len(sorted_links) > 1,
                    "is_true_duplicate": is_duplicate
                })
                print(json.dumps(metadata), flush=True)

