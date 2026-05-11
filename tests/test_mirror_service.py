"""Tests for the mirror service (mirror_repo).

Config-shape tests (parsing forges:, get_mirrors filtering) live in
tests/test_services/test_forge_config.py.
"""
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from repoindex.services.forge_config import ForgeConfig
from repoindex.services.mirror_service import MirrorResult, mirror_repo


def MirrorTarget(name: str, url_template: str) -> ForgeConfig:
    """Test-only shim: build a ForgeConfig with the old MirrorTarget shape.

    The deleted MirrorTarget dataclass only had (name, url_template). The
    new ForgeConfig carries more fields, but mirror_repo only uses these
    two. This shim keeps the legacy tests readable.
    """
    return ForgeConfig(
        name=name,
        source_id=name,        # arbitrary; mirror_repo doesn't read it
        role='mirror',
        url_template=url_template,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_result(returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(
        args=['fake'], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def _init_git_repo(path: Path) -> Path:
    """Create a minimal initialized git repo with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', str(path)], capture_output=True)
    subprocess.run(
        ['git', 'config', 'user.email', 'test@test.com'],
        cwd=str(path), capture_output=True,
    )
    subprocess.run(
        ['git', 'config', 'user.name', 'Test'],
        cwd=str(path), capture_output=True,
    )
    (path / 'file.txt').write_text('initial')
    subprocess.run(['git', 'add', '.'], cwd=str(path), capture_output=True)
    subprocess.run(
        ['git', 'commit', '-m', 'init'],
        cwd=str(path), capture_output=True,
    )
    return path


# ---------------------------------------------------------------------------
# mirror_repo: dry-run
# ---------------------------------------------------------------------------


class TestMirrorRepoDryRun:
    def test_dry_run_does_not_call_git_push(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            # Remote get-url fails (so it plans `remote add`)
            mock_run.return_value = _make_run_result(returncode=1)
            r = mirror_repo('/tmp/fake-repo', target, dry_run=True)

        # Collect all subprocess.run calls (as command lists)
        called_cmds = [c.args[0] for c in mock_run.call_args_list]
        # No push or fetch should have been invoked in dry-run
        assert not any(cmd[:2] == ['git', 'push'] for cmd in called_cmds)
        assert not any(cmd[:2] == ['git', 'fetch'] for cmd in called_cmds)
        assert not any(cmd[:3] == ['git', 'remote', 'add'] for cmd in called_cmds)
        assert r.status == 'dry-run'
        # Planned actions should include fetch and push (preview)
        assert any('push --mirror' in a for a in r.planned_actions)
        assert any('fetch' in a for a in r.planned_actions)

    def test_dry_run_previews_remote_add_when_missing(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            mock_run.return_value = _make_run_result(returncode=1)
            r = mirror_repo('/tmp/newrepo', target, dry_run=True)

        assert r.status == 'dry-run'
        assert r.added_remote
        assert any('remote add codeberg' in a for a in r.planned_actions)

    def test_dry_run_with_force_previews_force(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            mock_run.return_value = _make_run_result(returncode=1)
            r = mirror_repo('/tmp/fakerepo', target, dry_run=True, force=True)
        assert '--force' in r.detail


# ---------------------------------------------------------------------------
# mirror_repo: URL conflict path
# ---------------------------------------------------------------------------


class TestMirrorRepoURLConflict:
    def test_conflict_skips_without_changes(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            # git remote get-url returns a DIFFERENT url
            mock_run.return_value = _make_run_result(
                returncode=0,
                stdout='https://different.example/other.git\n',
            )
            r = mirror_repo('/tmp/fake', target, dry_run=False)

        assert r.status == 'skipped'
        assert 'URL conflict' in r.detail
        # Only one call (get-url); no add/fetch/push.
        called_cmds = [c.args[0] for c in mock_run.call_args_list]
        assert called_cmds == [['git', 'remote', 'get-url', 'codeberg']]

    def test_matching_existing_remote_used_as_is(self):
        """If existing URL matches template, no add, no conflict, just push."""
        target = MirrorTarget(
            name='codeberg',
            url_template='https://codeberg.org/x/{repo}.git',
        )
        repo_name = 'sample'

        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[:3] == ['git', 'remote', 'get-url']:
                    return _make_run_result(
                        stdout=f'https://codeberg.org/x/{repo_name}.git\n'
                    )
                # fetch, push, for-each-ref, rev-parse, merge-base — all ok
                return _make_run_result(returncode=0, stdout='')
            mock_run.side_effect = side_effect

            r = mirror_repo(f'/tmp/{repo_name}', target)

        assert r.status == 'ok'
        assert not r.added_remote
        # No `remote add` command called.
        called_cmds = [c.args[0] for c in mock_run.call_args_list]
        assert not any(
            cmd[:3] == ['git', 'remote', 'add'] for cmd in called_cmds
        )


# ---------------------------------------------------------------------------
# mirror_repo: fast-forward / force
# ---------------------------------------------------------------------------


class TestFastForward:
    def _setup_mocks(self, mock_run, diverged: bool, remote_exists=False):
        """Return a side-effect function simulating git responses.

        ``diverged=True`` makes merge-base return nonzero (not ancestor)
        for at least one branch.
        """
        def side_effect(cmd, **kwargs):
            if cmd[:3] == ['git', 'remote', 'get-url']:
                if remote_exists:
                    return _make_run_result(
                        stdout='https://codeberg.org/x/fake.git\n'
                    )
                return _make_run_result(returncode=1)
            if cmd[:3] == ['git', 'remote', 'add']:
                return _make_run_result(returncode=0)
            if cmd[:2] == ['git', 'fetch']:
                return _make_run_result(returncode=0)
            if cmd[:2] == ['git', 'for-each-ref']:
                return _make_run_result(stdout='main\n')
            if cmd[:3] == ['git', 'rev-parse', '--verify']:
                # local main resolves; mirror branch resolves
                if 'refs/heads/main' in cmd:
                    return _make_run_result(stdout='aaaaaaaa\n')
                if 'refs/remotes/codeberg/main' in cmd:
                    return _make_run_result(stdout='bbbbbbbb\n')
                return _make_run_result(returncode=1)
            if cmd[:3] == ['git', 'merge-base', '--is-ancestor']:
                return _make_run_result(returncode=1 if diverged else 0)
            if cmd[:2] == ['git', 'push']:
                return _make_run_result(returncode=0)
            return _make_run_result(returncode=0)

        mock_run.side_effect = side_effect

    def test_ff_passes_when_ancestor(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            self._setup_mocks(mock_run, diverged=False, remote_exists=True)
            r = mirror_repo('/tmp/fake', target)
        assert r.status == 'ok', r.detail

    def test_ff_fails_when_diverged(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            self._setup_mocks(mock_run, diverged=True, remote_exists=True)
            r = mirror_repo('/tmp/fake', target, force=False)
        assert r.status == 'failed'
        assert 'non-fast-forward' in r.detail
        assert "'main'" in r.detail

    def test_force_bypasses_ff_check(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            self._setup_mocks(mock_run, diverged=True, remote_exists=True)
            r = mirror_repo('/tmp/fake', target, force=True)
        assert r.status == 'ok'
        # Confirm push was called with --force
        push_cmds = [c.args[0] for c in mock_run.call_args_list
                     if c.args[0][:2] == ['git', 'push']]
        assert push_cmds
        assert '--force' in push_cmds[0]
        assert '--mirror' in push_cmds[0]

    def test_push_without_force_has_no_force_flag(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            self._setup_mocks(mock_run, diverged=False, remote_exists=True)
            mirror_repo('/tmp/fake', target, force=False)
        push_cmds = [c.args[0] for c in mock_run.call_args_list
                     if c.args[0][:2] == ['git', 'push']]
        assert push_cmds
        assert '--force' not in push_cmds[0]

    def test_ff_check_ignores_branches_absent_on_mirror(self):
        """A branch that exists locally but not on the mirror isn't
        'diverged' — there's nothing to fail-forward against."""
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[:3] == ['git', 'remote', 'get-url']:
                    return _make_run_result(stdout='https://codeberg.org/x/fake.git\n')
                if cmd[:2] == ['git', 'fetch']:
                    return _make_run_result(returncode=0)
                if cmd[:2] == ['git', 'for-each-ref']:
                    return _make_run_result(stdout='main\nfeature\n')
                if cmd[:3] == ['git', 'rev-parse', '--verify']:
                    # local resolves, mirror/main resolves, mirror/feature missing
                    if 'refs/heads/' in cmd[-1]:
                        return _make_run_result(stdout='aaaaaaaa\n')
                    if cmd[-1] == 'refs/remotes/codeberg/main':
                        return _make_run_result(stdout='aaaaaaaa\n')
                    return _make_run_result(returncode=1)
                if cmd[:3] == ['git', 'merge-base', '--is-ancestor']:
                    return _make_run_result(returncode=0)  # ancestor
                if cmd[:2] == ['git', 'push']:
                    return _make_run_result(returncode=0)
                return _make_run_result(returncode=0)
            mock_run.side_effect = side_effect
            r = mirror_repo('/tmp/fake', target)
        assert r.status == 'ok', r.detail


# ---------------------------------------------------------------------------
# mirror_repo: auto-add remote
# ---------------------------------------------------------------------------


class TestAutoAddRemote:
    def test_remote_added_when_missing(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[:3] == ['git', 'remote', 'get-url']:
                    return _make_run_result(returncode=1)  # missing
                if cmd[:3] == ['git', 'remote', 'add']:
                    return _make_run_result(returncode=0)
                if cmd[:2] == ['git', 'fetch']:
                    return _make_run_result(returncode=0)
                if cmd[:2] == ['git', 'for-each-ref']:
                    return _make_run_result(stdout='main\n')
                if cmd[:3] == ['git', 'rev-parse', '--verify']:
                    if 'refs/heads/main' in cmd:
                        return _make_run_result(stdout='aaaaaaaa\n')
                    return _make_run_result(returncode=1)
                if cmd[:2] == ['git', 'push']:
                    return _make_run_result(returncode=0)
                return _make_run_result(returncode=0)
            mock_run.side_effect = side_effect

            r = mirror_repo('/tmp/newrepo', target)

        assert r.status == 'ok'
        assert r.added_remote
        assert 'added remote' in r.detail

        called = [c.args[0] for c in mock_run.call_args_list]
        assert ['git', 'remote', 'add', 'codeberg',
                'https://codeberg.org/x/newrepo.git'] in called

    def test_remote_add_failure_reported(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[:3] == ['git', 'remote', 'get-url']:
                    return _make_run_result(returncode=1)
                if cmd[:3] == ['git', 'remote', 'add']:
                    return _make_run_result(returncode=128, stderr='boom')
                return _make_run_result(returncode=0)
            mock_run.side_effect = side_effect
            r = mirror_repo('/tmp/fake', target)
        assert r.status == 'failed'
        assert 'remote add' in r.detail


# ---------------------------------------------------------------------------
# mirror_repo: init flag
# ---------------------------------------------------------------------------


class TestInitFlag:
    def test_init_creates_bare_repo_when_missing(self, tmp_path):
        """With --init, a missing file:// target is initialized before push."""
        source = _init_git_repo(tmp_path / 'source')
        bare = tmp_path / 'mirrors' / 'source.git'
        assert not bare.exists()

        target = MirrorTarget(
            name='local',
            url_template=f'file://{tmp_path}/mirrors/{{repo}}.git',
        )
        r = mirror_repo(str(source), target, init=True)

        assert r.status == 'init+pushed', r.detail
        assert bare.exists()
        assert (bare / 'HEAD').exists()

    def test_missing_target_without_init_is_error(self, tmp_path):
        source = _init_git_repo(tmp_path / 'source')
        target = MirrorTarget(
            name='local',
            url_template=f'file://{tmp_path}/mirrors/{{repo}}.git',
        )
        r = mirror_repo(str(source), target, init=False)
        assert r.status == 'failed'
        assert 'pass --init' in r.detail
        assert not (tmp_path / 'mirrors').exists()

    def test_init_in_dry_run_does_not_create(self, tmp_path):
        source = _init_git_repo(tmp_path / 'source')
        target = MirrorTarget(
            name='local',
            url_template=f'file://{tmp_path}/mirrors/{{repo}}.git',
        )
        r = mirror_repo(str(source), target, init=True, dry_run=True)
        assert r.status == 'dry-run'
        assert not (tmp_path / 'mirrors').exists()
        assert any('init --bare' in a for a in r.planned_actions)

    def test_init_not_triggered_for_non_file_url(self):
        """--init is a no-op for https/ssh URLs (it's file-scheme only)."""
        target = MirrorTarget(
            name='codeberg',
            url_template='https://codeberg.org/x/{repo}.git',
        )
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            mock_run.return_value = _make_run_result(returncode=1)
            mirror_repo('/tmp/fake', target, init=True, dry_run=True)

        # Should not attempt `git init --bare` for an https URL
        called = [c.args[0] for c in mock_run.call_args_list]
        assert not any(cmd[:3] == ['git', 'init', '--bare'] for cmd in called)


# ---------------------------------------------------------------------------
# mirror_repo: live end-to-end with local bare (integration-flavor)
# ---------------------------------------------------------------------------


class TestMirrorRepoIntegration:
    def test_mirror_to_local_bare_succeeds(self, tmp_path):
        source = _init_git_repo(tmp_path / 'source')
        bare = tmp_path / 'mirror.git'
        subprocess.run(
            ['git', 'init', '--bare', str(bare)], capture_output=True,
        )

        target = MirrorTarget(
            name='localmirror',
            url_template=f'file://{tmp_path}/mirror.git',  # no {repo} in path
        )
        # But url_template MUST have {repo} — so use a parametrized one.
        target = MirrorTarget(
            name='localmirror',
            url_template=f'file://{tmp_path}/{{repo}}-mirror.git',
        )
        # And create a matching bare path.
        matching_bare = tmp_path / 'source-mirror.git'
        subprocess.run(
            ['git', 'init', '--bare', str(matching_bare)],
            capture_output=True,
        )

        r = mirror_repo(str(source), target)
        assert r.status == 'ok', r.detail

        # Bare should now contain refs/heads/<default-branch>
        refs = subprocess.run(
            ['git', '--git-dir', str(matching_bare), 'for-each-ref',
             'refs/heads/'],
            capture_output=True, text=True,
        )
        assert refs.stdout.strip(), refs.stderr

    def test_mirror_fails_fast_forward_against_local_bare(self, tmp_path):
        """Simulate a divergent mirror by pushing one commit then rewriting
        history to a non-ancestor tip."""
        source = _init_git_repo(tmp_path / 'source')
        target = MirrorTarget(
            name='localmirror',
            url_template=f'file://{tmp_path}/{{repo}}-mirror.git',
        )
        # First mirror (init creates bare).
        r1 = mirror_repo(str(source), target, init=True)
        assert r1.status == 'init+pushed'

        # Rewrite history locally by resetting to a sibling commit with
        # the SAME parent but a different tree/message (guaranteed new SHA).
        subprocess.run(
            ['git', 'reset', '--soft', 'HEAD~1'],
            cwd=str(source), capture_output=True,
        )
        # If HEAD~1 doesn't exist (single-commit repo), the soft reset above
        # returns nonzero; just force a different SHA by writing a new root.
        # Simplest: delete .git/refs/heads/<branch> and re-commit.
        (source / 'other.txt').write_text('different content')
        subprocess.run(
            ['git', 'checkout', '--orphan', 'newbase'],
            cwd=str(source), capture_output=True,
        )
        subprocess.run(
            ['git', 'add', '-A'], cwd=str(source), capture_output=True,
        )
        subprocess.run(
            ['git', 'commit', '-m', 'sibling root'],
            cwd=str(source), capture_output=True,
        )
        # Rename newbase over the original default branch (force).
        r = subprocess.run(
            ['git', 'symbolic-ref', '--short', 'HEAD'],
            cwd=str(source), capture_output=True, text=True,
        )
        current = r.stdout.strip()
        # Move the new branch over the previously pushed default branch.
        # Figure out what branch was pushed initially.
        default_branch = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=str(source), capture_output=True, text=True,
        ).stdout.strip()  # will be 'newbase' right now
        # Force-move: delete the old branch and rename.
        subprocess.run(
            ['git', 'branch', '-D', 'master'],
            cwd=str(source), capture_output=True,
        )
        subprocess.run(
            ['git', 'branch', '-D', 'main'],
            cwd=str(source), capture_output=True,
        )
        # Rename newbase to the originally-pushed branch name.
        pushed_ref = subprocess.run(
            ['git', '--git-dir', str(tmp_path / 'source-mirror.git'),
             'symbolic-ref', 'HEAD'],
            capture_output=True, text=True,
        ).stdout.strip().replace('refs/heads/', '')
        subprocess.run(
            ['git', 'branch', '-M', pushed_ref],
            cwd=str(source), capture_output=True,
        )

        # Now push without --force should fail the FF check.
        r2 = mirror_repo(str(source), target, init=False, force=False)
        assert r2.status == 'failed', r2.detail
        assert 'non-fast-forward' in r2.detail

        # With --force it should succeed.
        r3 = mirror_repo(str(source), target, init=False, force=True)
        assert r3.status == 'ok', r3.detail


# ---------------------------------------------------------------------------
# mirror_repo: timeout / exception safety
# ---------------------------------------------------------------------------


class TestMirrorRepoTimeouts:
    def test_push_timeout_surfaces_as_failed(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[:3] == ['git', 'remote', 'get-url']:
                    return _make_run_result(returncode=1)
                if cmd[:3] == ['git', 'remote', 'add']:
                    return _make_run_result(returncode=0)
                if cmd[:2] == ['git', 'fetch']:
                    return _make_run_result(returncode=0)
                if cmd[:2] == ['git', 'for-each-ref']:
                    return _make_run_result(stdout='')
                if cmd[:2] == ['git', 'push']:
                    raise subprocess.TimeoutExpired(cmd, 120)
                return _make_run_result(returncode=0)
            mock_run.side_effect = side_effect
            r = mirror_repo('/tmp/fake', target)
        assert r.status == 'failed'
        assert 'timeout' in r.detail

    def test_fetch_timeout_surfaces_as_failed(self):
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[:3] == ['git', 'remote', 'get-url']:
                    return _make_run_result(returncode=1)
                if cmd[:3] == ['git', 'remote', 'add']:
                    return _make_run_result(returncode=0)
                if cmd[:2] == ['git', 'fetch']:
                    raise subprocess.TimeoutExpired(cmd, 120)
                return _make_run_result(returncode=0)
            mock_run.side_effect = side_effect
            r = mirror_repo('/tmp/fake', target)
        assert r.status == 'failed'
        assert 'timeout' in r.detail

    def test_fetch_error_on_non_init_is_failure(self):
        """A fetch error with an existing (non-init) mirror is fatal."""
        target = MirrorTarget(name='codeberg',
                              url_template='https://codeberg.org/x/{repo}.git')
        with patch(
            'repoindex.services.mirror_service.subprocess.run'
        ) as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[:3] == ['git', 'remote', 'get-url']:
                    return _make_run_result(
                        stdout='https://codeberg.org/x/fake.git\n'
                    )
                if cmd[:2] == ['git', 'fetch']:
                    return _make_run_result(returncode=1, stderr='auth failed')
                return _make_run_result(returncode=0)
            mock_run.side_effect = side_effect
            r = mirror_repo('/tmp/fake', target)
        assert r.status == 'failed'
        assert 'fetch' in r.detail


# ---------------------------------------------------------------------------
# MirrorResult: dataclass
# ---------------------------------------------------------------------------


class TestMirrorResult:
    def test_default_fields(self):
        r = MirrorResult(
            repo_name='x', repo_path='/x',
            mirror_name='m', mirror_url='u', status='ok',
        )
        assert r.detail == ''
        assert not r.added_remote
        assert r.planned_actions == []

    def test_planned_actions_is_fresh_list(self):
        """Two default instances must not share a mutable default list."""
        r1 = MirrorResult(
            repo_name='a', repo_path='/a',
            mirror_name='m', mirror_url='u', status='ok',
        )
        r2 = MirrorResult(
            repo_name='b', repo_path='/b',
            mirror_name='m', mirror_url='u', status='ok',
        )
        r1.planned_actions.append('surprise')
        assert r2.planned_actions == []
