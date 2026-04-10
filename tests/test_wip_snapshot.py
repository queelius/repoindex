"""Tests for WIP snapshot service."""
import subprocess

import pytest
from pathlib import Path

from repoindex.services.wip_service import snapshot_repo, SnapshotResult


def _init_repo(path, with_remote=True, with_commit=True):
    """Create a minimal git repo for testing."""
    subprocess.run(['git', 'init', str(path)], capture_output=True)
    subprocess.run(
        ['git', 'config', 'user.email', 'test@test.com'],
        cwd=str(path), capture_output=True,
    )
    subprocess.run(
        ['git', 'config', 'user.name', 'Test'],
        cwd=str(path), capture_output=True,
    )

    if with_commit:
        (path / 'file.txt').write_text('initial')
        subprocess.run(['git', 'add', '.'], cwd=str(path), capture_output=True)
        subprocess.run(
            ['git', 'commit', '-m', 'init'],
            cwd=str(path), capture_output=True,
        )

    if with_remote and with_commit:
        # Create a bare remote
        remote_path = path.parent / f'{path.name}-remote.git'
        subprocess.run(
            ['git', 'init', '--bare', str(remote_path)],
            capture_output=True,
        )
        subprocess.run(
            ['git', 'remote', 'add', 'origin', str(remote_path)],
            cwd=str(path), capture_output=True,
        )
        # Push whatever the default branch is
        r = subprocess.run(
            ['git', 'symbolic-ref', '--short', 'HEAD'],
            cwd=str(path), capture_output=True, text=True,
        )
        branch = r.stdout.strip()
        subprocess.run(
            ['git', 'push', 'origin', branch],
            cwd=str(path), capture_output=True,
        )

    return path


class TestSnapshotResult:
    def test_dataclass_fields(self):
        r = SnapshotResult('test', '/path', True, branch='wip/h/d', commit_sha='abc123')
        assert r.repo_name == 'test'
        assert r.repo_path == '/path'
        assert r.success
        assert r.branch == 'wip/h/d'
        assert r.commit_sha == 'abc123'
        assert r.error == ''
        assert not r.skipped
        assert r.skip_reason == ''

    def test_defaults(self):
        r = SnapshotResult('x', '/x', False)
        assert not r.success
        assert r.branch == ''
        assert r.commit_sha == ''
        assert r.error == ''
        assert not r.skipped
        assert r.skip_reason == ''

    def test_skipped_result(self):
        r = SnapshotResult('x', '/x', False, skipped=True, skip_reason='clean')
        assert r.skipped
        assert r.skip_reason == 'clean'


class TestSnapshotRepoSkips:
    def test_clean_repo_is_skipped(self, tmp_path):
        repo = _init_repo(tmp_path / 'clean')
        result = snapshot_repo(str(repo))
        assert result.skipped
        assert result.skip_reason == 'clean'
        assert not result.success

    def test_no_remote_is_skipped(self, tmp_path):
        repo = _init_repo(tmp_path / 'noremote', with_remote=False)
        (repo / 'dirty.txt').write_text('dirty')
        result = snapshot_repo(str(repo))
        assert result.skipped
        assert result.skip_reason == 'no remote'

    def test_no_head_is_skipped(self, tmp_path):
        # Create repo with remote but no commits (no HEAD)
        repo = _init_repo(tmp_path / 'empty', with_remote=False, with_commit=False)
        remote_path = tmp_path / 'empty-remote.git'
        subprocess.run(
            ['git', 'init', '--bare', str(remote_path)],
            capture_output=True,
        )
        subprocess.run(
            ['git', 'remote', 'add', 'origin', str(remote_path)],
            cwd=str(repo), capture_output=True,
        )
        result = snapshot_repo(str(repo))
        assert result.skipped
        assert result.skip_reason == 'no HEAD'


