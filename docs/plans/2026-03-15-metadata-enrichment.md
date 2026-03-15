# Metadata Enrichment Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract richer metadata from local project files (pyproject.toml, DESCRIPTION, package.json, Cargo.toml) and improve existing provider quality (CRAN API instead of scraping, GitHub releases).

**Architecture:** Local metadata extraction happens during the existing refresh scan step — no HTTP calls needed. Provider improvements are independent changes to individual provider files. Each task is self-contained and can be implemented/tested independently.

**Tech Stack:** Python stdlib (`tomllib`/`tomli`, `json`, `re`), existing provider ABC

**Depends on:** Plan 1 (refresh-performance-cli) should be done first for the parallel infrastructure, but this plan works independently.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `repoindex/services/repository_service.py` | Modify | Extract keywords/classifiers from pyproject.toml, package.json, etc. |
| `repoindex/database/schema.py` | Modify | Add `keywords` column to repos table (JSON array) |
| `repoindex/providers/cran.py` | Modify | Switch from web scraping to CRAN API |
| `repoindex/providers/pypi.py` | Modify | Extract download counts from PyPI stats API |
| `tests/test_metadata_enrichment.py` | Create | Tests for local file parsing |
| `tests/test_providers/test_cran_provider.py` | Modify | Update for new API |

---

### Task 1: Extract keywords from pyproject.toml during scan

**Files:**
- Modify: `repoindex/services/repository_service.py`
- Modify: `repoindex/database/schema.py`
- Test: `tests/test_metadata_enrichment.py`

During refresh, repoindex already reads pyproject.toml for package detection. It should also extract `[project].keywords` and store them. These keywords can auto-populate tags and improve searchability.

The repos table needs a `keywords` column (JSON array, nullable) for storing extracted keywords from project metadata files.

- [ ] **Step 1: Add `keywords` column to schema**

In `repoindex/database/schema.py`, add to the migration:

```python
# In the migration function for the next schema version:
db.execute("ALTER TABLE repos ADD COLUMN keywords TEXT")  # JSON array
```

- [ ] **Step 2: Write test for keyword extraction**

```python
import json
import pytest
from pathlib import Path


class TestKeywordExtraction:
    def test_pyproject_keywords(self, tmp_path):
        """Extract keywords from pyproject.toml [project].keywords."""
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text('''
[project]
name = "mypackage"
keywords = ["cli", "git", "metadata"]
''')
        keywords = _extract_keywords(tmp_path)
        assert keywords == ["cli", "git", "metadata"]

    def test_package_json_keywords(self, tmp_path):
        """Extract keywords from package.json."""
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "mypackage",
            "keywords": ["nodejs", "api"]
        }))
        keywords = _extract_keywords(tmp_path)
        assert keywords == ["nodejs", "api"]

    def test_cargo_toml_keywords(self, tmp_path):
        """Extract keywords from Cargo.toml."""
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "Cargo.toml").write_text('''
[package]
name = "mypackage"
keywords = ["cli", "rust"]
''')
        keywords = _extract_keywords(tmp_path)
        assert keywords == ["cli", "rust"]

    def test_description_keywords(self, tmp_path):
        """Extract keywords from R DESCRIPTION file."""
        from repoindex.services.repository_service import _extract_keywords
        # R doesn't have keywords, but has Title and Description
        (tmp_path / "DESCRIPTION").write_text(
            'Package: mypkg\nTitle: My Package\nDescription: A tool for analysis\n'
        )
        keywords = _extract_keywords(tmp_path)
        assert keywords is None  # R DESCRIPTION doesn't have keywords field

    def test_no_project_files(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        keywords = _extract_keywords(tmp_path)
        assert keywords is None

    def test_pyproject_no_keywords(self, tmp_path):
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "mypackage"\n')
        keywords = _extract_keywords(tmp_path)
        assert keywords is None

    def test_priority_pyproject_over_package_json(self, tmp_path):
        """When both exist, pyproject.toml wins."""
        from repoindex.services.repository_service import _extract_keywords
        (tmp_path / "pyproject.toml").write_text('''
[project]
name = "mypackage"
keywords = ["python"]
''')
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "mypackage", "keywords": ["node"]
        }))
        keywords = _extract_keywords(tmp_path)
        assert keywords == ["python"]
```

- [ ] **Step 3: Implement `_extract_keywords`**

Add to `repoindex/services/repository_service.py`:

