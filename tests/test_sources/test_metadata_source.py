"""Tests for MetadataSource ABC and discovery."""
import pytest


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
        # Built-in sources are still present; the wrong_type.py source is not
        assert all(s.source_id != 'wrong_type' for s in result)

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
        # Built-in sources are present; non-.py files are not loaded as user sources
        assert all(s.source_id != 'readme' for s in result)


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


class TestBuiltinSourcesDiscovery:
    """Test that discover_sources() finds built-in native sources."""

    def test_discovers_github_platform(self):
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

    def test_github_has_repos_target(self):
        from repoindex.sources import discover_sources
        sources = discover_sources(only=['github'])
        assert len(sources) == 1
        assert sources[0].target == 'repos'

    def test_pypi_has_publications_target(self):
        from repoindex.sources import discover_sources
        sources = discover_sources(only=['pypi'])
        assert len(sources) == 1
        assert sources[0].target == 'publications'

    def test_only_filter_works(self):
        from repoindex.sources import discover_sources
        sources = discover_sources(only=['github', 'pypi'])
        ids = {s.source_id for s in sources}
        assert ids == {'github', 'pypi'}


class TestTargetValidation:
    """Tests for MetadataSource.target validation in discover_sources.

    Sources with an unknown target would silently no-op in the refresh
    dispatcher (neither the 'repos' nor 'publications' branch fires),
    so discover_sources filters them out with a WARNING log. This
    catches typos in user-provided sources dropped into
    ~/.repoindex/sources/*.py.
    """

    def test_valid_targets_exported(self):
        from repoindex.sources import VALID_TARGETS
        assert VALID_TARGETS == frozenset({"repos", "publications"})

    def test_bogus_target_skipped_with_warning(self, tmp_path, caplog):
        import logging
        from repoindex.sources import discover_sources

        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "bogus.py").write_text('''
from repoindex.sources import MetadataSource

class BogusSource(MetadataSource):
    source_id = "bogus"
    name = "Bogus"
    target = "bogus"  # invalid!
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = BogusSource()
''')
        with caplog.at_level(logging.WARNING, logger='repoindex.sources'):
            result = discover_sources(user_dir=str(user_dir))

        ids = [s.source_id for s in result]
        # bogus is dropped
        assert 'bogus' not in ids
        # warning mentions the bogus source and its invalid target
        messages = ' '.join(r.message for r in caplog.records)
        assert 'bogus' in messages
        assert "'bogus'" in messages or '"bogus"' in messages

    def test_typo_target_repo_singular_rejected(self, tmp_path, caplog):
        """A common typo target='repo' (singular) is caught as invalid."""
        import logging
        from repoindex.sources import discover_sources

        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "typo.py").write_text('''
from repoindex.sources import MetadataSource

class TypoSource(MetadataSource):
    source_id = "typo"
    name = "Typo"
    target = "repo"  # singular! -- the real target is "repos"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = TypoSource()
''')
        with caplog.at_level(logging.WARNING, logger='repoindex.sources'):
            result = discover_sources(user_dir=str(user_dir))

        assert 'typo' not in [s.source_id for s in result]

    def test_valid_targets_kept(self, tmp_path):
        """Sources with valid targets 'repos' and 'publications' are kept."""
        from repoindex.sources import discover_sources

        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "good_repos.py").write_text('''
from repoindex.sources import MetadataSource

class RepoSource(MetadataSource):
    source_id = "good_repos"
    name = "Good Repos"
    target = "repos"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = RepoSource()
''')
        (user_dir / "good_pubs.py").write_text('''
from repoindex.sources import MetadataSource

class PubSource(MetadataSource):
    source_id = "good_pubs"
    name = "Good Pubs"
    target = "publications"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = PubSource()
''')
        result = discover_sources(user_dir=str(user_dir))
        ids = [s.source_id for s in result]
        assert 'good_repos' in ids
        assert 'good_pubs' in ids

    def test_mixed_valid_and_invalid_only_invalid_dropped(self, tmp_path):
        """When both good and bad sources are present, only bad ones are dropped."""
        from repoindex.sources import discover_sources

        user_dir = tmp_path / "sources"
        user_dir.mkdir()
        (user_dir / "good.py").write_text('''
from repoindex.sources import MetadataSource

class Good(MetadataSource):
    source_id = "keeper"
    name = "Keeper"
    target = "repos"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = Good()
''')
        (user_dir / "bad.py").write_text('''
from repoindex.sources import MetadataSource

class Bad(MetadataSource):
    source_id = "discard"
    name = "Discard"
    target = "nowhere"
    def detect(self, repo_path, repo_record=None):
        return False
    def fetch(self, repo_path, repo_record=None, config=None):
        return None

source = Bad()
''')
        result = discover_sources(user_dir=str(user_dir))
        ids = [s.source_id for s in result]
        assert 'keeper' in ids
        assert 'discard' not in ids
