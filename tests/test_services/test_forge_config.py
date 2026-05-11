"""Tests for repoindex.services.forge_config."""

import pytest

from repoindex.services.forge_config import (
    ForgeConfig,
    ForgeConfigError,
    find_forge_for_host,
    get_mirrors,
    get_primaries,
    load_forges,
)


class TestForgeConfigUrlFor:
    def test_basic_substitution(self):
        f = ForgeConfig(
            name='codeberg',
            source_id='gitea',
            url_template='https://codeberg.org/queelius/{repo}.git',
        )
        assert f.url_for('dreamlog') == 'https://codeberg.org/queelius/dreamlog.git'

    def test_file_url(self):
        f = ForgeConfig(
            name='local',
            source_id='gitea',
            url_template='file:///tmp/git/{repo}.git',
        )
        assert f.url_for('mcts') == 'file:///tmp/git/mcts.git'

    def test_without_template_raises(self):
        f = ForgeConfig(name='codeberg', source_id='gitea')
        with pytest.raises(ForgeConfigError):
            f.url_for('any')


class TestLoadForges:
    def test_missing_section_returns_empty(self):
        assert load_forges({}) == []

    def test_empty_dict_returns_empty(self):
        assert load_forges({'forges': {}}) == []

    def test_none_value_returns_empty(self):
        assert load_forges({'forges': None}) == []

    def test_single_primary(self):
        cfg = {'forges': {'github': {'token_env': 'GITHUB_TOKEN'}}}
        out = load_forges(cfg)
        assert len(out) == 1
        assert out[0].name == 'github'
        assert out[0].source_id == 'github'  # defaults to entry key
        assert out[0].role == 'primary'      # default
        assert out[0].token_env == 'GITHUB_TOKEN'

    def test_mirror_with_source_id(self):
        cfg = {
            'forges': {
                'codeberg': {
                    'source_id': 'gitea',
                    'host': 'codeberg.org',
                    'role': 'mirror',
                    'token_env': 'CODEBERG_TOKEN',
                    'url_template': 'https://codeberg.org/u/{repo}.git',
                },
            }
        }
        out = load_forges(cfg)
        assert len(out) == 1
        e = out[0]
        assert e.name == 'codeberg'
        assert e.source_id == 'gitea'
        assert e.host == 'codeberg.org'
        assert e.role == 'mirror'
        assert e.token_env == 'CODEBERG_TOKEN'
        assert e.url_template.endswith('/{repo}.git')

    def test_multiple_entries(self):
        cfg = {
            'forges': {
                'github': {'role': 'primary'},
                'codeberg': {'source_id': 'gitea', 'role': 'mirror',
                             'host': 'codeberg.org',
                             'url_template': 'https://codeberg.org/u/{repo}.git'},
                'nas': {'source_id': 'gitea', 'role': 'mirror',
                        'host': 'nas.local',
                        'url_template': 'ssh://nas.local/srv/{repo}.git'},
            }
        }
        out = load_forges(cfg)
        names = [e.name for e in out]
        assert set(names) == {'github', 'codeberg', 'nas'}

    def test_forges_not_a_mapping(self):
        with pytest.raises(ForgeConfigError):
            load_forges({'forges': ['not', 'a', 'dict']})

    def test_entry_not_a_dict(self):
        with pytest.raises(ForgeConfigError):
            load_forges({'forges': {'codeberg': 'just-a-string'}})

    def test_invalid_name_dash_prefix(self):
        with pytest.raises(ForgeConfigError):
            load_forges({'forges': {'-bad': {}}})

    def test_invalid_name_space(self):
        with pytest.raises(ForgeConfigError):
            load_forges({'forges': {'bad name': {}}})

    def test_invalid_name_slash(self):
        with pytest.raises(ForgeConfigError):
            load_forges({'forges': {'a/b': {}}})

    def test_unknown_role_rejected(self):
        with pytest.raises(ForgeConfigError):
            load_forges({'forges': {'codeberg': {'role': 'whatever'}}})

    def test_template_without_repo_placeholder(self):
        cfg = {'forges': {'codeberg': {'url_template': 'https://no-placeholder/x.git'}}}
        with pytest.raises(ForgeConfigError):
            load_forges(cfg)

    def test_template_with_extra_placeholder(self):
        cfg = {'forges': {'codeberg': {'url_template': 'https://x/{user}/{repo}.git'}}}
        with pytest.raises(ForgeConfigError):
            load_forges(cfg)

    def test_empty_template_rejected(self):
        cfg = {'forges': {'codeberg': {'url_template': ''}}}
        with pytest.raises(ForgeConfigError):
            load_forges(cfg)

    def test_empty_source_id_rejected(self):
        with pytest.raises(ForgeConfigError):
            load_forges({'forges': {'codeberg': {'source_id': ''}}})


class TestRoleFiltering:
    def test_get_mirrors_only(self):
        cfg = {
            'forges': {
                'github': {'role': 'primary'},
                'codeberg': {'source_id': 'gitea', 'role': 'mirror',
                             'host': 'codeberg.org',
                             'url_template': 'https://codeberg.org/u/{repo}.git'},
                'nas': {'source_id': 'gitea', 'role': 'mirror',
                        'host': 'nas.local',
                        'url_template': 'ssh://nas.local/{repo}.git'},
            }
        }
        names = [m.name for m in get_mirrors(cfg)]
        assert set(names) == {'codeberg', 'nas'}

    def test_get_primaries_only(self):
        cfg = {
            'forges': {
                'github': {'role': 'primary'},
                'codeberg': {'role': 'mirror', 'source_id': 'gitea',
                             'host': 'codeberg.org',
                             'url_template': 'https://x/{repo}.git'},
            }
        }
        names = [p.name for p in get_primaries(cfg)]
        assert names == ['github']

    def test_default_role_is_primary(self):
        cfg = {'forges': {'github': {}}}
        primaries = get_primaries(cfg)
        mirrors = get_mirrors(cfg)
        assert len(primaries) == 1
        assert mirrors == []


class TestFindForgeForHost:
    def test_finds_by_host(self):
        cfg = {
            'forges': {
                'codeberg': {'source_id': 'gitea', 'host': 'codeberg.org',
                             'role': 'mirror',
                             'url_template': 'https://codeberg.org/u/{repo}.git'},
            }
        }
        e = find_forge_for_host('codeberg.org', cfg)
        assert e is not None
        assert e.name == 'codeberg'

    def test_returns_none_for_unknown(self):
        assert find_forge_for_host('unknown.example.com', {'forges': {}}) is None

    def test_empty_host_returns_none(self):
        assert find_forge_for_host('', {'forges': {}}) is None
