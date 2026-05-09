"""Tests for the Source ABC hierarchy and discovery (Wave V2.A).

The legacy ``MetadataSource`` was replaced by:

    Source (ABC)
      LocalScanner       (citation_cff, keywords, local_assets)
      RemoteSource
        GitForge         (github, gitea)
        Registry         (pypi, cran, zenodo, npm, cargo, conda, docker,
                          rubygems, go)

The data destination during refresh is implicit in the subclass:
LocalScanner and GitForge populate the repos table; Registry populates
publications. The ``target`` discriminator is gone.
"""
import pytest


# ---------------------------------------------------------------------------
# ABC behavior
# ---------------------------------------------------------------------------

class TestSourceABC:
    def test_cannot_instantiate_abstract_source(self):
        from repoindex.sources import Source
        with pytest.raises(TypeError):
            Source()

    def test_cannot_instantiate_abstract_localscanner(self):
        from repoindex.sources import LocalScanner
        with pytest.raises(TypeError):
            LocalScanner()

    def test_cannot_instantiate_abstract_remotesource(self):
        from repoindex.sources import RemoteSource
        with pytest.raises(TypeError):
            RemoteSource()

    def test_cannot_instantiate_abstract_gitforge(self):
        from repoindex.sources import GitForge
        with pytest.raises(TypeError):
            GitForge()

    def test_cannot_instantiate_abstract_registry(self):
        from repoindex.sources import Registry
        with pytest.raises(TypeError):
            Registry()

    def test_localscanner_concrete(self):
        from repoindex.sources import LocalScanner

        class FakeScanner(LocalScanner):
            source_id = "fake_scanner"
            name = "Fake Scanner"

            def detect(self, repo_path, repo_record=None):
                return True

            def fetch(self, repo_path, repo_record=None, config=None):
                return {'foo': 1}

        s = FakeScanner()
        assert s.source_id == "fake_scanner"
        assert s.detect("/repo")
        assert s.fetch("/repo") == {'foo': 1}

    def test_gitforge_concrete(self):
        from repoindex.sources import GitForge

        class FakeForge(GitForge):
            source_id = "fake_forge"
            name = "Fake Forge"

            def detect(self, repo_path, repo_record=None):
                return True

            def fetch(self, repo_path, repo_record=None, config=None):
                return {'fake_stars': 42}

        f = FakeForge()
        assert f.source_id == "fake_forge"
        assert f.fetch("/repo") == {'fake_stars': 42}

    def test_registry_concrete(self):
        from repoindex.sources import Registry

        class FakeRegistry(Registry):
            source_id = "fake_registry"
            name = "Fake Registry"

            def detect(self, repo_path, repo_record=None):
                return True

            def fetch(self, repo_path, repo_record=None, config=None):
                return {'registry': 'fake', 'name': 'pkg', 'published': True}

        r = FakeRegistry()
        assert r.fetch("/repo") == {'registry': 'fake', 'name': 'pkg', 'published': True}
        assert r.batch is False

    def test_registry_batch_flag(self):
        from repoindex.sources import Registry

        class BatchReg(Registry):
            source_id = "batch_reg"
            name = "Batch"
            batch = True
            _called = False

            def detect(self, repo_path, repo_record=None):
                return True

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

            def prefetch(self, config):
                self._called = True

        r = BatchReg()
        assert r.batch is True
        r.prefetch({})
        assert r._called is True

    def test_partial_implementation_raises(self):
        from repoindex.sources import LocalScanner

        class Partial(LocalScanner):
            source_id = "partial"
            name = "Partial"

            def detect(self, repo_path, repo_record=None):
                return True
            # Missing fetch()

        with pytest.raises(TypeError):
            Partial()

    def test_default_prefetch_is_noop(self):
        from repoindex.sources import LocalScanner

        class Min(LocalScanner):
            source_id = "min"
            name = "Min"

            def detect(self, repo_path, repo_record=None):
                return False

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        Min().prefetch({})  # must not raise

    def test_source_id_and_name_defaults(self):
        from repoindex.sources import LocalScanner

        class Bare(LocalScanner):
            def detect(self, repo_path, repo_record=None):
                return False

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        s = Bare()
        assert s.source_id == ""
        assert s.name == ""

    def test_subclass_isinstance_chain(self):
        """LocalScanner / GitForge / Registry are all Source subclasses."""
        from repoindex.sources import (
            Source, LocalScanner, RemoteSource, GitForge, Registry,
        )
        assert issubclass(LocalScanner, Source)
        assert issubclass(RemoteSource, Source)
        assert issubclass(GitForge, RemoteSource)
        assert issubclass(GitForge, Source)
        assert issubclass(Registry, RemoteSource)
        assert issubclass(Registry, Source)
        # GitForge and Registry are sibling roles, not parent/child
        assert not issubclass(GitForge, Registry)
        assert not issubclass(Registry, GitForge)


