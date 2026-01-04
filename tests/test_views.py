"""Tests for the view system (domain and service)."""

import pytest
import json
import tempfile
import os
from pathlib import Path

from repoindex.domain.view import (
    View, ViewSpec, ViewEntry, ViewTemplate,
    Overlay, Annotation, ViewMetadata,
    OrderSpec, OrderDirection, ViewOperator
)
from repoindex.domain import Repository
from repoindex.services import ViewService


# =============================================================================
# Domain Layer Tests
# =============================================================================

class TestOverlay:
    """Tests for Overlay domain object."""

    def test_empty_overlay(self):
        """Test creating empty overlay."""
        overlay = Overlay()
        assert overlay.description is None
        assert overlay.tags == frozenset()
        assert overlay.highlight is False
        assert overlay.hidden is False

    def test_overlay_with_values(self):
        """Test creating overlay with values."""
        overlay = Overlay(
            description="Custom description",
            tags=frozenset(["teaching", "example"]),
            highlight=True,
            extra={"difficulty": "intermediate"}
        )
        assert overlay.description == "Custom description"
        assert "teaching" in overlay.tags
        assert overlay.highlight is True
        assert overlay.extra["difficulty"] == "intermediate"

    def test_overlay_to_dict(self):
        """Test serialization to dict."""
        overlay = Overlay(
            description="Test",
            tags=frozenset(["a", "b"]),
            highlight=True
        )
        d = overlay.to_dict()
        assert d['description'] == "Test"
        assert set(d['tags']) == {"a", "b"}
        assert d['highlight'] is True

    def test_overlay_from_dict(self):
        """Test creating overlay from dict."""
        overlay = Overlay.from_dict({
            'description': 'From dict',
            'tags': ['x', 'y'],
            'highlight': True,
            'custom_field': 'value'
        })
        assert overlay.description == 'From dict'
        assert overlay.tags == frozenset(['x', 'y'])
        assert overlay.extra['custom_field'] == 'value'

    def test_overlay_merge(self):
        """Test merging two overlays."""
        o1 = Overlay(description="First", tags=frozenset(["a"]))
        o2 = Overlay(description="Second", tags=frozenset(["b"]), highlight=True)
        merged = o1.merge(o2)

        assert merged.description == "Second"  # o2 takes precedence
        assert merged.tags == frozenset(["a", "b"])  # Union
        assert merged.highlight is True


class TestAnnotation:
    """Tests for Annotation domain object."""

    def test_empty_annotation(self):
        """Test creating empty annotation."""
        annotation = Annotation()
        assert annotation.note is None
        assert annotation.section is None

    def test_annotation_with_values(self):
        """Test creating annotation with values."""
        annotation = Annotation(
            note="Start here",
            section="Foundations",
            section_intro="The early work."
        )
        assert annotation.note == "Start here"
        assert annotation.section == "Foundations"

    def test_annotation_to_dict(self):
        """Test serialization."""
        annotation = Annotation(note="Test note")
        d = annotation.to_dict()
        assert d['note'] == "Test note"
        assert 'section' not in d  # None values omitted

    def test_annotation_from_dict(self):
        """Test creating from dict."""
        annotation = Annotation.from_dict({'note': 'From dict', 'section': 'S1'})
        assert annotation.note == 'From dict'
        assert annotation.section == 'S1'


class TestViewEntry:
    """Tests for ViewEntry domain object."""

    def test_simple_entry(self):
        """Test creating simple entry."""
        entry = ViewEntry(repo_ref="myrepo")
        assert entry.repo_ref == "myrepo"
        assert entry.overlay.description is None
        assert entry.annotation.note is None

    def test_entry_with_overlay_and_annotation(self):
        """Test entry with full details."""
        entry = ViewEntry(
            repo_ref="myrepo",
            overlay=Overlay(description="Custom"),
            annotation=Annotation(note="Important")
        )
        assert entry.overlay.description == "Custom"
        assert entry.annotation.note == "Important"

    def test_entry_from_string(self):
        """Test creating entry from just a string."""
        entry = ViewEntry.from_dict("myrepo")
        assert entry.repo_ref == "myrepo"

    def test_entry_from_dict(self):
        """Test creating entry from dict."""
        entry = ViewEntry.from_dict({
            'repo': 'myrepo',
            'overlay': {'description': 'Desc'},
            'note': 'Note'  # Annotation field
        })
        assert entry.repo_ref == 'myrepo'
        assert entry.overlay.description == 'Desc'
        assert entry.annotation.note == 'Note'