```python
def _extract_keywords(repo_path) -> Optional[list]:
    """Extract keywords/tags from project metadata files.

    Priority: pyproject.toml > Cargo.toml > package.json
    Returns list of strings, or None if no keywords found.
    """
    repo_path = Path(repo_path)

    # pyproject.toml (Python)
    pyproject = repo_path / 'pyproject.toml'
    if pyproject.exists():
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        try:
            with open(pyproject, 'rb') as f:
                data = tomllib.load(f)
            keywords = data.get('project', {}).get('keywords')
            if keywords and isinstance(keywords, list):
                return keywords
        except Exception:
            pass

    # Cargo.toml (Rust)
    cargo = repo_path / 'Cargo.toml'
    if cargo.exists():
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        try:
            with open(cargo, 'rb') as f:
                data = tomllib.load(f)
            keywords = data.get('package', {}).get('keywords')
            if keywords and isinstance(keywords, list):
                return keywords
        except Exception:
            pass

    # package.json (Node.js)
    pkg_json = repo_path / 'package.json'
    if pkg_json.exists():
        try:
            import json
            with open(pkg_json) as f:
                data = json.load(f)
            keywords = data.get('keywords')
            if keywords and isinstance(keywords, list):
                return keywords
        except Exception:
            pass

    return None
```

- [ ] **Step 4: Wire into refresh scan**

In the `get_status` or scan method, call `_extract_keywords` and store the result:

```python
keywords = _extract_keywords(repo.path)
if keywords:
    # Store as JSON array in repos.keywords column
    repo_dict['keywords'] = json.dumps(keywords)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_metadata_enrichment.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```
feat: extract keywords from pyproject.toml, Cargo.toml, package.json during refresh
```

---

### Task 2: Improve CRAN provider — use API instead of web scraping

**Files:**
- Modify: `repoindex/providers/cran.py`
- Modify: `tests/test_providers/test_cran_provider.py`

The current CRAN provider scrapes HTML web pages — fragile and slow. CRAN has a simple metadata API:
- `https://cran.r-project.org/web/packages/{name}/DESCRIPTION` — returns raw DCF
- Or: `https://crandb.r-pkg.org/{name}` — returns JSON (community API, reliable)

Switch to the JSON API for robust metadata extraction.

- [ ] **Step 1: Update CRAN check method**

```python
def check(self, package_name, config=None):
    """Check CRAN for package using crandb JSON API."""
    import requests

    # Try CRAN via crandb (JSON API)
    try:
        url = f'https://crandb.r-pkg.org/{package_name}'
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return PackageMetadata(
                registry='cran',
                package_name=package_name,
                version=data.get('Version'),
                published=True,
                url=f'https://cran.r-project.org/package={package_name}',
            )
    except Exception:
        pass

    # Fallback: try Bioconductor
    try:
        url = f'https://bioconductor.org/packages/json/{package_name}'
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return PackageMetadata(
                registry='bioconductor',
                package_name=package_name,
                published=True,
                url=f'https://bioconductor.org/packages/{package_name}',
            )
    except Exception:
        pass

    return None
```

- [ ] **Step 2: Update tests with mock JSON responses**

- [ ] **Step 3: Run tests**

- [ ] **Step 4: Commit**

```
fix(cran): switch from web scraping to crandb JSON API
```

---

### Task 3: Extract richer metadata from R DESCRIPTION files

**Files:**
- Modify: `repoindex/providers/cran.py` (detection)
- Test: `tests/test_metadata_enrichment.py`

The CRAN provider reads DESCRIPTION for package name but ignores Title, Description, Author, URL, BugReports, Maintainer. These should be extracted and stored.

- [ ] **Step 1: Write test**

```python
class TestDescriptionParsing:
    def test_extracts_title(self, tmp_path):
        from repoindex.providers.cran import _parse_description
        (tmp_path / "DESCRIPTION").write_text(
            'Package: mypkg\nTitle: My Amazing Package\nVersion: 1.0.0\n'
            'Author: Alex Towell\nMaintainer: Alex <alex@example.com>\n'
            'URL: https://github.com/user/mypkg\nBugReports: https://github.com/user/mypkg/issues\n'
        )
        info = _parse_description(tmp_path / "DESCRIPTION")
        assert info['title'] == 'My Amazing Package'
        assert info['author'] == 'Alex Towell'
        assert info['url'] == 'https://github.com/user/mypkg'
```

- [ ] **Step 2: Implement `_parse_description`**

Returns a dict of all extracted fields (package, title, version, author, maintainer, url, bugreports, description, license).

- [ ] **Step 3: Store richer data**

The `detect` method can return the full parsed info, and `match` can include it in the PackageMetadata or repo enrichment.

