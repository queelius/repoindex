"""Tests for parallel source execution."""
import time
from unittest.mock import MagicMock
import pytest

from repoindex.sources import MetadataSource


def _make_source(source_id, target="repos", detect_val=True, fetch_val=None, detect_fn=None, fetch_fn=None):
    """Helper to create a mock MetadataSource with desired behavior."""
    src = MagicMock(spec=MetadataSource)
    src.source_id = source_id
    src.name = source_id.title()
    src.target = target
    src.batch = False

    if detect_fn:
        src.detect = detect_fn
    else:
        src.detect = MagicMock(return_value=detect_val)

    if fetch_fn:
        src.fetch = fetch_fn
    else:
        src.fetch = MagicMock(return_value=fetch_val)

    return src


class TestRunSourcesParallel:
    def test_concurrent_execution(self):
        from repoindex.commands.refresh import _run_sources_parallel

        def slow_detect(path, repo_dict):
            return True

        def slow_fetch(path, repo_dict, config):
            time.sleep(0.1)
            return {'fake_val': 1}

        sources = []
        for i in range(5):
            src = _make_source(
                f'mock_{i}', detect_fn=slow_detect, fetch_fn=slow_fetch
            )
            sources.append(src)

        start = time.time()
        results = _run_sources_parallel(sources, '/fake', {}, {})
        elapsed = time.time() - start
        assert elapsed < 0.3  # Serial would be 0.5s+
        assert len(results) == 5

    def test_error_isolation(self):
        from repoindex.commands.refresh import _run_sources_parallel

        good = _make_source('good', detect_val=True, fetch_val={'good_val': 1})
        bad = _make_source('bad', detect_val=True)
        bad.detect = MagicMock(side_effect=ConnectionError("down"))

        results = _run_sources_parallel([bad, good], '/fake', {}, {})
        assert len(results) == 1
        assert results[0][0].source_id == 'good'

    def test_empty_sources(self):
        from repoindex.commands.refresh import _run_sources_parallel
        assert _run_sources_parallel([], '/fake', {}, {}) == []

    def test_all_fail_returns_empty(self):
        from repoindex.commands.refresh import _run_sources_parallel
        bad = _make_source('bad', detect_val=True)
        bad.detect = MagicMock(side_effect=Exception("fail"))
        assert _run_sources_parallel([bad], '/fake', {}, {}) == []

    def test_none_results_filtered(self):
        from repoindex.commands.refresh import _run_sources_parallel
        src = _make_source('none_returner', detect_val=True, fetch_val=None)
        assert _run_sources_parallel([src], '/fake', {}, {}) == []

    def test_detect_false_skips_fetch(self):
        from repoindex.commands.refresh import _run_sources_parallel
        src = _make_source('skip', detect_val=False, fetch_val={'val': 1})
        results = _run_sources_parallel([src], '/fake', {}, {})
        assert results == []
        src.fetch.assert_not_called()

    def test_returns_source_and_data_tuples(self):
        from repoindex.commands.refresh import _run_sources_parallel
        src = _make_source('test', detect_val=True, fetch_val={'stars': 42})
        results = _run_sources_parallel([src], '/fake', {}, {})
        assert len(results) == 1
        returned_source, returned_data = results[0]
        assert returned_source.source_id == 'test'
        assert returned_data == {'stars': 42}

    def test_mixed_targets(self):
        """Sources with different targets both run correctly."""
        from repoindex.commands.refresh import _run_sources_parallel
        repo_src = _make_source('github', target='repos', detect_val=True,
                                fetch_val={'github_stars': 10})
        pub_src = _make_source('pypi', target='publications', detect_val=True,
                               fetch_val={'registry': 'pypi', 'name': 'pkg'})
        results = _run_sources_parallel([repo_src, pub_src], '/fake', {}, {})
        assert len(results) == 2
        targets = {r[0].target for r in results}
        assert targets == {'repos', 'publications'}