class TestOrderSpec:
    """Tests for OrderSpec domain object."""

    def test_default_order(self):
        """Test default ordering."""
        order = OrderSpec()
        assert order.field == "name"
        assert order.direction == OrderDirection.ASC

    def test_order_from_string(self):
        """Test parsing from string."""
        order = OrderSpec.from_dict("stars desc")
        assert order.field == "stars"
        assert order.direction == OrderDirection.DESC

    def test_order_from_dict(self):
        """Test parsing from dict."""
        order = OrderSpec.from_dict({'by': 'created_at', 'direction': 'desc'})
        assert order.field == "created_at"
        assert order.direction == OrderDirection.DESC


class TestViewSpec:
    """Tests for ViewSpec domain object."""

    def test_minimal_spec(self):
        """Test creating minimal spec."""
        spec = ViewSpec(name="test")
        assert spec.name == "test"
        assert spec.repos == ()
        assert spec.query is None

    def test_spec_with_repos(self):
        """Test spec with explicit repos."""
        spec = ViewSpec(name="test", repos=("repo1", "repo2"))
        assert spec.repos == ("repo1", "repo2")
        assert spec.is_primitive() is True

    def test_spec_with_composition(self):
        """Test spec with composition operators."""
        spec = ViewSpec(
            name="test",
            union=("view1", "view2"),
            subtract=("excluded",)
        )
        assert spec.is_primitive() is False
        assert spec.union == ("view1", "view2")

    def test_spec_from_dict(self):
        """Test creating spec from dict."""
        spec = ViewSpec.from_dict("myview", {
            'repos': ['a', 'b'],
            'query': "language == 'Python'",
            'title': 'My View',
            'overlay': {
                'a': {'description': 'Repo A'}
            }
        })
        assert spec.name == "myview"
        assert spec.repos == ('a', 'b')
        assert spec.query == "language == 'Python'"
        assert spec.metadata.title == 'My View'
        assert 'a' in spec.overlays
        assert spec.overlays['a'].description == 'Repo A'

    def test_spec_to_dict(self):
        """Test serialization."""
        spec = ViewSpec(
            name="test",
            repos=("a", "b"),
            query="test query"
        )
        d = spec.to_dict()
        assert d['repos'] == ['a', 'b']
        assert d['query'] == "test query"

    def test_spec_is_template_instantiation(self):
        """Test template detection."""
        spec = ViewSpec(name="test", template="lang-portfolio")
        assert spec.is_template_instantiation() is True

        spec2 = ViewSpec(name="test", repos=("a",))
        assert spec2.is_template_instantiation() is False


