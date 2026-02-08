"""
Audit service for repoindex.

Evaluates repository metadata completeness across categories:
- Essentials: README, LICENSE, .gitignore, remote
- Development: CI, tests, build config, clean tree, synced
- Discoverability: description, topics, citation, DOI, published
- Documentation: changelog, docs, contributing, code of conduct, CLAUDE.md

Each check has a severity (critical/recommended/suggested) and optional
fix hints pointing to repoindex generate commands.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

from ..domain.audit import (
    AuditCheck,
    AuditSummary,
    Category,
    CategoryScore,
    CheckResult,
    RepoAuditResult,
    Severity,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Check registry — 19 checks across 4 categories
# ============================================================================

CHECKS: List[AuditCheck] = [
    # --- Essentials ---
    AuditCheck('readme', 'README', Category.ESSENTIALS, Severity.CRITICAL,
               fix_hint='Add a README.md file'),
    AuditCheck('license', 'LICENSE', Category.ESSENTIALS, Severity.CRITICAL,
               fix_hint='Add a LICENSE file',
               fix_command='repoindex ops generate license --license mit'),
    AuditCheck('gitignore', '.gitignore', Category.ESSENTIALS, Severity.CRITICAL,
               fix_hint='Add a .gitignore file',
               fix_command='repoindex ops generate gitignore'),
    AuditCheck('remote', 'Remote URL', Category.ESSENTIALS, Severity.RECOMMENDED,
               fix_hint='Add a git remote (e.g., GitHub)'),

    # --- Development ---
    AuditCheck('ci', 'CI/CD', Category.DEVELOPMENT, Severity.RECOMMENDED,
               fix_hint='Add CI configuration (.github/workflows/)'),
    AuditCheck('tests', 'Tests', Category.DEVELOPMENT, Severity.RECOMMENDED,
               fix_hint='Add a tests/ directory'),
    AuditCheck('build_config', 'Build config', Category.DEVELOPMENT, Severity.RECOMMENDED,
               fix_hint='Add a build config (pyproject.toml, package.json, etc.)'),
    AuditCheck('clean', 'Clean tree', Category.DEVELOPMENT, Severity.SUGGESTED,
               fix_hint='Commit or stash uncommitted changes'),
    AuditCheck('synced', 'Synced', Category.DEVELOPMENT, Severity.SUGGESTED,
               fix_hint='Push unpushed commits',
               fix_command='repoindex ops git push'),

    # --- Discoverability ---
    AuditCheck('description', 'Description', Category.DISCOVERABILITY, Severity.RECOMMENDED,
               fix_hint='Add a project description'),
    AuditCheck('topics', 'Topics', Category.DISCOVERABILITY, Severity.RECOMMENDED,
               fix_hint='Add GitHub topics/keywords'),
    AuditCheck('citation', 'Citation file', Category.DISCOVERABILITY, Severity.SUGGESTED,
               fix_hint='Add CITATION.cff',
               fix_command='repoindex ops generate citation'),
    AuditCheck('doi', 'DOI', Category.DISCOVERABILITY, Severity.SUGGESTED,
               fix_hint='Mint a DOI via Zenodo',
               fix_command='repoindex ops generate zenodo'),
    AuditCheck('published', 'Published', Category.DISCOVERABILITY, Severity.SUGGESTED,
               fix_hint='Publish to a package registry (PyPI, CRAN, etc.)'),

    # --- Documentation ---
    AuditCheck('changelog', 'Changelog', Category.DOCUMENTATION, Severity.RECOMMENDED,
               fix_hint='Add CHANGELOG.md'),
    AuditCheck('docs', 'Docs site', Category.DOCUMENTATION, Severity.SUGGESTED,
               fix_hint='Add documentation (mkdocs.yml or docs/)',
               fix_command='repoindex ops generate mkdocs'),
    AuditCheck('contributing', 'Contributing', Category.DOCUMENTATION, Severity.SUGGESTED,
               fix_hint='Add CONTRIBUTING.md',
               fix_command='repoindex ops generate contributing'),
    AuditCheck('code_of_conduct', 'Code of Conduct', Category.DOCUMENTATION, Severity.SUGGESTED,
               fix_hint='Add CODE_OF_CONDUCT.md',
               fix_command='repoindex ops generate code-of-conduct'),
    AuditCheck('claude_md', 'CLAUDE.md', Category.DOCUMENTATION, Severity.SUGGESTED,
               fix_hint='Add CLAUDE.md for Claude Code context'),
]

# Index for fast lookup
_CHECKS_BY_ID: Dict[str, AuditCheck] = {c.id: c for c in CHECKS}

# Build config files to look for (any one present = pass)
_BUILD_CONFIG_FILES = [
    'pyproject.toml', 'setup.py', 'setup.cfg',
    'Cargo.toml',
    'package.json',
    'go.mod',
    'pom.xml', 'build.gradle',
    'Makefile',
    'CMakeLists.txt',
]

# Changelog file names
_CHANGELOG_FILES = ['CHANGELOG.md', 'CHANGELOG', 'HISTORY.md', 'CHANGES.md']


class AuditService:
    """
    Service for auditing repository metadata completeness.

    Evaluates repos against a registry of checks, grouped by category
    and severity. Results are structured for both human display and
    machine consumption (JSON).

    Example:
        service = AuditService()
        for progress in service.audit_repos(repos, db=db):
            print(progress)
        results = service.last_results
        summary = service.last_summary
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.last_results: Optional[List[RepoAuditResult]] = None
        self.last_summary: Optional[AuditSummary] = None

    def get_checks(
        self,
        category: Optional[Category] = None,
        severity: Optional[Severity] = None,
    ) -> List[AuditCheck]:
        """Return checks, optionally filtered by category and/or minimum severity.

        Severity filtering is threshold-based:
        - CRITICAL: only critical checks
        - RECOMMENDED: critical + recommended
        - SUGGESTED: all (default)
        """
        severity_order = [Severity.CRITICAL, Severity.RECOMMENDED, Severity.SUGGESTED]

        if severity is not None:
            threshold = severity_order.index(severity)
            allowed = set(severity_order[:threshold + 1])
        else:
            allowed = set(severity_order)

        result = []
        for check in CHECKS:
            if category is not None and check.category != category:
                continue
            if check.severity not in allowed:
                continue
            result.append(check)
        return result

    def audit_repos(
        self,
        repos: List[Dict[str, Any]],
        db=None,
        category: Optional[Category] = None,
        severity: Optional[Severity] = None,
    ) -> Generator[str, None, None]:
        """Audit repositories and yield progress messages.

        After consuming the generator, results are available via
        self.last_results and self.last_summary.

        Args:
            repos: List of repo dicts (from database query)
            db: Optional Database context for publications check
            category: Filter to one category
            severity: Minimum severity threshold
        """
        checks = self.get_checks(category=category, severity=severity)
        if not checks:
            self.last_results = []
            self.last_summary = AuditSummary()
            return

        check_ids = {c.id for c in checks}

        # Pre-load published repo IDs if needed
        published_ids: Set[int] = set()
        if 'published' in check_ids and db is not None:
            published_ids = self._load_published_ids(db)

        results: List[RepoAuditResult] = []
        total = len(repos)

        for i, repo in enumerate(repos):
            name = repo.get('name', '')
            yield f"Auditing {name} ({i + 1}/{total})..."

            repo_result = self._audit_single_repo(
                repo, checks, published_ids
            )
            results.append(repo_result)

        # Build summary
        summary = self._build_summary(results, checks)

        self.last_results = results
        self.last_summary = summary

    def _audit_single_repo(
        self,
        repo: Dict[str, Any],
        checks: List[AuditCheck],
        published_ids: Set[int],
    ) -> RepoAuditResult:
        """Run all applicable checks on a single repo."""
        repo_path = repo.get('path', '')
        path_exists = repo_path and Path(repo_path).is_dir()

        check_results: List[CheckResult] = []

        for check in checks:
            passed = self._evaluate_check(
                check, repo, path_exists, published_ids
            )
            cr = CheckResult(
                check_id=check.id,
                passed=passed,
            )
            if not passed:
                cr.fix_hint = check.fix_hint
                cr.fix_command = check.fix_command
            check_results.append(cr)

        # Compute category scores
        cat_scores = self._compute_category_scores(check_results, checks)

        return RepoAuditResult(
            name=repo.get('name', ''),
            path=repo_path,
            results=check_results,
            category_scores=cat_scores,
        )

    def _evaluate_check(
        self,
        check: AuditCheck,
        repo: Dict[str, Any],
        path_exists: bool,
        published_ids: Set[int],
    ) -> bool:
        """Evaluate a single check against a repo. Returns True if passed."""
        cid = check.id

        # --- DB-based checks ---
        if cid == 'readme':
            return bool(repo.get('has_readme'))
        if cid == 'license':
            return bool(repo.get('has_license'))
        if cid == 'remote':
            return bool(repo.get('remote_url'))
        if cid == 'ci':
            return bool(repo.get('has_ci'))
        if cid == 'clean':
            return bool(repo.get('is_clean'))
        if cid == 'synced':
            return repo.get('ahead', 0) == 0
        if cid == 'description':
            return bool(repo.get('github_description') or repo.get('description'))
        if cid == 'topics':
            topics = repo.get('github_topics')
            return bool(topics and topics != '[]')
        if cid == 'citation':
            return bool(repo.get('has_citation'))
        if cid == 'doi':
            return bool(repo.get('citation_doi'))

        # --- Published check (DB + logic) ---
        if cid == 'published':
            repo_id = repo.get('id')
            if repo_id is not None and repo_id in published_ids:
                return True
            # If repo has no build config, check is not applicable → pass
            if not path_exists:
                return True
            repo_path = Path(repo.get('path', ''))
            has_build = any(
                repo_path.joinpath(f).exists() for f in _BUILD_CONFIG_FILES
            )
            if not has_build:
                return True
            return False

        # --- Filesystem checks (skip if path doesn't exist) ---
        if not path_exists:
            return True

        repo_path = Path(repo.get('path', ''))

        if cid == 'gitignore':
            return repo_path.joinpath('.gitignore').exists()
        if cid == 'tests':
            return (repo_path / 'tests').is_dir() or (repo_path / 'test').is_dir()
        if cid == 'build_config':
            return any(repo_path.joinpath(f).exists() for f in _BUILD_CONFIG_FILES)
        if cid == 'changelog':
            return any(repo_path.joinpath(f).exists() for f in _CHANGELOG_FILES)
        if cid == 'docs':
            return (repo_path / 'mkdocs.yml').exists() or (repo_path / 'docs').is_dir()
        if cid == 'contributing':
            return repo_path.joinpath('CONTRIBUTING.md').exists()
        if cid == 'code_of_conduct':
            return repo_path.joinpath('CODE_OF_CONDUCT.md').exists()
        if cid == 'claude_md':
            return repo_path.joinpath('CLAUDE.md').exists()

        # Unknown check — default to pass
        logger.warning("Unknown check ID: %s", cid)
        return True

    def _compute_category_scores(
        self,
        check_results: List[CheckResult],
        checks: List[AuditCheck],
    ) -> List[CategoryScore]:
        """Compute per-category scores from check results."""
        # Build a lookup from check_id to category
        cat_map = {c.id: c.category for c in checks}

        # Aggregate
        cat_data: Dict[Category, CategoryScore] = {}
        for cr in check_results:
            cat = cat_map.get(cr.check_id)
            if cat is None:
                continue
            if cat not in cat_data:
                cat_data[cat] = CategoryScore(category=cat)
            cat_data[cat].total += 1
            if cr.passed:
                cat_data[cat].passed += 1

        # Return in canonical category order
        return [
            cat_data[c] for c in Category if c in cat_data
        ]

    def _load_published_ids(self, db) -> Set[int]:
        """Load repo IDs that have confirmed publications."""
        try:
            db.execute("SELECT DISTINCT repo_id FROM publications WHERE published = 1")
            return {row['repo_id'] for row in db.fetchall()}
        except Exception:
            logger.debug("Could not query publications table", exc_info=True)
            return set()

    def _build_summary(
        self,
        results: List[RepoAuditResult],
        checks: List[AuditCheck],
    ) -> AuditSummary:
        """Build collection-wide summary from per-repo results."""
        total_repos = len(results)

        # Per-check stats
        check_stats: Dict[str, Dict[str, Any]] = {}
        for check in checks:
            check_stats[check.id] = {
                'label': check.label,
                'category': check.category.value,
                'severity': check.severity.value,
                'passed': 0,
                'total': total_repos,
            }

        for repo_result in results:
            for cr in repo_result.results:
                if cr.check_id in check_stats and cr.passed:
                    check_stats[cr.check_id]['passed'] += 1

        # Per-category aggregation
        cat_agg: Dict[str, Dict[str, Any]] = {}
        for check in checks:
            cv = check.category.value
            if cv not in cat_agg:
                cat_agg[cv] = {'passed': 0, 'total': 0}
            stats = check_stats[check.id]
            cat_agg[cv]['passed'] += stats['passed']
            cat_agg[cv]['total'] += stats['total']

        for cv, data in cat_agg.items():
            data['score'] = round(data['passed'] / data['total'], 2) if data['total'] > 0 else 1.0

        # Overall score
        overall = 0.0
        if total_repos > 0:
            overall = sum(r.score for r in results) / total_repos

        return AuditSummary(
            total_repos=total_repos,
            overall_score=overall,
            checks=check_stats,
            categories=cat_agg,
        )
