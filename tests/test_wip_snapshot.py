"""Tests for WIP snapshot service."""
import re
import subprocess

import pytest
from pathlib import Path

from repoindex.services.wip_service import snapshot_repo, SnapshotResult


# Branch format: wip/<host>/YYYY-MM-DD-HHMMSS-<8 hex chars>
_BRANCH_SUFFIX_RE = re.compile(r'^\d{4}-\d{2}-\d{2}-\d{6}-[0-9a-f]{8}$')


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
        assert result.branch.startswith('wip/testhost/')
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
        """Index should be untouched after a snapshot."""
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

    def test_pre_staged_index_preserved(self, tmp_path):
        """Pre-staged blobs must survive the snapshot unchanged.

        Regression test for the 'git add -A then git reset' data-loss bug:
        a partially-staged file (MM) used to lose its staged version.
        """
        repo = _init_repo(tmp_path / 'staged')
        # Create a file, stage one version, then modify it further so
        # we have a partially-staged (MM) state.
        (repo / 'file.txt').write_text('staged version')
        subprocess.run(
            ['git', 'add', 'file.txt'],
            cwd=str(repo), capture_output=True,
        )
        (repo / 'file.txt').write_text('further modified')

        # Capture status before
        before = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout

        # Confirm we genuinely have an MM state to protect (sanity check).
        assert before.startswith('MM '), f'expected MM, got: {before!r}'

        result = snapshot_repo(str(repo), hostname='test')
        assert result.success

        # Status must be IDENTICAL after — same two-character code, same file.
        after = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout
        assert before == after

        # And the staged blob must still be accessible via :0:file.txt.
        staged = subprocess.run(
            ['git', 'show', ':0:file.txt'],
            cwd=str(repo), capture_output=True, text=True,
        )
        assert staged.stdout == 'staged version'

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

    def test_latest_pointer_updated_on_remote(self, tmp_path):
        """Every snapshot must also update wip/<host>/latest on origin."""
        repo = _init_repo(tmp_path / 'latestptr')
        (repo / 'data.txt').write_text('first')
        r1 = snapshot_repo(str(repo), hostname='myhost')
        assert r1.success

        remote_path = tmp_path / 'latestptr-remote.git'
        latest_sha = subprocess.run(
            ['git', 'rev-parse', 'refs/heads/wip/myhost/latest'],
            cwd=str(remote_path), capture_output=True, text=True,
        ).stdout.strip()
        assert latest_sha == r1.commit_sha

        # Second snapshot advances latest.
        (repo / 'data.txt').write_text('second')
        r2 = snapshot_repo(str(repo), hostname='myhost')
        assert r2.success
        latest_sha2 = subprocess.run(
            ['git', 'rev-parse', 'refs/heads/wip/myhost/latest'],
            cwd=str(remote_path), capture_output=True, text=True,
        ).stdout.strip()
        assert latest_sha2 == r2.commit_sha
        assert latest_sha != latest_sha2

    def test_branch_name_format(self, tmp_path):
        """Branch name: wip/<host>/YYYY-MM-DD-HHMMSS-<8 hex>."""
        repo = _init_repo(tmp_path / 'branchfmt')
        (repo / 'file.txt').write_text('changed')
        result = snapshot_repo(str(repo), hostname='mybox')
        assert result.branch.startswith('wip/mybox/')
        suffix = result.branch[len('wip/mybox/'):]
        assert _BRANCH_SUFFIX_RE.match(suffix), (
            f'branch suffix {suffix!r} does not match expected '
            f'YYYY-MM-DD-HHMMSS-<8hex>'
        )

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


class TestSnapshotRepoUniqueBranches:
    def test_branch_names_are_unique_across_runs(self, tmp_path):
        """Back-to-back snapshots must produce distinct branch names.

        Regression test for the day-resolution collision bug: the old
        'wip/<host>/<date>' format silently force-pushed over the earlier
        snapshot. The unique suffix (timestamp + uuid) guarantees every
        snapshot is independently recoverable.
        """
        repo = _init_repo(tmp_path / 'unique')
        (repo / 'file.txt').write_text('change')
        r1 = snapshot_repo(str(repo), hostname='test')
        (repo / 'file.txt').write_text('different change')
        r2 = snapshot_repo(str(repo), hostname='test')
        assert r1.success and r2.success
        assert r1.branch != r2.branch  # unique per run
        assert r1.commit_sha != r2.commit_sha

    def test_both_snapshots_survive_on_remote(self, tmp_path):
        """Both unique branches must exist on the remote after two runs."""
        repo = _init_repo(tmp_path / 'bothsurvive')
        (repo / 'file.txt').write_text('first change')
        r1 = snapshot_repo(str(repo), hostname='test')
        (repo / 'file.txt').write_text('second change')
        r2 = snapshot_repo(str(repo), hostname='test')
        assert r1.success and r2.success

        remote_path = tmp_path / 'bothsurvive-remote.git'
        # Confirm both unique branches still point at their snapshot commits.
        sha1 = subprocess.run(
            ['git', 'rev-parse', f'refs/heads/{r1.branch}'],
            cwd=str(remote_path), capture_output=True, text=True,
        ).stdout.strip()
        sha2 = subprocess.run(
            ['git', 'rev-parse', f'refs/heads/{r2.branch}'],
            cwd=str(remote_path), capture_output=True, text=True,
        ).stdout.strip()
        assert sha1 == r1.commit_sha
        assert sha2 == r2.commit_sha


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
        assert result.branch.startswith('wip/laptop/')