class TestView:
    """Tests for View domain object."""

    def test_empty_view(self):
        """Test creating empty view."""
        view = View(name="empty")
        assert len(view) == 0
        assert view.repo_names == []

    def test_view_with_entries(self):
        """Test view with entries."""
        entries = [
            ViewEntry(repo_ref="repo1"),
            ViewEntry(repo_ref="repo2"),
        ]
        view = View(name="test", entries=entries)
        assert len(view) == 2
        assert view.repo_names == ["repo1", "repo2"]

    def test_view_contains(self):
        """Test checking if view contains repo."""
        view = View(name="test", entries=[
            ViewEntry(repo_ref="repo1"),
            ViewEntry(repo_ref="repo2"),
        ])
        assert view.contains("repo1") is True
        assert view.contains("repo3") is False

    def test_view_get_entry(self):
        """Test getting specific entry."""
        view = View(name="test", entries=[
            ViewEntry(repo_ref="repo1", annotation=Annotation(note="First")),
            ViewEntry(repo_ref="repo2"),
        ])
        entry = view.get_entry("repo1")
        assert entry is not None
        assert entry.annotation.note == "First"

        assert view.get_entry("nonexistent") is None

    def test_view_iteration(self):
        """Test iterating over view."""
        view = View(name="test", entries=[
            ViewEntry(repo_ref="a"),
            ViewEntry(repo_ref="b"),
        ])
        names = [e.repo_ref for e in view]
        assert names == ["a", "b"]

    def test_view_indexing(self):
        """Test indexing into view."""
        view = View(name="test", entries=[
            ViewEntry(repo_ref="a"),
            ViewEntry(repo_ref="b"),
        ])
        assert view[0].repo_ref == "a"
        assert view[1].repo_ref == "b"

    def test_view_union(self):
        """Test union of two views."""
        v1 = View(name="v1", entries=[
            ViewEntry(repo_ref="a"),
            ViewEntry(repo_ref="b"),
        ])
        v2 = View(name="v2", entries=[
            ViewEntry(repo_ref="b"),  # Duplicate
            ViewEntry(repo_ref="c"),
        ])
        result = v1.union(v2)
        assert len(result) == 3
        assert result.repo_names == ["a", "b", "c"]  # Deduped, order preserved

    def test_view_intersect(self):
        """Test intersection of two views."""
        v1 = View(name="v1", entries=[
            ViewEntry(repo_ref="a"),
            ViewEntry(repo_ref="b"),
            ViewEntry(repo_ref="c"),
        ])
        v2 = View(name="v2", entries=[
            ViewEntry(repo_ref="b"),
            ViewEntry(repo_ref="c"),
            ViewEntry(repo_ref="d"),
        ])
        result = v1.intersect(v2)
        assert result.repo_names == ["b", "c"]  # Only common ones, v1's order

    def test_view_subtract(self):
        """Test subtraction of views."""
        v1 = View(name="v1", entries=[
            ViewEntry(repo_ref="a"),
            ViewEntry(repo_ref="b"),
            ViewEntry(repo_ref="c"),
        ])
        v2 = View(name="v2", entries=[
            ViewEntry(repo_ref="b"),
        ])
        result = v1.subtract(v2)
        assert result.repo_names == ["a", "c"]

    def test_view_filter(self):
        """Test filtering view with predicate."""
        view = View(name="test", entries=[
            ViewEntry(repo_ref="a", overlay=Overlay(highlight=True)),
            ViewEntry(repo_ref="b"),
            ViewEntry(repo_ref="c", overlay=Overlay(highlight=True)),
        ])
        highlighted = view.filter(lambda e: e.overlay.highlight)
        assert highlighted.repo_names == ["a", "c"]

    def test_view_with_overlay(self):
        """Test applying overlay to specific repo."""
        view = View(name="test", entries=[
            ViewEntry(repo_ref="a"),
            ViewEntry(repo_ref="b"),
        ])
        updated = view.with_overlay("a", Overlay(description="New desc"))
        assert updated.get_entry("a").overlay.description == "New desc"
        # Original unchanged
        assert view.get_entry("a").overlay.description is None

    def test_view_to_dict(self):
        """Test serialization."""
        view = View(
            name="test",
            entries=[ViewEntry(repo_ref="a")],
            metadata=ViewMetadata(title="Test View")
        )
        d = view.to_dict()
        assert d['name'] == "test"
        assert d['count'] == 1
        assert d['metadata']['title'] == "Test View"


class TestViewTemplate:
    """Tests for ViewTemplate domain object."""

    def test_template_creation(self):
        """Test creating template."""
        template = ViewTemplate(
            name="lang-portfolio",
            params=("lang",),
            spec_template={
                'query': "language == '{lang}'"
            }
        )
        assert template.name == "lang-portfolio"
        assert template.params == ("lang",)

    def test_template_instantiation(self):
        """Test instantiating template."""
        template = ViewTemplate(
            name="lang-portfolio",
            params=("lang", "min_stars"),
            spec_template={
                'query': "language == '{lang}' and stars >= {min_stars}",
                'order': {'by': 'stars', 'direction': 'desc'}
            },
            defaults={'min_stars': 0}
        )
        spec = template.instantiate({'lang': 'Python', 'min_stars': 10})
        assert "language == 'Python'" in spec.query
        assert "stars >= 10" in spec.query

    def test_template_missing_param(self):
        """Test error when required param missing."""
        template = ViewTemplate(
            name="test",
            params=("required_param",),
            spec_template={'query': "{required_param}"}
        )
        with pytest.raises(ValueError, match="Missing template parameters"):
            template.instantiate({})

    def test_template_defaults(self):
        """Test default parameter values."""
        template = ViewTemplate(
            name="test",
            params=("lang", "min_stars"),
            spec_template={'query': "{lang} {min_stars}"},
            defaults={'min_stars': 0}
        )
        spec = template.instantiate({'lang': 'Python'})
        assert "Python 0" in spec.query

    def test_template_from_dict(self):
        """Test creating template from dict."""
        template = ViewTemplate.from_dict("test", {
            'params': ['lang'],
            'defaults': {'min_stars': 0},
            'query': "language == '{lang}'"
        })
        assert template.name == "test"
        assert template.params == ("lang",)
        assert template.defaults['min_stars'] == 0


