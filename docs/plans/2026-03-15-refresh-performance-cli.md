# Refresh: PlatformProvider ABC, Parallel Execution, CLI Unification

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `PlatformProvider` ABC for hosting platform enrichment (GitHub, GitLab, etc.), refactor GitHub's special code path into this ABC, parallelize all provider HTTP calls, and unify the CLI so `--external` means everything.

**Architecture:** Two provider ABCs under one discovery mechanism: `PlatformProvider` enriches the repo entity (stars, topics → repos table), `RegistryProvider` detects publications (PyPI version → publications table). Both are discovered from `~/.repoindex/providers/`, both activated via `--provider` or `--external`. HTTP calls are parallelized with `ThreadPoolExecutor`. The existing `--github` flag becomes a convenience alias for `--provider github`.

**Tech Stack:** `concurrent.futures.ThreadPoolExecutor` (stdlib), existing `RegistryProvider` ABC, new `PlatformProvider` ABC

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `repoindex/providers/__init__.py` | Modify | Add `PlatformProvider` ABC, unified discovery returning both types |
| `repoindex/providers/github.py` | Create | `GitHubPlatformProvider` — refactors existing GitHub enrichment into ABC |
| `repoindex/commands/refresh.py` | Modify | Handle both provider types, parallelize, unify `--external` |
| `tests/test_providers/test_platform_provider.py` | Create | Tests for PlatformProvider ABC + GitHub implementation |
| `tests/test_refresh_parallel.py` | Create | Tests for parallel execution |

---

### Task 1: Add PlatformProvider ABC

**Files:**
- Modify: `repoindex/providers/__init__.py`

Add the new ABC alongside the existing `RegistryProvider`. Both share the same discovery mechanism.

- [ ] **Step 1: Write test for PlatformProvider interface**

Create `tests/test_providers/test_platform_provider.py`:

```python
"""Tests for PlatformProvider ABC and discovery."""
import pytest
from unittest.mock import MagicMock


class TestPlatformProviderABC:
    def test_cannot_instantiate_abstract(self):
        from repoindex.providers import PlatformProvider
        with pytest.raises(TypeError):
            PlatformProvider()

    def test_concrete_implementation(self):
        from repoindex.providers import PlatformProvider

        class FakePlatform(PlatformProvider):
            platform_id = "fake"
            name = "Fake Platform"
            prefix = "fake"

            def detect(self, repo_path, repo_record=None):
                return 'fake.com' in (repo_record or {}).get('remote_url', '')

            def enrich(self, repo_path, repo_record=None, config=None):
                return {'fake_stars': 10}

        p = FakePlatform()
        assert p.platform_id == "fake"
        assert p.detect("/repo", {'remote_url': 'https://fake.com/user/repo'})
        assert not p.detect("/repo", {'remote_url': 'https://github.com/user/repo'})
        result = p.enrich("/repo")
        assert result == {'fake_stars': 10}

    def test_platform_provider_in_exports(self):
        from repoindex.providers import PlatformProvider
        assert PlatformProvider is not None


class TestUnifiedDiscovery:
    def test_discover_returns_both_types(self):
        from repoindex.providers import discover_providers, discover_platforms
        # Registry providers should still work
        registry = discover_providers(only=['pypi'])
        assert len(registry) >= 1
        # Platform providers should be discoverable
        platforms = discover_platforms()
        # GitHub should be in there (after Task 2)
        # For now just verify function exists and returns a list
        assert isinstance(platforms, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_providers/test_platform_provider.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement PlatformProvider ABC**

Add to `repoindex/providers/__init__.py`:

```python
class PlatformProvider(ABC):
    """
    Abstract base class for hosting platform providers.

    Platform providers enrich repo-level metadata (stars, topics, forks, etc.)
    from hosting platforms like GitHub, GitLab, Codeberg.

    Unlike RegistryProvider (which creates publication entities in the publications
    table), PlatformProvider enriches the repo entity itself — its fields are
    merged into the repos table with a platform-specific prefix.

    Attributes:
        platform_id: Short identifier (e.g., "github", "gitlab")
        name: Human-readable name (e.g., "GitHub")
        prefix: Column prefix for repos table (e.g., "github" → github_stars)
    """
    platform_id: str = ""
    name: str = ""
    prefix: str = ""

    @abstractmethod
    def detect(self, repo_path: str, repo_record: Optional[dict] = None) -> bool:
        """
        Detect whether this repo is hosted on this platform.

        Args:
            repo_path: Filesystem path to the repository
            repo_record: Optional dict of repo metadata (has remote_url, owner, name)

        Returns:
            True if this repo has a remote on this platform
        """

    @abstractmethod
    def enrich(self, repo_path: str, repo_record: Optional[dict] = None,
               config: Optional[dict] = None) -> Optional[dict]:
        """
        Fetch platform metadata for this repo.

        Args:
            repo_path: Filesystem path to the repository
            repo_record: Optional dict of repo metadata
            config: Optional configuration dict (auth tokens, etc.)

        Returns:
            Dict of {prefix}_* fields to merge into repos table, or None
        """


