"""CliRunner tests for `repoindex ops mirror`."""
import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from repoindex.commands.ops import mirror_handler
from repoindex.services.mirror_service import MirrorResult


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _fake_config_with_mirrors():
    return {
        'mirrors': [
            {'name': 'codeberg',
             'url_template': 'https://codeberg.org/queelius/{repo}.git'},
            {'name': 'gitea-gdrive',
             'url_template': 'file:///mnt/gdrive/git-mirrors/{repo}.git'},
        ]
    }


def _fake_config_no_mirrors():
    return {'mirrors': []}


def _fake_repos():
    return [
        {'path': '/home/x/github/dreamlog', 'name': 'dreamlog'},
        {'path': '/home/x/github/mcts', 'name': 'mcts'},
    ]


def _patch_cli_env(monkeypatch, config=None, repos=None):
    """Patch load_config + _get_repos_from_query used by the handler."""
    monkeypatch.setattr(
        'repoindex.commands.ops.load_config',
        lambda: config if config is not None else _fake_config_with_mirrors(),
    )
    monkeypatch.setattr(
        'repoindex.commands.ops._get_repos_from_query',
        lambda *a, **kw: (repos if repos is not None else _fake_repos()),
    )


# ---------------------------------------------------------------------------
# Scoping errors
# ---------------------------------------------------------------------------


class TestScoping:
    def test_no_to_and_no_all_errors(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(mirror_handler, [])
        assert result.exit_code == 2
        # The error should mention --to or --all.
        assert '--to' in result.output or '--to' in result.stderr \
            or 'Specify' in (result.output + (result.stderr or ''))

    def test_both_to_and_all_errors(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg', '--all']
        )
        assert result.exit_code == 2
        combined = result.output + (result.stderr or '')
        assert 'mutually exclusive' in combined

    def test_unknown_mirror_name_errors(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--to', 'nosuch'])
        assert result.exit_code == 2
        combined = result.output + (result.stderr or '')
        assert 'unknown mirror' in combined

    def test_no_mirrors_configured_errors(self, monkeypatch):
        _patch_cli_env(monkeypatch, config=_fake_config_no_mirrors())
        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--to', 'codeberg'])
        assert result.exit_code == 2

    def test_invalid_mirrors_config_errors(self, monkeypatch):
        _patch_cli_env(
            monkeypatch,
            config={'mirrors': [{'name': 'codeberg'}]},  # missing url_template
        )
        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--to', 'codeberg'])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestToFlag:
    def test_to_single_mirror(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        calls = []

        def fake_mirror(repo_path, target, force=False, init=False, dry_run=False):
            calls.append((repo_path, target.name))
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u',
                status='ok', detail='pushed',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--to', 'codeberg'])
        assert result.exit_code == 0, result.output
        # Each of 2 repos mirrored to 1 target -> 2 calls
        assert len(calls) == 2
        assert all(name == 'codeberg' for _, name in calls)

    def test_all_flag_uses_every_mirror(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        calls = []

        def fake_mirror(repo_path, target, force=False, init=False, dry_run=False):
            calls.append((repo_path, target.name))
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u',
                status='ok', detail='',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--all'])
        assert result.exit_code == 0, result.output
        # 2 repos x 2 mirrors = 4 calls
        assert len(calls) == 4
        names = {name for _, name in calls}
        assert names == {'codeberg', 'gitea-gdrive'}

    def test_multiple_to_flags(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        calls = []

        def fake_mirror(repo_path, target, force=False, init=False, dry_run=False):
            calls.append((repo_path, target.name))
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u', status='ok',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg', '--to', 'gitea-gdrive'],
        )
        assert result.exit_code == 0, result.output
        names = {name for _, name in calls}
        assert names == {'codeberg', 'gitea-gdrive'}


# ---------------------------------------------------------------------------
# Flag plumbing
# ---------------------------------------------------------------------------


class TestFlagPlumbing:
    def test_dry_run_forwarded(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        captured = {}

        def fake_mirror(repo_path, target, force=False, init=False, dry_run=False):
            captured['dry_run'] = dry_run
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u',
                status='dry-run', detail='would push',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg', '--dry-run'],
        )
        assert result.exit_code == 0
        assert captured['dry_run'] is True

    def test_force_forwarded(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        captured = {}

        def fake_mirror(repo_path, target, force=False, init=False, dry_run=False):
            captured['force'] = force
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u', status='ok',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg', '--force'],
        )
        assert result.exit_code == 0
        assert captured['force'] is True

    def test_init_forwarded(self, monkeypatch):
        _patch_cli_env(monkeypatch)
        captured = {}

        def fake_mirror(repo_path, target, force=False, init=False, dry_run=False):
            captured['init'] = init
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u', status='ok',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg', '--init'],
        )
        assert result.exit_code == 0
        assert captured['init'] is True


