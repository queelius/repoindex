"""Tests for MetadataSource ABC and discovery."""
import os
import pytest
from unittest.mock import MagicMock


class TestMetadataSourceABC:
    def test_cannot_instantiate_abstract(self):
        from repoindex.sources import MetadataSource
        with pytest.raises(TypeError):
            MetadataSource()

    def test_repos_target_source(self):
        from repoindex.sources import MetadataSource

        class FakeRepoSource(MetadataSource):
            source_id = "fake_repo"
            name = "Fake Repo Source"
            target = "repos"
            def detect(self, repo_path, repo_record=None):
                return True
            def fetch(self, repo_path, repo_record=None, config=None):
                return {'fake_stars': 42}

        s = FakeRepoSource()
        assert s.source_id == "fake_repo"
        assert s.target == "repos"
        assert s.detect("/repo")
        assert s.fetch("/repo") == {'fake_stars': 42}

    def test_publications_target_source(self):
        from repoindex.sources import MetadataSource

        class FakePubSource(MetadataSource):
            source_id = "fake_pub"
            name = "Fake Publication Source"
            target = "publications"
            def detect(self, repo_path, repo_record=None):
                return True
            def fetch(self, repo_path, repo_record=None, config=None):
                return {'registry': 'fake', 'name': 'pkg', 'published': True}

        s = FakePubSource()
        assert s.target == "publications"
        result = s.fetch("/repo")
        assert result['registry'] == 'fake'

    def test_default_target_is_repos(self):
        from repoindex.sources import MetadataSource

        class MinimalSource(MetadataSource):
            source_id = "min"
            name = "Minimal"
            def detect(self, repo_path, repo_record=None):
                return False
            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        assert MinimalSource().target == "repos"

    def test_default_batch_is_false(self):
        from repoindex.sources import MetadataSource

        class MinimalSource(MetadataSource):
            source_id = "min"
            name = "Minimal"
            def detect(self, repo_path, repo_record=None):
                return False
            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        assert MinimalSource().batch is False

    def test_prefetch_default_is_noop(self):
        from repoindex.sources import MetadataSource

        class MinimalSource(MetadataSource):
            source_id = "min"
            name = "Minimal"
            def detect(self, repo_path, repo_record=None):
                return False
            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        # Should not raise
        MinimalSource().prefetch({})

    def test_batch_source(self):
        from repoindex.sources import MetadataSource

        class BatchSource(MetadataSource):
            source_id = "batch"
            name = "Batch Source"
            target = "publications"
            batch = True
            _prefetched = False
            def detect(self, repo_path, repo_record=None):
                return True
            def fetch(self, repo_path, repo_record=None, config=None):
                return {'registry': 'batch', 'name': 'pkg'}
            def prefetch(self, config):
                self._prefetched = True

        s = BatchSource()
        assert s.batch is True
        s.prefetch({})
        assert s._prefetched is True

    def test_partial_implementation_raises(self):
        from repoindex.sources import MetadataSource

        class PartialSource(MetadataSource):
            source_id = "partial"
            name = "Partial"
            def detect(self, repo_path, repo_record=None):
                return True
            # Missing fetch()

        with pytest.raises(TypeError):
            PartialSource()

    def test_detect_receives_repo_record(self):
        from repoindex.sources import MetadataSource

        class RecordSource(MetadataSource):
            source_id = "record"
            name = "Record Source"
            def detect(self, repo_path, repo_record=None):
                return repo_record is not None and 'remote_url' in repo_record
            def fetch(self, repo_path, repo_record=None, config=None):
                return {'enriched': True}

        s = RecordSource()
        assert not s.detect("/repo")
        assert not s.detect("/repo", repo_record={})
        assert s.detect("/repo", repo_record={'remote_url': 'https://...'})

    def test_fetch_receives_config(self):
        from repoindex.sources import MetadataSource

        class ConfigSource(MetadataSource):
            source_id = "cfg"
            name = "Config Source"
            def detect(self, repo_path, repo_record=None):
                return True
            def fetch(self, repo_path, repo_record=None, config=None):
                if config and config.get('token'):
                    return {'authed': True}
                return {'authed': False}

        s = ConfigSource()
        assert s.fetch("/repo") == {'authed': False}
        assert s.fetch("/repo", config={'token': 'abc'}) == {'authed': True}

    def test_fetch_returns_none(self):
        from repoindex.sources import MetadataSource

        class NoneSource(MetadataSource):
            source_id = "none"
            name = "None Source"
            def detect(self, repo_path, repo_record=None):
                return True
            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        assert NoneSource().fetch("/repo") is None

    def test_source_id_and_name_defaults(self):
        from repoindex.sources import MetadataSource

        class BareSource(MetadataSource):
            def detect(self, repo_path, repo_record=None):
                return False
            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        s = BareSource()
        assert s.source_id == ""
        assert s.name == ""


