"""Tests for the RegistryProvider interface and discovery system."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from repoindex.providers import (
    RegistryProvider,
    PackageMetadata,
    discover_providers,
    BUILTIN_PROVIDERS,
)


class DummyProvider(RegistryProvider):
    """Concrete provider for testing."""
    registry = "dummy"
    name = "Dummy Provider"
    batch = False

    def detect(self, repo_path, repo_record=None):
        return "dummy-package"

    def check(self, package_name, config=None):
        return PackageMetadata(
            registry="dummy",
            name=package_name,
            version="1.0.0",
            published=True,
            url="https://example.com/dummy-package",
        )


class BatchDummyProvider(RegistryProvider):
    """Batch provider for testing."""
    registry = "batch-dummy"
    name = "Batch Dummy"
    batch = True

    def __init__(self):
        self.prefetched = False
        self.match_result = None

    def detect(self, repo_path, repo_record=None):
        return None

    def check(self, package_name, config=None):
        return None

    def prefetch(self, config):
        self.prefetched = True

    def match(self, repo_path, repo_record=None, config=None):
        return self.match_result


# === Interface tests ===

class TestRegistryProviderInterface:
    """Test the ABC interface contract."""

    def test_concrete_provider_instantiation(self):
        p = DummyProvider()
        assert p.registry == "dummy"
        assert p.name == "Dummy Provider"
        assert p.batch is False

    def test_detect_returns_name(self):
        p = DummyProvider()
        assert p.detect("/some/path") == "dummy-package"

    def test_check_returns_metadata(self):
        p = DummyProvider()
        result = p.check("dummy-package")
        assert isinstance(result, PackageMetadata)
        assert result.registry == "dummy"
        assert result.name == "dummy-package"
        assert result.version == "1.0.0"
        assert result.published is True

    def test_match_default_detect_then_check(self):
        p = DummyProvider()
        result = p.match("/some/path")
        assert result is not None
        assert result.name == "dummy-package"
        assert result.published is True

    def test_match_returns_none_when_detect_fails(self):
        p = DummyProvider()
        p.detect = MagicMock(return_value=None)
        result = p.match("/some/path")
        assert result is None

    def test_batch_provider_attributes(self):
        p = BatchDummyProvider()
        assert p.batch is True
        assert p.registry == "batch-dummy"

    def test_batch_provider_prefetch(self):
        p = BatchDummyProvider()
        p.prefetch({"key": "value"})
        assert p.prefetched is True

    def test_batch_provider_match_override(self):
        p = BatchDummyProvider()
        p.match_result = PackageMetadata(
            registry="batch-dummy", name="test", published=True
        )
        result = p.match("/some/path")
        assert result is not None
        assert result.registry == "batch-dummy"

    def test_prefetch_default_is_noop(self):
        p = DummyProvider()
        # Should not raise
        p.prefetch({"some": "config"})

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            RegistryProvider()


# === Discovery tests ===

class TestDiscoverProviders:
    """Test the provider discovery mechanism."""

    def test_discovers_all_builtin_providers(self):
        providers = discover_providers()
        registries = {p.registry for p in providers}
        assert 'pypi' in registries
        assert 'cran' in registries
        assert 'zenodo' in registries
        assert 'npm' in registries
        assert 'cargo' in registries
        assert 'conda' in registries
        assert 'docker' in registries
        assert 'rubygems' in registries
        assert 'go' in registries

    def test_discover_with_only_filter(self):
        providers = discover_providers(only=['pypi', 'npm'])
        registries = {p.registry for p in providers}
        assert registries == {'pypi', 'npm'}

    def test_discover_with_empty_only_returns_none(self):
        providers = discover_providers(only=[])
        assert len(providers) == 0

    def test_discover_with_nonexistent_only(self):
        providers = discover_providers(only=['nonexistent'])
        assert len(providers) == 0

    def test_all_builtin_module_names_listed(self):
        """Ensure BUILTIN_PROVIDERS covers all expected registries."""
        assert 'pypi' in BUILTIN_PROVIDERS
        assert 'cran' in BUILTIN_PROVIDERS
        assert 'zenodo' in BUILTIN_PROVIDERS
        assert 'npm' in BUILTIN_PROVIDERS
        assert 'cargo' in BUILTIN_PROVIDERS
        assert 'conda' in BUILTIN_PROVIDERS
        assert 'docker' in BUILTIN_PROVIDERS
        assert 'rubygems' in BUILTIN_PROVIDERS
        assert 'go' in BUILTIN_PROVIDERS

    def test_all_providers_are_registry_provider_instances(self):
        providers = discover_providers()
        for p in providers:
            assert isinstance(p, RegistryProvider)

    def test_user_provider_directory_not_exists(self):
        """Non-existent user dir should not cause errors."""
        providers = discover_providers(user_dir='/nonexistent/path')
        # Should still have builtins
        assert len(providers) > 0

    def test_user_provider_loading(self, tmp_path):
        """Test loading a custom provider from a user directory."""
        user_provider = tmp_path / "custom.py"
        user_provider.write_text('''
from repoindex.providers import RegistryProvider, PackageMetadata

class CustomProvider(RegistryProvider):
    registry = "custom"
    name = "Custom Test"
    batch = False

    def detect(self, repo_path, repo_record=None):
        return None

    def check(self, package_name, config=None):
        return None

provider = CustomProvider()
''')
        providers = discover_providers(user_dir=str(tmp_path))
        registries = {p.registry for p in providers}
        assert 'custom' in registries

    def test_user_provider_with_only_filter(self, tmp_path):
        """User providers are also subject to the 'only' filter."""
        user_provider = tmp_path / "custom.py"
        user_provider.write_text('''
from repoindex.providers import RegistryProvider, PackageMetadata

class CustomProvider(RegistryProvider):
    registry = "custom"
    name = "Custom Test"
    batch = False

    def detect(self, repo_path, repo_record=None):
        return None

    def check(self, package_name, config=None):
        return None

provider = CustomProvider()
''')
        # Only load 'custom' — should find it
        providers = discover_providers(user_dir=str(tmp_path), only=['custom'])
        assert len(providers) >= 1
        assert any(p.registry == 'custom' for p in providers)

        # Only load 'pypi' — should not load custom
        providers = discover_providers(user_dir=str(tmp_path), only=['pypi'])
        assert not any(p.registry == 'custom' for p in providers)

    def test_broken_user_provider_is_skipped(self, tmp_path):
        """A broken user provider file should be skipped with a warning."""
        broken = tmp_path / "broken.py"
        broken.write_text("raise RuntimeError('broken')")

        providers = discover_providers(user_dir=str(tmp_path))
        # Should still have builtins, broken file skipped
        assert len(providers) > 0
