"""
View domain object for repoindex.

Views are curated, ordered collections of repositories with:
- Selection: Which repos to include (query, explicit list, or composition)
- Ordering: How repos are arranged
- Overlays: View-local metadata overrides (descriptions, tags, etc.)
- Annotations: Narrative content (notes, section markers, prose)

Views follow SICP principles:
- Primitives: Explicit repo lists, queries, tag patterns
- Combination: Union, intersection, difference, sequence
- Abstraction: Named views, parameterized templates
- Closure: All operations on views produce views

Views are read-only projections - they don't modify source repo data.
"""

from dataclasses import dataclass, field
from typing import (
    Dict, Any, List, Optional, FrozenSet, Tuple,
    Union, Iterator
)
from enum import Enum
import json


class ViewOperator(Enum):
    """View combination operators."""
    UNION = "union"           # A ∪ B: repos from either
    INTERSECT = "intersect"   # A ∩ B: repos in both
    SUBTRACT = "subtract"     # A - B: repos in A but not B
    SEQUENCE = "sequence"     # Explicit ordered concatenation


class OrderDirection(Enum):
    """Sort direction for view ordering."""
    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True)
class Overlay:
    """
    View-local metadata overrides for a repository.

    Overlays don't modify the source repo - they provide contextual
    metadata that applies only within this view.

    Example:
        Overlay(
            description="Demonstrates algebraic data types",
            tags=frozenset(["teaching", "example"]),
            extra={"difficulty": "intermediate", "prerequisites": ["basic-python"]}
        )
    """
    description: Optional[str] = None
    tags: FrozenSet[str] = field(default_factory=frozenset)
    highlight: bool = False
    hidden: bool = False  # Include in view but don't render (e.g., for dependencies)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.description is not None:
            result['description'] = self.description
        if self.tags:
            result['tags'] = list(self.tags)
        if self.highlight:
            result['highlight'] = True
        if self.hidden:
            result['hidden'] = True
        if self.extra:
            result['extra'] = self.extra
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Overlay':
        """Create Overlay from dictionary."""
        return cls(
            description=data.get('description'),
            tags=frozenset(data.get('tags', [])),
            highlight=data.get('highlight', False),
            hidden=data.get('hidden', False),
            extra={k: v for k, v in data.items()
                   if k not in ('description', 'tags', 'highlight', 'hidden')}
        )

    def merge(self, other: 'Overlay') -> 'Overlay':
        """Merge two overlays, with other taking precedence."""
        return Overlay(
            description=other.description if other.description is not None else self.description,
            tags=self.tags | other.tags,
            highlight=other.highlight or self.highlight,
            hidden=other.hidden or self.hidden,
            extra={**self.extra, **other.extra}
        )


@dataclass(frozen=True)
class Annotation:
    """
    Narrative content attached to a repo or section in a view.

    Annotations add human context that isn't metadata:
    - Notes explaining why this repo is included
    - Section markers for grouping
    - Transition text between repos

    Example:
        Annotation(
            note="Start here - this introduces core concepts",
            section="Foundations",
            section_intro="The early experiments that shaped everything."
        )
    """
    note: Optional[str] = None           # Per-repo annotation
    section: Optional[str] = None        # Section this repo starts
    section_intro: Optional[str] = None  # Prose intro for the section

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        if self.note is not None:
            result['note'] = self.note
        if self.section is not None:
            result['section'] = self.section
        if self.section_intro is not None:
            result['section_intro'] = self.section_intro
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Annotation':
        """Create Annotation from dictionary."""
        return cls(
            note=data.get('note'),
            section=data.get('section'),
            section_intro=data.get('section_intro')
        )


@dataclass(frozen=True)
class ViewEntry:
    """
    A repository reference within a view, with its overlay and annotation.

    ViewEntry is the unit of a resolved view - it combines:
    - repo_ref: Name or path of the repository
    - overlay: View-local metadata overrides
    - annotation: Narrative content

    The actual Repository object is resolved at evaluation time.
    """
    repo_ref: str  # Repository name or path
    overlay: Overlay = field(default_factory=Overlay)
    annotation: Annotation = field(default_factory=Annotation)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {'repo': self.repo_ref}
        overlay_dict = self.overlay.to_dict()
        if overlay_dict:
            result['overlay'] = overlay_dict
        annotation_dict = self.annotation.to_dict()
        if annotation_dict:
            result['annotation'] = annotation_dict
        return result

    @classmethod
    def from_dict(cls, data: Union[str, Dict[str, Any]]) -> 'ViewEntry':
        """Create ViewEntry from dictionary or string."""
        if isinstance(data, str):
            return cls(repo_ref=data)
        return cls(
            repo_ref=data.get('repo', data.get('name', '')),
            overlay=Overlay.from_dict(data.get('overlay', {})),
            annotation=Annotation.from_dict(data.get('annotation', data))
        )