# ---------------------------------------------------------------------------
# Wave V2.A invariants on built-in sources
# ---------------------------------------------------------------------------

class TestBuiltinSourcesHierarchy:
    """Every built-in source must subclass one of the three role ABCs and
    must not carry the legacy ``target`` attribute."""

    def test_all_builtin_sources_are_typed(self):
        """Every built-in source must be a LocalScanner, GitForge, or Registry."""
        from repoindex.sources import (
            discover_sources, LocalScanner, GitForge, Registry,
        )
        sources = discover_sources()
        for s in sources:
            assert isinstance(s, (LocalScanner, GitForge, Registry)), (
                f"{s.source_id} is not a LocalScanner / GitForge / Registry "
                f"(type={type(s).__name__})"
            )

    def test_no_source_has_target_attribute(self):
        """Wave V2.A: target field is removed."""
        from repoindex.sources import discover_sources
        sources = discover_sources()
        for s in sources:
            # Neither the class itself nor any base in the MRO should define
            # a class-level ``target`` attribute.
            for klass in type(s).__mro__:
                assert 'target' not in klass.__dict__, (
                    f"{type(s).__name__} or one of its bases defines target"
                )

    def test_localscanner_examples(self):
        """citation_cff, keywords, local_assets are LocalScanner."""
        from repoindex.sources import discover_sources, LocalScanner
        sources = {s.source_id: s for s in discover_sources()}
        for sid in ('citation_cff', 'keywords', 'local_assets'):
            assert sid in sources
            assert isinstance(sources[sid], LocalScanner), (
                f"{sid} should be a LocalScanner, got {type(sources[sid]).__name__}"
            )

    def test_gitforge_examples(self):
        """github, gitea are GitForge."""
        from repoindex.sources import discover_sources, GitForge
        sources = {s.source_id: s for s in discover_sources()}
        for sid in ('github', 'gitea'):
            assert sid in sources
            assert isinstance(sources[sid], GitForge), (
                f"{sid} should be a GitForge, got {type(sources[sid]).__name__}"
            )

    def test_registry_examples(self):
        """pypi, cran, zenodo are Registry."""
        from repoindex.sources import discover_sources, Registry
        sources = {s.source_id: s for s in discover_sources()}
        for sid in ('pypi', 'cran', 'zenodo'):
            assert sid in sources
            assert isinstance(sources[sid], Registry), (
                f"{sid} should be a Registry, got {type(sources[sid]).__name__}"
            )

    def test_zenodo_is_batch(self):
        """zenodo Registry has batch=True."""
        from repoindex.sources import discover_sources
        sources = {s.source_id: s for s in discover_sources()}
        assert sources['zenodo'].batch is True

    def test_pypi_is_not_batch(self):
        """pypi Registry has batch=False (only zenodo is batch)."""
        from repoindex.sources import discover_sources
        sources = {s.source_id: s for s in discover_sources()}
        assert sources['pypi'].batch is False


