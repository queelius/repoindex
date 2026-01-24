"""
Tag management commands for repoindex.

Provides CLI parity with the shell's filesystem-like tag operations.
"""

import click
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

from ..config import load_config, save_config
from ..utils import find_git_repos_from_config, is_git_repo
from ..commands.catalog import get_repository_tags, is_protected_tag
from ..database.connection import Database, get_db_path
from ..database.repository import get_all_repos
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

console = Console()


def get_implicit_tags_from_row(repo_dict: Dict[str, Any]) -> List[str]:
    """
    Generate implicit tags from a database row.

    This produces the same tags as TagService.get_implicit_tags() but works
    directly from database rows without needing full domain object conversion.

    Args:
        repo_dict: Database row as dictionary

    Returns:
        List of implicit tag strings
    """
    tags = []

    # repo:name
    if repo_dict.get('name'):
        tags.append(f"repo:{repo_dict['name']}")

    # dir:parent (from path)
    if repo_dict.get('path'):
        parent = Path(repo_dict['path']).parent.name
        tags.append(f"dir:{parent}")

    # lang:language
    if repo_dict.get('language'):
        tags.append(f"lang:{repo_dict['language'].lower()}")

    # owner:owner
    if repo_dict.get('owner'):
        tags.append(f"owner:{repo_dict['owner']}")

    # license:key
    if repo_dict.get('license_key'):
        tags.append(f"license:{repo_dict['license_key']}")

    # status:clean or status:dirty
    if repo_dict.get('is_clean') is not None:
        status = "clean" if repo_dict['is_clean'] else "dirty"
        tags.append(f"status:{status}")

    # GitHub-specific implicit tags (all have github_ prefix in database)
    if repo_dict.get('github_owner'):
        # visibility:public/private
        if repo_dict.get('github_is_private'):
            tags.append("visibility:private")
        else:
            tags.append("visibility:public")

        # source:fork
        if repo_dict.get('github_is_fork'):
            tags.append("source:fork")

        # archived:true
        if repo_dict.get('github_is_archived'):
            tags.append("archived:true")

        # Stars buckets
        stars = repo_dict.get('github_stars', 0) or 0
        if stars >= 1000:
            tags.append("stars:1000+")
        elif stars >= 100:
            tags.append("stars:100+")
        elif stars >= 10:
            tags.append("stars:10+")

        # GitHub topics as topic:{topic} (provider tags)
        if repo_dict.get('github_topics'):
            try:
                topics = json.loads(repo_dict['github_topics'])
                for topic in topics:
                    tags.append(f"topic:{topic}")
            except (json.JSONDecodeError, TypeError):
                pass

    # Package registry tags
    # Note: these would come from publications table, not repos table
    # For now, we skip these as they require a join

    return tags


def get_all_tags_from_database(
    config: Dict[str, Any],
    tag_filter: Optional[str] = None
) -> Dict[str, List[str]]:
    """
    Get all tags (explicit + implicit) from the database.

    Args:
        config: Configuration dictionary
        tag_filter: Optional filter pattern (supports wildcards)

    Returns:
        Dict mapping tag strings to list of repo paths
    """
    from ..tags import filter_tags

    tag_repos = defaultdict(list)

    # Get explicit tags from config
    explicit_repo_tags = config.get("repository_tags", {})

    # Check if database exists
    db_path = get_db_path(config)
    if not db_path.exists():
        # Fall back to explicit tags only
        for repo_path, tags in explicit_repo_tags.items():
            for tag in tags:
                if tag_filter:
                    matching = filter_tags([tag], tag_filter)
                    if matching:
                        tag_repos[tag].append(repo_path)
                else:
                    tag_repos[tag].append(repo_path)
        return dict(tag_repos)

    # Query database for repos
    with Database(config=config, read_only=True) as db:
        for repo_dict in get_all_repos(db):
            repo_path = repo_dict['path']

            # Explicit tags from config
            explicit_tags = explicit_repo_tags.get(repo_path, [])
            for tag in explicit_tags:
                if tag_filter:
                    matching = filter_tags([tag], tag_filter)
                    if matching:
                        tag_repos[tag].append(repo_path)
                else:
                    tag_repos[tag].append(repo_path)

            # Implicit tags from database row
            implicit_tags = get_implicit_tags_from_row(repo_dict)
            for tag in implicit_tags:
                if tag_filter:
                    matching = filter_tags([tag], tag_filter)
                    if matching:
                        tag_repos[tag].append(repo_path)
                else:
                    tag_repos[tag].append(repo_path)

    return dict(tag_repos)