class TestSnapshotRepoErrors:
    """Test error handling paths using mocked subprocess.run."""

    def test_write_tree_failure(self, tmp_path, monkeypatch):
        repo = _init_repo(tmp_path / 'writerr')
        (repo / 'dirty.txt').write_text('dirty')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
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
            # Let checks pass, timeout on add (which happens inside _run_env)
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

    def test_status_failure_reported_not_skipped(self, tmp_path):
        """A corrupt index must produce a real error, not 'skipped: clean'.

        Regression test for the bug where ``git status --porcelain`` was
        checked only by empty-output, so a non-zero exit that printed
        nothing to stdout was silently treated as 'nothing to snapshot'.
        """
        repo = _init_repo(tmp_path / 'corrupt')
        # Corrupt the index to force ``git status`` to fail.
        (repo / '.git' / 'index').write_text('garbage')

        result = snapshot_repo(str(repo), hostname='test')
        assert not result.success
        assert not result.skipped  # NOT skipped as 'clean'
        assert 'status' in result.error.lower() or 'index' in result.error.lower()

    def test_add_failure_reported(self, tmp_path, monkeypatch):
        """A failed ``git add -A`` must surface as an error, not a
        half-finished snapshot."""
        repo = _init_repo(tmp_path / 'adderr')
        (repo / 'dirty.txt').write_text('dirty')

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            # Fail only the add into the temp index (GIT_INDEX_FILE in env).
            if cmd[:2] == ['git', 'add'] and 'env' in kwargs:
                return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='add failed')
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        result = snapshot_repo(str(repo), hostname='h')
        assert not result.success
        assert 'add' in result.error


class TestSnapshotRepoCleanup:
    def test_temp_index_is_removed_on_success(self, tmp_path, monkeypatch):
        """The GIT_INDEX_FILE temp path must not leak after success."""
        repo = _init_repo(tmp_path / 'cleanup_ok')
        (repo / 'file.txt').write_text('changed')

        seen_paths: list[str] = []
        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            env = kwargs.get('env')
            if env and 'GIT_INDEX_FILE' in env:
                seen_paths.append(env['GIT_INDEX_FILE'])
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        result = snapshot_repo(str(repo), hostname='h')
        assert result.success
        assert seen_paths, 'expected at least one command with GIT_INDEX_FILE'
        for p in set(seen_paths):
            assert not Path(p).exists(), f'temp index {p} leaked'

    def test_temp_index_is_removed_on_failure(self, tmp_path, monkeypatch):
        """Temp index must still be unlinked if a step fails."""
        repo = _init_repo(tmp_path / 'cleanup_fail')
        (repo / 'file.txt').write_text('changed')

        seen_paths: list[str] = []
        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            env = kwargs.get('env')
            if env and 'GIT_INDEX_FILE' in env:
                seen_paths.append(env['GIT_INDEX_FILE'])
            if cmd[:2] == ['git', 'write-tree']:
                return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='boom')
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        result = snapshot_repo(str(repo), hostname='h')
        assert not result.success
        for p in set(seen_paths):
            assert not Path(p).exists(), f'temp index {p} leaked on failure'


class TestWipSnapshotCLI:
    """Integration tests for the wip-snapshot CLI handler's exception
    isolation — a failure in one repo must not kill the whole batch."""

    def test_handler_isolates_per_repo_exceptions(self, tmp_path, monkeypatch):
        """If ``snapshot_repo`` raises for one repo, the other repos'
        results must still be collected and reported (not discarded)."""
        from click.testing import CliRunner

        from repoindex.commands.ops import wip_snapshot_handler
        from repoindex.services import wip_service as wip_module

        good_repo = _init_repo(tmp_path / 'good')
        (good_repo / 'file.txt').write_text('changed')
        bad_repo = _init_repo(tmp_path / 'bad')
        (bad_repo / 'file.txt').write_text('changed')

        fake_repos = [
            {'path': str(good_repo), 'name': 'good'},
            {'path': str(bad_repo), 'name': 'bad'},
        ]

        # Patch the DB-facing repo resolver to skip the database entirely.
        monkeypatch.setattr(
            'repoindex.commands.ops._get_repos_from_query',
            lambda *a, **kw: fake_repos,
        )

        real_snapshot = wip_module.snapshot_repo

        def flaky_snapshot(path, hostname=None, dry_run=False):
            if path == str(bad_repo):
                raise RuntimeError('simulated explosion')
            return real_snapshot(path, hostname=hostname, dry_run=dry_run)

        # The handler imports snapshot_repo inside the function body, so we
        # patch the module attribute that import will pick up.
        monkeypatch.setattr(wip_module, 'snapshot_repo', flaky_snapshot)

        runner = CliRunner()
        result = runner.invoke(
            wip_snapshot_handler,
            ['--json', '--hostname', 'ci'],
            catch_exceptions=False,
        )

        # The command must complete cleanly — no uncaught exception bubbling.
        assert result.exit_code == 0, result.output

        # JSONL (written to stdout) must include one 'snapshotted' line
        # (good repo) AND one 'failed' line (bad repo), proving neither
        # was dropped. Human progress text goes to stderr (click.echo
        # err=True) so it won't pollute stdout in click 8.2+.
        import json
        lines = []
        for line in result.output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                # In older click (<8.2) stderr may mingle into output;
                # silently drop non-JSON lines rather than failing the test.
                pass
        statuses = [rec.get('status') for rec in lines if 'status' in rec]
        assert 'snapshotted' in statuses, lines
        assert 'failed' in statuses, lines

        failed_recs = [rec for rec in lines if rec.get('status') == 'failed']
        assert any(
            'simulated explosion' in rec.get('error', '')
            or 'unexpected' in rec.get('error', '')
            for rec in failed_recs
        ), failed_recs
