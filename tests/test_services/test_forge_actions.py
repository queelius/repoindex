"""Tests for the forge_actions service helpers (Wave V2.C)."""

from __future__ import annotations

from unittest.mock import patch

from repoindex.sources import GitForge
from repoindex.services.forge_actions import find_forge, lookup_repo_forge


class _FakeForge(GitForge):
    """Test double that satisfies the GitForge ABC."""

    def __init__(self, source_id):
        self.source_id = source_id
        self.name = source_id

    def detect(self, repo_path, repo_record=None):
        return True

    def fetch(self, repo_path, repo_record=None, config=None):
        return None


class TestFindForge:
    def test_returns_matching_source(self):
        a = _FakeForge('github')
        b = _FakeForge('gitea')
        with patch(
            'repoindex.services.forge_actions.discover_sources',
            return_value=[a, b],
        ):
            assert find_forge('github') is a
            assert find_forge('gitea') is b

    def test_returns_none_when_no_match(self):
        with patch(
            'repoindex.services.forge_actions.discover_sources',
            return_value=[_FakeForge('github')],
        ):
            assert find_forge('gitlab') is None

    def test_returns_none_for_empty_id(self):
        with patch(
            'repoindex.services.forge_actions.discover_sources',
            return_value=[_FakeForge('github')],
        ):
            assert find_forge('') is None

    def test_skips_non_gitforge_sources(self):
        """Other Source subclasses (LocalScanner, Registry) shouldn't match."""
        from repoindex.sources import LocalScanner

        class _Scanner(LocalScanner):
            source_id = 'fake'
            name = 'fake'

            def detect(self, repo_path, repo_record=None):
                return False

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        with patch(
            'repoindex.services.forge_actions.discover_sources',
            return_value=[_Scanner()],
        ):
            assert find_forge('fake') is None


class TestLookupRepoForge:
    def test_returns_forge_for_record(self):
        forge = _FakeForge('github')
        with patch(
            'repoindex.services.forge_actions.discover_sources',
            return_value=[forge],
        ):
            assert lookup_repo_forge({'forge_id': 'github'}) is forge

    def test_returns_none_when_record_lacks_forge_id(self):
        with patch(
            'repoindex.services.forge_actions.discover_sources',
            return_value=[_FakeForge('github')],
        ):
            assert lookup_repo_forge({}) is None
            assert lookup_repo_forge({'forge_id': None}) is None

    def test_returns_none_when_record_empty(self):
        with patch(
            'repoindex.services.forge_actions.discover_sources',
            return_value=[],
        ):
            assert lookup_repo_forge(None) is None

    def test_returns_none_when_forge_id_unknown(self):
        with patch(
            'repoindex.services.forge_actions.discover_sources',
            return_value=[_FakeForge('github')],
        ):
            assert lookup_repo_forge({'forge_id': 'gitlab'}) is None
