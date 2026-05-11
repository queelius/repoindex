"""Tests for repoindex.sources.forge_resolution.resolve_forge.

Wave V2.B: this helper bridges the source ABC discovery layer and the
per-repo forge metadata fetch by mapping a remote_url to a forge_id.
"""

from repoindex.sources.forge_resolution import (
    DEFAULT_FORGE_HOSTS,
    resolve_forge,
    _extract_host,
)


class TestDefaultForgeHosts:
    def test_github_canonical(self):
        assert DEFAULT_FORGE_HOSTS['github.com'] == 'github'

    def test_codeberg_runs_gitea(self):
        assert DEFAULT_FORGE_HOSTS['codeberg.org'] == 'gitea'


class TestExtractHost:
    def test_https(self):
        assert _extract_host('https://github.com/u/r.git') == 'github.com'

    def test_http(self):
        assert _extract_host('http://gitea.example.com/u/r') == 'gitea.example.com'

    def test_ssh_with_scheme(self):
        assert _extract_host('ssh://git@github.com:22/u/r.git') == 'github.com'

    def test_ssh_no_scheme(self):
        assert _extract_host('git@github.com:user/repo.git') == 'github.com'

    def test_ssh_other_user(self):
        assert _extract_host('admin@gitea.internal:team/repo.git') == 'gitea.internal'

    def test_https_strips_port(self):
        assert _extract_host('https://gitea.example.com:3000/u/r') == 'gitea.example.com'

    def test_empty(self):
        assert _extract_host('') is None

    def test_none_string(self):
        # _extract_host is only called with strings, but be defensive.
        assert _extract_host('') is None

    def test_garbage(self):
        assert _extract_host('not-a-url') is None


class TestResolveForge:
    def test_github_https(self):
        assert resolve_forge('https://github.com/u/r.git', None) == ('github', 'github.com')

    def test_github_ssh(self):
        assert resolve_forge('git@github.com:user/repo.git', None) == ('github', 'github.com')

    def test_codeberg_resolves_to_gitea(self):
        assert resolve_forge('https://codeberg.org/user/repo.git', None) == ('gitea', 'codeberg.org')

    def test_codeberg_ssh(self):
        assert resolve_forge('git@codeberg.org:user/repo.git', None) == ('gitea', 'codeberg.org')

    def test_unknown_host_returns_none(self):
        assert resolve_forge('https://gitlab.com/u/r.git', None) is None

    def test_empty_url_returns_none(self):
        assert resolve_forge('', None) is None

    def test_none_url_returns_none(self):
        assert resolve_forge(None, None) is None

    def test_garbage_url_returns_none(self):
        assert resolve_forge('not-a-url', None) is None

    def test_user_configured_forge_dict(self):
        config = {
            'forges': {
                'gitea-internal': {
                    'source_id': 'gitea',
                    'host': 'gitea.example.com',
                },
            }
        }
        assert resolve_forge(
            'https://gitea.example.com/team/proj.git', config
        ) == ('gitea', 'gitea.example.com')

    def test_user_configured_forge_falls_back_to_entry_name(self):
        """When source_id is missing, the entry name is used as forge_id."""
        config = {
            'forges': {
                'gitea': {
                    'host': 'gitea.example.com',
                },
            }
        }
        assert resolve_forge(
            'https://gitea.example.com/team/proj.git', config
        ) == ('gitea', 'gitea.example.com')

    def test_built_in_takes_precedence_over_user_config(self):
        """github.com always resolves to 'github' regardless of user config."""
        config = {
            'forges': {
                'sneaky': {
                    'source_id': 'something-else',
                    'host': 'github.com',
                },
            }
        }
        assert resolve_forge(
            'https://github.com/u/r.git', config
        ) == ('github', 'github.com')

    def test_self_hosted_gitea_via_ssh(self):
        config = {
            'forges': {
                'gitea-vps': {
                    'source_id': 'gitea',
                    'host': 'gitea.myvps.net',
                },
            }
        }
        assert resolve_forge(
            'git@gitea.myvps.net:me/notes.git', config
        ) == ('gitea', 'gitea.myvps.net')

    def test_no_forges_in_config(self):
        assert resolve_forge('https://gitlab.com/u/r.git', {}) is None
        assert resolve_forge('https://gitlab.com/u/r.git', {'forges': {}}) is None
        assert resolve_forge('https://gitlab.com/u/r.git', {'forges': None}) is None

    def test_mirror_role_entries_still_contribute_to_resolution(self):
        """A repo cloned from a mirror's host is still a forge repo.

        The mirror role tags the entry as a redundancy destination but does
        not remove it from the hostname mapping used during refresh.
        """
        config = {
            'forges': {
                'codeberg': {
                    'source_id': 'gitea',
                    'host': 'codeberg.example',
                    'role': 'mirror',
                    'url_template': 'https://codeberg.example/u/{repo}.git',
                },
            }
        }
        assert resolve_forge(
            'https://codeberg.example/team/proj.git', config
        ) == ('gitea', 'codeberg.example')
