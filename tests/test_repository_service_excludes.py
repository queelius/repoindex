"""Tests for RepositoryService discovery-time exclusion.

The discovery path used by ``repoindex refresh`` now honors
``config['exclude_directories']`` as a path-prefix filter (subtree
exclusion). Basename exclusion via ``EXCLUDE_DIRS`` and the
``exclude_patterns`` argument continues to work alongside it.

Covers the gap closed by wiring ``exclude_directories`` into
``RepositoryService.discover``: previously the config key existed but
was only consulted at query time, so refreshes still indexed every
repo under ~/github/archived even when the user had asked to exclude
it.
"""

from pathlib import Path

import pytest

from repoindex.services.repository_service import RepositoryService


def _make_repo(parent: Path, name: str) -> Path:
    """Create a minimal git repo (just a .git dir) at parent/name."""
    repo = parent / name
    (repo / '.git').mkdir(parents=True)
    return repo


@pytest.fixture
def repo_tree(tmp_path):
    """Create a small repo tree:

        tmp/
          github/
            active/repo-a/.git
            active/repo-b/.git
            archived/old-1/.git
            archived/old-2/.git
            forks/external/.git
            archive-extra/repo/.git    # name-similar to 'archived' (prefix safety)
    """
    root = tmp_path / 'github'
    _make_repo(root / 'active', 'repo-a')
    _make_repo(root / 'active', 'repo-b')
    _make_repo(root / 'archived', 'old-1')
    _make_repo(root / 'archived', 'old-2')
    _make_repo(root / 'forks', 'external')
    _make_repo(root / 'archive-extra', 'repo')
    return root


def _names(repos):
    return sorted(r.name for r in repos)


class TestDiscoverExcludeDirectories:
    def test_no_excludes_finds_everything(self, repo_tree):
        config = {
            'repository_directories': [str(repo_tree)],
            'exclude_directories': [],
        }
        repos = list(RepositoryService(config=config).discover(recursive=True))
        assert _names(repos) == ['external', 'old-1', 'old-2', 'repo', 'repo-a', 'repo-b']

    def test_exclude_single_subtree(self, repo_tree):
        config = {
            'repository_directories': [str(repo_tree)],
            'exclude_directories': [str(repo_tree / 'archived')],
        }
        repos = list(RepositoryService(config=config).discover(recursive=True))
        assert _names(repos) == ['external', 'repo', 'repo-a', 'repo-b']

    def test_exclude_multiple_subtrees(self, repo_tree):
        config = {
            'repository_directories': [str(repo_tree)],
            'exclude_directories': [
                str(repo_tree / 'archived'),
                str(repo_tree / 'forks'),
            ],
        }
        repos = list(RepositoryService(config=config).discover(recursive=True))
        assert _names(repos) == ['repo', 'repo-a', 'repo-b']

    def test_exclude_prefix_safety(self, repo_tree):
        """Excluding 'archived' must NOT also exclude 'archive-extra'."""
        config = {
            'repository_directories': [str(repo_tree)],
            'exclude_directories': [str(repo_tree / 'archived')],
        }
        names = _names(list(RepositoryService(config=config).discover(recursive=True)))
        assert 'repo' in names           # archive-extra/repo survives
        assert 'old-1' not in names      # archived/old-1 dropped
        assert 'old-2' not in names

    def test_exclude_exact_repo_path(self, repo_tree):
        """Excluding the path of the repo itself removes it."""
        config = {
            'repository_directories': [str(repo_tree)],
            'exclude_directories': [str(repo_tree / 'active' / 'repo-a')],
        }
        names = _names(list(RepositoryService(config=config).discover(recursive=True)))
        assert 'repo-a' not in names
        assert 'repo-b' in names

    def test_exclude_with_trailing_glob_stripped(self, repo_tree):
        """Trailing /** or /* is treated as 'this subtree'."""
        config = {
            'repository_directories': [str(repo_tree)],
            'exclude_directories': [str(repo_tree / 'archived') + '/**'],
        }
        names = _names(list(RepositoryService(config=config).discover(recursive=True)))
        assert 'old-1' not in names
        assert 'old-2' not in names

    def test_exclude_tilde_expansion(self, tmp_path, monkeypatch):
        """~/ in exclude paths is expanded to the user's home."""
        monkeypatch.setenv('HOME', str(tmp_path))
        root = tmp_path / 'github'
        _make_repo(root / 'active', 'kept')
        _make_repo(root / 'archived', 'gone')
        config = {
            'repository_directories': [str(root)],
            'exclude_directories': ['~/github/archived'],
        }
        names = _names(list(RepositoryService(config=config).discover(recursive=True)))
        assert names == ['kept']

    def test_exclude_glob_expansion(self, tmp_path):
        """Glob patterns in exclude_directories expand to matched directories."""
        root = tmp_path / 'github'
        _make_repo(root / 'archived-2024', 'r1')
        _make_repo(root / 'archived-2025', 'r2')
        _make_repo(root / 'active', 'r3')
        config = {
            'repository_directories': [str(root)],
            'exclude_directories': [str(root / 'archived-*')],
        }
        names = _names(list(RepositoryService(config=config).discover(recursive=True)))
        assert names == ['r3']

    def test_explicit_exclude_paths_arg_overrides_config(self, repo_tree):
        """Direct ``exclude_paths=`` argument wins over config."""
        config = {
            'repository_directories': [str(repo_tree)],
            'exclude_directories': [str(repo_tree / 'archived')],
        }
        # Pass an empty list explicitly: should NOT consult config.
        repos = list(
            RepositoryService(config=config).discover(
                recursive=True,
                exclude_paths=[],
            )
        )
        assert 'old-1' in _names(repos)

    def test_exclude_directories_default_empty(self, repo_tree):
        """A config without exclude_directories key behaves like empty list."""
        config = {'repository_directories': [str(repo_tree)]}
        repos = list(RepositoryService(config=config).discover(recursive=True))
        assert len(repos) == 6


class TestExpandExcludeSubtreesHelper:
    """The internal helper has subtle path-handling. Cover the edge cases."""

    def test_strips_trailing_double_glob(self, tmp_path):
        from repoindex.services.repository_service import _expand_exclude_subtrees
        target = tmp_path / 'arch'
        target.mkdir()
        out = _expand_exclude_subtrees([f'{target}/**'])
        assert out == {str(target.resolve())}

    def test_strips_trailing_single_glob(self, tmp_path):
        from repoindex.services.repository_service import _expand_exclude_subtrees
        target = tmp_path / 'arch'
        target.mkdir()
        out = _expand_exclude_subtrees([f'{target}/*'])
        assert out == {str(target.resolve())}

    def test_keeps_nonexistent_paths(self, tmp_path):
        """A path that doesn't exist yet is still resolved and kept."""
        from repoindex.services.repository_service import _expand_exclude_subtrees
        ghost = tmp_path / 'will-exist-someday'
        out = _expand_exclude_subtrees([str(ghost)])
        # Resolved to absolute, not dropped.
        assert str(ghost.resolve()) in out

    def test_empty_input(self):
        from repoindex.services.repository_service import _expand_exclude_subtrees
        assert _expand_exclude_subtrees([]) == set()
        assert _expand_exclude_subtrees(None) == set()
