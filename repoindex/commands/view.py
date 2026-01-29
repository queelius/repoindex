"""
View management commands for repoindex.

Views are curated, ordered collections of repositories with
overlays and annotations following SICP principles of
abstraction, composition, and closure.
"""

import click
import json
import sys
from typing import Dict, Any, Optional

from ..config import load_config
from ..services import ViewService, RepositoryService
from ..domain.view import ViewSpec, ViewMetadata, Overlay, Annotation
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()
console_err = Console(stderr=True)


def get_view_service() -> ViewService:
    """Get a ViewService instance, loading views."""
    config = load_config()
    service = ViewService(config=config)
    service.load()
    return service


def get_repo_lookup(config: Dict[str, Any]):
    """Create a repo lookup function."""
    repo_service = RepositoryService(config=config)
    repos = list(repo_service.discover())
    repo_map = {r.name: r for r in repos}
    repo_map.update({r.path: r for r in repos})

    def lookup(ref: str):
        return repo_map.get(ref)

    return lookup, repos


@click.group(name='view')
def view_cmd():
    """Manage curated repository views.

    \b
    Views are ordered collections of repositories with:
    - Selection: queries, tags, or explicit lists
    - Composition: union, intersect, subtract operations
    - Overlays: view-local metadata overrides
    - Annotations: narrative content and notes

    Views follow SICP principles - all operations produce views,
    enabling arbitrary composition.

    \b
    Examples:
        repoindex view list
        repoindex view show portfolio
        repoindex view create myview --repos repo1 repo2
        repoindex view eval portfolio
    """
    pass


@view_cmd.command('list')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
@click.option('--templates', is_flag=True, help='Include templates')
def view_list(output_json: bool, templates: bool):
    """List all defined views.

    \b
    Examples:
        repoindex view list
        repoindex view list --templates
        repoindex view list --json | jq '.name'
    """
    service = get_view_service()
    views = service.list_views()
    template_names = service.list_templates() if templates else []

    if output_json:
        # JSONL output
        for name in views:
            spec = service.get_spec(name)
            output = {
                "name": name,
                "type": "view",
                **spec.to_dict()
            }
            print(json.dumps(output), flush=True)

        if templates:
            for name in template_names:
                tmpl = service.get_template(name)
                output = {
                    "name": name,
                    "type": "template",
                    **tmpl.to_dict()
                }
                print(json.dumps(output), flush=True)
    else:
        # Pretty table (default)
        if views:
            table = Table(title="Views")
            table.add_column("Name", style="cyan")
            table.add_column("Type", style="dim")
            table.add_column("Description")

            for name in sorted(views):
                spec = service.get_spec(name)
                desc = spec.metadata.description or spec.metadata.title or ""
                view_type = _get_view_type(spec)
                table.add_row(name, view_type, desc[:50] + "..." if len(desc) > 50 else desc)

            console.print(table)
        else:
            console.print("[dim]No views defined.[/dim]")

        if template_names:
            console.print()
            table = Table(title="Templates")
            table.add_column("Name", style="cyan")
            table.add_column("Parameters", style="dim")

            for name in sorted(template_names):
                tmpl = service.get_template(name)
                params = ", ".join(tmpl.params)
                table.add_row(name, params)

            console.print(table)


@view_cmd.command('show')
@click.argument('name')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')
def view_show(name: str, output_json: bool):
    """Show view specification (unevaluated).

    NAME: Name of the view to show

    \b
    Examples:
        repoindex view show portfolio
        repoindex view show portfolio --json
    """
    service = get_view_service()
    spec = service.get_spec(name)

    if not spec:
        console_err.print(f"[red]View not found: {name}[/red]")
        sys.exit(1)

    if output_json:
        print(json.dumps({"name": name, **spec.to_dict()}, indent=2))
    else:
        _render_spec_pretty(spec)