def get_repo_tags_from_database(config: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Get all tags (explicit + implicit) organized by repository.

    This returns the same format as config['repository_tags'] but includes
    implicit tags from the database.

    Args:
        config: Configuration dictionary

    Returns:
        Dict mapping repo paths to list of tag strings
    """
    repo_tags = defaultdict(list)

    # Get explicit tags from config
    explicit_repo_tags = config.get("repository_tags", {})

    # Check if database exists
    db_path = get_db_path(config)
    if not db_path.exists():
        # Fall back to explicit tags only
        return dict(explicit_repo_tags)

    # Query database for repos
    with Database(config=config, read_only=True) as db:
        for repo_dict in get_all_repos(db):
            repo_path = repo_dict['path']

            # Explicit tags from config
            explicit_tags = explicit_repo_tags.get(repo_path, [])
            repo_tags[repo_path].extend(explicit_tags)

            # Implicit tags from database row
            implicit_tags = get_implicit_tags_from_row(repo_dict)
            repo_tags[repo_path].extend(implicit_tags)

    return dict(repo_tags)


@click.group(name='tag')
def tag_cmd():
    """Manage repository tags with hierarchical support.

    Tag operations mirror the shell's filesystem commands:
    - add: Add tags to repositories (like shell 'cp')
    - remove: Remove tags from repositories (like shell 'rm')
    - move: Move repository between tags (like shell 'mv')
    - list: List tags and repositories
    - tree: Show tag hierarchy as a tree
    """
    pass


@tag_cmd.command('add')
@click.argument('repository')
@click.argument('tags', nargs=-1, required=True)
def tag_add(repository, tags):
    """Add one or more tags to a repository.

    REPOSITORY: Path or name of the repository
    TAGS: One or more tags to add (supports hierarchical tags)

    Examples:
        repoindex tag add myproject alex/beta
        repoindex tag add myproject topic:ml/research work/active
        repoindex tag add /path/to/repo client/acme/backend
    """
    config = load_config()

    # Resolve repository path
    repo_path = resolve_repository_path(repository, config)
    if not repo_path:
        console.print(f"[red]Error: Repository '{repository}' not found[/red]")
        raise click.Abort()

    # Get current tags
    repo_tags = config.get("repository_tags", {})
    current_tags = repo_tags.get(repo_path, [])

    # Add new tags
    added = []
    skipped = []
    protected = []

    for tag in tags:
        if is_protected_tag(tag):
            protected.append(tag)
        elif tag in current_tags:
            skipped.append(tag)
        else:
            current_tags.append(tag)
            added.append(tag)

    # Save if we added any tags
    if added:
        repo_tags[repo_path] = current_tags
        config["repository_tags"] = repo_tags
        save_config(config)

        console.print(f"[green]Added {len(added)} tag(s) to {Path(repo_path).name}:[/green]")
        for tag in added:
            console.print(f"  • {tag}")

    if skipped:
        console.print(f"[yellow]Already tagged (skipped {len(skipped)}):[/yellow]")
        for tag in skipped:
            console.print(f"  • {tag}")

    if protected:
        console.print(f"[red]Cannot add protected tags (skipped {len(protected)}):[/red]")
        for tag in protected:
            console.print(f"  • {tag}")


@tag_cmd.command('remove')
@click.argument('repository')
@click.argument('tags', nargs=-1, required=True)
def tag_remove(repository, tags):
    """Remove one or more tags from a repository.

    REPOSITORY: Path or name of the repository
    TAGS: One or more tags to remove

    Examples:
        repoindex tag remove myproject alex/beta
        repoindex tag remove myproject topic:ml/research work/active
    """
    config = load_config()

    # Resolve repository path
    repo_path = resolve_repository_path(repository, config)
    if not repo_path:
        console.print(f"[red]Error: Repository '{repository}' not found[/red]")
        raise click.Abort()

    # Get current tags
    repo_tags = config.get("repository_tags", {})
    current_tags = repo_tags.get(repo_path, [])

    # Remove tags
    removed = []
    not_found = []

    for tag in tags:
        if tag in current_tags:
            current_tags.remove(tag)
            removed.append(tag)
        else:
            not_found.append(tag)

    # Save if we removed any tags
    if removed:
        if current_tags:
            repo_tags[repo_path] = current_tags
        else:
            # Remove repo entry if no tags left
            if repo_path in repo_tags:
                del repo_tags[repo_path]

        config["repository_tags"] = repo_tags
        save_config(config)

        console.print(f"[green]Removed {len(removed)} tag(s) from {Path(repo_path).name}:[/green]")
        for tag in removed:
            console.print(f"  • {tag}")

    if not_found:
        console.print(f"[yellow]Tag(s) not found (skipped {len(not_found)}):[/yellow]")
        for tag in not_found:
            console.print(f"  • {tag}")


@tag_cmd.command('move')
@click.argument('repository')
@click.argument('old_tag')
@click.argument('new_tag')
def tag_move(repository, old_tag, new_tag):
    """Move a repository from one tag to another.

    REPOSITORY: Path or name of the repository
    OLD_TAG: Tag to remove
    NEW_TAG: Tag to add

    This is equivalent to removing old_tag and adding new_tag.

    Examples:
        repoindex tag move myproject alex/beta alex/production
        repoindex tag move myproject topic:ml topic:nlp
    """
    config = load_config()

    # Resolve repository path
    repo_path = resolve_repository_path(repository, config)
    if not repo_path:
        console.print(f"[red]Error: Repository '{repository}' not found[/red]")
        raise click.Abort()

    # Get current tags
    repo_tags = config.get("repository_tags", {})
    current_tags = repo_tags.get(repo_path, [])

    # Check if old tag exists
    if old_tag not in current_tags:
        console.print(f"[red]Error: Tag '{old_tag}' not found on repository[/red]")
        raise click.Abort()

    # Check if new tag is protected
    if is_protected_tag(new_tag):
        console.print(f"[red]Error: Cannot add protected tag '{new_tag}'[/red]")
        raise click.Abort()

    # Perform the move
    current_tags.remove(old_tag)
    if new_tag not in current_tags:
        current_tags.append(new_tag)

    repo_tags[repo_path] = current_tags
    config["repository_tags"] = repo_tags
    save_config(config)

    console.print(f"[green]Moved {Path(repo_path).name}:[/green]")
    console.print(f"  From: {old_tag}")
    console.print(f"  To:   {new_tag}")


@tag_cmd.command('list')
@click.option('-t', '--tag', 'tag_filter', help='Filter by tag (supports wildcards)')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSONL')
@click.option('-r', '--repository', help='Show tags for specific repository')
def tag_list(tag_filter, json_output, repository):
    """List tags and their repositories.

    Examples:
        repoindex tag list                      # List all tags
        repoindex tag list -t "alex/*"          # List alex/* tags
        repoindex tag list -t "topic:ml"        # List topic:ml tag
        repoindex tag list -r myproject         # Show tags for myproject
    """
    config = load_config()

    if repository:
        # Show tags for a specific repository
        repo_path = resolve_repository_path(repository, config)
        if not repo_path:
            console.print(f"[red]Error: Repository '{repository}' not found[/red]")
            raise click.Abort()

        tags = get_repository_tags(repo_path)

        if json_output:
            print(json.dumps({"repository": repo_path, "tags": tags}))
        else:
            console.print(f"[bold cyan]Tags for {Path(repo_path).name}:[/bold cyan]")
            for tag in sorted(tags):
                # Mark implicit/protected tags
                if is_protected_tag(tag):
                    console.print(f"  • {tag} [dim](implicit)[/dim]")
                else:
                    console.print(f"  • {tag}")
    else:
        # List all tags and their repos (explicit + implicit from database)
        tag_repos = get_all_tags_from_database(config, tag_filter)

        if json_output:
            for tag, repos in sorted(tag_repos.items()):
                print(json.dumps({
                    "tag": tag,
                    "repositories": [Path(r).name for r in repos],
                    "count": len(repos)
                }))
        else:
            if not tag_repos:
                console.print("[yellow]No tags found[/yellow]")
                return

            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Tag", style="green")
            table.add_column("Repositories", style="blue")
            table.add_column("Count", justify="right", style="yellow")

            for tag, repos in sorted(tag_repos.items()):
                repo_names = ", ".join([Path(r).name for r in sorted(repos)])
                table.add_row(tag, repo_names, str(len(repos)))

            console.print(table)


@tag_cmd.command('tree')
@click.option('-t', '--tag-prefix', help='Show tree for specific tag prefix')
def tag_tree(tag_prefix):
    """Show tag hierarchy as a tree.

    Examples:
        repoindex tag tree                 # Show full tag hierarchy
        repoindex tag tree -t alex         # Show alex/* hierarchy
        repoindex tag tree -t topic        # Show topic:* hierarchy
    """
    config = load_config()
    # Get all tags (explicit + implicit) from database
    repo_tags = get_repo_tags_from_database(config)

    # Build hierarchical structure
    tree_data = build_tag_tree(repo_tags, tag_prefix)

    # Create Rich tree
    if tag_prefix:
        tree = Tree(f"[bold cyan]{tag_prefix}/[/bold cyan]")
    else:
        tree = Tree("[bold cyan]Tags[/bold cyan]")

    def add_to_tree(parent, data):
        for name, content in sorted(data.items()):
            if 'repos' in content:
                # Leaf node with repositories
                branch = parent.add(f"[green]{name}[/green] ({len(content['repos'])} repos)")
                for repo in sorted(content['repos']):
                    branch.add(f"[blue]{Path(repo).name}[/blue]")
            else:
                # Directory node
                branch = parent.add(f"[yellow]{name}/[/yellow]")
                add_to_tree(branch, content)

    add_to_tree(tree, tree_data)
    console.print(tree)


def resolve_repository_path(repository: str, config: Dict[str, Any]) -> str:
    """Resolve a repository name or path to its full path.

    Args:
        repository: Repository name or path
        config: Configuration dictionary

    Returns:
        Full path to repository, or None if not found
    """
    # If it's already a path and exists, use it
    if os.path.exists(repository) and is_git_repo(repository):
        return os.path.abspath(repository)

    # Search for repository by name
    repo_dirs = config.get("repository_directories", [])
    for repo_path in find_git_repos_from_config(repo_dirs):
        if Path(repo_path).name == repository:
            return repo_path

    # Try as relative path from cwd
    cwd_path = os.path.join(os.getcwd(), repository)
    if os.path.exists(cwd_path) and is_git_repo(cwd_path):
        return os.path.abspath(cwd_path)

    return None


def build_tag_tree(repo_tags: Dict[str, List[str]], prefix: Optional[str] = None) -> Dict[str, Any]:
    """Build a hierarchical tree structure from tags.

    Args:
        repo_tags: Dictionary mapping repo paths to tag lists
        prefix: Optional prefix to filter tags

    Returns:
        Nested dictionary representing tag hierarchy
    """
    tree = {}

    for repo_path, tags in repo_tags.items():
        for tag in tags:
            # Apply prefix filter
            if prefix:
                if not (tag.startswith(f"{prefix}/") or tag.startswith(f"{prefix}:")):
                    continue

            # Parse tag into levels
            levels = parse_tag_into_levels(tag)

            # Build tree path
            current = tree
            for i, level in enumerate(levels):
                if i == len(levels) - 1:
                    # Leaf level - add repository
                    if level not in current:
                        current[level] = {'repos': []}
                    if 'repos' not in current[level]:
                        current[level]['repos'] = []
                    current[level]['repos'].append(repo_path)
                else:
                    # Directory level
                    if level not in current:
                        current[level] = {}
                    elif 'repos' in current[level]:
                        # Convert leaf to directory
                        repos = current[level]['repos']
                        current[level] = {'_repos': repos}
                    current = current[level]

    return tree


def parse_tag_into_levels(tag: str) -> List[str]:
    """Parse a tag into hierarchical levels.

    Args:
        tag: Tag string (e.g., "alex/beta", "topic:scientific/engineering/ai")

    Returns:
        List of hierarchical levels
    """
    if ':' in tag:
        key, value = tag.split(':', 1)
        if '/' in value:
            return [key] + value.split('/')
        else:
            return [key, value]
    elif '/' in tag:
        return tag.split('/')
    else:
        return [tag]