BUILTIN_PLATFORMS = [
    'github',
]
```

Add `discover_platforms()` function (mirrors `discover_providers()`):

```python
def discover_platforms(
    user_dir: Optional[str] = None,
    only: Optional[List[str]] = None,
) -> List[PlatformProvider]:
    """Discover and load platform providers."""
    platforms: List[PlatformProvider] = []

    for module_name in BUILTIN_PLATFORMS:
        try:
            mod = importlib.import_module(f'.{module_name}', package='repoindex.providers')
            platform = getattr(mod, 'platform', None)
            if platform and isinstance(platform, PlatformProvider):
                if only is None or platform.platform_id in only:
                    platforms.append(platform)
        except ImportError:
            logger.debug(f"Built-in platform module not found: {module_name}")
        except Exception as e:
            logger.warning(f"Failed to load built-in platform '{module_name}': {e}")

    # Load user platforms from ~/.repoindex/providers/
    if user_dir is None:
        user_dir = os.path.expanduser('~/.repoindex/providers')

    if os.path.isdir(user_dir):
        for filename in sorted(os.listdir(user_dir)):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue
            filepath = os.path.join(user_dir, filename)
            mod_name = filename[:-3]
            try:
                spec = importlib.util.spec_from_file_location(
                    f'repoindex_user_provider_{mod_name}', filepath
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    platform = getattr(mod, 'platform', None)
                    if platform and isinstance(platform, PlatformProvider):
                        if only is None or platform.platform_id in only:
                            platforms.append(platform)
            except Exception as e:
                logger.warning(f"Failed to load user platform '{filepath}': {e}")

    return platforms
```

Update `__all__` to include `PlatformProvider` and `discover_platforms`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_providers/test_platform_provider.py::TestPlatformProviderABC -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
feat: add PlatformProvider ABC for hosting platform enrichment
```

---

### Task 2: Refactor GitHub into GitHubPlatformProvider

**Files:**
- Create: `repoindex/providers/github.py`
- Test: `tests/test_providers/test_platform_provider.py`

Move the existing GitHub enrichment logic from `repository_service.py` and `infra/github_client.py` into a proper `PlatformProvider` implementation.

The provider should:
1. `detect()`: Check if `remote_url` contains `github.com`
2. `enrich()`: Call GitHub API (using existing `GitHubClient`), return `github_*` prefixed fields

- [ ] **Step 1: Write tests**

Add to `tests/test_providers/test_platform_provider.py`:

```python
class TestGitHubPlatformProvider:
    def test_detect_github_remote(self):
        from repoindex.providers.github import platform
        assert platform.detect('/repo', {'remote_url': 'https://github.com/user/repo.git'})
        assert platform.detect('/repo', {'remote_url': 'git@github.com:user/repo.git'})

    def test_detect_non_github(self):
        from repoindex.providers.github import platform
        assert not platform.detect('/repo', {'remote_url': 'https://gitlab.com/user/repo.git'})
        assert not platform.detect('/repo', {'remote_url': ''})
        assert not platform.detect('/repo', {})
        assert not platform.detect('/repo', None)

    def test_detect_extracts_owner_name(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('https://github.com/queelius/repoindex.git')
        assert owner == 'queelius'
        assert name == 'repoindex'

    def test_detect_ssh_url(self):
        from repoindex.providers.github import _parse_github_remote
        owner, name = _parse_github_remote('git@github.com:queelius/repoindex.git')
        assert owner == 'queelius'
        assert name == 'repoindex'

    def test_enrich_returns_prefixed_fields(self):
        """Enrich should return github_* prefixed fields."""
        from repoindex.providers.github import platform
        from unittest.mock import patch, MagicMock

        mock_response = {
            'stargazers_count': 42,
            'forks_count': 3,
            'subscribers_count': 5,
            'open_issues_count': 2,
            'fork': False,
            'private': False,
            'archived': False,
            'description': 'A test repo',
            'topics': ['python', 'cli'],
            'created_at': '2024-01-01T00:00:00Z',
            'updated_at': '2026-03-14T00:00:00Z',
            'license': {'spdx_id': 'MIT'},
            'has_issues': True,
            'has_wiki': True,
            'has_pages': False,
        }

        with patch('repoindex.providers.github.GitHubClient') as MockClient:
            MockClient.return_value.get_repo.return_value = mock_response
            result = platform.enrich(
                '/repo',
                repo_record={'remote_url': 'https://github.com/user/repo.git'},
                config={'github': {'token': 'fake'}},
            )

        assert result['github_stars'] == 42
        assert result['github_forks'] == 3
        assert result['github_is_fork'] == 0
        assert result['github_is_private'] == 0
        assert result['github_topics'] == '["python", "cli"]'
        assert result['github_description'] == 'A test repo'

    def test_enrich_returns_none_for_non_github(self):
        from repoindex.providers.github import platform
        result = platform.enrich('/repo', {'remote_url': 'https://gitlab.com/user/repo'})
        assert result is None

    def test_platform_attributes(self):
        from repoindex.providers.github import platform
        assert platform.platform_id == 'github'
        assert platform.prefix == 'github'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_providers/test_platform_provider.py::TestGitHubPlatformProvider -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `repoindex/providers/github.py`**

```python
"""GitHub platform provider for repoindex.

Enriches repo-level metadata from the GitHub API: stars, forks, topics,
archive status, license, etc. Fields are prefixed with github_* and
merged into the repos table.
"""

import json
import re
from typing import Optional

from . import PlatformProvider
from ..infra.github_client import GitHubClient

_GITHUB_HTTPS_RE = re.compile(r'github\.com[:/]([^/]+)/([^/.]+)')


def _parse_github_remote(url: str):
    """Extract (owner, name) from a GitHub remote URL."""
    if not url:
        return None, None
    match = _GITHUB_HTTPS_RE.search(url)
    if match:
        return match.group(1), match.group(2)
    return None, None


class GitHubPlatformProvider(PlatformProvider):
    platform_id = "github"
    name = "GitHub"
    prefix = "github"

    def detect(self, repo_path, repo_record=None):
        url = (repo_record or {}).get('remote_url', '')
        owner, name = _parse_github_remote(url)
        return owner is not None and name is not None

    def enrich(self, repo_path, repo_record=None, config=None):
        url = (repo_record or {}).get('remote_url', '')
        owner, name = _parse_github_remote(url)
        if not owner or not name:
            return None

        config = config or {}
        token = config.get('github', {}).get('token')
        client = GitHubClient(token=token)
        data = client.get_repo(owner, name)
        if not data:
            return None

        result = {
            'github_stars': data.get('stargazers_count', 0),
            'github_forks': data.get('forks_count', 0),
            'github_watchers': data.get('subscribers_count', 0),
            'github_open_issues': data.get('open_issues_count', 0),
            'github_is_fork': int(bool(data.get('fork', False))),
            'github_is_private': int(bool(data.get('private', False))),
            'github_is_archived': int(bool(data.get('archived', False))),
            'github_description': data.get('description') or '',
            'github_created_at': data.get('created_at'),
            'github_updated_at': data.get('updated_at'),
        }

        # Topics as JSON array
        topics = data.get('topics')
        if topics and isinstance(topics, list):
            result['github_topics'] = json.dumps(topics)

        # License
        license_info = data.get('license')
        if license_info and isinstance(license_info, dict):
            spdx = license_info.get('spdx_id')
            if spdx and spdx != 'NOASSERTION':
                result['github_license'] = spdx

        # Boolean features
        for key in ('has_issues', 'has_wiki', 'has_pages'):
            val = data.get(key)
            if val is not None:
                result[f'github_{key}'] = int(bool(val))

        return result


platform = GitHubPlatformProvider()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_providers/test_platform_provider.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
feat: refactor GitHub into GitHubPlatformProvider

Moves GitHub enrichment from special code path in repository_service.py
to a proper PlatformProvider implementation. Same data, new interface.
Uses existing GitHubClient for API calls.
```

---

### Task 3: Wire PlatformProviders into refresh command

**Files:**
- Modify: `repoindex/commands/refresh.py`

The refresh command currently handles GitHub as a special `fetch_github` boolean. Change it to:
1. Discover platform providers alongside registry providers
2. Run platform providers during `_process_repo` (alongside registry providers)
3. Merge platform enrichment results into the repo record before upsert
4. `--provider github` activates the GitHub platform provider
5. `--external` activates ALL providers (both platform and registry)
6. Keep `--github` as a convenience alias for `--provider github`

- [ ] **Step 1: Update refresh_handler to discover platforms**

After discovering registry providers, also discover platforms:

```python
from ..providers import discover_providers, discover_platforms

# Discover platforms
active_platforms = []
if active_provider_names or fetch_github:
    platform_names = list(active_provider_names) if '__all__' not in active_provider_names else None
    if fetch_github and platform_names is not None and 'github' not in platform_names:
        platform_names.append('github')
    active_platforms = discover_platforms(
        only=None if '__all__' in active_provider_names else platform_names
    )
```

Pass `active_platforms` to `_process_repo`.

- [ ] **Step 2: Update `_process_repo` to run platform providers**

Before the registry provider block, add platform enrichment:

```python
# Run platform providers (enrich repo-level metadata)
if active_platforms:
    repo_dict = {'remote_url': enriched.remote_url, 'name': enriched.name, 'owner': enriched.owner}
    for plat in active_platforms:
        try:
            if plat.detect(repo.path, repo_dict):
                platform_data = plat.enrich(repo.path, repo_dict, config)
                if platform_data:
                    # Merge platform fields into repo record for DB upsert
                    _update_repo_platform_fields(db, repo_id, platform_data)
        except Exception as e:
            if not quiet:
                click.echo(f"  Warning: {plat.name} failed for {repo.name}: {e}", err=True)
```

The `_update_repo_platform_fields` function issues SQL UPDATEs for the platform-prefixed columns:

```python
def _update_repo_platform_fields(db, repo_id, fields):
    """Update repo with platform-specific fields."""
    if not fields:
        return
    set_clauses = ', '.join(f'{k} = ?' for k in fields.keys())
    params = list(fields.values()) + [repo_id]
    db.execute(f"UPDATE repos SET {set_clauses} WHERE id = ?", tuple(params))
```

- [ ] **Step 3: Remove old `fetch_github` code path**

Remove the `fetch_github` parameter from `service.get_status()` call. The GitHub enrichment is now handled by the platform provider, not by the repository service.

Keep the `--github` CLI flag but make it just add `'github'` to `provider_names`:

```python
# In refresh_handler, replace the special fetch_github resolution:
if github is True or (github is None and external):
    provider_names = list(provider_names) + ['github']
elif github is None and ext_config.get('github', False):
    provider_names = list(provider_names) + ['github']
```

Remove `fetch_github` from `_process_repo` signature.

- [ ] **Step 4: Update tests**

Update existing refresh tests that mock `fetch_github=True` to instead mock the platform discovery.

- [ ] **Step 5: Run full test suite**

Run: `pytest --maxfail=5 -q`

- [ ] **Step 6: Commit**

```
refactor: wire PlatformProvider into refresh, remove GitHub special code path

GitHub enrichment now goes through the PlatformProvider ABC like all
other external sources. --github flag adds 'github' to provider list.
--external activates everything (platforms + registries).
```

---

### Task 4: Parallelize provider HTTP calls

**Files:**
- Modify: `repoindex/commands/refresh.py`
- Create: `tests/test_refresh_parallel.py`

Both platform and registry providers make HTTP calls. Parallelize all of them for each repo.

- [ ] **Step 1: Write tests**

Create `tests/test_refresh_parallel.py`:

```python
"""Tests for parallel provider execution."""
import time
from unittest.mock import MagicMock

import pytest


class TestRunProvidersParallel:
    def test_concurrent_execution(self):
        """Multiple providers should run in parallel, not serial."""
        from repoindex.commands.refresh import _run_providers_parallel

        def slow_match(path, repo_record=None, config=None):
            time.sleep(0.1)
            return None

        providers = []
        for i in range(5):
            p = MagicMock()
            p.registry = f'mock_{i}'
            p.match = slow_match
            providers.append(p)

        start = time.time()
        _run_providers_parallel(providers, '/fake', {}, {})
        elapsed = time.time() - start
        # Serial ~0.5s, parallel ~0.1s
        assert elapsed < 0.3

    def test_error_isolation(self):
        """One failing provider shouldn't block others."""
        from repoindex.commands.refresh import _run_providers_parallel

        good = MagicMock()
        good.registry = 'good'
        good.match = MagicMock(return_value=MagicMock(registry='good'))

        bad = MagicMock()
        bad.registry = 'bad'
        bad.match = MagicMock(side_effect=ConnectionError("down"))

        results = _run_providers_parallel([bad, good], '/fake', {}, {})
        assert len(results) == 1

    def test_empty_providers(self):
        from repoindex.commands.refresh import _run_providers_parallel
        assert _run_providers_parallel([], '/fake', {}, {}) == []


class TestRunPlatformsParallel:
    def test_concurrent_platform_execution(self):
        """Platform providers should also run in parallel."""
        from repoindex.commands.refresh import _run_platforms_parallel

        def slow_enrich(path, repo_record=None, config=None):
            time.sleep(0.1)
            return {'fake_stars': 1}

        platforms = []
        for i in range(3):
            p = MagicMock()
            p.platform_id = f'plat_{i}'
            p.detect = MagicMock(return_value=True)
            p.enrich = slow_enrich
            platforms.append(p)

        start = time.time()
        results = _run_platforms_parallel(platforms, '/fake', {}, {})
        elapsed = time.time() - start
        assert elapsed < 0.25
        assert len(results) == 3
```

- [ ] **Step 2: Implement parallel helpers**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

_PROVIDER_WORKERS = 8


def _run_providers_parallel(providers, repo_path, repo_dict, config):
    """Run registry provider.match() calls in parallel."""
    if not providers:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=min(len(providers), _PROVIDER_WORKERS)) as pool:
        futures = {
            pool.submit(p.match, repo_path, repo_record=repo_dict, config=config): p
            for p in providers
        }
        for future in as_completed(futures):
            try:
                metadata = future.result()
                if metadata:
                    results.append(metadata)
            except Exception:
                pass
    return results


def _run_platforms_parallel(platforms, repo_path, repo_dict, config):
    """Run platform provider detect+enrich calls in parallel."""
    if not platforms:
        return []

    def _check(plat):
        if plat.detect(repo_path, repo_dict):
            return plat.enrich(repo_path, repo_dict, config)
        return None

    results = []
    with ThreadPoolExecutor(max_workers=min(len(platforms), _PROVIDER_WORKERS)) as pool:
        futures = {pool.submit(_check, p): p for p in platforms}
        for future in as_completed(futures):
            try:
                data = future.result()
                if data:
                    results.append(data)
            except Exception:
                pass
    return results
```

- [ ] **Step 3: Wire into `_process_repo`**

Replace both the platform and registry provider loops with parallel calls:

```python
# Platform providers (parallel)
if active_platforms:
    repo_dict = {'remote_url': enriched.remote_url, 'name': enriched.name, 'owner': enriched.owner}
    platform_results = _run_platforms_parallel(active_platforms, repo.path, repo_dict, config)
    for fields in platform_results:
        _update_repo_platform_fields(db, repo_id, fields)

# Registry providers (parallel)
if providers and repo_id:
    from ..database.repository import _upsert_publication
    repo_dict = {'remote_url': enriched.remote_url, 'name': enriched.name}
    matched = _run_providers_parallel(providers, repo.path, repo_dict, config)
    for metadata in matched:
        _upsert_publication(db, repo_id, metadata)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_refresh_parallel.py tests/test_providers/test_platform_provider.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --maxfail=5 -q`

- [ ] **Step 6: Commit**

```
perf: parallelize platform and registry provider HTTP calls

Both PlatformProvider.enrich() and RegistryProvider.match() now run
concurrently via ThreadPoolExecutor. Errors are isolated — one failing
provider doesn't block others.
```

---

### Task 5: Integration test and docs

- [ ] **Step 1: Smoke test**

```bash
# Verify --external now includes GitHub
repoindex refresh --external -d ~/github/beta/repoindex 2>&1 | head -5
# Should show GitHub enrichment happening

# Verify --provider github works
repoindex refresh --provider github -d ~/github/beta/repoindex 2>&1 | head -5

# Verify other providers still work
repoindex refresh --provider pypi -d ~/github/beta/repoindex 2>&1 | head -5
```

- [ ] **Step 2: Update CLAUDE.md**

Add PlatformProvider to the extension systems section:

```markdown
**Providers** (`providers/`): Two ABCs for external metadata:
- `PlatformProvider` — hosting platform enrichment (GitHub, GitLab). Enriches repos table with platform-prefixed fields (`github_stars`, `gitlab_issues`).
- `RegistryProvider` — package registry detection (PyPI, CRAN, npm). Creates publication records in publications table.
Both share discovery: built-in + `~/.repoindex/providers/*.py` (export `provider` or `platform` attribute).
```

- [ ] **Step 3: Update docs/index.md refresh section**

```bash
repoindex refresh --external    # All external: GitHub + all registries
repoindex refresh --provider github --provider pypi   # Specific
```

- [ ] **Step 4: Commit**

```
docs: PlatformProvider ABC, parallel refresh, unified --external
```
