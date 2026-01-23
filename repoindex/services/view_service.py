"""
View service for repoindex.

Provides operations for loading, evaluating, and querying views.
Views are curated collections of repositories with overlays and annotations.
"""

from typing import (
    Dict, Any, List, Optional, Callable
)
from pathlib import Path
import logging
import os
import fnmatch
import yaml
import json

from ..domain import Repository
from ..domain.view import (
    View, ViewSpec, ViewEntry, ViewTemplate,
    Overlay, Annotation, ViewMetadata, OrderSpec, OrderDirection
)
from ..query import Query

logger = logging.getLogger(__name__)


class ViewService:
    """
    Service for managing and evaluating views.

    Views are loaded from ~/.repoindex/views.yaml and evaluated
    against the repository index to produce ordered collections.

    Example:
        service = ViewService()
        service.load()  # Load from default location

        # Get a specific view
        view = service.evaluate("portfolio", repo_lookup)

        # Check which views contain a repo
        views = service.views_containing("repoindex")
    """

    def __init__(
        self,
        views_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize ViewService.

        Args:
            views_path: Path to views.yaml (uses default if None)
            config: Configuration dict
        """
        self.views_path = views_path or self._default_views_path()
        self.config = config or {}

        # Storage for loaded specs and templates
        self._specs: Dict[str, ViewSpec] = {}
        self._templates: Dict[str, ViewTemplate] = {}

        # Cache for evaluated views
        self._cache: Dict[str, View] = {}

    def _default_views_path(self) -> str:
        """Get default path to views.yaml."""
        if 'REPOINDEX_VIEWS' in os.environ:
            return os.environ['REPOINDEX_VIEWS']

        # Check ~/.repoindex/views.yaml
        repoindex_dir = Path.home() / '.repoindex'
        for ext in ('yaml', 'yml', 'json'):
            path = repoindex_dir / f'views.{ext}'
            if path.exists():
                return str(path)

        # Return default (may not exist yet)
        return str(repoindex_dir / 'views.yaml')

    def load(self, path: Optional[str] = None) -> None:
        """
        Load view definitions from file.

        Args:
            path: Path to views file (uses default if None)
        """
        path = path or self.views_path
        self._specs.clear()
        self._templates.clear()
        self._cache.clear()

        if not os.path.exists(path):
            logger.debug(f"Views file not found: {path}")
            return

        with open(path, 'r') as f:
            if path.endswith('.json'):
                data = json.load(f)
            else:
                data = yaml.safe_load(f)

        if not data:
            return

        # Load templates first (views may reference them)
        templates_data = data.get('templates', {})
        for name, template_dict in templates_data.items():
            self._templates[name] = ViewTemplate.from_dict(name, template_dict)

        # Load view specs
        views_data = data.get('views', {})
        for name, view_dict in views_data.items():
            self._specs[name] = ViewSpec.from_dict(name, view_dict)

        logger.debug(f"Loaded {len(self._specs)} views and {len(self._templates)} templates from {path}")

    def save(self, path: Optional[str] = None) -> None:
        """
        Save view definitions to file.

        Args:
            path: Path to save to (uses default if None)
        """
        path = path or self.views_path

        # Ensure directory exists
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        data = {
            'views': {name: spec.to_dict() for name, spec in self._specs.items()},
            'templates': {name: tmpl.to_dict() for name, tmpl in self._templates.items()}
        }

        with open(path, 'w') as f:
            if path.endswith('.json'):
                json.dump(data, f, indent=2)
            else:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

        logger.debug(f"Saved {len(self._specs)} views to {path}")

    def get_spec(self, name: str) -> Optional[ViewSpec]:
        """Get a view specification by name."""
        return self._specs.get(name)

    def get_template(self, name: str) -> Optional[ViewTemplate]:
        """Get a view template by name."""
        return self._templates.get(name)

    def list_views(self) -> List[str]:
        """List all defined view names."""
        return list(self._specs.keys())

    def list_templates(self) -> List[str]:
        """List all defined template names."""
        return list(self._templates.keys())

    def add_spec(self, spec: ViewSpec) -> None:
        """Add or update a view specification."""
        self._specs[spec.name] = spec
        # Invalidate cache
        self._cache.pop(spec.name, None)

    def add_template(self, template: ViewTemplate) -> None:
        """Add or update a view template."""
        self._templates[template.name] = template

    def remove_spec(self, name: str) -> bool:
        """Remove a view specification."""
        if name in self._specs:
            del self._specs[name]
            self._cache.pop(name, None)
            return True
        return False

    def evaluate(
        self,
        name: str,
        repo_lookup: Callable[[str], Optional[Repository]],
        all_repos: Optional[List[Repository]] = None,
        use_cache: bool = True
    ) -> Optional[View]:
        """
        Evaluate a view specification into a resolved View.

        Args:
            name: View name to evaluate
            repo_lookup: Function to lookup Repository by name
            all_repos: List of all repositories (for queries)
            use_cache: Whether to use cached result

        Returns:
            Resolved View or None if not found
        """
        if use_cache and name in self._cache:
            return self._cache[name]

        spec = self._specs.get(name)
        if not spec:
            logger.warning(f"View not found: {name}")
            return None

        view = self._evaluate_spec(spec, repo_lookup, all_repos or [])
        if use_cache:
            self._cache[name] = view
        return view

    def _evaluate_spec(
        self,
        spec: ViewSpec,
        repo_lookup: Callable[[str], Optional[Repository]],
        all_repos: List[Repository]
    ) -> View:
        """
        Evaluate a ViewSpec into a View.

        This is the core evaluation logic that handles:
        - Template instantiation
        - Base set selection (repos, query, tags)
        - Composition (extends, union, intersect, subtract)
        - Modifications (include, exclude)
        - Ordering
        - Overlay/annotation application
        """
        # Handle template instantiation
        if spec.is_template_instantiation():
            template = self._templates.get(spec.template)
            if not template:
                raise ValueError(f"Template not found: {spec.template}")
            instantiated = template.instantiate(spec.template_args)
            return self._evaluate_spec(instantiated, repo_lookup, all_repos)

        # Start with base set
        repo_refs: List[str] = []

        # Handle extends (inherit from another view)
        if spec.extends:
            parent = self.evaluate(spec.extends, repo_lookup, all_repos, use_cache=True)
            if parent:
                repo_refs = parent.repo_names.copy()

        # Handle explicit repos
        if spec.repos:
            if spec.extends:
                # Merge with parent
                seen = set(repo_refs)
                for ref in spec.repos:
                    if ref not in seen:
                        repo_refs.append(ref)
                        seen.add(ref)
            else:
                repo_refs = list(spec.repos)

        # Handle query
        if spec.query:
            query_results = self._evaluate_query(spec.query, all_repos)
            if spec.extends or spec.repos:
                # Add to existing
                seen = set(repo_refs)
                for repo in query_results:
                    if repo.name not in seen:
                        repo_refs.append(repo.name)
                        seen.add(repo.name)
            else:
                repo_refs = [r.name for r in query_results]

        # Handle tag patterns
        if spec.tags:
            tagged_repos = self._evaluate_tags(spec.tags, all_repos)
            if spec.extends or spec.repos or spec.query:
                seen = set(repo_refs)
                for repo in tagged_repos:
                    if repo.name not in seen:
                        repo_refs.append(repo.name)
                        seen.add(repo.name)
            else:
                repo_refs = [r.name for r in tagged_repos]

        # Handle composition operators
        if spec.union:
            for view_name in spec.union:
                other = self.evaluate(view_name, repo_lookup, all_repos)
                if other:
                    seen = set(repo_refs)
                    for ref in other.repo_names:
                        if ref not in seen:
                            repo_refs.append(ref)
                            seen.add(ref)

        if spec.intersect:
            for view_name in spec.intersect:
                other = self.evaluate(view_name, repo_lookup, all_repos)
                if other:
                    other_refs = set(other.repo_names)
                    repo_refs = [r for r in repo_refs if r in other_refs]

        if spec.subtract:
            for view_name in spec.subtract:
                other = self.evaluate(view_name, repo_lookup, all_repos)
                if other:
                    other_refs = set(other.repo_names)
                    repo_refs = [r for r in repo_refs if r not in other_refs]

        # Handle include (force add)
        if spec.include:
            seen = set(repo_refs)
            for ref in spec.include:
                if ref not in seen:
                    repo_refs.append(ref)
                    seen.add(ref)

        # Handle exclude (force remove, supports patterns)
        if spec.exclude:
            def matches_exclude(ref: str) -> bool:
                for pattern in spec.exclude:
                    if fnmatch.fnmatch(ref, pattern):
                        return True
                return False
            repo_refs = [r for r in repo_refs if not matches_exclude(r)]

        # Handle explicit ordering
        if spec.explicit_order:
            # Reorder based on explicit list
            order_map = {name: i for i, name in enumerate(spec.explicit_order)}
            # Items in explicit_order come first in that order, rest follow
            def sort_key(ref: str) -> tuple:
                if ref in order_map:
                    return (0, order_map[ref])
                return (1, repo_refs.index(ref))
            repo_refs = sorted(repo_refs, key=sort_key)

        # Handle order by field
        elif spec.order:
            repo_refs = self._apply_order(repo_refs, spec.order, repo_lookup)

        # Build entries with overlays and annotations
        entries: List[ViewEntry] = []
        for ref in repo_refs:
            overlay = spec.overlays.get(ref, Overlay())
            annotation = spec.annotations.get(ref, Annotation())
            entries.append(ViewEntry(
                repo_ref=ref,
                overlay=overlay,
                annotation=annotation
            ))

        return View(
            name=spec.name,
            entries=entries,
            metadata=spec.metadata,
            source_spec=spec
        )

    def _evaluate_query(
        self,
        query_str: str,
        all_repos: List[Repository]
    ) -> List[Repository]:
        """Evaluate a query against all repositories."""
        try:
            query = Query(query_str)
            return [repo for repo in all_repos if query.evaluate(repo.to_dict())]
        except Exception as e:
            logger.error(f"Query evaluation failed: {e}")
            return []

    def _evaluate_tags(
        self,
        patterns: tuple,
        all_repos: List[Repository]
    ) -> List[Repository]:
        """Find repos matching any tag pattern."""
        result = []
        for repo in all_repos:
            for pattern in patterns:
                if repo.has_tag(pattern):
                    result.append(repo)
                    break
        return result

    def _apply_order(
        self,
        repo_refs: List[str],
        order: OrderSpec,
        repo_lookup: Callable[[str], Optional[Repository]]
    ) -> List[str]:
        """Apply ordering to repo refs."""
        def get_sort_key(ref: str):
            repo = repo_lookup(ref)
            if not repo:
                return (1, ref)  # Unknown repos sort last

            # Get field value using dot notation
            value = self._get_field(repo.to_dict(), order.field)
            if value is None:
                return (1, ref)  # None values sort last
            return (0, value)

        reverse = order.direction == OrderDirection.DESC
        return sorted(repo_refs, key=get_sort_key, reverse=reverse)

    def _get_field(self, data: Dict[str, Any], field: str) -> Any:
        """Get nested field using dot notation."""
        parts = field.split('.')
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def views_containing(self, repo_ref: str) -> List[str]:
        """
        Find all views that contain a repository.

        Args:
            repo_ref: Repository name or path

        Returns:
            List of view names containing the repo
        """
        # This requires evaluating all views, so we check specs directly
        # for explicit includes, and cached views for evaluated results
        containing = []

        for name, spec in self._specs.items():
            # Check explicit repos
            if repo_ref in spec.repos:
                containing.append(name)
                continue

            # Check explicit includes
            if repo_ref in spec.include:
                containing.append(name)
                continue

            # Check cached evaluation
            if name in self._cache:
                if self._cache[name].contains(repo_ref):
                    containing.append(name)

        return containing

    def invalidate_cache(self, name: Optional[str] = None) -> None:
        """
        Invalidate cached views.

        Args:
            name: Specific view to invalidate (all if None)
        """
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()

    def create_view_from_repos(
        self,
        name: str,
        repo_names: List[str],
        title: Optional[str] = None,
        description: Optional[str] = None
    ) -> ViewSpec:
        """
        Create a simple view from a list of repo names.

        Args:
            name: View name
            repo_names: List of repository names
            title: Optional title
            description: Optional description

        Returns:
            Created ViewSpec
        """
        metadata = ViewMetadata(title=title, description=description)
        spec = ViewSpec(
            name=name,
            repos=tuple(repo_names),
            metadata=metadata
        )
        self.add_spec(spec)
        return spec

    def to_dict(self) -> Dict[str, Any]:
        """Export all views and templates as dictionary."""
        return {
            'views': {name: spec.to_dict() for name, spec in self._specs.items()},
            'templates': {name: tmpl.to_dict() for name, tmpl in self._templates.items()}
        }
