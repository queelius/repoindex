"""Tests for GiteaSource write capabilities (Wave V2.C).

Each action goes through a cached ``requests.Session``; tests stub
``session.request`` to assert URL, method, payload, and auth header.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from repoindex.sources import GitForge, RemoteRepo
from repoindex.sources.forges.gitea import GiteaSource


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset session cache between tests."""
    src = GiteaSource()
    src._client_cache.clear()
    yield


def _ok_response(body=None, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = '{}' if body is None else 'body'
    resp.json.return_value = body or {}
    return resp


class TestGiteaActions:
    """Gitea PATCH/PUT/POST request shape."""

    def _record(self, host='codeberg.org', owner='u', name='r'):
        return {
            'forge_host': host,
            'forge_owner': owner,
            'forge_name': name,
            'remote_url': f'https://{host}/{owner}/{name}.git',
        }

    def test_set_topics_puts(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response()
            src.set_topics(self._record(), ['python', 'cli'], {})

        args, kwargs = req.call_args
        assert args[0] == 'PUT'
        assert args[1] == 'https://codeberg.org/api/v1/repos/u/r/topics'
        assert kwargs['json'] == {'topics': ['python', 'cli']}

    def test_set_description_patches(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response()
            src.set_description(self._record(), 'A description', {})

        args, kwargs = req.call_args
        assert args[0] == 'PATCH'
        assert args[1] == 'https://codeberg.org/api/v1/repos/u/r'
        assert kwargs['json'] == {'description': 'A description'}

    def test_set_archived_patches(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response()
            src.set_archived(self._record(), True, {})

        args, kwargs = req.call_args
        assert args[0] == 'PATCH'
        assert kwargs['json'] == {'archived': True}

    def test_set_visibility_public(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response()
            src.set_visibility(self._record(), True, {})

        _, kwargs = req.call_args
        assert kwargs['json'] == {'private': False}

    def test_set_visibility_private(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response()
            src.set_visibility(self._record(), False, {})

        _, kwargs = req.call_args
        assert kwargs['json'] == {'private': True}

    def test_set_default_branch(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response()
            src.set_default_branch(self._record(), 'main', {})

        _, kwargs = req.call_args
        assert kwargs['json'] == {'default_branch': 'main'}

    def test_enable_pages_raises_not_implemented(self):
        src = GiteaSource()
        with pytest.raises(NotImplementedError, match='gitea'):
            src.enable_pages(self._record(), 'gh-pages', '/', {})

    def test_action_failure_raises_runtime_error(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            resp = MagicMock()
            resp.status_code = 403
            resp.text = '{"message": "forbidden"}'
            resp.json.return_value = {'message': 'forbidden'}
            req.return_value = resp
            with pytest.raises(RuntimeError, match='forbidden'):
                src.set_topics(self._record(), ['x'], {})

    def test_record_fallback_to_remote_url(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response()
            # No forge_owner/forge_name; force parse from remote_url
            src.set_description(
                {'remote_url': 'https://codeberg.org/x/y.git'},
                'desc', {},
            )
        args, _ = req.call_args
        assert args[1] == 'https://codeberg.org/api/v1/repos/x/y'

    def test_missing_target_raises(self):
        src = GiteaSource()
        with pytest.raises(ValueError, match='Cannot resolve'):
            src.set_topics({'remote_url': 'https://github.com/x/y'}, [], {})


class TestGiteaAuthResolution:
    """Token resolution via forges.* config and env vars."""

    def test_token_from_forges_env(self, monkeypatch):
        src = GiteaSource()
        monkeypatch.setenv('MY_CODEBERG_TOKEN', 'secret-1')
        config = {
            'forges': {
                'codeberg': {
                    'host': 'codeberg.org',
                    'token_env': 'MY_CODEBERG_TOKEN',
                }
            }
        }
        assert src._get_token(config, 'codeberg.org') == 'secret-1'

    def test_token_legacy_tokens_map(self):
        src = GiteaSource()
        config = {
            'gitea': {'tokens': {'codeberg.org': 'legacy-token'}}
        }
        assert src._get_token(config, 'codeberg.org') == 'legacy-token'

    def test_token_generic_env_fallback(self, monkeypatch):
        src = GiteaSource()
        monkeypatch.setenv('GITEA_TOKEN', 'generic')
        assert src._get_token({}, 'codeberg.org') == 'generic'

    def test_token_none_when_unset(self, monkeypatch):
        src = GiteaSource()
        monkeypatch.delenv('GITEA_TOKEN', raising=False)
        assert src._get_token({}, 'codeberg.org') is None


class TestGiteaEnumerate:
    """enumerate_user_repos paginates GET /repos/search."""

    def test_enumerate_uses_login_from_author_config(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.side_effect = [
                _ok_response({
                    'data': [
                        {'name': 'a', 'clone_url': 'https://codeberg.org/u/a.git'},
                        {'name': 'b', 'clone_url': 'https://codeberg.org/u/b.git'},
                    ]
                }),
            ]
            results = list(src.enumerate_user_repos({
                'author': {'github': 'u'},
            }))
        assert [r.name for r in results] == ['a', 'b']
        assert all(isinstance(r, RemoteRepo) for r in results)
        # URL must include owner=u
        args, _ = req.call_args
        assert 'owner=u' in args[1]

    def test_enumerate_paginates(self):
        src = GiteaSource()
        full = [
            {'name': f'r{i}', 'clone_url': f'https://codeberg.org/u/r{i}.git'}
            for i in range(50)
        ]
        with patch('requests.Session.request') as req:
            req.side_effect = [
                _ok_response({'data': full}),
                _ok_response({'data': [
                    {'name': 'last', 'clone_url': 'https://codeberg.org/u/last.git'},
                ]}),
            ]
            results = list(src.enumerate_user_repos({'author': {'github': 'u'}}))

        assert results[-1].name == 'last'
        assert req.call_count == 2

    def test_enumerate_skips_host_without_login(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            results = list(src.enumerate_user_repos({}))
            req.assert_not_called()
        assert results == []

    def test_enumerate_login_from_per_host_user_field(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response({'data': []})
            list(src.enumerate_user_repos({
                'forges': {
                    'codeberg': {
                        'host': 'codeberg.org',
                        'user': 'overridden-login',
                    }
                }
            }))
        args, _ = req.call_args
        assert 'owner=overridden-login' in args[1]

    def test_enumerate_archive_flag_propagates(self):
        src = GiteaSource()
        with patch('requests.Session.request') as req:
            req.return_value = _ok_response({
                'data': [
                    {'name': 'live', 'clone_url': 'u', 'archived': False},
                    {'name': 'dead', 'clone_url': 'v', 'archived': True},
                ]
            })
            results = list(src.enumerate_user_repos({'author': {'github': 'u'}}))
        assert results[0].is_archived is False
        assert results[1].is_archived is True


class TestGiteaSubclass:
    def test_is_gitforge(self):
        assert isinstance(GiteaSource(), GitForge)