# =============================================================================
# Service Layer Tests
# =============================================================================

class TestViewService:
    """Tests for ViewService."""

    @pytest.fixture
    def temp_views_file(self):
        """Create a temporary views file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""views:
  portfolio:
    repos: [repoindex, ctk, btk]
    title: "My Portfolio"

  python-libs:
    query: "language == 'Python'"
    order:
      by: stars
      direction: desc

  combined:
    union: [portfolio, python-libs]
    exclude: ["*-wip"]

templates:
  lang-view:
    params: [lang]
    query: "language == '{lang}'"
""")
            temp_path = f.name
        # File is now closed and flushed
        yield temp_path
        os.unlink(temp_path)

    @pytest.fixture
    def mock_repos(self):
        """Create mock repositories."""
        return [
            Repository(path="/path/repoindex", name="repoindex", language="Python"),
            Repository(path="/path/ctk", name="ctk", language="Python"),
            Repository(path="/path/btk", name="btk", language="Python"),
            Repository(path="/path/rust-tool", name="rust-tool", language="Rust"),
            Repository(path="/path/test-wip", name="test-wip", language="Python"),
        ]

    @pytest.fixture
    def repo_lookup(self, mock_repos):
        """Create repo lookup function."""
        repo_map = {r.name: r for r in mock_repos}
        return lambda ref: repo_map.get(ref)

    def test_load_views(self, temp_views_file):
        """Test loading views from file."""
        service = ViewService(views_path=temp_views_file)
        service.load()

        assert "portfolio" in service.list_views()
        assert "python-libs" in service.list_views()
        assert "combined" in service.list_views()
        assert "lang-view" in service.list_templates()

    def test_get_spec(self, temp_views_file):
        """Test getting view spec."""
        service = ViewService(views_path=temp_views_file)
        service.load()

        spec = service.get_spec("portfolio")
        assert spec is not None
        assert spec.repos == ("repoindex", "ctk", "btk")

    def test_evaluate_explicit_repos(self, temp_views_file, repo_lookup, mock_repos):
        """Test evaluating view with explicit repos."""
        service = ViewService(views_path=temp_views_file)
        service.load()

        view = service.evaluate("portfolio", repo_lookup, mock_repos)
        assert view is not None
        assert len(view) == 3
        assert view.repo_names == ["repoindex", "ctk", "btk"]

    def test_evaluate_with_exclude(self, temp_views_file, repo_lookup, mock_repos):
        """Test evaluating view with exclude patterns."""
        service = ViewService(views_path=temp_views_file)
        service.load()

        view = service.evaluate("combined", repo_lookup, mock_repos)
        # Should have union of portfolio + python-libs, minus *-wip
        assert "test-wip" not in view.repo_names

    def test_views_containing(self, temp_views_file, repo_lookup, mock_repos):
        """Test finding views containing a repo."""
        service = ViewService(views_path=temp_views_file)
        service.load()

        # Evaluate views to populate cache
        service.evaluate("portfolio", repo_lookup, mock_repos)

        containing = service.views_containing("repoindex")
        assert "portfolio" in containing

    def test_add_and_save(self):
        """Test adding spec and saving."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("views: {}")
            temp_path = f.name

        try:
            service = ViewService(views_path=temp_path)
            service.load()

            spec = ViewSpec(name="new-view", repos=("a", "b"))
            service.add_spec(spec)
            service.save()

            # Reload and verify
            service2 = ViewService(views_path=temp_path)
            service2.load()
            assert "new-view" in service2.list_views()
        finally:
            os.unlink(temp_path)

    def test_remove_spec(self, temp_views_file):
        """Test removing a spec."""
        service = ViewService(views_path=temp_views_file)
        service.load()

        assert "portfolio" in service.list_views()
        result = service.remove_spec("portfolio")
        assert result is True
        assert "portfolio" not in service.list_views()

    def test_create_view_from_repos(self):
        """Test convenience method for creating views."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("views: {}")
            temp_path = f.name

        try:
            service = ViewService(views_path=temp_path)
            service.load()

            spec = service.create_view_from_repos(
                "quick-view",
                ["repo1", "repo2"],
                title="Quick View",
                description="A quick view"
            )

            assert spec.name == "quick-view"
            assert spec.repos == ("repo1", "repo2")
            assert spec.metadata.title == "Quick View"
        finally:
            os.unlink(temp_path)

    def test_cache_invalidation(self, temp_views_file, repo_lookup, mock_repos):
        """Test cache invalidation."""
        service = ViewService(views_path=temp_views_file)
        service.load()

        # Evaluate to populate cache
        service.evaluate("portfolio", repo_lookup, mock_repos)
        assert "portfolio" in service._cache

        # Invalidate specific
        service.invalidate_cache("portfolio")
        assert "portfolio" not in service._cache

        # Evaluate again
        service.evaluate("portfolio", repo_lookup, mock_repos)
        service.evaluate("python-libs", repo_lookup, mock_repos)

        # Invalidate all
        service.invalidate_cache()
        assert len(service._cache) == 0

    def test_empty_views_file(self):
        """Test handling of missing views file."""
        service = ViewService(views_path="/nonexistent/path.yaml")
        service.load()  # Should not raise
        assert service.list_views() == []

    def test_template_instantiation_via_service(self, temp_views_file, repo_lookup, mock_repos):
        """Test evaluating a view that uses a template."""
        service = ViewService(views_path=temp_views_file)
        service.load()

        # Add a view that uses the template
        spec = ViewSpec(
            name="rust-view",
            template="lang-view",
            template_args={'lang': 'Rust'}
        )
        service.add_spec(spec)

        view = service.evaluate("rust-view", repo_lookup, mock_repos)
        assert view is not None
        # Should contain rust-tool (our mock Rust repo)
        assert "rust-tool" in view.repo_names