@view_cmd.command('eval')
@click.argument('name')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')
@click.option('--full', is_flag=True, help='Include overlay and annotation details')
def view_eval(name: str, output_json: bool, full: bool):
    """Evaluate a view and show resolved repositories.

    NAME: Name of the view to evaluate

    \b
    Examples:
        repoindex view eval portfolio
        repoindex view eval portfolio --full
        repoindex view eval portfolio --json
    """
    service = get_view_service()
    config = load_config()
    repo_lookup, all_repos = get_repo_lookup(config)

    view = service.evaluate(name, repo_lookup, all_repos)

    if not view:
        console_err.print(f"[red]View not found: {name}[/red]")
        sys.exit(1)

    if output_json:
        # JSON output
        output = view.to_dict()
        if not full:
            # Slim output without overlay/annotation details
            output['entries'] = [{"repo": e['repo']} for e in output['entries']]
        print(json.dumps(output))
    else:
        _render_view_pretty(view, repo_lookup, full)


@view_cmd.command('create')
@click.argument('name')
@click.option('--repos', '-r', multiple=True, help='Repository names to include')
@click.option('--query', '-q', help='Query expression')
@click.option('--tags', '-t', multiple=True, help='Tag patterns')
@click.option('--extends', '-e', help='Extend another view')
@click.option('--title', help='View title')
@click.option('--description', '-d', help='View description')
def view_create(
    name: str,
    repos: tuple,
    query: Optional[str],
    tags: tuple,
    extends: Optional[str],
    title: Optional[str],
    description: Optional[str]
):
    """Create a new view.

    NAME: Name for the new view

    \b
    Examples:
        repoindex view create portfolio --repos repoindex ctk btk
        repoindex view create python-libs --query "language == 'Python'"
        repoindex view create ml-research --tags "research/ml" "research/nlp"
        repoindex view create active --extends portfolio --query "not archived"
    """
    service = get_view_service()

    # Check if view already exists
    if service.get_spec(name):
        console_err.print(f"[red]View already exists: {name}[/red]")
        console_err.print("[dim]Use 'repoindex view update' to modify or delete first.[/dim]")
        sys.exit(1)

    # Build the spec
    metadata = ViewMetadata(title=title, description=description)
    spec = ViewSpec(
        name=name,
        repos=tuple(repos) if repos else (),
        query=query,
        tags=tuple(tags) if tags else (),
        extends=extends,
        metadata=metadata
    )

    service.add_spec(spec)
    service.save()

    console_err.print(f"[green]Created view: {name}[/green]")
    _render_spec_pretty(spec)


@view_cmd.command('delete')
@click.argument('name')
@click.option('--force', '-f', is_flag=True, help='Skip confirmation')
def view_delete(name: str, force: bool):
    """Delete a view.

    NAME: Name of the view to delete

    \b
    Examples:
        repoindex view delete old-portfolio
        repoindex view delete temp --force
    """
    service = get_view_service()

    spec = service.get_spec(name)
    if not spec:
        console_err.print(f"[red]View not found: {name}[/red]")
        sys.exit(1)

    if not force:
        if not click.confirm(f"Delete view '{name}'?"):
            console_err.print("[dim]Cancelled.[/dim]")
            return

    service.remove_spec(name)
    service.save()

    console_err.print(f"[green]Deleted view: {name}[/green]")