class TestGitForgeOptionalCapabilities:
    """The GitForge optional write capabilities raise NotImplementedError by
    default. Wave V2.C wires real implementations on github + gitea.
    """

    def _make_minimal_forge(self):
        from repoindex.sources import GitForge

        class Empty(GitForge):
            source_id = "empty_forge"
            name = "Empty Forge"

            def detect(self, repo_path, repo_record=None):
                return False

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        return Empty()

    def test_enumerate_user_repos_raises(self):
        f = self._make_minimal_forge()
        with pytest.raises(NotImplementedError):
            list(f.enumerate_user_repos({}))

    def test_set_topics_raises(self):
        f = self._make_minimal_forge()
        with pytest.raises(NotImplementedError):
            f.set_topics({}, ['x'], {})

    def test_set_description_raises(self):
        f = self._make_minimal_forge()
        with pytest.raises(NotImplementedError):
            f.set_description({}, 'desc', {})

    def test_set_archived_raises(self):
        f = self._make_minimal_forge()
        with pytest.raises(NotImplementedError):
            f.set_archived({}, True, {})

    def test_set_visibility_raises(self):
        f = self._make_minimal_forge()
        with pytest.raises(NotImplementedError):
            f.set_visibility({}, True, {})

    def test_set_default_branch_raises(self):
        f = self._make_minimal_forge()
        with pytest.raises(NotImplementedError):
            f.set_default_branch({}, 'main', {})

    def test_enable_pages_raises(self):
        f = self._make_minimal_forge()
        with pytest.raises(NotImplementedError):
            f.enable_pages({}, 'main', '/', {})

    def test_gitforge_optional_methods_raise(self):
        """Default GitForge methods raise NotImplementedError until V2.C.

        Roll-up assertion in the same shape as the wave plan.
        """
        f = self._make_minimal_forge()
        method_calls = [
            lambda: list(f.enumerate_user_repos({})),
            lambda: f.set_topics({}, [], {}),
            lambda: f.set_description({}, '', {}),
            lambda: f.set_archived({}, True, {}),
            lambda: f.set_visibility({}, True, {}),
            lambda: f.set_default_branch({}, 'main', {}),
            lambda: f.enable_pages({}, 'main', '/', {}),
        ]
        for call in method_calls:
            with pytest.raises(NotImplementedError):
                call()


class TestRegistryOptionalCapabilities:
    def test_enumerate_user_packages_raises(self):
        from repoindex.sources import Registry

        class Empty(Registry):
            source_id = "empty_reg"
            name = "Empty Registry"

            def detect(self, repo_path, repo_record=None):
                return False

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        with pytest.raises(NotImplementedError):
            list(Empty().enumerate_user_packages({}))


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class TestRemoteRepoDataclass:
    def test_minimum_fields(self):
        from repoindex.sources import RemoteRepo
        r = RemoteRepo(name='repo', clone_url='https://example.com/r.git')
        assert r.name == 'repo'
        assert r.clone_url == 'https://example.com/r.git'
        assert r.default_branch is None
        assert r.is_archived is False
        assert r.description is None

    def test_all_fields(self):
        from repoindex.sources import RemoteRepo
        r = RemoteRepo(
            name='repo', clone_url='https://example.com/r.git',
            default_branch='main', is_archived=True, description='hi',
        )
        assert r.default_branch == 'main'
        assert r.is_archived is True
        assert r.description == 'hi'

    def test_frozen(self):
        from repoindex.sources import RemoteRepo
        from dataclasses import FrozenInstanceError
        r = RemoteRepo(name='r', clone_url='u')
        with pytest.raises(FrozenInstanceError):
            r.name = 'other'


