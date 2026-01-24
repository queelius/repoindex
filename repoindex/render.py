"""
Rendering functions for repoindex output.

This module handles all pretty-printing and table formatting.
Core functions return data, this module makes it human-readable.
"""

from rich.table import Table
from rich.console import Console
from rich import box
from typing import List, Dict, Any, Optional
from pathlib import Path

console = Console()


def render_table(headers: List[str], rows: List[List[str]], title: Optional[str] = None) -> None:
    """
    Render a generic table with the given headers and rows.
    
    Args:
        headers: List of column headers
        rows: List of rows, where each row is a list of values
        title: Optional table title
    """
    if not rows:
        console.print("[yellow]No data to display.[/yellow]")
        return
    
    # Create table
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Add columns
    for header in headers:
        table.add_column(header)
    
    # Add rows
    for row in rows:
        table.add_row(*[str(val) for val in row])
    
    console.print(table)


def render_status_table(repos: List[Dict[str, Any]]) -> None:
    """
    Render repository status as a pretty table.
    
    Args:
        repos: List of repository status dictionaries
    """
    if not repos:
        console.print("[yellow]No repositories found.[/yellow]")
        return
    
    # Filter out error objects
    errors = [r for r in repos if 'error' in r]
    repos = [r for r in repos if 'error' not in r]
    
    # Create table
    table = Table(
        title="Repository Status",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Add columns
    table.add_column("Repository", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Git", style="green")  # Combined branch/ahead/behind
    table.add_column("Status", style="yellow")
    table.add_column("License", style="blue")
    table.add_column("Package", style="magenta")
    
    # Add rows
    for repo in sorted(repos, key=lambda x: x['name']):
        status = repo.get('status', {})
        
        # Status symbols
        status_parts = []
        if status.get('uncommitted_changes'):
            status_parts.append("📝")
        if status.get('unpushed_commits'):
            status_parts.append("📤")
        
        status_str = " ".join(status_parts) if status_parts else "✅"
        
        # License display
        license_display = ""
        if 'license' in repo:
            license_display = repo['license'].get('type', 'Unknown')
        
        # Package display
        package_display = ""
        if 'package' in repo:
            pkg = repo['package']
            package_display = pkg.get('name', '')
            if pkg.get('outdated'):
                package_display += " ⚠️"
        
        # Pages display (computed for future use)
        _pages_display = ""  # noqa: F841 - reserved for future table column
        if 'github' in repo and repo['github'].get('pages_url'):
            _pages_display = "📄"
        
        # Path display with deduplication info
        path_display = repo.get('path', 'N/A')
        if path_display != 'N/A':
            p = Path(path_display)
            path_display = f"{p.parent.name}/{p.name}"
            
            # Add deduplication indicators
            if 'all_paths' in repo and len(repo['all_paths']) > 1:
                if repo.get('is_linked'):
                    path_display += f" (+{len(repo['all_paths'])-1} links)"
                elif repo.get('is_true_duplicate'):
                    path_display += f" (+{len(repo['all_paths'])-1} dups)"
            elif repo.get('is_true_duplicate'):
                path_display += " (duplicate)"
        
        # Combined git status: branch +ahead/-behind
        git_display = status.get('branch', 'N/A')
        ahead = status.get('ahead', 0)
        behind = status.get('behind', 0)
        if ahead > 0 or behind > 0:
            git_display += " "
            if ahead > 0:
                git_display += f"+{ahead}"
            if behind > 0:
                if ahead > 0:
                    git_display += "/"
                git_display += f"-{behind}"
        
        # Add GitHub Pages icon to repository name if present
        repo_name_display = repo['name']
        if 'github' in repo and repo['github'].get('pages_url'):
            repo_name_display += " 🔗"
        
        # Build row
        table.add_row(
            repo_name_display,
            path_display,
            git_display,
            status_str,
            license_display,
            package_display
        )
    
    console.print(table)
    
    # Print errors if any
    if errors:
        console.print("\n[red]Errors:[/red]")
        for error in errors:
            console.print(f"  [red]✗[/red] {error['context']['path']}: {error['error']}")
    
    # Print summary
    print_status_summary(repos)


def print_status_summary(repos: List[Dict[str, Any]]) -> None:
    """Print summary statistics for repository status."""
    total = len(repos)
    if total == 0:
        return
    
    # Calculate statistics
    uncommitted = sum(1 for r in repos if r.get('status', {}).get('uncommitted_changes'))
    unpushed = sum(1 for r in repos if r.get('status', {}).get('unpushed_commits'))
    behind = sum(1 for r in repos if r.get('status', {}).get('behind', 0) > 0)
    ahead = sum(1 for r in repos if r.get('status', {}).get('ahead', 0) > 0)
    licensed = sum(1 for r in repos if 'license' in r)
    with_packages = sum(1 for r in repos if 'package' in r)
    pages_enabled = sum(1 for r in repos if r.get('github', {}).get('pages_url'))
    
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Total repositories: {total}")
    
    if uncommitted:
        console.print(f"  [yellow]Uncommitted changes: {uncommitted}[/yellow]")
    if unpushed:
        console.print(f"  [yellow]Unpushed commits: {unpushed}[/yellow]")
    if behind:
        console.print(f"  [red]Behind upstream: {behind}[/red]")
    if ahead:
        console.print(f"  [green]Ahead of upstream: {ahead}[/green]")
    
    console.print(f"  Licensed: {licensed}/{total}")
    
    if with_packages:
        outdated = sum(1 for r in repos if r.get('package', {}).get('outdated'))
        console.print(f"  Packages: {with_packages}")
        if outdated:
            console.print(f"  [yellow]Outdated packages: {outdated}[/yellow]")
    
    if pages_enabled:
        console.print(f"  GitHub Pages enabled: {pages_enabled}")


def render_social_media_posts(posts: List[Dict[str, Any]], as_json: bool = False) -> None:
    """
    Render social media posts for preview.
    
    Args:
        posts: List of post dictionaries
        as_json: Whether to output as JSON
    """
    import json
    
    if as_json:
        print(json.dumps(posts, indent=2, ensure_ascii=False))
        return
    
    if not posts:
        console.print("[yellow]No posts generated.[/yellow]")
        return
    
    for i, post in enumerate(posts, 1):
        console.print(f"\n[bold cyan]Post {i}:[/bold cyan]")
        console.print(f"[bold]Repository:[/bold] {post.get('repo_name', 'Unknown')}")
        console.print(f"[bold]URL:[/bold] {post.get('url', 'N/A')}")
        
        # Show content for each platform
        for platform, content in post.get('platforms', {}).items():
            console.print(f"\n[bold green]{platform.title()}:[/bold green]")
            console.print(content)
            
        if post.get('tags'):
            console.print(f"\n[bold]Tags:[/bold] {' '.join(post['tags'])}")


def render_list_table(repos: List[Dict[str, Any]]) -> None:
    """
    Render repository list as a pretty table.
    
    Args:
        repos: List of repository dictionaries
    """
    if not repos:
        console.print("[yellow]No repositories found.[/yellow]")
        return
    
    # Create table
    table = Table(
        title="Repository List",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Add columns
    table.add_column("Repository", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("License", style="green", justify="center")
    table.add_column("Package", style="blue", justify="center")
    table.add_column("Type", style="yellow")
    table.add_column("Pages", style="cyan", justify="center", width=5)
    table.add_column("Remote URL", style="dim")
    
    # Add rows
    for repo in sorted(repos, key=lambda x: x['name']):
        # License indicator
        license_indicator = "✓" if repo.get('has_license') else "✗"
        license_style = "green" if repo.get('has_license') else "red"
        
        # Package indicator
        package_indicator = "✓" if repo.get('has_package') else "✗"
        package_style = "green" if repo.get('has_package') else "red"
        
        # Repository type
        repo_type = []
        github_info = repo.get('github') or {}
        if github_info.get('is_private') is True:
            repo_type.append("🔒 Private")
        elif github_info.get('is_private') is False:
            # Only show Public if we explicitly know it's public
            pass
        if github_info.get('is_fork'):
            repo_type.append("🔱 Fork")
        
        # Default type string based on what we know
        if repo_type:
            type_str = " ".join(repo_type)
        elif github_info.get('is_private') is False:
            type_str = "Public"
        else:
            type_str = "Unknown"
        
        # Get remote URL
        remote_url = repo.get('remote_url', 'N/A')
        
        # Handle path display - check for dedup details first
        if 'all_paths' in repo:
            # Dedup details mode - show all paths
            paths = repo['all_paths']
            _primary_path = repo.get('primary_path', paths[0])  # noqa: F841 - for debugging
            
            if len(paths) > 1:
                # Multiple paths - show the first path (which is usually the real one)
                # The paths are sorted, so we get consistent display
                display_path = paths[0]
                p = Path(display_path)
                path = f"{p.parent.name}/{p.name}"
                
                if repo.get('is_linked'):
                    path += f" (+{len(paths)-1} links)"
                elif repo.get('is_true_duplicate'):
                    path += f" (+{len(paths)-1} dups)"
            else:
                # Single path - but might still be a true duplicate
                p = Path(paths[0])
                path = f"{p.parent.name}/{p.name}"
                if repo.get('is_true_duplicate'):
                    path += " (duplicate)"
        elif 'duplicate_count' in repo and repo['duplicate_count'] > 1:
            # Regular dedup mode - show duplicate count
            path = repo.get('path', 'N/A')
            if path != 'N/A':
                p = Path(path)
                path = f"{p.parent.name}/{p.name} (+{repo['duplicate_count']-1} dups)"
        else:
            # Regular mode - show single path
            path = repo.get('path', 'N/A')
            if path != 'N/A':
                p = Path(path)
                # Show parent/name format
                path = f"{p.parent.name}/{p.name}"
        
        # GitHub Pages indicator
        pages_indicator = ""
        github_info = repo.get('github') or {}
        if github_info.get('pages_url'):
            pages_indicator = "🔗"
        
        table.add_row(
            repo['name'],
            path,
            f"[{license_style}]{license_indicator}[/{license_style}]",
            f"[{package_style}]{package_indicator}[/{package_style}]",
            type_str,
            pages_indicator,
            remote_url
        )
    
    console.print(table)
    
    # Print summary
    # Count actual unique repos (considering true duplicates)
    unique_repos = set()
    for repo in repos:
        unique_repos.add((repo['name'], repo.get('remote_url', '')))
    total = len(unique_repos)
    with_license = sum(1 for r in repos if r.get('has_license'))
    with_package = sum(1 for r in repos if r.get('has_package'))
    private_count = sum(1 for r in repos if (r.get('github') or {}).get('is_private'))
    fork_count = sum(1 for r in repos if (r.get('github') or {}).get('is_fork'))
    
    # Count duplicates and links
    linked_count = sum(1 for r in repos if r.get('is_linked'))
    dup_count = sum(1 for r in repos if r.get('is_true_duplicate'))
    dedup_count = sum(1 for r in repos if r.get('duplicate_count', 1) > 1)
    
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Total repositories: {total}")
    console.print(f"  With license: {with_license} ({with_license*100//total if total else 0}%)")
    console.print(f"  With package: {with_package} ({with_package*100//total if total else 0}%)")
    if private_count:
        console.print(f"  Private: {private_count}")
    if fork_count:
        console.print(f"  Forks: {fork_count}")
    if linked_count:
        console.print(f"  Linked (soft links): {linked_count}")
    if dup_count:
        console.print(f"  True duplicates: {dup_count}")
    if dedup_count:
        console.print(f"  Deduplicated: {dedup_count}")


def render_cache_stats_table(stats: Dict[str, Any]) -> None:
    """
    Render cache statistics as a formatted table.
    
    Args:
        stats: Dictionary containing cache statistics
    """
    # Overview table
    overview_table = Table(title="Cache Overview", box=box.ROUNDED)
    overview_table.add_column("Metric", style="bold cyan")
    overview_table.add_column("Value", justify="right")
    
    overview_table.add_row("Cache Directory", stats.get('cache_dir', 'N/A'))
    overview_table.add_row("Total Entries", str(stats.get('total_entries', 0)))
    overview_table.add_row("Active Entries", f"[green]{stats.get('active_entries', 0)}[/green]")
    overview_table.add_row("Expired Entries", f"[red]{stats.get('expired_entries', 0)}[/red]")
    overview_table.add_row("Total Size", f"{stats.get('total_size_mb', 0)} MB")
    
    if stats.get('oldest_entry_date'):
        overview_table.add_row("Oldest Entry", stats['oldest_entry_date'])
    if stats.get('newest_entry_date'):
        overview_table.add_row("Newest Entry", stats['newest_entry_date'])
    
    console.print(overview_table)
    
    # Entries by type table
    if stats.get('entries_by_type'):
        console.print()
        type_table = Table(title="Entries by Type", box=box.SIMPLE)
        type_table.add_column("Type", style="bold")
        type_table.add_column("Count", justify="right")
        
        for entry_type, count in sorted(stats['entries_by_type'].items()):
            type_table.add_row(entry_type.title(), str(count))
        
        console.print(type_table)


def render_update_table(updates: List[Dict[str, Any]]) -> None:
    """
    Render repository update results as a pretty table.
    
    Args:
        updates: List of update result dictionaries
    """
    if not updates:
        console.print("[yellow]No repositories found.[/yellow]")
        return
    
    # Filter out errors for separate display
    errors = [u for u in updates if u.get('error')]
    updates_ok = [u for u in updates if not u.get('error')]
    
    # Create table
    table = Table(
        title="Repository Updates",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Add columns
    table.add_column("Repository", style="cyan")
    table.add_column("Committed", style="green", justify="center")
    table.add_column("Pulled", style="blue", justify="center")
    table.add_column("Pushed", style="magenta", justify="center")
    table.add_column("Status", style="yellow")
    table.add_column("Details", style="dim")
    
    # Add rows
    for update in sorted(updates_ok, key=lambda x: x['name']):
        actions = update.get('actions', {})
        
        # Status symbols
        committed = "✓" if actions.get('committed') else "-"
        pulled = "✓" if actions.get('pulled') else "-"
        pushed = "✓" if actions.get('pushed') else "-"
        
        # Overall status
        if actions.get('conflicts'):
            status = "⚠️ Conflicts"
            status_color = "red"
        elif actions.get('pulled') or actions.get('committed'):
            status = "✅ Updated"
            status_color = "green"
        else:
            status = "⏭️ Up to date"
            status_color = "dim"
        
        # Details summary
        details = []
        if actions.get('committed'):
            msg = update.get('details', {}).get('commit_message', '')
            if msg:
                details.append(f"Committed: {msg[:30]}...")
        if actions.get('pulled'):
            details.append("Pulled changes")
        if actions.get('conflicts'):
            details.append("Has conflicts")
        
        details_str = "; ".join(details) if details else "No changes"
        
        table.add_row(
            update['name'],
            committed,
            pulled,
            pushed,
            f"[{status_color}]{status}[/{status_color}]",
            details_str
        )
    
    console.print(table)
    
    # Print errors if any
    if errors:
        console.print("\n[red]Errors:[/red]")
        for error in errors:
            console.print(f"  [red]✗[/red] {error['name']}: {error['error']}")
    
    # Print summary
    print_update_summary(updates)


def print_update_summary(updates: List[Dict[str, Any]]) -> None:
    """Print summary statistics for repository updates."""
    total = len(updates)
    if total == 0:
        return
    
    # Calculate statistics
    committed = sum(1 for u in updates if u.get('actions', {}).get('committed'))
    pulled = sum(1 for u in updates if u.get('actions', {}).get('pulled'))
    pushed = sum(1 for u in updates if u.get('actions', {}).get('pushed'))
    conflicts = sum(1 for u in updates if u.get('actions', {}).get('conflicts'))
    errors = sum(1 for u in updates if u.get('error'))
    up_to_date = total - pulled - errors
    
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Total repositories: {total}")
    console.print(f"  Up to date: {up_to_date}")
    
    if committed:
        console.print(f"  [green]Committed: {committed}[/green]")
    if pulled:
        console.print(f"  [blue]Pulled: {pulled}[/blue]")
    if pushed:
        console.print(f"  [magenta]Pushed: {pushed}[/magenta]")
    if conflicts:
        console.print(f"  [red]Conflicts: {conflicts}[/red]")
    if errors:
        console.print(f"  [red]Errors: {errors}[/red]")


def render_get_table(results: List[Dict[str, Any]]) -> None:
    """
    Render repository clone results as a pretty table.
    
    Args:
        results: List of clone result dictionaries
    """
    if not results:
        console.print("[yellow]No operations performed.[/yellow]")
        return
    
    # Filter out errors for separate display
    errors = [r for r in results if r.get('error') or r.get('type') == 'user_error']
    results_ok = [r for r in results if not r.get('error') and r.get('type') != 'user_error']
    
    if results_ok:
        # Create table
        table = Table(
            title="Repository Clone Results",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta"
        )
        
        # Add columns
        table.add_column("Repository", style="cyan")
        table.add_column("User", style="blue")
        table.add_column("Status", style="yellow")
        table.add_column("Type", style="dim")
        table.add_column("Path", style="dim")
        
        # Add rows
        for result in sorted(results_ok, key=lambda x: (x.get('user', ''), x.get('name', ''))):
            actions = result.get('actions', {})
            
            # Status
            if actions.get('ignored'):
                status = "⏭️ Ignored"
                status_color = "dim"
            elif actions.get('existed'):
                status = "📁 Exists"
                status_color = "yellow"
            elif actions.get('cloned'):
                status = "✅ Cloned"
                status_color = "green"
            else:
                status = "❌ Failed"
                status_color = "red"
            
            # Repository type
            repo_type = []
            if result.get('is_private'):
                repo_type.append("🔒")
            if result.get('is_fork'):
                repo_type.append("🔱")
            type_str = " ".join(repo_type) if repo_type else "Public"
            
            # Path display
            path = result.get('path', '')
            if path:
                path = f".../{Path(path).parent.name}/{Path(path).name}"
            
            table.add_row(
                result.get('name', 'Unknown'),
                result.get('user', ''),
                f"[{status_color}]{status}[/{status_color}]",
                type_str,
                path
            )
        
        console.print(table)
    
    # Print errors if any
    if errors:
        console.print("\n[red]Errors:[/red]")
        for error in errors:
            if error.get('type') == 'user_error':
                console.print(f"  [red]✗[/red] User '{error.get('user', 'Unknown')}': {error.get('error', 'Unknown error')}")
            else:
                console.print(f"  [red]✗[/red] {error.get('name', 'Unknown')}: {error.get('error', 'Unknown error')}")
    
    # Print summary
    print_get_summary(results)


def print_get_summary(results: List[Dict[str, Any]]) -> None:
    """Print summary statistics for repository cloning."""
    total = len([r for r in results if r.get('type') != 'user_error'])
    if total == 0 and not any(r.get('type') == 'user_error' for r in results):
        return
    
    # Calculate statistics
    cloned = sum(1 for r in results if r.get('actions', {}).get('cloned') and not r.get('error'))
    existed = sum(1 for r in results if r.get('actions', {}).get('existed'))
    ignored = sum(1 for r in results if r.get('actions', {}).get('ignored'))
    errors = sum(1 for r in results if r.get('error') and r.get('type') != 'user_error')
    user_errors = sum(1 for r in results if r.get('type') == 'user_error')
    
    console.print("\n[bold]Summary:[/bold]")
    if total > 0:
        console.print(f"  Total repositories: {total}")
        if cloned:
            console.print(f"  [green]Cloned: {cloned}[/green]")
        if existed:
            console.print(f"  [yellow]Already existed: {existed}[/yellow]")
        if ignored:
            console.print(f"  [dim]Ignored: {ignored}[/dim]")
        if errors:
            console.print(f"  [red]Failed: {errors}[/red]")
    if user_errors:
        console.print(f"  [red]User errors: {user_errors}[/red]")


def render_catalog_list_table(catalog_stats: List[Dict[str, Any]]) -> None:
    """
    Render catalog list as a formatted table.
    
    Args:
        catalog_stats: List of catalog statistics
    """
    if not catalog_stats:
        console.print("[yellow]No catalogs defined.[/yellow]")
        return
    
    # Create table
    table = Table(
        title="Repository Catalogs",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Add columns
    table.add_column("Type", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Directories", style="blue", justify="right")
    table.add_column("Repositories", style="magenta", justify="right")
    
    # Sort by type and value
    sorted_stats = sorted(catalog_stats, key=lambda x: (x['type'], x['value']))
    
    # Add rows
    for stat in sorted_stats:
        table.add_row(
            stat['type'].title(),
            stat['value'],
            str(stat['directories']),
            str(stat['repositories'])
        )
    
    console.print(table)
    
    # Print summary
    total_catalogs = len(catalog_stats)
    total_dirs = sum(s['directories'] for s in catalog_stats)
    total_repos = sum(s['repositories'] for s in catalog_stats)
    
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Total catalogs: {total_catalogs}")
    console.print(f"  Total directories: {total_dirs}")
    console.print(f"  Total repositories: {total_repos}")


def render_catalog_table(repos: List[Dict[str, Any]], catalog_type: str, catalog_value: str) -> None:
    """
    Render repositories in a catalog as a formatted table.
    
    Args:
        repos: List of repository dictionaries
        catalog_type: Type of catalog
        catalog_value: Value of catalog
    """
    if not repos:
        console.print(f"[yellow]No repositories in {catalog_type}='{catalog_value}'[/yellow]")
        return
    
    # Create table
    table = Table(
        title=f"Repositories in {catalog_type.title()}: {catalog_value}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Add columns
    table.add_column("Repository", style="cyan")
    table.add_column("Path", style="dim")
    
    # Check if any repo has metadata to show
    has_metadata = any(r.get('metadata') for r in repos)
    if has_metadata:
        table.add_column("Organization", style="blue")
        table.add_column("Category", style="yellow")
        table.add_column("Tags", style="green")
    
    # Sort by name
    sorted_repos = sorted(repos, key=lambda x: x['name'])
    
    # Add rows
    for repo in sorted_repos:
        row = [repo['name'], repo['path']]
        
        if has_metadata:
            metadata = repo.get('metadata', {})
            row.extend([
                metadata.get('organization', ''),
                metadata.get('category', ''),
                ', '.join(metadata.get('tags', []))
            ])
        
        table.add_row(*row)
    
    console.print(table)
    
    # Print summary
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Total repositories: {len(repos)}")
    
    # Count by metadata if available
    if has_metadata:
        orgs = set(r.get('metadata', {}).get('organization', '') for r in repos if r.get('metadata', {}).get('organization'))
        categories = set(r.get('metadata', {}).get('category', '') for r in repos if r.get('metadata', {}).get('category'))
        all_tags = set()
        for r in repos:
            tags = r.get('metadata', {}).get('tags', [])
            all_tags.update(tags)
        
        if orgs:
            console.print(f"  Organizations: {len(orgs)}")
        if categories:
            console.print(f"  Categories: {len(categories)}")
        if all_tags:
            console.print(f"  Unique tags: {len(all_tags)}")


def render_docs_table(docs_statuses: List[Dict[str, Any]]) -> None:
    """
    Render documentation status as a pretty table.
    
    Args:
        docs_statuses: List of documentation status dictionaries
    """
    if not docs_statuses:
        console.print("[yellow]No repositories found.[/yellow]")
        return
    
    # Create table
    table = Table(
        title="Documentation Status",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )
    
    # Add columns
    table.add_column("Repository", style="cyan")
    table.add_column("Tool", style="green")
    table.add_column("Config", style="yellow")
    table.add_column("Files", style="blue")
    table.add_column("Pages", style="magenta", justify="center", width=5)
    table.add_column("Pages URL", style="dim")
    
    # Add rows
    for repo in sorted(docs_statuses, key=lambda x: x['name']):
        # Tool display
        tool = repo.get('docs_tool') or "None"
        tool_style = "green" if tool != "None" else "red"
        
        # Config display
        config = repo.get('docs_config') or "N/A"
        
        # Files display
        files = repo.get('detected_files', [])
        if len(files) > 2:
            files_display = f"{', '.join(files[:2])}..."
        else:
            files_display = ', '.join(files) if files else "None"
        
        # Pages indicator
        pages_url = repo.get('pages_url')
        pages_display = "[green]✓[/green]" if pages_url else "[red]✗[/red]"
        
        # Pages URL display (truncated if too long)
        if pages_url and len(pages_url) > 40:
            pages_url_display = pages_url[:37] + "..."
        else:
            pages_url_display = pages_url or ""
        
        table.add_row(
            repo['name'],
            f"[{tool_style}]{tool}[/{tool_style}]",
            config,
            files_display,
            pages_display,
            pages_url_display
        )
    
    # Print table
    console.print(table)
    
    # Print summary
    total = len(docs_statuses)
    has_docs = sum(1 for r in docs_statuses if r.get('has_docs'))
    pages_enabled = sum(1 for r in docs_statuses if r.get('pages_url'))
    
    # Count by tool
    tool_counts: Dict[str, int] = {}
    for repo in docs_statuses:
        tool = repo.get('docs_tool')
        if tool:
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
    
    summary = "\n[bold]Summary:[/bold]"
    summary += f"\n  Total repositories: {total}"
    summary += f"\n  [bold green]With docs:[/bold green] {has_docs}"
    summary += f"\n  [bold magenta]Pages enabled:[/bold magenta] {pages_enabled}"
    
    if tool_counts:
        summary += "\n  [bold]Tools:[/bold] "
        tool_parts = []
        for tool, count in sorted(tool_counts.items()):
            tool_parts.append(f"{tool}: {count}")
        summary += " | ".join(tool_parts)
    
    console.print(summary)