# ---------------------------------------------------------------------------
# Repo filtering
# ---------------------------------------------------------------------------


class TestRepoFiltering:
    def test_language_flag_forwarded_to_resolver(self, monkeypatch):
        captured = {}

        def fake_resolver(*args, **kwargs):
            captured.update(kwargs)
            return _fake_repos()

        monkeypatch.setattr(
            'repoindex.commands.ops.load_config',
            lambda: _fake_config_with_mirrors(),
        )
        monkeypatch.setattr(
            'repoindex.commands.ops._get_repos_from_query', fake_resolver,
        )
        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo',
            lambda p, t, **kw: MirrorResult(
                repo_name='x', repo_path=p,
                mirror_name=t.name, mirror_url='u', status='ok',
            ),
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg', '--language', 'python'],
        )
        assert result.exit_code == 0
        assert captured.get('language') == 'python'

    def test_dirty_flag_forwarded_to_resolver(self, monkeypatch):
        captured = {}

        def fake_resolver(*args, **kwargs):
            captured.update(kwargs)
            return _fake_repos()

        monkeypatch.setattr(
            'repoindex.commands.ops.load_config',
            lambda: _fake_config_with_mirrors(),
        )
        monkeypatch.setattr(
            'repoindex.commands.ops._get_repos_from_query', fake_resolver,
        )
        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo',
            lambda p, t, **kw: MirrorResult(
                repo_name='x', repo_path=p,
                mirror_name=t.name, mirror_url='u', status='ok',
            ),
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg', '--dirty'],
        )
        assert result.exit_code == 0
        assert captured.get('dirty') is True

    def test_tag_flag_forwarded_to_resolver(self, monkeypatch):
        captured = {}

        def fake_resolver(*args, **kwargs):
            captured.update(kwargs)
            return _fake_repos()

        monkeypatch.setattr(
            'repoindex.commands.ops.load_config',
            lambda: _fake_config_with_mirrors(),
        )
        monkeypatch.setattr(
            'repoindex.commands.ops._get_repos_from_query', fake_resolver,
        )
        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo',
            lambda p, t, **kw: MirrorResult(
                repo_name='x', repo_path=p,
                mirror_name=t.name, mirror_url='u', status='ok',
            ),
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg',
                             '--tag', 'work/*', '--tag', 'active'],
        )
        assert result.exit_code == 0
        assert captured.get('tag') == ('work/*', 'active')

    def test_recent_flag_forwarded_to_resolver(self, monkeypatch):
        captured = {}

        def fake_resolver(*args, **kwargs):
            captured.update(kwargs)
            return _fake_repos()

        monkeypatch.setattr(
            'repoindex.commands.ops.load_config',
            lambda: _fake_config_with_mirrors(),
        )
        monkeypatch.setattr(
            'repoindex.commands.ops._get_repos_from_query', fake_resolver,
        )
        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo',
            lambda p, t, **kw: MirrorResult(
                repo_name='x', repo_path=p,
                mirror_name=t.name, mirror_url='u', status='ok',
            ),
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--to', 'codeberg', '--recent', '7d'],
        )
        assert result.exit_code == 0
        assert captured.get('recent') == '7d'

    def test_empty_repo_list_returns_cleanly(self, monkeypatch):
        _patch_cli_env(monkeypatch, repos=[])
        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--to', 'codeberg'])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------