class TestDiscoverSources:
    def test_returns_list(self):
        from repoindex.sources import discover_sources
        result = discover_sources()
        assert isinstance(result, list)

    def test_only_filter(self):
        from repoindex.sources import discover_sources
        result = discover_sources(only=['nonexistent'])
        assert result == []

    def test_user_source_loaded(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "my_source.py").write_text('''
from repoindex.sources import MetadataSource

class MySource(MetadataSource):
    source_id = "mysource"
    name = "My Source"
    target = "repos"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = MySource()
''')
        result = discover_sources(user_dir=str(user_dir))
        ids = [s.source_id for s in result]
        assert "mysource" in ids

    def test_user_source_with_only_filter(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "my_source.py").write_text('''
from repoindex.sources import MetadataSource

class MySource(MetadataSource):
    source_id = "mysource"
    name = "My Source"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = MySource()
''')
        # Filter includes mysource
        result = discover_sources(user_dir=str(user_dir), only=['mysource'])
        assert len(result) == 1
        # Filter excludes mysource
        result = discover_sources(user_dir=str(user_dir), only=['other'])
        assert len(result) == 0

    def test_broken_user_source_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "broken.py").write_text("raise ImportError('broken')")
        result = discover_sources(user_dir=str(user_dir))
        assert isinstance(result, list)  # No crash

    def test_underscore_files_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "__init__.py").write_text("")
        (user_dir / "_helper.py").write_text("")
        result = discover_sources(user_dir=str(user_dir))
        assert isinstance(result, list)

    def test_nonexistent_user_dir(self, tmp_path):
        from repoindex.sources import discover_sources
        result = discover_sources(user_dir=str(tmp_path / 'nope'))
        assert isinstance(result, list)

    def test_multiple_user_sources(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        for name in ("alpha", "beta"):
            (user_dir / f"{name}.py").write_text(f'''
from repoindex.sources import MetadataSource

class S(MetadataSource):
    source_id = "{name}"
    name = "{name.title()}"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = S()
''')
        result = discover_sources(user_dir=str(user_dir))
        ids = [s.source_id for s in result]
        assert "alpha" in ids
        assert "beta" in ids

    def test_module_without_source_attr_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "no_attr.py").write_text("x = 42\n")
        result = discover_sources(user_dir=str(user_dir))
        assert result == [] or all(s.source_id != "" for s in result)

    def test_non_metadatasource_attr_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "wrong_type.py").write_text("source = 'not a MetadataSource'\n")
        result = discover_sources(user_dir=str(user_dir))
        assert len(result) == 0

    def test_backward_compat_providers_dir(self, tmp_path, monkeypatch):
        """User sources in ~/.repoindex/providers/ with MetadataSource are discovered."""
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        providers_dir = tmp_path / "providers"
        providers_dir.mkdir()
        (providers_dir / "compat_source.py").write_text('''
from repoindex.sources import MetadataSource

class CompatSource(MetadataSource):
    source_id = "compat"
    name = "Compat"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = CompatSource()
''')
        # Monkeypatch expanduser so providers dir is found
        original_expanduser = os.path.expanduser
        def fake_expanduser(path):
            if path == '~/.repoindex/providers':
                return str(providers_dir)
            return original_expanduser(path)
        monkeypatch.setattr(os.path, 'expanduser', fake_expanduser)

        result = discover_sources(user_dir=str(user_dir))
        ids = [s.source_id for s in result]
        assert "compat" in ids

    def test_backward_compat_provider_attr(self, tmp_path, monkeypatch):
        """Old-style 'provider' attribute that is a MetadataSource is discovered."""
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        providers_dir = tmp_path / "providers"
        providers_dir.mkdir()
        (providers_dir / "old_provider.py").write_text('''
from repoindex.sources import MetadataSource

class OldProvider(MetadataSource):
    source_id = "old_prov"
    name = "Old Provider"
    target = "publications"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

provider = OldProvider()
''')
        original_expanduser = os.path.expanduser
        def fake_expanduser(path):
            if path == '~/.repoindex/providers':
                return str(providers_dir)
            return original_expanduser(path)
        monkeypatch.setattr(os.path, 'expanduser', fake_expanduser)

        result = discover_sources(user_dir=str(user_dir))
        ids = [s.source_id for s in result]
        assert "old_prov" in ids

    def test_backward_compat_platform_attr(self, tmp_path, monkeypatch):
        """Old-style 'platform' attribute that is a MetadataSource is discovered."""
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        providers_dir = tmp_path / "providers"
        providers_dir.mkdir()
        (providers_dir / "old_platform.py").write_text('''
from repoindex.sources import MetadataSource

class OldPlatform(MetadataSource):
    source_id = "old_plat"
    name = "Old Platform"
    target = "repos"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

platform = OldPlatform()
''')
        original_expanduser = os.path.expanduser
        def fake_expanduser(path):
            if path == '~/.repoindex/providers':
                return str(providers_dir)
            return original_expanduser(path)
        monkeypatch.setattr(os.path, 'expanduser', fake_expanduser)

        result = discover_sources(user_dir=str(user_dir))
        ids = [s.source_id for s in result]
        assert "old_plat" in ids

    def test_only_filter_applies_to_all_sources(self, tmp_path, monkeypatch):
        """The only filter applies to both user sources and backward compat providers."""
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "s1.py").write_text('''
from repoindex.sources import MetadataSource

class S1(MetadataSource):
    source_id = "s1"
    name = "S1"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = S1()
''')
        providers_dir = tmp_path / "providers"
        providers_dir.mkdir()
        (providers_dir / "s2.py").write_text('''
from repoindex.sources import MetadataSource

class S2(MetadataSource):
    source_id = "s2"
    name = "S2"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = S2()
''')
        original_expanduser = os.path.expanduser
        def fake_expanduser(path):
            if path == '~/.repoindex/providers':
                return str(providers_dir)
            return original_expanduser(path)
        monkeypatch.setattr(os.path, 'expanduser', fake_expanduser)

        # Only s1
        result = discover_sources(user_dir=str(user_dir), only=['s1'])
        ids = [s.source_id for s in result]
        assert 's1' in ids
        assert 's2' not in ids

        # Only s2
        result = discover_sources(user_dir=str(user_dir), only=['s2'])
        ids = [s.source_id for s in result]
        assert 's2' in ids
        assert 's1' not in ids

    def test_syntax_error_in_user_source_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "bad_syntax.py").write_text("def broken(\n")
        result = discover_sources(user_dir=str(user_dir))
        assert isinstance(result, list)

    def test_non_py_files_skipped(self, tmp_path):
        from repoindex.sources import discover_sources
        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "readme.txt").write_text("not a source")
        (user_dir / "data.json").write_text("{}")
        result = discover_sources(user_dir=str(user_dir))
        assert result == []


class TestBuiltinSources:
    def test_builtin_sources_is_list(self):
        from repoindex.sources import BUILTIN_SOURCES
        assert isinstance(BUILTIN_SOURCES, list)

    def test_builtin_sources_currently_empty(self):
        from repoindex.sources import BUILTIN_SOURCES
        assert len(BUILTIN_SOURCES) == 0

    def test_all_builtins_are_metadata_sources(self):
        from repoindex.sources import BUILTIN_SOURCES, MetadataSource
        for s in BUILTIN_SOURCES:
            assert isinstance(s, MetadataSource)


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
from repoindex.sources import MetadataSource

class M(MetadataSource):
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
from repoindex.sources import MetadataSource

class A(MetadataSource):
    source_id = "from_source"
    name = "A"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

class B(MetadataSource):
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
from repoindex.sources import MetadataSource

class S(MetadataSource):
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
