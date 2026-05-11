"""CLI tests for ``ops sync`` (Wave V2.C).

The handler is wrapped in CliRunner and the dependencies
(``discover_sources``, ``Database``, and ``git clone`` subprocess) are
stubbed so the test runs deterministically and offline.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from repoindex.sources import GitForge, RemoteRepo


def _runner():
    return CliRunner()


class _FakeForge(GitForge):
    """In-memory test double for a GitForge."""

    def __init__(self, source_id, repos=None, raise_enum=None):
        self.source_id = source_id
        self.name = source_id
        self._repos = repos or []
        self._raise_enum = raise_enum

    def detect(self, repo_path, repo_record=None):
        return True

    def fetch(self, repo_path, repo_record=None, config=None):
        return None

    def enumerate_user_repos(self, config):
        if self._raise_enum:
            raise self._raise_enum
        for r in self._repos:
            yield r


def _stub_db_existing(urls=None):
    """Patch ``Database`` for ``_load_existing_remote_urls``."""
    urls = list(urls or [])

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *args, **kwargs):
            pass

        def fetchall(self):
            return [{'remote_url': u} for u in urls]

    return patch('repoindex.commands.ops.Database', return_value=_FakeDB())


class TestSyncErrors:
    def test_missing_from_and_all(self):
        from repoindex.commands.ops import sync_handler

        result = _runner().invoke(sync_handler, [])
        assert result.exit_code != 0
        assert 'from' in (result.output + result.stderr).lower()

    def test_from_and_all_conflict(self):
        from repoindex.commands.ops import sync_handler

        result = _runner().invoke(sync_handler, ['--from', 'github', '--all'])
        assert result.exit_code != 0
        assert 'mutually exclusive' in (result.output + result.stderr).lower()


class TestSyncDryRun:
    def test_dry_run_lists_pending(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        fake = _FakeForge('github', repos=[
            RemoteRepo(
                name='new-repo',
                clone_url='https://github.com/u/new-repo.git',
                default_branch='main',
                is_archived=False,
            ),
        ])

        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing([]):
            result = _runner().invoke(
                sync_handler,
                ['--all', '--dry-run', '--into', str(tmp_path)],
            )
        assert result.exit_code == 0, result.stderr
        combined = result.output + result.stderr
        assert 'new-repo' in combined


class TestSyncDedup:
    def test_skips_existing_clone_url(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        fake = _FakeForge('github', repos=[
            RemoteRepo(
                name='already',
                clone_url='https://github.com/u/already.git',
            ),
            RemoteRepo(
                name='new',
                clone_url='https://github.com/u/new.git',
            ),
        ])
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing(
            ['git@github.com:u/already.git']
        ):
            result = _runner().invoke(
                sync_handler,
                ['--all', '--dry-run', '--json', '--into', str(tmp_path)],
            )
        assert result.exit_code == 0, result.stderr
        # Both repos appear in output; one as already-have, one pending.
        assert 'already-have' in result.output
        assert '"new"' in result.output

    def test_normalize_ssh_vs_https_match(self, tmp_path):
        """An SSH remote in the DB should match an HTTPS remote at the forge."""
        from repoindex.commands.ops import sync_handler

        fake = _FakeForge('github', repos=[
            RemoteRepo(
                name='alias',
                clone_url='https://github.com/u/alias.git',
            ),
        ])
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing(
            ['git@github.com:u/alias.git']  # SSH variant
        ):
            result = _runner().invoke(
                sync_handler,
                ['--all', '--dry-run', '--json', '--into', str(tmp_path)],
            )
        assert result.exit_code == 0
        assert 'already-have' in result.output


class TestSyncFilters:
    def test_include_archived_flag(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        fake = _FakeForge('github', repos=[
            RemoteRepo(
                name='old',
                clone_url='https://github.com/u/old.git',
                is_archived=True,
            ),
        ])
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing([]):
            # default: archived skipped
            result = _runner().invoke(
                sync_handler,
                ['--all', '--dry-run', '--json', '--into', str(tmp_path)],
            )
        assert 'skipped-archived' in result.output

        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing([]):
            result2 = _runner().invoke(
                sync_handler,
                ['--all', '--include-archived', '--dry-run', '--json',
                 '--into', str(tmp_path)],
            )
        assert 'pending' in result2.output

    def test_name_filter(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        fake = _FakeForge('github', repos=[
            RemoteRepo(name='lib-a', clone_url='https://github.com/u/lib-a.git'),
            RemoteRepo(name='app-a', clone_url='https://github.com/u/app-a.git'),
        ])
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing([]):
            result = _runner().invoke(
                sync_handler,
                ['--all', '--filter', 'lib-*', '--dry-run', '--json',
                 '--into', str(tmp_path)],
            )
        # lib-a pending, app-a skipped-filter
        assert '"pending"' in result.output
        assert 'skipped-filter' in result.output
        assert '"lib-a"' in result.output
        assert '"app-a"' in result.output


class TestSyncForgeSelection:
    def test_from_filters_to_forge(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        gh = _FakeForge('github', repos=[
            RemoteRepo(name='gh1', clone_url='https://github.com/u/gh1.git'),
        ])
        gt = _FakeForge('gitea', repos=[
            RemoteRepo(name='gt1', clone_url='https://codeberg.org/u/gt1.git'),
        ])
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[gh, gt],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing([]):
            result = _runner().invoke(
                sync_handler,
                ['--from', 'github', '--dry-run', '--json',
                 '--into', str(tmp_path)],
            )
        assert result.exit_code == 0
        assert 'gh1' in result.output
        assert 'gt1' not in result.output

    def test_unknown_from_errors(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        gh = _FakeForge('github')
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[gh],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ):
            result = _runner().invoke(
                sync_handler,
                ['--from', 'unknown', '--dry-run', '--into', str(tmp_path)],
            )
        assert result.exit_code != 0


class TestSyncEnumerateNotImplemented:
    def test_not_implemented_recorded_as_forge_error(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        fake = _FakeForge(
            'gitlab',
            raise_enum=NotImplementedError("gitlab enumerate not supported"),
        )
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing([]):
            result = _runner().invoke(
                sync_handler,
                ['--all', '--dry-run', '--json', '--into', str(tmp_path)],
            )
        assert result.exit_code == 0
        assert 'forge-error' in result.output or '"error"' in result.output


class TestSyncDestination:
    def test_into_overrides_default(self):
        from repoindex.commands.ops import _resolve_sync_destination

        path = _resolve_sync_destination(
            'github', 'foo', '/tmp/imports', {},
        )
        assert path == '/tmp/imports/github/foo'

    def test_config_sync_into(self):
        from repoindex.commands.ops import _resolve_sync_destination

        config = {
            'forges': {
                'github': {'sync_into': '/data/gh-mirror'},
            }
        }
        path = _resolve_sync_destination('github', 'foo', None, config)
        assert path == '/data/gh-mirror/foo'

    def test_default_destination(self, monkeypatch, tmp_path):
        from repoindex.commands.ops import _resolve_sync_destination

        monkeypatch.setenv('HOME', str(tmp_path))
        path = _resolve_sync_destination('github', 'foo', None, {})
        # Path is expanded with ~ resolution against HOME
        assert path == str(tmp_path / 'github' / 'imported' / 'github' / 'foo')


class TestNormalizeRemote:
    def test_https_and_ssh_match(self):
        from repoindex.commands.ops import _normalize_remote

        a = _normalize_remote('https://github.com/user/repo.git')
        b = _normalize_remote('git@github.com:user/repo.git')
        c = _normalize_remote('ssh://git@github.com/user/repo.git')
        d = _normalize_remote('https://github.com/user/repo')
        assert a == b == c == d

    def test_strips_trailing_slash(self):
        from repoindex.commands.ops import _normalize_remote

        assert _normalize_remote('https://gh.com/u/r/') == 'gh.com/u/r'

    def test_empty(self):
        from repoindex.commands.ops import _normalize_remote

        assert _normalize_remote('') == ''


class TestSyncActualClone:
    def test_clone_invokes_git_clone(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        fake = _FakeForge('github', repos=[
            RemoteRepo(name='live', clone_url='https://github.com/u/live.git'),
        ])
        clone_proc = MagicMock(returncode=0, stdout='', stderr='')
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing([]), patch(
            'subprocess.run', return_value=clone_proc,
        ) as run:
            result = _runner().invoke(
                sync_handler,
                ['--all', '--json', '--into', str(tmp_path)],
            )
        assert result.exit_code == 0, result.stderr
        # First positional arg of subprocess.run is the command list
        args, _ = run.call_args
        assert args[0][0] == 'git'
        assert args[0][1] == 'clone'

    def test_clone_failure_marks_failed(self, tmp_path):
        from repoindex.commands.ops import sync_handler

        fake = _FakeForge('github', repos=[
            RemoteRepo(name='broken', clone_url='https://github.com/u/x.git'),
        ])
        clone_proc = MagicMock(
            returncode=128, stdout='', stderr='fatal: repository not found',
        )
        with patch(
            'repoindex.commands.ops.discover_sources',
            return_value=[fake],
        ), patch(
            'repoindex.commands.ops.load_config', return_value={},
        ), _stub_db_existing([]), patch(
            'subprocess.run', return_value=clone_proc,
        ):
            result = _runner().invoke(
                sync_handler,
                ['--all', '--json', '--into', str(tmp_path)],
            )
        # Failure should exit non-zero and mark the row as failed
        assert result.exit_code != 0
        assert '"failed"' in result.output