- [ ] **Step 4: Commit**

```
feat(cran): extract Title, Author, URL from R DESCRIPTION files
```

---

### Task 4: Add download counts for PyPI

**Files:**
- Modify: `repoindex/providers/pypi.py`
- Test: `tests/test_providers/test_pypi_provider.py`

The PyPI JSON API at `https://pypi.org/pypi/{name}/json` already includes `info.version` but not download counts. PyPI Stats API provides downloads:
- `https://pypistats.org/api/packages/{name}/recent` — returns last day/week/month

This is a secondary API call — only make it if the package exists.

- [ ] **Step 1: Add download count fetching**

After confirming a package exists, optionally query pypistats:

```python
def _fetch_downloads(self, package_name):
    """Fetch recent download stats from PyPI Stats API."""
    try:
        resp = requests.get(
            f'https://pypistats.org/api/packages/{package_name}/recent',
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get('data', {}).get('last_month')
    except Exception:
        pass
    return None
```

- [ ] **Step 2: Include in PackageMetadata**

```python
downloads = self._fetch_downloads(package_name)
return PackageMetadata(
    ...
    downloads_total=downloads,
)
```

- [ ] **Step 3: Tests with mocked responses**

- [ ] **Step 4: Commit**

```
feat(pypi): fetch monthly download counts from pypistats API
```

---

### Task 5: Detect more local asset files

**Files:**
- Modify: `repoindex/services/repository_service.py`
- Test: `tests/test_metadata_enrichment.py`

Currently repoindex detects: README, LICENSE, CITATION.cff, CI configs. Add detection for:
- `codemeta.json` → has_codemeta flag
- `.github/FUNDING.yml` → has_funding flag
- `CONTRIBUTORS` / `AUTHORS` → has_contributors flag
- `CHANGELOG.md` / `CHANGES.md` / `NEWS.md` → has_changelog flag

These are simple file-existence checks added to the existing scan step.

- [ ] **Step 1: Add columns to schema**

```sql
ALTER TABLE repos ADD COLUMN has_codemeta BOOLEAN DEFAULT 0;
ALTER TABLE repos ADD COLUMN has_funding BOOLEAN DEFAULT 0;
ALTER TABLE repos ADD COLUMN has_contributors BOOLEAN DEFAULT 0;
ALTER TABLE repos ADD COLUMN has_changelog BOOLEAN DEFAULT 0;
```

- [ ] **Step 2: Write tests**

```python
class TestLocalAssetDetection:
    def test_codemeta_detected(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / "codemeta.json").write_text("{}")
        from repoindex.services.repository_service import _detect_local_assets
        assets = _detect_local_assets(tmp_path)
        assert assets['has_codemeta'] is True

    def test_funding_detected(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "FUNDING.yml").write_text("github: user")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_funding'] is True

    def test_changelog_detected(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / "CHANGELOG.md").write_text("# Changes")
        assets = _detect_local_assets(tmp_path)
        assert assets['has_changelog'] is True

    def test_no_assets(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assets = _detect_local_assets(tmp_path)
        assert all(not v for v in assets.values())
```

- [ ] **Step 3: Implement `_detect_local_assets`**

```python
def _detect_local_assets(repo_path) -> dict:
    """Detect presence of common project asset files."""
    p = Path(repo_path)
    return {
        'has_codemeta': (p / 'codemeta.json').exists(),
        'has_funding': (p / '.github' / 'FUNDING.yml').exists(),
        'has_contributors': any(
            (p / name).exists()
            for name in ('CONTRIBUTORS', 'CONTRIBUTORS.md', 'AUTHORS', 'AUTHORS.md')
        ),
        'has_changelog': any(
            (p / name).exists()
            for name in ('CHANGELOG.md', 'CHANGES.md', 'NEWS.md', 'HISTORY.md')
        ),
    }
```

- [ ] **Step 4: Wire into scan step**

- [ ] **Step 5: Commit**

```
feat: detect codemeta.json, FUNDING.yml, CONTRIBUTORS, CHANGELOG during scan
```

---

### Task 6: Full integration test

- [ ] **Step 1: Run full test suite**

Run: `pytest --maxfail=5 -q`

- [ ] **Step 2: Smoke test with real repos**

```bash
repoindex refresh --full
repoindex sql "SELECT name, keywords FROM repos WHERE keywords IS NOT NULL LIMIT 10"
repoindex sql "SELECT name, has_codemeta, has_funding, has_changelog FROM repos WHERE has_changelog = 1 LIMIT 10"
```

- [ ] **Step 3: Commit and tag**