class TestRemotePackageDataclass:
    def test_minimum_fields(self):
        from repoindex.sources import RemotePackage
        p = RemotePackage(name='pkg')
        assert p.name == 'pkg'
        assert p.version is None
        assert p.url is None

    def test_frozen(self):
        from repoindex.sources import RemotePackage
        from dataclasses import FrozenInstanceError
        p = RemotePackage(name='pkg')
        with pytest.raises(FrozenInstanceError):
            p.name = 'other'


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscoverSources:
    def test_returns_list(self):
        from repoindex.sources import discover_sources
        result = discover_sources()
        assert isinstance(result, list)

    def test_only_filter(self):
        from repoindex.sources import discover_sources
        result = discover_sources(only=['nonexistent'])
        assert result == []

    def test_user_source_loaded_from_scanners(self, tmp_path):
        from repoindex.sources import discover_sources
        # User scanners go under sources/scanners/ now (Wave V2.A).
        scanners_dir = tmp_path / "scanners"
        scanners_dir.mkdir()
        (scanners_dir / "my_source.py").write_text('''
from repoindex.sources import LocalScanner

class MySource(LocalScanner):
    source_id = "mysource"
    name = "My Source"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = MySource()
''')
        result = discover_sources(user_dir=str(tmp_path))
        ids = [s.source_id for s in result]
        assert "mysource" in ids

    def test_user_source_loaded_from_forges(self, tmp_path):
        from repoindex.sources import discover_sources, GitForge
        forges_dir = tmp_path / "forges"
        forges_dir.mkdir()
        (forges_dir / "my_forge.py").write_text('''
from repoindex.sources import GitForge

class MyForge(GitForge):
    source_id = "myforge"
    name = "My Forge"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = MyForge()
''')
        result = discover_sources(user_dir=str(tmp_path))
        forge = next((s for s in result if s.source_id == "myforge"), None)
        assert forge is not None
        assert isinstance(forge, GitForge)

    def test_user_source_loaded_from_registries(self, tmp_path):
        from repoindex.sources import discover_sources, Registry
        registries_dir = tmp_path / "registries"
        registries_dir.mkdir()
        (registries_dir / "my_reg.py").write_text('''
from repoindex.sources import Registry

class MyReg(Registry):
    source_id = "myreg"
    name = "My Reg"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = MyReg()
''')
        result = discover_sources(user_dir=str(tmp_path))
        reg = next((s for s in result if s.source_id == "myreg"), None)
        assert reg is not None
        assert isinstance(reg, Registry)

    def test_flat_user_dir_does_not_load_sources(self, tmp_path):
        """Flat ~/.repoindex/sources/*.py path is gone in V2.A; sources must
        live under scanners/, forges/, or registries/.
        """
        from repoindex.sources import discover_sources
        # Drop a source directly in the user_dir (not in any subdir)
        (tmp_path / "loose.py").write_text('''
from repoindex.sources import LocalScanner

class LooseSource(LocalScanner):
    source_id = "loose"
    name = "Loose"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = LooseSource()
''')
        result = discover_sources(user_dir=str(tmp_path))
        assert "loose" not in [s.source_id for s in result]

    def test_user_source_with_only_filter(self, tmp_path):
        from repoindex.sources import discover_sources
        scanners_dir = tmp_path / "scanners"
        scanners_dir.mkdir()
        (scanners_dir / "my_source.py").write_text('''
from repoindex.sources import LocalScanner

class MySource(LocalScanner):
    source_id = "mysource"
    name = "My Source"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = MySource()
''')
        result = discover_sources(user_dir=str(tmp_path), only=['mysource'])
        assert len(result) == 1
        result = discover_sources(user_dir=str(tmp_path), only=['other'])
        assert len(result) == 0

    def test_broken_user_source_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        scanners_dir = tmp_path / "scanners"
        scanners_dir.mkdir()
        (scanners_dir / "broken.py").write_text("raise ImportError('broken')")
        result = discover_sources(user_dir=str(tmp_path))
        assert isinstance(result, list)  # No crash

    def test_underscore_files_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        scanners_dir = tmp_path / "scanners"
        scanners_dir.mkdir()
        (scanners_dir / "__init__.py").write_text("")
        (scanners_dir / "_helper.py").write_text("")
        result = discover_sources(user_dir=str(tmp_path))
        assert isinstance(result, list)

    def test_nonexistent_user_dir(self, tmp_path):
        from repoindex.sources import discover_sources
        result = discover_sources(user_dir=str(tmp_path / 'nope'))
        assert isinstance(result, list)

    def test_module_without_source_attr_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        scanners_dir = tmp_path / "scanners"
        scanners_dir.mkdir()
        (scanners_dir / "no_attr.py").write_text("x = 42\n")
        result = discover_sources(user_dir=str(tmp_path))
        assert all(s.source_id != "" for s in result)

    def test_non_source_attr_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        scanners_dir = tmp_path / "scanners"
        scanners_dir.mkdir()
        (scanners_dir / "wrong_type.py").write_text("source = 'not a Source'\n")
        result = discover_sources(user_dir=str(tmp_path))
        assert all(s.source_id != 'wrong_type' for s in result)

    def test_syntax_error_in_user_source_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        scanners_dir = tmp_path / "scanners"
        scanners_dir.mkdir()
        (scanners_dir / "bad_syntax.py").write_text("def broken(\n")
        result = discover_sources(user_dir=str(tmp_path))
        assert isinstance(result, list)

    def test_non_py_files_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        scanners_dir = tmp_path / "scanners"
        scanners_dir.mkdir()
        (scanners_dir / "readme.txt").write_text("not a source")
        (scanners_dir / "data.json").write_text("{}")
        result = discover_sources(user_dir=str(tmp_path))
        assert all(s.source_id not in ('readme', 'data') for s in result)


