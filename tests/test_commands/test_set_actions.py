"""CLI tests for the new ops set-* commands (Wave V2.C).

Each handler is exercised through Click's CliRunner. We stub
``find_forge`` / ``lookup_repo_forge`` and ``get_repo_by_name`` so the
tests don't touch the real DB or HTTP layer.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


def _runner():
    return CliRunner()


def _make_repo_row(name='myrepo', forge_id='github'):
    """A minimal DB row stub matching what get_repo_by_name returns."""
    return {
        'id': 1,
        'name': name,
        'path': f'/tmp/{name}',
        'remote_url': f'https://github.com/user/{name}.git',
        'forge_id': forge_id,
        'forge_owner': 'user',
        'forge_name': name,
    }


def _patch_for_single_repo(forge_id='github', name='myrepo'):
    """Convenience to stack the DB + forge stubs."""
    repo = _make_repo_row(name, forge_id)
    fake_forge = MagicMock()
    fake_forge.source_id = forge_id

    patchers = [
        patch('repoindex.commands.ops.load_config', return_value={}),
        patch(
            'repoindex.database.repository.get_repo_by_name',
            return_value=repo,
        ),
        patch(
            'repoindex.services.forge_actions.lookup_repo_forge',
            return_value=fake_forge,
        ),
    ]
    return patchers, fake_forge


def _start_all(patchers):
    return [p.start() for p in patchers]


def _stop_all(patchers):
    for p in patchers:
        p.stop()


class TestSetTopics:
    def test_single_repo(self):
        from repoindex.commands.ops import set_topics_handler

        patchers, fake = _patch_for_single_repo()
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_topics_handler,
                ['myrepo', 'python', 'cli'],
            )
            assert result.exit_code == 0, result.stderr
            fake.set_topics.assert_called_once()
            args, _ = fake.set_topics.call_args
            assert args[1] == ['python', 'cli']
        finally:
            _stop_all(patchers)

    def test_dry_run_does_not_invoke_forge(self):
        from repoindex.commands.ops import set_topics_handler

        patchers, fake = _patch_for_single_repo()
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_topics_handler,
                ['myrepo', 'python', '--dry-run'],
            )
            assert result.exit_code == 0, result.stderr
            fake.set_topics.assert_not_called()
            assert 'dry-run' in (result.output + result.stderr).lower() or \
                'DRY' in (result.output + result.stderr)
        finally:
            _stop_all(patchers)

    def test_no_repo_and_no_all_errors(self):
        from repoindex.commands.ops import set_topics_handler

        result = _runner().invoke(set_topics_handler, ['python'])
        # Click sees REPO=python and topics=() -> empty topics; or REPO=python
        # is the positional and we hit "provide topics" -> sys.exit(2)
        assert result.exit_code != 0

    def test_no_topics_errors(self):
        from repoindex.commands.ops import set_topics_handler

        result = _runner().invoke(set_topics_handler, [])
        assert result.exit_code != 0

    def test_bulk_mode_requires_all(self):
        """Without REPO and without --all, the resolver should refuse."""
        from repoindex.commands.ops import set_topics_handler

        with patch('repoindex.commands.ops.load_config', return_value={}):
            result = _runner().invoke(set_topics_handler, ['--language', 'python'])
        assert result.exit_code != 0

    def test_bulk_with_all(self):
        from repoindex.commands.ops import set_topics_handler

        fake = MagicMock()
        fake.source_id = 'github'
        repos = [
            _make_repo_row('a'),
            _make_repo_row('b'),
        ]
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch(
                 'repoindex.commands.ops._get_repos_from_query',
                 return_value=repos,
             ), \
             patch(
                 'repoindex.services.forge_actions.lookup_repo_forge',
                 return_value=fake,
             ):
            result = _runner().invoke(
                set_topics_handler, ['--all', 'python', 'cli'],
            )
        assert result.exit_code == 0, result.stderr
        assert fake.set_topics.call_count == 2

    def test_unknown_repo_errors(self):
        from repoindex.commands.ops import set_topics_handler

        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch(
                 'repoindex.database.repository.get_repo_by_name',
                 return_value=None,
             ):
            result = _runner().invoke(set_topics_handler, ['nope', 'x'])
        assert result.exit_code != 0

    def test_repo_without_forge_id_skipped(self):
        from repoindex.commands.ops import set_topics_handler

        row = _make_repo_row('myrepo', forge_id=None)
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch(
                 'repoindex.database.repository.get_repo_by_name',
                 return_value=row,
             ):
            result = _runner().invoke(
                set_topics_handler, ['myrepo', 'x'],
            )
        # No failure, just a "skipped" row in output (forge_id missing).
        assert result.exit_code == 0
        combined = result.output + result.stderr
        assert 'skipped' in combined.lower() or 'forge_id' in combined

    def test_not_implemented_surfaces_as_skipped(self):
        from repoindex.commands.ops import set_topics_handler

        patchers, fake = _patch_for_single_repo()
        fake.set_topics.side_effect = NotImplementedError(
            "this forge has no set_topics"
        )
        _start_all(patchers)
        try:
            result = _runner().invoke(set_topics_handler, ['myrepo', 'x'])
            assert result.exit_code == 0
            assert 'skipped' in (result.output + result.stderr).lower()
        finally:
            _stop_all(patchers)


class TestSetDescription:
    def test_single_repo(self):
        from repoindex.commands.ops import set_description_handler

        patchers, fake = _patch_for_single_repo()
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_description_handler, ['myrepo', 'A new description'],
            )
            assert result.exit_code == 0, result.stderr
            args, _ = fake.set_description.call_args
            assert args[1] == 'A new description'
        finally:
            _stop_all(patchers)

    def test_missing_description_errors(self):
        from repoindex.commands.ops import set_description_handler

        result = _runner().invoke(set_description_handler, ['myrepo'])
        assert result.exit_code != 0


class TestSetArchived:
    @pytest.mark.parametrize('value,expected', [
        ('true', True),
        ('false', False),
        ('TRUE', True),
        ('False', False),
    ])
    def test_value_parsing(self, value, expected):
        from repoindex.commands.ops import set_archived_handler

        patchers, fake = _patch_for_single_repo()
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_archived_handler, ['myrepo', value],
            )
            assert result.exit_code == 0, result.stderr
            args, _ = fake.set_archived.call_args
            assert args[1] is expected
        finally:
            _stop_all(patchers)

    def test_invalid_value_errors(self):
        from repoindex.commands.ops import set_archived_handler

        result = _runner().invoke(set_archived_handler, ['myrepo', 'maybe'])
        assert result.exit_code != 0


class TestSetVisibility:
    @pytest.mark.parametrize('value,public', [
        ('public', True),
        ('private', False),
    ])
    def test_value_parsing(self, value, public):
        from repoindex.commands.ops import set_visibility_handler

        patchers, fake = _patch_for_single_repo()
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_visibility_handler, ['myrepo', value],
            )
            assert result.exit_code == 0, result.stderr
            args, _ = fake.set_visibility.call_args
            assert args[1] is public
        finally:
            _stop_all(patchers)


class TestSetDefaultBranch:
    def test_branch_arg(self):
        from repoindex.commands.ops import set_default_branch_handler

        patchers, fake = _patch_for_single_repo()
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_default_branch_handler, ['myrepo', 'main'],
            )
            assert result.exit_code == 0, result.stderr
            args, _ = fake.set_default_branch.call_args
            assert args[1] == 'main'
        finally:
            _stop_all(patchers)

    def test_missing_branch_errors(self):
        from repoindex.commands.ops import set_default_branch_handler

        result = _runner().invoke(set_default_branch_handler, ['myrepo'])
        assert result.exit_code != 0


class TestSetPages:
    def test_branch_and_path(self):
        from repoindex.commands.ops import set_pages_handler

        patchers, fake = _patch_for_single_repo()
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_pages_handler,
                ['myrepo', '--branch', 'gh-pages', '--path', '/'],
            )
            assert result.exit_code == 0, result.stderr
            args, _ = fake.enable_pages.call_args
            assert args[1] == 'gh-pages'
            assert args[2] == '/'
        finally:
            _stop_all(patchers)

    def test_no_all_flag(self):
        """set-pages has no --all option (per-repo only)."""
        from repoindex.commands.ops import set_pages_handler

        result = _runner().invoke(
            set_pages_handler,
            ['myrepo', '--all', '--branch', 'gh-pages'],
        )
        # --all is not a defined option; Click should error.
        assert result.exit_code != 0

    def test_gitea_pages_surfaces_skipped(self):
        from repoindex.commands.ops import set_pages_handler

        patchers, fake = _patch_for_single_repo(forge_id='gitea')
        fake.enable_pages.side_effect = NotImplementedError(
            "gitea does not support enable_pages"
        )
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_pages_handler,
                ['myrepo', '--branch', 'gh-pages'],
            )
            assert result.exit_code == 0
            combined = result.output + result.stderr
            assert 'skipped' in combined.lower() or 'gitea' in combined.lower()
        finally:
            _stop_all(patchers)


class TestJsonOutput:
    def test_json_summary_emitted(self):
        from repoindex.commands.ops import set_topics_handler

        patchers, fake = _patch_for_single_repo()
        _start_all(patchers)
        try:
            result = _runner().invoke(
                set_topics_handler,
                ['myrepo', 'x', '--json'],
            )
            assert result.exit_code == 0, result.stderr
            # JSON output goes to stdout (not stderr)
            assert '"summary"' in result.output
        finally:
            _stop_all(patchers)


class TestForgeFailurePropagates:
    def test_runtime_error_is_failed_row(self):
        from repoindex.commands.ops import set_topics_handler

        patchers, fake = _patch_for_single_repo()
        fake.set_topics.side_effect = RuntimeError('bad token')
        _start_all(patchers)
        try:
            result = _runner().invoke(set_topics_handler, ['myrepo', 'x'])
            # Failure exits non-zero
            assert result.exit_code != 0
            combined = result.output + result.stderr
            assert 'bad token' in combined.lower() or 'failed' in combined.lower()
        finally:
            _stop_all(patchers)