class TestSnapshotRepoSuccess:
    def test_dirty_repo_succeeds(self, tmp_path):
        repo = _init_repo(tmp_path / 'dirty')
        (repo / 'new_file.txt').write_text('uncommitted work')
        result = snapshot_repo(str(repo), hostname='testhost')
        assert result.success
        assert not result.skipped
        assert 'wip/testhost/' in result.branch
        assert len(result.commit_sha) > 0

    def test_modified_file_succeeds(self, tmp_path):
        repo = _init_repo(tmp_path / 'modified')
        (repo / 'file.txt').write_text('changed content')
        result = snapshot_repo(str(repo), hostname='testhost')
        assert result.success
        assert result.commit_sha

    def test_working_tree_unchanged_after_snapshot(self, tmp_path):
        repo = _init_repo(tmp_path / 'unchanged')
        (repo / 'work.txt').write_text('in progress')

        # Record state before
        before = (repo / 'work.txt').read_text()

        snapshot_repo(str(repo), hostname='test')

        # Verify file unchanged
        assert (repo / 'work.txt').read_text() == before
        # Verify still dirty (not committed on main)
        r = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=str(repo),
            capture_output=True, text=True,
        )
        assert r.stdout.strip()  # still dirty

    def test_index_restored_after_snapshot(self, tmp_path):
        """Index should be restored to pre-snapshot state."""
        repo = _init_repo(tmp_path / 'indextest')
        (repo / 'unstaged.txt').write_text('not staged')

        # Before: unstaged file shows as ?? (untracked)
        before = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout.strip()

        snapshot_repo(str(repo), hostname='test')

        # After: should be same status
        after = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout.strip()
        assert before == after

    def test_wip_branch_exists_on_remote(self, tmp_path):
        repo = _init_repo(tmp_path / 'pushtest')
        (repo / 'data.txt').write_text('snapshot me')
        result = snapshot_repo(str(repo), hostname='myhost')
        assert result.success

        # Verify branch on remote
        remote_path = tmp_path / 'pushtest-remote.git'
        r = subprocess.run(
            ['git', 'branch', '--list', 'wip/myhost/*'],
            cwd=str(remote_path), capture_output=True, text=True,
        )
        assert 'wip/myhost/' in r.stdout

    def test_branch_name_format(self, tmp_path):
        repo = _init_repo(tmp_path / 'branchfmt')
        (repo / 'file.txt').write_text('changed')
        result = snapshot_repo(str(repo), hostname='mybox')
        assert result.branch.startswith('wip/mybox/')
        # Date portion should be YYYY-MM-DD format
        date_part = result.branch.split('/')[-1]
        assert len(date_part) == 10
        assert date_part[4] == '-' and date_part[7] == '-'

    def test_repo_name_from_path(self, tmp_path):
        repo = _init_repo(tmp_path / 'myrepo')
        (repo / 'file.txt').write_text('changed')
        result = snapshot_repo(str(repo), hostname='h')
        assert result.repo_name == 'myrepo'

    def test_commit_sha_is_valid_hex(self, tmp_path):
        repo = _init_repo(tmp_path / 'shahex')
        (repo / 'file.txt').write_text('changed')
        result = snapshot_repo(str(repo), hostname='h')
        assert result.success
        assert len(result.commit_sha) == 40
        assert all(c in '0123456789abcdef' for c in result.commit_sha)

    def test_snapshot_commit_has_correct_parent(self, tmp_path):
        """The WIP commit's parent should be the repo's HEAD."""
        repo = _init_repo(tmp_path / 'parenttest')
        head_before = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout.strip()

        (repo / 'new.txt').write_text('data')
        result = snapshot_repo(str(repo), hostname='h')
        assert result.success

        # Verify parent of snapshot commit
        remote_path = tmp_path / 'parenttest-remote.git'
        r = subprocess.run(
            ['git', 'log', '--format=%P', '-1', result.commit_sha],
            cwd=str(remote_path), capture_output=True, text=True,
        )
        assert r.stdout.strip() == head_before

    def test_head_unchanged_after_snapshot(self, tmp_path):
        """HEAD should still point to same commit after snapshot."""
        repo = _init_repo(tmp_path / 'headtest')
        head_before = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout.strip()

        (repo / 'new.txt').write_text('data')
        snapshot_repo(str(repo), hostname='h')

        head_after = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout.strip()
        assert head_before == head_after