class TestOutput:
    def test_json_output_has_one_row_per_repo_mirror_pair(self, monkeypatch):
        _patch_cli_env(monkeypatch)

        def fake_mirror(repo_path, target, **kw):
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name,
                mirror_url=f'https://codeberg.org/x/{target.name}.git',
                status='ok', detail='pushed',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--all', '--json'])
        assert result.exit_code == 0, result.output

        records = []
        for line in result.output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Human-mode lines from stderr may leak into older clicks.
                pass

        # Filter to per-pair rows (not summary)
        pair_rows = [r for r in records if 'status' in r and 'mirror' in r]
        # 2 repos x 2 mirrors = 4 rows
        assert len(pair_rows) == 4

        # Check one summary line exists
        summaries = [r for r in records if 'summary' in r]
        assert len(summaries) == 1
        assert summaries[0]['summary']['mirrored'] == 4
        assert summaries[0]['summary']['failed'] == 0

    def test_json_summary_counts_mixed_statuses(self, monkeypatch):
        _patch_cli_env(monkeypatch)

        # Return different statuses per call
        call_i = {'n': 0}

        def fake_mirror(repo_path, target, **kw):
            call_i['n'] += 1
            statuses = ['ok', 'skipped', 'failed']
            status = statuses[(call_i['n'] - 1) % 3]
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u',
                status=status, detail='test',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--all', '--json'])
        assert result.exit_code == 0

        records = []
        for line in result.output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        summaries = [r for r in records if 'summary' in r]
        assert summaries
        # 4 calls total -> 2 ok, 1 skipped, 1 failed
        # (call sequence 1..4 → ok, skipped, failed, ok)
        s = summaries[0]['summary']
        assert s['mirrored'] == 2
        assert s['skipped'] == 1
        assert s['failed'] == 1

    def test_pretty_output_runs_without_error(self, monkeypatch):
        _patch_cli_env(monkeypatch)

        def fake_mirror(repo_path, target, **kw):
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u',
                status='ok', detail='pushed',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--to', 'codeberg'])
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Exception isolation
# ---------------------------------------------------------------------------


class TestExceptionIsolation:
    def test_one_mirror_failure_does_not_kill_batch(self, monkeypatch):
        _patch_cli_env(monkeypatch)

        def fake_mirror(repo_path, target, **kw):
            if target.name == 'codeberg' and 'dreamlog' in repo_path:
                raise RuntimeError('simulated explosion')
            return MirrorResult(
                repo_name='x', repo_path=repo_path,
                mirror_name=target.name, mirror_url='u',
                status='ok', detail='pushed',
            )

        monkeypatch.setattr(
            'repoindex.services.mirror_service.mirror_repo', fake_mirror,
        )

        runner = CliRunner()
        result = runner.invoke(
            mirror_handler, ['--all', '--json'], catch_exceptions=False,
        )
        assert result.exit_code == 0

        records = []
        for line in result.output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        statuses = [r['status'] for r in records if 'status' in r]
        # Must include both the ok'd rows and the failed one.
        assert 'ok' in statuses
        assert 'failed' in statuses


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------


class TestHelp:
    def test_help_lists_scoping_flags(self):
        runner = CliRunner()
        result = runner.invoke(mirror_handler, ['--help'])
        assert result.exit_code == 0
        assert '--to' in result.output
        assert '--all' in result.output
        assert '--init' in result.output
        assert '--force' in result.output
        assert '--dry-run' in result.output
