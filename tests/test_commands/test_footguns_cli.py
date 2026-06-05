"""CLI footgun guards: dead positional query_string and set-* confirmation.

Mirrors the CliRunner patterns in tests/test_commands/test_set_actions.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner


def _runner():
    return CliRunner()


class TestQueryStringGuard:
    def test_get_repos_from_query_raises_on_nonempty(self):
        from repoindex.commands.ops import _get_repos_from_query

        with pytest.raises(click.UsageError) as exc:
            _get_repos_from_query({}, "language == 'Python'")
        msg = str(exc.value)
        assert "positional queries were removed in v0.16" in msg
        assert "--language" in msg

    def test_git_status_positional_errors(self):
        from repoindex.commands.ops import git_status_handler

        with patch('repoindex.commands.ops.load_config', return_value={}):
            result = _runner().invoke(
                git_status_handler, ["language == 'Python'"]
            )
        assert result.exit_code != 0
        assert "positional queries were removed in v0.16" in result.output

    def test_wip_snapshot_positional_errors(self):
        from repoindex.commands.ops import wip_snapshot_handler

        with patch('repoindex.commands.ops.load_config', return_value={}):
            result = _runner().invoke(
                wip_snapshot_handler, ["name == 'dreamlog'"]
            )
        assert result.exit_code != 0
        assert "positional queries were removed in v0.16" in result.output

    def test_audit_positional_errors(self):
        from repoindex.commands.ops import ops_audit_handler

        with patch('repoindex.commands.ops.load_config', return_value={}):
            result = _runner().invoke(
                ops_audit_handler, ["not has_license"]
            )
        assert result.exit_code != 0
        assert "positional queries were removed in v0.16" in result.output


class TestFlagPathStillWorks:
    def test_empty_positional_passes_flags_through(self):
        from repoindex.commands.ops import _get_repos_from_query

        sentinel = [{'name': 'a', 'path': '/tmp/a'}]
        with patch(
            'repoindex.commands.ops.fetch_repos_by_flags',
            return_value=sentinel,
        ) as fake:
            repos = _get_repos_from_query(
                {}, '', language='python', dirty=True,
                tag=('work/*',), recent='7d',
            )
        assert repos is sentinel
        _, kwargs = fake.call_args
        assert kwargs['language'] == 'python'
        assert kwargs['dirty'] is True
        assert kwargs['tag'] == ('work/*',)
        assert kwargs['recent'] == '7d'


class TestNoDslDocstrings:
    def test_no_dsl_examples_in_source(self):
        import inspect
        import repoindex.commands.ops as ops_mod

        src = inspect.getsource(ops_mod)
        forbidden = [
            'git push "language',
            'pull "is_clean"',
            'license "not has_license"',
            'license --license apache-2.0 "not has_license"',
            'wip-snapshot "name ==',
            'same query filters as the query command',
        ]
        offenders = [f for f in forbidden if f in src]
        assert offenders == [], f"DSL residue still present: {offenders}"


class TestConfirmBulkSetHelper:
    def test_single_repo_never_prompts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=1, dry_run=False, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_dry_run_never_prompts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=True, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_json_never_prompts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=True, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_non_tty_never_prompts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=False), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_yes_bypasses_prompt(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=False, yes=True,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_not_called()

    def test_bulk_tty_prompts_and_yes_answer_proceeds(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm', return_value=True) as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is True
        confirm.assert_called_once()

    def test_bulk_tty_prompts_and_no_answer_aborts(self):
        from repoindex.commands.ops import _confirm_bulk_set

        with patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm', return_value=False) as confirm:
            ok = _confirm_bulk_set(
                n=5, dry_run=False, output_json=False, yes=False,
                action_name='set_topics',
            )
        assert ok is False
        confirm.assert_called_once()


class TestSetTopicsConfirmation:
    def _bulk_patches(self):
        fake = MagicMock()
        fake.source_id = 'github'
        repos = [
            {'name': 'a', 'path': '/tmp/a', 'forge_id': 'github'},
            {'name': 'b', 'path': '/tmp/b', 'forge_id': 'github'},
        ]
        return fake, repos

    def test_bulk_aborts_on_no(self):
        from repoindex.commands.ops import set_topics_handler

        fake, repos = self._bulk_patches()
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.commands.ops._get_repos_from_query', return_value=repos), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm', return_value=False), \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['--all', 'python', 'cli'],
            )
        assert 'Aborted.' in result.output
        fake.set_topics.assert_not_called()

    def test_bulk_prompts_and_proceeds_on_yes_answer(self):
        from repoindex.commands.ops import set_topics_handler

        fake, repos = self._bulk_patches()
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.commands.ops._get_repos_from_query', return_value=repos), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm', return_value=True) as confirm, \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['--all', 'python', 'cli'],
            )
        assert result.exit_code == 0, result.output
        confirm.assert_called_once()
        assert fake.set_topics.call_count == 2

    def test_yes_flag_bypasses_prompt(self):
        from repoindex.commands.ops import set_topics_handler

        fake, repos = self._bulk_patches()
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.commands.ops._get_repos_from_query', return_value=repos), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm, \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['--all', '--yes', 'python', 'cli'],
            )
        assert result.exit_code == 0, result.output
        confirm.assert_not_called()
        assert fake.set_topics.call_count == 2

    def test_single_repo_does_not_prompt(self):
        from repoindex.commands.ops import set_topics_handler

        fake = MagicMock()
        fake.source_id = 'github'
        repo = {'name': 'myrepo', 'path': '/tmp/myrepo', 'forge_id': 'github'}
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.database.repository.get_repo_by_name', return_value=repo), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm, \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['myrepo', 'python'],
            )
        assert result.exit_code == 0, result.output
        confirm.assert_not_called()
        fake.set_topics.assert_called_once()

    def test_json_bulk_does_not_prompt(self):
        from repoindex.commands.ops import set_topics_handler

        fake, repos = self._bulk_patches()
        with patch('repoindex.commands.ops.load_config', return_value={}), \
             patch('repoindex.commands.ops._get_repos_from_query', return_value=repos), \
             patch('repoindex.commands.ops._stdout_isatty', return_value=True), \
             patch('repoindex.commands.ops.click.confirm') as confirm, \
             patch('repoindex.services.forge_actions.lookup_repo_forge', return_value=fake):
            result = _runner().invoke(
                set_topics_handler, ['--all', '--json', 'python', 'cli'],
            )
        assert result.exit_code == 0, result.output
        confirm.assert_not_called()
        assert '"summary"' in result.output


class TestYesFlagAccepted:
    @pytest.mark.parametrize('handler_name', [
        'set_topics_handler',
        'set_description_handler',
        'set_archived_handler',
        'set_visibility_handler',
        'set_default_branch_handler',
        'set_pages_handler',
    ])
    def test_handler_has_yes_param(self, handler_name):
        import repoindex.commands.ops as ops_mod

        handler = getattr(ops_mod, handler_name)
        params = [p.name for p in handler.params]
        assert 'yes' in params
