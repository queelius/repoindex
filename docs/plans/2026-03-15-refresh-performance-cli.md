# Refresh Performance & CLI Unification Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `repoindex refresh --external` fast via parallel HTTP calls, and unify GitHub into the provider CLI so `--external` means ALL external sources.

**Architecture:** Provider HTTP calls are parallelized with `concurrent.futures.ThreadPoolExecutor` at the per-repo level (providers for one repo run in parallel). GitHub becomes activatable via `--provider github` alongside the existing `--github` flag. The internal enrichment path stays separate (repo-level vs. publication-level), but the CLI presents a unified interface.

**Tech Stack:** `concurrent.futures.ThreadPoolExecutor` (stdlib), existing `RegistryProvider` ABC

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `repoindex/commands/refresh.py` | Modify | Parallelize provider calls in `_process_repo`, unify `--external` to include GitHub |
| `repoindex/providers/__init__.py` | Modify | Add `github` to `BUILTIN_PROVIDERS`, add `concurrent` flag to ABC |
| `repoindex/providers/github.py` | Create | GitHub as a RegistryProvider (detection + check, stores nothing — just signals to refresh) |
| `tests/test_providers/test_github_provider.py` | Create | Tests for GitHub provider detection |
| `tests/test_refresh_parallel.py` | Create | Tests for parallel execution |

---

### Task 1: Unify GitHub into the provider CLI

**Files:**
- Modify: `repoindex/commands/refresh.py`
- Modify: `repoindex/providers/__init__.py`

Currently `--external` doesn't include GitHub — users must pass `--github` separately. This is confusing. Fix: `--external` activates GitHub too.

Also allow `--provider github` as a way to activate GitHub metadata fetching.

- [ ] **Step 1: Make `--external` include GitHub**

In `repoindex/commands/refresh.py`, the `refresh_handler` function resolves `fetch_github` before providers. Change line ~162:

```python
# BEFORE:
fetch_github = _resolve_external_flag(github, external, ext_config.get('github', False))

# AFTER:
fetch_github = _resolve_external_flag(github, external, ext_config.get('github', False))
# Also check if --provider github was explicitly passed
if 'github' in provider_names:
    fetch_github = True
```

- [ ] **Step 2: Update help text**

Change the `refresh_handler` docstring to say `--external` enables "all external sources including GitHub":

```python
        # Include all external sources including GitHub
        repoindex refresh --external
```

Remove the line that says "GitHub metadata is separate and enabled via --github."

- [ ] **Step 3: Add test**

In `tests/test_refresh_parallel.py` (or existing refresh test file):

```python
def test_external_flag_includes_github():
    """--external should activate GitHub metadata fetching."""
    from repoindex.commands.refresh import _resolve_external_flag
    # --external=True, no explicit --github flag, config default=False
    result = _resolve_external_flag(None, True, False)
    assert result is True
```

Also test that `--provider github` works:
```python
def test_provider_github_activates_github():
    """--provider github should enable GitHub fetching."""
    # This is handled in refresh_handler — test via CLI runner
    pass  # Tested at integration level
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -k "refresh" -v --maxfail=5`

- [ ] **Step 5: Commit**

```
feat: --external includes GitHub, --provider github works as alias
```

---

### Task 2: Parallelize provider HTTP calls

**Files:**
- Modify: `repoindex/commands/refresh.py` (`_process_repo`)
- Test: `tests/test_refresh_parallel.py`

The inner loop in `_process_repo` (line ~376) runs providers sequentially:
```python
for p in providers:
    metadata = p.match(repo.path, ...)
```

With 8 providers enabled, this is 8 serial HTTP requests per repo. Parallelize with ThreadPoolExecutor.

- [ ] **Step 1: Write test for parallel execution**