@view_cmd.command('repos')
@click.argument('repo_name')
@click.option('--json', 'output_json', is_flag=True, help='Output as JSONL')
def view_repos(repo_name: str, output_json: bool):
    """Show which views contain a repository.

    REPO_NAME: Name of the repository to look up

    \b
    Examples:
        repoindex view repos repoindex
        repoindex view repos myproject --json | jq '.view'
    """
    service = get_view_service()
    config = load_config()
    repo_lookup, all_repos = get_repo_lookup(config)

    # Evaluate all views to check membership
    views_containing = []
    for view_name in service.list_views():
        view = service.evaluate(view_name, repo_lookup, all_repos)
        if view and view.contains(repo_name):
            entry = view.get_entry(repo_name)
            views_containing.append({
                "view": view_name,
                "has_overlay": bool(entry.overlay.to_dict()) if entry else False,
                "has_annotation": bool(entry.annotation.to_dict()) if entry else False
            })

    if output_json:
        for v in views_containing:
            print(json.dumps({"repo": repo_name, **v}), flush=True)
    else:
        if views_containing:
            console.print(f"[cyan]{repo_name}[/cyan] appears in {len(views_containing)} view(s):\n")
            for v in views_containing:
                extras = []
                if v["has_overlay"]:
                    extras.append("overlay")
                if v["has_annotation"]:
                    extras.append("annotation")
                extra_str = f" ({', '.join(extras)})" if extras else ""
                console.print(f"  • {v['view']}{extra_str}")
        else:
            console.print(f"[dim]{repo_name} is not in any views.[/dim]")


@view_cmd.command('overlay')
@click.argument('view_name')
@click.argument('repo_name')
@click.option('--description', '-d', help='Override description')
@click.option('--tag', '-t', multiple=True, help='Add view-local tags')
@click.option('--highlight', is_flag=True, help='Mark as highlighted')
@click.option('--note', '-n', help='Add annotation note')
def view_overlay(
    view_name: str,
    repo_name: str,
    description: Optional[str],
    tag: tuple,
    highlight: bool,
    note: Optional[str]
):
    """Add or update overlay/annotation for a repo in a view.

    \b
    VIEW_NAME: Name of the view
    REPO_NAME: Name of the repository

    \b
    Examples:
        repoindex view overlay portfolio repoindex -d "Repository management toolkit"
        repoindex view overlay teaching algebraic-ds --highlight -n "Start here"
    """
    service = get_view_service()
    spec = service.get_spec(view_name)

    if not spec:
        console_err.print(f"[red]View not found: {view_name}[/red]", stderr=True)
        sys.exit(1)

    # Get existing overlays/annotations
    overlays = dict(spec.overlays)
    annotations = dict(spec.annotations)

    # Update overlay
    if description or tag or highlight:
        existing = overlays.get(repo_name, Overlay())
        new_tags = frozenset(tag) if tag else existing.tags
        overlays[repo_name] = Overlay(
            description=description if description else existing.description,
            tags=existing.tags | new_tags,
            highlight=highlight or existing.highlight,
            extra=existing.extra
        )

    # Update annotation
    if note:
        existing = annotations.get(repo_name, Annotation())
        annotations[repo_name] = Annotation(
            note=note,
            section=existing.section,
            section_intro=existing.section_intro
        )

    # Create updated spec (immutable, so we recreate)
    # ViewSpec is frozen, need to create new one
    new_spec = ViewSpec(
        name=spec.name,
        repos=spec.repos,
        query=spec.query,
        tags=spec.tags,
        extends=spec.extends,
        union=spec.union,
        intersect=spec.intersect,
        subtract=spec.subtract,
        include=spec.include,
        exclude=spec.exclude,
        order=spec.order,
        explicit_order=spec.explicit_order,
        overlays=overlays,
        annotations=annotations,
        metadata=spec.metadata,
        template=spec.template,
        template_args=spec.template_args
    )

    service.add_spec(new_spec)
    service.save()

    console_err.print(f"[green]Updated overlay for {repo_name} in {view_name}[/green]")


# =============================================================================
# Helper functions
# =============================================================================

def _get_view_type(spec: ViewSpec) -> str:
    """Determine view type for display."""
    if spec.template:
        return "template instance"
    if spec.extends:
        return "extends"
    if spec.union or spec.intersect or spec.subtract:
        return "composite"
    if spec.query:
        return "query"
    if spec.tags:
        return "tags"
    if spec.repos:
        return "explicit"
    return "empty"