@dataclass(frozen=True)
class OrderSpec:
    """Specification for view ordering."""
    field: str = "name"
    direction: OrderDirection = OrderDirection.ASC

    def to_dict(self) -> Dict[str, Any]:
        return {
            'by': self.field,
            'direction': self.direction.value
        }

    @classmethod
    def from_dict(cls, data: Union[str, Dict[str, Any]]) -> 'OrderSpec':
        """Parse order specification."""
        if isinstance(data, str):
            # "name desc" or just "name"
            parts = data.split()
            field = parts[0]
            direction = OrderDirection.DESC if len(parts) > 1 and parts[1].lower() == 'desc' else OrderDirection.ASC
            return cls(field=field, direction=direction)
        return cls(
            field=data.get('by', data.get('field', 'name')),
            direction=OrderDirection(data.get('direction', 'asc'))
        )


@dataclass(frozen=True)
class ViewMetadata:
    """
    Top-level metadata for a view (narrative structure).

    This provides document-level context for archive export:
    - Title and author for the view as a document
    - Introduction and conclusion prose
    - Export configuration
    """
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    intro: Optional[str] = None
    conclusion: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    export_config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        for key in ('title', 'author', 'description', 'intro', 'conclusion',
                    'created_at', 'updated_at'):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.export_config:
            result['export'] = self.export_config
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ViewMetadata':
        return cls(
            title=data.get('title'),
            author=data.get('author'),
            description=data.get('description'),
            intro=data.get('intro'),
            conclusion=data.get('conclusion'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            export_config=data.get('export', {})
        )


# =============================================================================
# VIEW SPECIFICATION (DSL representation - unevaluated)
# =============================================================================

@dataclass(frozen=True)
class ViewSpec:
    """
    Unevaluated view specification from DSL.

    ViewSpec is the AST representation of a view definition.
    It describes HOW to compute a view, not the result.

    Evaluation resolves ViewSpec → View against the repository index.

    Types of ViewSpec:
    - Primitive: repos=["a", "b"], query="...", tags=["..."]
    - Composite: union=[spec1, spec2], intersect=[...], subtract={from: ..., remove: ...}
    - Reference: extends="other_view"
    - Parameterized: template="...", with={params}
    """
    name: str

    # Selection (one of these defines the base set)
    repos: Tuple[str, ...] = ()           # Explicit repo list
    query: Optional[str] = None           # Query expression
    tags: Tuple[str, ...] = ()            # Tag patterns

    # Composition (combines with base or replaces it)
    extends: Optional[str] = None         # Inherit from another view
    union: Tuple[str, ...] = ()           # Union with named views
    intersect: Tuple[str, ...] = ()       # Intersect with named views
    subtract: Tuple[str, ...] = ()        # Subtract named views

    # Modification
    include: Tuple[str, ...] = ()         # Force include repos
    exclude: Tuple[str, ...] = ()         # Force exclude repos/patterns

    # Ordering
    order: Optional[OrderSpec] = None     # Sort specification
    explicit_order: Tuple[str, ...] = ()  # Explicit ordering (overrides order)

    # Overlays and annotations (keyed by repo name)
    overlays: Dict[str, Overlay] = field(default_factory=dict)
    annotations: Dict[str, Annotation] = field(default_factory=dict)

    # View-level metadata
    metadata: ViewMetadata = field(default_factory=ViewMetadata)

    # Template instantiation
    template: Optional[str] = None        # Template name
    template_args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary (for YAML/JSON output)."""
        result: Dict[str, Any] = {}

        # Selection
        if self.repos:
            result['repos'] = list(self.repos)
        if self.query:
            result['query'] = self.query
        if self.tags:
            result['tags'] = list(self.tags)

        # Composition
        if self.extends:
            result['extends'] = self.extends
        if self.union:
            result['union'] = list(self.union)
        if self.intersect:
            result['intersect'] = list(self.intersect)
        if self.subtract:
            result['subtract'] = list(self.subtract)

        # Modification
        if self.include:
            result['include'] = list(self.include)
        if self.exclude:
            result['exclude'] = list(self.exclude)

        # Ordering
        if self.order:
            result['order'] = self.order.to_dict()
        if self.explicit_order:
            result['explicit_order'] = list(self.explicit_order)

        # Overlays and annotations
        if self.overlays:
            result['overlay'] = {k: v.to_dict() for k, v in self.overlays.items()}
        if self.annotations:
            result['annotate'] = {k: v.to_dict() for k, v in self.annotations.items()}

        # Metadata
        metadata_dict = self.metadata.to_dict()
        if metadata_dict:
            result.update(metadata_dict)

        # Template
        if self.template:
            result['from_template'] = self.template
            if self.template_args:
                result['with'] = self.template_args

        return result

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'ViewSpec':
        """Parse ViewSpec from dictionary."""
        # Parse overlays
        overlays = {}
        overlay_data = data.get('overlay', {})
        for repo_name, overlay_dict in overlay_data.items():
            overlays[repo_name] = Overlay.from_dict(overlay_dict)

        # Parse annotations
        annotations = {}
        annotate_data = data.get('annotate', data.get('annotations', {}))
        for repo_name, annot_dict in annotate_data.items():
            if isinstance(annot_dict, str):
                annotations[repo_name] = Annotation(note=annot_dict)
            else:
                annotations[repo_name] = Annotation.from_dict(annot_dict)

        # Parse order
        order = None
        if 'order' in data:
            order = OrderSpec.from_dict(data['order'])
        elif 'order_by' in data:
            order = OrderSpec.from_dict(data['order_by'])

        return cls(
            name=name,
            repos=tuple(data.get('repos', [])),
            query=data.get('query'),
            tags=tuple(data.get('tags', [])),
            extends=data.get('extends'),
            union=tuple(data.get('union', [])),
            intersect=tuple(data.get('intersect', [])),
            subtract=tuple(data.get('subtract', [])),
            include=tuple(data.get('include', [])),
            exclude=tuple(data.get('exclude', [])),
            order=order,
            explicit_order=tuple(data.get('explicit_order', data.get('sequence', []))),
            overlays=overlays,
            annotations=annotations,
            metadata=ViewMetadata.from_dict(data),
            template=data.get('from_template', data.get('template')),
            template_args=data.get('with', {})
        )

    def is_primitive(self) -> bool:
        """Check if this is a primitive view (no composition)."""
        return not (self.extends or self.union or self.intersect or self.subtract)

    def is_template_instantiation(self) -> bool:
        """Check if this view is created from a template."""
        return self.template is not None


# =============================================================================
# VIEW (evaluated, resolved)
# =============================================================================

@dataclass
class View:
    """
    A resolved, evaluated view - an ordered sequence of repositories.

    Unlike ViewSpec (which describes HOW to compute), View IS the result:
    - Ordered list of ViewEntries
    - Each entry has its repo resolved against the index
    - Overlays and annotations attached
    - Ready for export/rendering

    Views are mutable during construction but should be treated as
    immutable once fully built.
    """
    name: str
    entries: List[ViewEntry] = field(default_factory=list)
    metadata: ViewMetadata = field(default_factory=ViewMetadata)
    source_spec: Optional[ViewSpec] = None  # The spec that produced this view

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[ViewEntry]:
        return iter(self.entries)

    def __getitem__(self, index: int) -> ViewEntry:
        return self.entries[index]

    @property
    def repo_names(self) -> List[str]:
        """Get list of repository names in order."""
        return [e.repo_ref for e in self.entries]

    def contains(self, repo_ref: str) -> bool:
        """Check if view contains a repository."""
        return any(e.repo_ref == repo_ref for e in self.entries)

    def get_entry(self, repo_ref: str) -> Optional[ViewEntry]:
        """Get entry for a specific repo."""
        for entry in self.entries:
            if entry.repo_ref == repo_ref:
                return entry
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize view to dictionary."""
        return {
            'name': self.name,
            'entries': [e.to_dict() for e in self.entries],
            'metadata': self.metadata.to_dict(),
            'count': len(self.entries)
        }

    def to_jsonl(self) -> str:
        """Convert to single-line JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    # View algebra operations (return new View, preserving closure)

    def union(self, other: 'View', name: Optional[str] = None) -> 'View':
        """Combine with another view (A ∪ B)."""
        seen = set()
        entries = []
        for entry in self.entries:
            if entry.repo_ref not in seen:
                entries.append(entry)
                seen.add(entry.repo_ref)
        for entry in other.entries:
            if entry.repo_ref not in seen:
                entries.append(entry)
                seen.add(entry.repo_ref)
        return View(
            name=name or f"{self.name}|{other.name}",
            entries=entries
        )

    def intersect(self, other: 'View', name: Optional[str] = None) -> 'View':
        """Keep only repos in both views (A ∩ B), preserving self's order."""
        other_refs = {e.repo_ref for e in other.entries}
        entries = [e for e in self.entries if e.repo_ref in other_refs]
        return View(
            name=name or f"{self.name}&{other.name}",
            entries=entries
        )

    def subtract(self, other: 'View', name: Optional[str] = None) -> 'View':
        """Remove repos in other from self (A - B)."""
        other_refs = {e.repo_ref for e in other.entries}
        entries = [e for e in self.entries if e.repo_ref not in other_refs]
        return View(
            name=name or f"{self.name}-{other.name}",
            entries=entries
        )

    def filter(self, predicate) -> 'View':
        """Filter entries by predicate function."""
        entries = [e for e in self.entries if predicate(e)]
        return View(
            name=f"{self.name}:filtered",
            entries=entries,
            metadata=self.metadata
        )

    def reorder(self, key_func, reverse: bool = False) -> 'View':
        """Reorder entries by key function."""
        entries = sorted(self.entries, key=key_func, reverse=reverse)
        return View(
            name=self.name,
            entries=entries,
            metadata=self.metadata,
            source_spec=self.source_spec
        )

    def with_overlay(self, repo_ref: str, overlay: Overlay) -> 'View':
        """Apply overlay to a specific repo, returning new View."""
        entries = []
        for entry in self.entries:
            if entry.repo_ref == repo_ref:
                merged_overlay = entry.overlay.merge(overlay)
                entries.append(ViewEntry(
                    repo_ref=entry.repo_ref,
                    overlay=merged_overlay,
                    annotation=entry.annotation
                ))
            else:
                entries.append(entry)
        return View(
            name=self.name,
            entries=entries,
            metadata=self.metadata,
            source_spec=self.source_spec
        )

    def __str__(self) -> str:
        return f"View({self.name}, {len(self.entries)} repos)"

    def __repr__(self) -> str:
        return f"View(name={self.name!r}, entries={len(self.entries)})"


# =============================================================================
# TEMPLATE SUPPORT
# =============================================================================

@dataclass(frozen=True)
class ViewTemplate:
    """
    Parameterized view template.

    Templates allow reusable view patterns with variable substitution.

    Example:
        ViewTemplate(
            name="language-portfolio",
            params=("lang", "min_stars"),
            spec_template={
                "query": "language == '{lang}' and stars >= {min_stars}",
                "order": {"by": "stars", "direction": "desc"}
            }
        )
    """
    name: str
    params: Tuple[str, ...]
    spec_template: Dict[str, Any]
    defaults: Dict[str, Any] = field(default_factory=dict)

    def instantiate(self, args: Dict[str, Any]) -> ViewSpec:
        """
        Create a ViewSpec by substituting parameters.

        Args:
            args: Parameter values to substitute

        Returns:
            Instantiated ViewSpec
        """
        # Merge with defaults
        full_args = {**self.defaults, **args}

        # Check all required params are provided
        missing = set(self.params) - set(full_args.keys())
        if missing:
            raise ValueError(f"Missing template parameters: {missing}")

        # Deep substitute in spec_template
        substituted = self._substitute(self.spec_template, full_args)

        # Generate instance name
        instance_name = f"{self.name}[{','.join(f'{k}={v}' for k, v in args.items())}]"

        return ViewSpec.from_dict(instance_name, substituted)

    def _substitute(self, obj: Any, args: Dict[str, Any]) -> Any:
        """Recursively substitute {param} placeholders."""
        if isinstance(obj, str):
            result = obj
            for key, value in args.items():
                result = result.replace(f'{{{key}}}', str(value))
            return result
        elif isinstance(obj, dict):
            return {k: self._substitute(v, args) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._substitute(item, args) for item in obj]
        else:
            return obj

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'params': list(self.params),
            'defaults': self.defaults,
            **self.spec_template
        }

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'ViewTemplate':
        params = tuple(data.get('params', []))
        defaults = data.get('defaults', {})
        # Everything else is the spec template
        spec_template = {k: v for k, v in data.items()
                        if k not in ('params', 'defaults', 'name')}
        return cls(
            name=name,
            params=params,
            spec_template=spec_template,
            defaults=defaults
        )