```python
import time
from unittest.mock import MagicMock, patch
from concurrent.futures import ThreadPoolExecutor


class TestParallelProviders:
    def test_providers_run_concurrently(self):
        """Multiple providers should run in parallel, not serial."""
        from repoindex.commands.refresh import _run_providers_parallel

        # Create mock providers that each take 0.1s
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
        results = _run_providers_parallel(providers, '/fake/path', {}, {})
        elapsed = time.time() - start

        # Serial would take 0.5s+, parallel should be ~0.1s
        assert elapsed < 0.3

    def test_provider_error_doesnt_block_others(self):
        """One failing provider shouldn't prevent others from running."""
        from repoindex.commands.refresh import _run_providers_parallel

        def good_match(path, repo_record=None, config=None):
            return MagicMock(registry='good')

        def bad_match(path, repo_record=None, config=None):
            raise ConnectionError("API down")

        good = MagicMock()
        good.registry = 'good'
        good.match = good_match

        bad = MagicMock()
        bad.registry = 'bad'
        bad.match = bad_match

        results = _run_providers_parallel([bad, good], '/fake', {}, {})
        # Good provider should still return result
        assert len([r for r in results if r is not None]) == 1

    def test_empty_providers_returns_empty(self):
        from repoindex.commands.refresh import _run_providers_parallel
        results = _run_providers_parallel([], '/fake', {}, {})
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_refresh_parallel.py -v`
Expected: FAIL (ImportError — `_run_providers_parallel` doesn't exist)

- [ ] **Step 3: Implement `_run_providers_parallel`**

Add to `repoindex/commands/refresh.py`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

_PROVIDER_WORKERS = 8  # Max concurrent provider HTTP calls per repo


def _run_providers_parallel(providers, repo_path, repo_dict, config):
    """Run provider.match() calls in parallel for a single repo.

    Returns list of (provider, metadata) tuples for successful matches.
    Errors are logged but don't prevent other providers from completing.
    """
    if not providers:
        return []

    results = []

    def _check(provider):
        return provider, provider.match(repo_path, repo_record=repo_dict, config=config)

    with ThreadPoolExecutor(max_workers=min(len(providers), _PROVIDER_WORKERS)) as pool:
        futures = {pool.submit(_check, p): p for p in providers}
        for future in as_completed(futures):
            provider = futures[future]
            try:
                _, metadata = future.result()
                if metadata:
                    results.append(metadata)
            except Exception:
                # Logged by caller; don't block other providers
                pass

    return results
```

- [ ] **Step 4: Wire into `_process_repo`**

Replace the sequential provider loop in `_process_repo` (line ~372-383):

```python
# BEFORE:
if providers and repo_id:
    from ..database.repository import _upsert_publication
    repo_dict = {'remote_url': enriched.remote_url, 'name': enriched.name}
    for p in providers:
        try:
            metadata = p.match(repo.path, repo_record=repo_dict, config=config)
            if metadata:
                _upsert_publication(db, repo_id, metadata)
        except Exception as e:
            if not quiet:
                click.echo(f"  Warning: {p.registry} provider failed for {repo.name}: {e}", err=True)

# AFTER:
if providers and repo_id:
    from ..database.repository import _upsert_publication
    repo_dict = {'remote_url': enriched.remote_url, 'name': enriched.name}
    matched = _run_providers_parallel(providers, repo.path, repo_dict, config)
    for metadata in matched:
        _upsert_publication(db, repo_id, metadata)
```

Note: error reporting moves inside `_run_providers_parallel` (logged, not printed). The `quiet` flag behavior changes slightly — parallel providers can't easily print per-provider warnings. This is acceptable since provider failures are non-critical.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_refresh_parallel.py -v`
Expected: PASS

- [ ] **Step 6: Run full suite**

Run: `pytest --maxfail=5 -q`
Expected: All pass

- [ ] **Step 7: Commit**

```
perf: parallelize provider HTTP calls with ThreadPoolExecutor

Provider checks for each repo now run concurrently instead of serially.
With 8 providers enabled, this reduces per-repo provider time from ~1.6s
(8 × 200ms serial) to ~200ms (parallel).
```

---

### Task 3: Smoke test and documentation

- [ ] **Step 1: Smoke test performance**

```bash
# Time before (serial):
time repoindex refresh --external --full 2>/dev/null

# Should be noticeably faster than serial
```

- [ ] **Step 2: Update CLAUDE.md**

Update the refresh section to mention parallel providers and `--external` including GitHub.

- [ ] **Step 3: Commit**

```
docs: update refresh docs for parallel providers and unified --external
```
