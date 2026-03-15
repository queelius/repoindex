"""Tests for parallel provider execution."""
import time
from unittest.mock import MagicMock
import pytest


class TestRunProvidersParallel:
    def test_concurrent_execution(self):
        from repoindex.commands.refresh import _run_providers_parallel

        def slow_match(path, repo_record=None, config=None):
            time.sleep(0.1)
            return None

        providers = []
        for i in range(5):
            p = MagicMock()
            p.registry = f'mock_{i}'
            p.match = slow_match
            providers.append(p)

        start = time.time()
        _run_providers_parallel(providers, '/fake', {}, {})
        elapsed = time.time() - start
        assert elapsed < 0.3  # Serial would be 0.5s+

    def test_error_isolation(self):
        from repoindex.commands.refresh import _run_providers_parallel

        good = MagicMock()
        good.registry = 'good'
        good.match = MagicMock(return_value=MagicMock(registry='good'))

        bad = MagicMock()
        bad.registry = 'bad'
        bad.match = MagicMock(side_effect=ConnectionError("down"))

        results = _run_providers_parallel([bad, good], '/fake', {}, {})
        assert len(results) == 1

    def test_empty_providers(self):
        from repoindex.commands.refresh import _run_providers_parallel
        assert _run_providers_parallel([], '/fake', {}, {}) == []

    def test_all_fail_returns_empty(self):
        from repoindex.commands.refresh import _run_providers_parallel
        bad = MagicMock()
        bad.registry = 'bad'
        bad.match = MagicMock(side_effect=Exception("fail"))
        assert _run_providers_parallel([bad], '/fake', {}, {}) == []

    def test_none_results_filtered(self):
        from repoindex.commands.refresh import _run_providers_parallel
        p = MagicMock()
        p.registry = 'none_returner'
        p.match = MagicMock(return_value=None)
        assert _run_providers_parallel([p], '/fake', {}, {}) == []


class TestRunPlatformsParallel:
    def test_concurrent_execution(self):
        from repoindex.commands.refresh import _run_platforms_parallel

        def slow_enrich(path, repo_record=None, config=None):
            time.sleep(0.1)
            return {'fake_stars': 1}

        platforms = []
        for i in range(3):
            p = MagicMock()
            p.platform_id = f'plat_{i}'
            p.detect = MagicMock(return_value=True)
            p.enrich = slow_enrich
            platforms.append(p)

        start = time.time()
        results = _run_platforms_parallel(platforms, '/fake', {}, {})
        elapsed = time.time() - start
        assert elapsed < 0.25
        assert len(results) == 3

    def test_detect_false_skips_enrich(self):
        from repoindex.commands.refresh import _run_platforms_parallel
        p = MagicMock()
        p.platform_id = 'skip'
        p.detect = MagicMock(return_value=False)
        p.enrich = MagicMock()
        results = _run_platforms_parallel([p], '/fake', {}, {})
        assert results == []
        p.enrich.assert_not_called()

    def test_error_isolation(self):
        from repoindex.commands.refresh import _run_platforms_parallel

        good = MagicMock()
        good.platform_id = 'good'
        good.detect = MagicMock(return_value=True)
        good.enrich = MagicMock(return_value={'good_val': 1})

        bad = MagicMock()
        bad.platform_id = 'bad'
        bad.detect = MagicMock(return_value=True)
        bad.enrich = MagicMock(side_effect=Exception("fail"))

        results = _run_platforms_parallel([bad, good], '/fake', {}, {})
        assert len(results) == 1

    def test_empty_platforms(self):
        from repoindex.commands.refresh import _run_platforms_parallel
        assert _run_platforms_parallel([], '/fake', {}, {}) == []