class TestLoadSourcesFromDirectory:
    """Tests for the internal _load_sources_from_directory helper."""

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        from repoindex.sources import _load_sources_from_directory
        result = _load_sources_from_directory(
            str(tmp_path / "nope"), "test", ["source"]
        )
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path):
        from repoindex.sources import _load_sources_from_directory
        d = tmp_path / "empty"
        d.mkdir()
        result = _load_sources_from_directory(str(d), "test", ["source"])
        assert result == []

    def test_loads_source_attribute(self, tmp_path):
        from repoindex.sources import _load_sources_from_directory
        d = tmp_path / "dir"
        d.mkdir()
        (d / "my.py").write_text('''
from repoindex.sources import LocalScanner

class M(LocalScanner):
    source_id = "m"
    name = "M"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = M()
''')
        result = _load_sources_from_directory(str(d), "test", ["source"])
        assert len(result) == 1
        assert result[0].source_id == "m"

    def test_attribute_priority_order(self, tmp_path):
        """First matching attribute wins."""
        from repoindex.sources import _load_sources_from_directory
        d = tmp_path / "dir"
        d.mkdir()
        (d / "multi.py").write_text('''
from repoindex.sources import LocalScanner

class A(LocalScanner):
    source_id = "from_source"
    name = "A"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

class B(LocalScanner):
    source_id = "from_provider"
    name = "B"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = A()
provider = B()
''')
        result = _load_sources_from_directory(
            str(d), "test", ["source", "provider"]
        )
        assert len(result) == 1
        assert result[0].source_id == "from_source"

    def test_sorted_loading_order(self, tmp_path):
        """Files are loaded in sorted order."""
        from repoindex.sources import _load_sources_from_directory
        d = tmp_path / "dir"
        d.mkdir()
        for name in ("zz", "aa", "mm"):
            (d / f"{name}.py").write_text(f'''
from repoindex.sources import LocalScanner

class S(LocalScanner):
    source_id = "{name}"
    name = "{name}"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = S()
''')
        result = _load_sources_from_directory(str(d), "test", ["source"])
        ids = [s.source_id for s in result]
        assert ids == ["aa", "mm", "zz"]


class TestBuiltinSourcesDiscovery:
    """Test that discover_sources() finds built-in sources after the v2.A
    relocation under scanners/, forges/, registries/."""

    def test_discovers_github_forge(self):
        from repoindex.sources import discover_sources
        sources = discover_sources()
        ids = [s.source_id for s in sources]
        assert 'github' in ids

    def test_discovers_pypi_registry(self):
        from repoindex.sources import discover_sources
        sources = discover_sources()
        ids = [s.source_id for s in sources]
        assert 'pypi' in ids

    def test_discovers_cran_registry(self):
        from repoindex.sources import discover_sources
        sources = discover_sources()
        ids = [s.source_id for s in sources]
        assert 'cran' in ids

    def test_discovers_citation_cff_scanner(self):
        from repoindex.sources import discover_sources
        sources = discover_sources()
        ids = [s.source_id for s in sources]
        assert 'citation_cff' in ids

    def test_only_filter_works(self):
        from repoindex.sources import discover_sources
        sources = discover_sources(only=['github', 'pypi'])
        ids = {s.source_id for s in sources}
        assert ids == {'github', 'pypi'}

    def test_full_builtin_set_present(self):
        """All 14 built-in sources must be discovered after relocation."""
        from repoindex.sources import discover_sources
        ids = {s.source_id for s in discover_sources()}
        expected = {
            'citation_cff', 'keywords', 'local_assets',           # scanners
            'github', 'gitea',                                    # forges
            'pypi', 'cran', 'zenodo', 'npm', 'cargo',            # registries
            'conda', 'docker', 'rubygems', 'go',                 # registries
        }
        assert expected.issubset(ids)