class TestSnapshotRepoDryRun:
    def test_dry_run_no_push(self, tmp_path):
        repo = _init_repo(tmp_path / 'dryrun')
        (repo / 'file.txt').write_text('modified')
        result = snapshot_repo(str(repo), hostname='test', dry_run=True)
        assert result.success
        assert result.branch
        assert not result.commit_sha  # no actual commit

    def test_dry_run_no_remote_branch_created(self, tmp_path):
        repo = _init_repo(tmp_path / 'drynopush')
        (repo / 'file.txt').write_text('modified')
        snapshot_repo(str(repo), hostname='test', dry_run=True)

        # Verify no branch on remote
        remote_path = tmp_path / 'drynopush-remote.git'
        r = subprocess.run(
            ['git', 'branch'], cwd=str(remote_path),
            capture_output=True, text=True,
        )
        assert 'wip/' not in r.stdout

    def test_dry_run_index_unchanged(self, tmp_path):
        """Dry run should not modify git index."""
        repo = _init_repo(tmp_path / 'dryindex')
        (repo / 'new.txt').write_text('data')

        before = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout

        snapshot_repo(str(repo), hostname='test', dry_run=True)

        after = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout
        assert before == after


class TestSnapshotRepoIdempotent:
    def test_second_snapshot_same_day_overwrites(self, tmp_path):
        """Two snapshots same day should force-push to same branch."""
        repo = _init_repo(tmp_path / 'idempotent')
        (repo / 'file.txt').write_text('first change')
        r1 = snapshot_repo(str(repo), hostname='h')
        assert r1.success

        (repo / 'file.txt').write_text('second change')
        r2 = snapshot_repo(str(repo), hostname='h')
        assert r2.success
        assert r1.branch == r2.branch
        # Different commits since content changed
        assert r1.commit_sha != r2.commit_sha


class TestSnapshotRepoHostname:
    def test_default_hostname(self, tmp_path):
        import socket
        repo = _init_repo(tmp_path / 'defaulthost')
        (repo / 'file.txt').write_text('changed')
        result = snapshot_repo(str(repo))
        assert result.success
        assert socket.gethostname() in result.branch

    def test_custom_hostname(self, tmp_path):
        repo = _init_repo(tmp_path / 'customhost')
        (repo / 'file.txt').write_text('changed')
        result = snapshot_repo(str(repo), hostname='laptop')
        assert 'wip/laptop/' in result.branch


class TestSnapshotRepoErrors:
    """Test error handling paths using mocked subprocess.run."""

    def test_write_tree_failure(self, tmp_path, monkeypatch):
        repo = _init_repo(tmp_path / 'writerr')
        (repo / 'dirty.txt').write_text('dirty')

        original_run = subprocess.run
        call_count = [0]

        def mock_run(cmd, **kwargs):
            call_count[0] += 1
            # Let initial checks pass (remote, HEAD, status, add), fail write-tree
            if cmd[:2] == ['git', 'write-tree']:
                return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='write-tree failed')
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        result = snapshot_repo(str(repo), hostname='h')
        assert not result.success
        assert 'write-tree' in result.error

    def test_commit_tree_failure(self, tmp_path, monkeypatch):
        repo = _init_repo(tmp_path / 'commiterr')
        (repo / 'dirty.txt').write_text('dirty')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if cmd[:2] == ['git', 'commit-tree']:
                return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='commit-tree failed')
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        result = snapshot_repo(str(repo), hostname='h')
        assert not result.success
        assert 'commit-tree' in result.error

    def test_push_failure(self, tmp_path, monkeypatch):
        repo = _init_repo(tmp_path / 'pusherr')
        (repo / 'dirty.txt').write_text('dirty')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if cmd[:2] == ['git', 'push']:
                return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='push rejected')
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        result = snapshot_repo(str(repo), hostname='h')
        assert not result.success
        assert 'push' in result.error

    def test_timeout_handling(self, tmp_path, monkeypatch):
        repo = _init_repo(tmp_path / 'timeout')
        (repo / 'dirty.txt').write_text('dirty')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            # Let checks pass, timeout on add
            if cmd[:2] == ['git', 'add']:
                raise subprocess.TimeoutExpired(cmd, 60)
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        result = snapshot_repo(str(repo), hostname='h')
        assert not result.success
        assert result.error == 'timeout'

    def test_generic_exception_handling(self, tmp_path, monkeypatch):
        repo = _init_repo(tmp_path / 'generr')
        (repo / 'dirty.txt').write_text('dirty')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if cmd[:2] == ['git', 'add']:
                raise RuntimeError('something broke')
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        result = snapshot_repo(str(repo), hostname='h')
        assert not result.success
        assert 'something broke' in result.error