class TestViewServiceExtends:
    """Tests for view inheritance via extends."""

    @pytest.fixture
    def service_with_extends(self):
        """Create service with views that extend each other."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""views:
  base:
    repos: [a, b, c]

  extended:
    extends: base
    include: [d]
    exclude: [a]

  deeply-extended:
    extends: extended
    include: [e]
""")
            temp_path = f.name
        # File is now closed and flushed
        service = ViewService(views_path=temp_path)
        service.load()
        yield service
        os.unlink(temp_path)

    @pytest.fixture
    def mock_repos(self):
        return [
            Repository(path=f"/path/{name}", name=name)
            for name in ["a", "b", "c", "d", "e"]
        ]

    @pytest.fixture
    def repo_lookup(self, mock_repos):
        repo_map = {r.name: r for r in mock_repos}
        return lambda ref: repo_map.get(ref)

    def test_extends_basic(self, service_with_extends, repo_lookup, mock_repos):
        """Test basic extension."""
        view = service_with_extends.evaluate("extended", repo_lookup, mock_repos)
        # base has [a, b, c], extended excludes [a] and includes [d]
        assert set(view.repo_names) == {"b", "c", "d"}

    def test_extends_chain(self, service_with_extends, repo_lookup, mock_repos):
        """Test chained extension."""
        view = service_with_extends.evaluate("deeply-extended", repo_lookup, mock_repos)
        # extended has [b, c, d], deeply-extended adds [e]
        assert set(view.repo_names) == {"b", "c", "d", "e"}


class TestViewServiceOrder:
    """Tests for view ordering."""

    @pytest.fixture
    def mock_repos(self):
        return [
            Repository(path="/path/a", name="a"),
            Repository(path="/path/b", name="b"),
            Repository(path="/path/c", name="c"),
        ]

    @pytest.fixture
    def repo_lookup(self, mock_repos):
        repo_map = {r.name: r for r in mock_repos}
        return lambda ref: repo_map.get(ref)

    def test_explicit_order(self, repo_lookup, mock_repos):
        """Test explicit ordering."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""views:
  ordered:
    repos: [a, b, c]
    explicit_order: [c, a, b]
""")
            temp_path = f.name
        # File is now closed and flushed
        service = ViewService(views_path=temp_path)
        service.load()

        view = service.evaluate("ordered", repo_lookup, mock_repos)
        assert view.repo_names == ["c", "a", "b"]

        os.unlink(temp_path)