def _render_spec_pretty(spec: ViewSpec):
    """Render a view specification in human-readable format."""
    console.print(Panel(f"[bold cyan]{spec.name}[/bold cyan]", expand=False))

    if spec.metadata.title:
        console.print(f"[bold]Title:[/bold] {spec.metadata.title}")
    if spec.metadata.description:
        console.print(f"[bold]Description:[/bold] {spec.metadata.description}")

    console.print()
    console.print("[bold]Selection:[/bold]")

    if spec.extends:
        console.print(f"  extends: {spec.extends}")
    if spec.repos:
        console.print(f"  repos: {', '.join(spec.repos)}")
    if spec.query:
        console.print(f"  query: {spec.query}")
    if spec.tags:
        console.print(f"  tags: {', '.join(spec.tags)}")

    if spec.union or spec.intersect or spec.subtract:
        console.print()
        console.print("[bold]Composition:[/bold]")
        if spec.union:
            console.print(f"  union: {', '.join(spec.union)}")
        if spec.intersect:
            console.print(f"  intersect: {', '.join(spec.intersect)}")
        if spec.subtract:
            console.print(f"  subtract: {', '.join(spec.subtract)}")

    if spec.include or spec.exclude:
        console.print()
        console.print("[bold]Modifications:[/bold]")
        if spec.include:
            console.print(f"  include: {', '.join(spec.include)}")
        if spec.exclude:
            console.print(f"  exclude: {', '.join(spec.exclude)}")

    if spec.order or spec.explicit_order:
        console.print()
        console.print("[bold]Ordering:[/bold]")
        if spec.order:
            console.print(f"  order by: {spec.order.field} {spec.order.direction.value}")
        if spec.explicit_order:
            console.print(f"  explicit: {', '.join(spec.explicit_order)}")

    if spec.overlays:
        console.print()
        console.print(f"[bold]Overlays:[/bold] {len(spec.overlays)} repo(s)")
        for repo, overlay in list(spec.overlays.items())[:3]:
            console.print(f"  • {repo}: {overlay.description or '(no description)'}")
        if len(spec.overlays) > 3:
            console.print(f"  ... and {len(spec.overlays) - 3} more")

    if spec.annotations:
        console.print()
        console.print(f"[bold]Annotations:[/bold] {len(spec.annotations)} repo(s)")


def _render_view_pretty(view, repo_lookup, full: bool):
    """Render an evaluated view in human-readable format."""
    console.print(Panel(
        f"[bold cyan]{view.name}[/bold cyan] - {len(view)} repositories",
        expand=False
    ))

    if view.metadata.title:
        console.print(f"[bold]Title:[/bold] {view.metadata.title}")
    if view.metadata.intro:
        console.print()
        console.print(Markdown(view.metadata.intro))

    console.print()

    table = Table()
    table.add_column("#", style="dim", width=3)
    table.add_column("Repository", style="cyan")
    table.add_column("Status", style="dim")

    if full:
        table.add_column("Note", style="italic")

    current_section = None
    for i, entry in enumerate(view.entries, 1):
        # Handle section markers
        if entry.annotation.section and entry.annotation.section != current_section:
            current_section = entry.annotation.section
            # Add section header row
            if full:
                table.add_row("", f"[bold]── {current_section} ──[/bold]", "", "")
            else:
                table.add_row("", f"[bold]── {current_section} ──[/bold]", "")

        # Get repo status if available
        repo = repo_lookup(entry.repo_ref)
        status = ""
        if repo:
            if entry.overlay.highlight:
                status = "[yellow]★[/yellow] "
            if repo.status and not repo.status.clean:
                status += "[red]●[/red]"
            elif repo.status and repo.status.ahead > 0:
                status += "[green]↑[/green]"

        if full:
            note = entry.annotation.note or ""
            if len(note) > 40:
                note = note[:37] + "..."
            table.add_row(str(i), entry.repo_ref, status, note)
        else:
            table.add_row(str(i), entry.repo_ref, status)

    console.print(table)

    if view.metadata.conclusion:
        console.print()
        console.print(Markdown(view.metadata.conclusion))
