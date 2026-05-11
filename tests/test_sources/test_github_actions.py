"""Tests for GitHubSource write capabilities (Wave V2.C).

The GitHubSource exposes set_topics, set_description, set_archived,
set_visibility, set_default_branch, enable_pages, and enumerate_user_repos.
Each method goes through GitHubClient; the tests stub the HTTP layer
(``requests.request`` / ``requests.get``) to assert request shape.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from repoindex.sources import GitForge, RemoteRepo
from repoindex.sources.forges.github import GitHubSource


@pytest.fixture(autouse=True)
def _clear_client_cache():
    """Reset module-level source and reset per-test client cache."""
    from repoindex.sources.forges.github import source as module_source
    module_source._client_cache.clear()
    yield
    module_source._client_cache.clear()


def _stub_client(use_gh_cli: bool = False):
    """Return a patcher for GitHubClient construction that avoids gh CLI."""
    return patch(
        'repoindex.sources.forges.github.GitHubClient',
        autospec=True,
    )


class TestGitHubActionDispatch:
    """The action wrappers should route to the right GitHubClient method."""

    def test_set_topics_calls_replace_topics(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.replace_topics.return_value = (True, None)
            src.set_topics(
                {'forge_owner': 'owner', 'forge_name': 'repo',
                 'remote_url': 'https://github.com/owner/repo.git'},
                ['python', 'cli'],
                {'github': {'token': 't'}},
            )
            inst.replace_topics.assert_called_once_with(
                'owner', 'repo', ['python', 'cli']
            )

    def test_set_topics_raises_on_api_error(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.replace_topics.return_value = (False, 'forbidden')
            with pytest.raises(RuntimeError, match='forbidden'):
                src.set_topics(
                    {'forge_owner': 'owner', 'forge_name': 'repo',
                     'remote_url': ''},
                    ['x'],
                    {},
                )

    def test_set_description_patches_description(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.set_repo_field.return_value = (True, None)
            src.set_description(
                {'forge_owner': 'o', 'forge_name': 'r', 'remote_url': ''},
                'Hello',
                {},
            )
            inst.set_repo_field.assert_called_once_with(
                'o', 'r', 'description', 'Hello'
            )

    def test_set_archived_passes_bool(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.set_repo_field.return_value = (True, None)
            src.set_archived(
                {'forge_owner': 'o', 'forge_name': 'r', 'remote_url': ''},
                True,
                {},
            )
            inst.set_repo_field.assert_called_once_with(
                'o', 'r', 'archived', True
            )

    def test_set_archived_false(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.set_repo_field.return_value = (True, None)
            src.set_archived(
                {'forge_owner': 'o', 'forge_name': 'r', 'remote_url': ''},
                False,
                {},
            )
            inst.set_repo_field.assert_called_once_with(
                'o', 'r', 'archived', False
            )

    def test_set_visibility_public_sets_private_false(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.set_repo_field.return_value = (True, None)
            src.set_visibility(
                {'forge_owner': 'o', 'forge_name': 'r', 'remote_url': ''},
                True,  # public
                {},
            )
            inst.set_repo_field.assert_called_once_with(
                'o', 'r', 'private', False
            )

    def test_set_visibility_private_sets_private_true(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.set_repo_field.return_value = (True, None)
            src.set_visibility(
                {'forge_owner': 'o', 'forge_name': 'r', 'remote_url': ''},
                False,  # private
                {},
            )
            inst.set_repo_field.assert_called_once_with(
                'o', 'r', 'private', True
            )

    def test_set_default_branch(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.set_repo_field.return_value = (True, None)
            src.set_default_branch(
                {'forge_owner': 'o', 'forge_name': 'r', 'remote_url': ''},
                'main',
                {},
            )
            inst.set_repo_field.assert_called_once_with(
                'o', 'r', 'default_branch', 'main'
            )

    def test_enable_pages(self):
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.create_pages_site.return_value = (True, None)
            src.enable_pages(
                {'forge_owner': 'o', 'forge_name': 'r', 'remote_url': ''},
                'gh-pages',
                '/',
                {},
            )
            inst.create_pages_site.assert_called_once_with(
                'o', 'r', 'gh-pages', '/'
            )

    def test_owner_name_fallback_to_remote_url(self):
        """Older records without forge_owner should still resolve."""
        src = GitHubSource()
        with _stub_client() as Mock:
            inst = Mock.return_value
            inst.set_repo_field.return_value = (True, None)
            src.set_description(
                {'remote_url': 'https://github.com/legacy/repo.git'},
                'desc',
                {},
            )
            inst.set_repo_field.assert_called_once_with(
                'legacy', 'repo', 'description', 'desc'
            )

    def test_missing_owner_name_raises(self):
        src = GitHubSource()
        with _stub_client():
            with pytest.raises(ValueError, match='Cannot resolve'):
                src.set_topics({'remote_url': 'https://example.org/x'}, [], {})


class TestGitHubClientWriteRequests:
    """The GitHubClient write methods should fire correct HTTP calls."""

    def test_set_repo_field_patches(self):
        from repoindex.infra.github_client import GitHubClient

        client = GitHubClient.__new__(GitHubClient)
        client.token = 'tok'
        client._rate_limit_status = None
        client.max_retries = 3
        client.base_delay = 0.0
        client.max_delay = 0.0

        with patch('requests.request') as req:
            resp = MagicMock()
            resp.status_code = 200
            resp.text = '{}'
            resp.json.return_value = {}
            resp.headers = {}
            req.return_value = resp
            ok, err = client.set_repo_field('owner', 'repo', 'description', 'x')

        assert ok and err is None
        args, kwargs = req.call_args
        assert args[0] == 'PATCH'
        assert args[1].endswith('/repos/owner/repo')
        assert kwargs['json'] == {'description': 'x'}
        assert kwargs['headers']['Authorization'] == 'token tok'

    def test_replace_topics_puts(self):
        from repoindex.infra.github_client import GitHubClient

        client = GitHubClient.__new__(GitHubClient)
        client.token = None
        client._rate_limit_status = None
        client.max_retries = 3
        client.base_delay = 0.0
        client.max_delay = 0.0

        with patch('requests.request') as req:
            resp = MagicMock()
            resp.status_code = 200
            resp.text = '{"names": ["a", "b"]}'
            resp.json.return_value = {'names': ['a', 'b']}
            resp.headers = {}
            req.return_value = resp
            ok, err = client.replace_topics('o', 'r', ['a', 'b'])

        assert ok and err is None
        args, kwargs = req.call_args
        assert args[0] == 'PUT'
        assert args[1].endswith('/repos/o/r/topics')
        assert kwargs['json'] == {'names': ['a', 'b']}

    def test_create_pages_site_post(self):
        from repoindex.infra.github_client import GitHubClient

        client = GitHubClient.__new__(GitHubClient)
        client.token = None
        client._rate_limit_status = None
        client.max_retries = 3
        client.base_delay = 0.0
        client.max_delay = 0.0

        with patch('requests.request') as req:
            resp = MagicMock()
            resp.status_code = 201
            resp.text = '{}'
            resp.json.return_value = {}
            resp.headers = {}
            req.return_value = resp
            ok, err = client.create_pages_site('o', 'r', 'gh-pages', '/')

        assert ok
        args, _ = req.call_args
        assert args[0] == 'POST'

    def test_create_pages_site_falls_back_to_put_on_409(self):
        from repoindex.infra.github_client import GitHubClient

        client = GitHubClient.__new__(GitHubClient)
        client.token = None
        client._rate_limit_status = None
        client.max_retries = 3
        client.base_delay = 0.0
        client.max_delay = 0.0

        responses = [
            MagicMock(status_code=409, text='{}', json=lambda: {}, headers={}),
            MagicMock(status_code=200, text='{}', json=lambda: {}, headers={}),
        ]

        with patch('requests.request', side_effect=responses) as req:
            ok, err = client.create_pages_site('o', 'r', 'main', '/docs')

        assert ok
        assert req.call_count == 2
        assert req.call_args_list[1][0][0] == 'PUT'

    def test_set_repo_field_returns_error_message(self):
        from repoindex.infra.github_client import GitHubClient

        client = GitHubClient.__new__(GitHubClient)
        client.token = None
        client._rate_limit_status = None
        client.max_retries = 3
        client.base_delay = 0.0
        client.max_delay = 0.0

        with patch('requests.request') as req:
            resp = MagicMock()
            resp.status_code = 403
            resp.text = '{"message": "forbidden"}'
            resp.json.return_value = {'message': 'forbidden'}
            resp.headers = {}
            req.return_value = resp
            ok, err = client.set_repo_field('o', 'r', 'archived', True)

        assert not ok
        assert err == 'forbidden'


class TestEnumerateUserRepos:
    """enumerate_user_repos should paginate and filter by owner."""

    def _resp(self, body, link=None, status=200):
        m = MagicMock()
        m.status_code = status
        m.text = '[]'
        m.json.return_value = body
        m.headers = {'Link': link} if link else {}
        return m

    def test_enumerate_yields_remoterepos(self):
        src = GitHubSource()
        page1 = [
            {
                'name': 'repo1',
                'clone_url': 'https://github.com/u/repo1.git',
                'default_branch': 'main',
                'archived': False,
                'description': 'one',
                'owner': {'login': 'u'},
            },
            {
                'name': 'repo2',
                'clone_url': 'https://github.com/u/repo2.git',
                'default_branch': 'master',
                'archived': True,
                'description': None,
                'owner': {'login': 'u'},
            },
        ]
        with patch('requests.get') as get:
            get.return_value = self._resp(page1)
            results = list(src.enumerate_user_repos({'author': {'github': 'u'}}))

        assert len(results) == 2
        assert all(isinstance(r, RemoteRepo) for r in results)
        assert results[0].name == 'repo1'
        assert results[0].is_archived is False
        assert results[1].is_archived is True

    def test_enumerate_follows_link_next(self):
        src = GitHubSource()
        url1 = (
            '<https://api.github.com/user/repos?page=2>; rel="next", '
            '<https://api.github.com/user/repos?page=3>; rel="last"'
        )
        with patch('requests.get') as get:
            get.side_effect = [
                self._resp(
                    [{'name': 'a', 'clone_url': 'u', 'owner': {'login': 'u'}}],
                    link=url1,
                ),
                self._resp(
                    [{'name': 'b', 'clone_url': 'v', 'owner': {'login': 'u'}}],
                ),
            ]
            results = list(src.enumerate_user_repos({'author': {'github': 'u'}}))

        assert [r.name for r in results] == ['a', 'b']

    def test_enumerate_filters_by_login(self):
        src = GitHubSource()
        with patch('requests.get') as get:
            get.return_value = self._resp([
                {'name': 'mine', 'clone_url': 'a',
                 'owner': {'login': 'u'}},
                {'name': 'not_mine', 'clone_url': 'b',
                 'owner': {'login': 'someone_else'}},
            ])
            results = list(src.enumerate_user_repos({'author': {'github': 'u'}}))

        assert [r.name for r in results] == ['mine']

    def test_enumerate_no_login_returns_all(self):
        src = GitHubSource()
        with patch('requests.get') as get:
            get.return_value = self._resp([
                {'name': 'a', 'clone_url': 'a', 'owner': {'login': 'foo'}},
                {'name': 'b', 'clone_url': 'b', 'owner': {'login': 'bar'}},
            ])
            results = list(src.enumerate_user_repos({}))

        assert [r.name for r in results] == ['a', 'b']

    def test_enumerate_uses_auth_header(self):
        src = GitHubSource()
        with patch('requests.get') as get:
            get.return_value = self._resp([])
            list(src.enumerate_user_repos(
                {'github': {'token': 'tok'}, 'author': {'github': 'u'}}
            ))
            _, kwargs = get.call_args
            assert kwargs['headers']['Authorization'] == 'token tok'


class TestGitHubGitForgeSubclass:
    def test_is_gitforge(self):
        src = GitHubSource()
        assert isinstance(src, GitForge)
