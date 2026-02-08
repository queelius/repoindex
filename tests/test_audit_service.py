"""
Tests for audit domain objects, audit service, and audit CLI command.

Tests cover:
- AuditCheck, CheckResult, CategoryScore, RepoAuditResult, AuditSummary domain objects
- AuditService check registry, filtering, and evaluation logic
- CLI integration via CliRunner (JSON, pretty, simple output; --category/--severity filters)
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from repoindex.domain.audit import (
    AuditCheck,
    AuditSummary,
    Category,
    CategoryScore,
    CheckResult,
    RepoAuditResult,
    Severity,
)
from repoindex.services.audit_service import (
    AuditService,
    CHECKS,
    _CHECKS_BY_ID,
)


# ============================================================================
# Domain Object Tests
# ============================================================================

class TestSeverityEnum:
    def test_values(self):
        assert Severity.CRITICAL.value == "critical"
        assert Severity.RECOMMENDED.value == "recommended"
        assert Severity.SUGGESTED.value == "suggested"

    def test_from_string(self):
        assert Severity("critical") == Severity.CRITICAL


class TestCategoryEnum:
    def test_values(self):
        assert Category.ESSENTIALS.value == "essentials"
        assert Category.DEVELOPMENT.value == "development"
        assert Category.DISCOVERABILITY.value == "discoverability"
        assert Category.DOCUMENTATION.value == "documentation"


class TestAuditCheck:
    def test_creation(self):
        check = AuditCheck(
            id='readme', label='README',
            category=Category.ESSENTIALS, severity=Severity.CRITICAL,
            fix_hint='Add README', fix_command='echo hi',
        )
        assert check.id == 'readme'
        assert check.category == Category.ESSENTIALS
        assert check.severity == Severity.CRITICAL

    def test_frozen(self):
        check = AuditCheck(
            id='readme', label='README',
            category=Category.ESSENTIALS, severity=Severity.CRITICAL,
        )
        with pytest.raises(AttributeError):
            check.id = 'other'

    def test_to_dict(self):
        check = AuditCheck(
            id='license', label='LICENSE',
            category=Category.ESSENTIALS, severity=Severity.CRITICAL,
            fix_hint='Add LICENSE', fix_command='repoindex ops generate license',
        )
        d = check.to_dict()
        assert d['id'] == 'license'
        assert d['category'] == 'essentials'
        assert d['severity'] == 'critical'
        assert d['fix_hint'] == 'Add LICENSE'
        assert d['fix_command'] == 'repoindex ops generate license'

    def test_to_dict_no_fix(self):
        check = AuditCheck(
            id='remote', label='Remote',
            category=Category.ESSENTIALS, severity=Severity.RECOMMENDED,
        )
        d = check.to_dict()
        assert 'fix_hint' not in d
        assert 'fix_command' not in d


class TestCheckResult:
    def test_passed(self):
        cr = CheckResult(check_id='readme', passed=True)
        d = cr.to_dict()
        assert d == {'check_id': 'readme', 'passed': True}
        # No fix fields when passed
        assert 'fix_hint' not in d

    def test_failed_with_hints(self):
        cr = CheckResult(
            check_id='license', passed=False,
            fix_hint='Add LICENSE',
            fix_command='repoindex ops generate license',
        )
        d = cr.to_dict()
        assert d['passed'] is False
        assert d['fix_hint'] == 'Add LICENSE'
        assert d['fix_command'] == 'repoindex ops generate license'

    def test_failed_no_hints(self):
        cr = CheckResult(check_id='clean', passed=False)
        d = cr.to_dict()
        assert d == {'check_id': 'clean', 'passed': False}


class TestCategoryScore:
    def test_score_property(self):
        cs = CategoryScore(category=Category.ESSENTIALS, passed=3, total=4)
        assert cs.score == 0.75

    def test_score_zero_total(self):
        cs = CategoryScore(category=Category.ESSENTIALS, passed=0, total=0)
        assert cs.score == 1.0  # No checks = perfect score

    def test_to_dict(self):
        cs = CategoryScore(category=Category.DEVELOPMENT, passed=2, total=5)
        d = cs.to_dict()
        assert d['category'] == 'development'
        assert d['passed'] == 2
        assert d['total'] == 5
        assert d['score'] == 0.4


class TestRepoAuditResult:
    def _make_result(self, pass_count=3, fail_count=2):
        results = []
        for i in range(pass_count):
            results.append(CheckResult(check_id=f'pass_{i}', passed=True))
        for i in range(fail_count):
            cmd = f'fix-{i}' if i % 2 == 0 else None
            results.append(CheckResult(
                check_id=f'fail_{i}', passed=False,
                fix_hint=f'Fix it {i}', fix_command=cmd,
            ))
        return RepoAuditResult(
            name='myrepo', path='/home/user/myrepo',
            results=results,
            category_scores=[CategoryScore(Category.ESSENTIALS, pass_count, pass_count + fail_count)],
        )

    def test_score(self):
        r = self._make_result(3, 2)
        assert r.passed == 3
        assert r.total == 5
        assert r.score == 0.6

    def test_score_empty(self):
        r = RepoAuditResult(name='empty', path='/tmp/empty')
        assert r.score == 1.0
        assert r.passed == 0
        assert r.total == 0

    def test_failed_checks(self):
        r = self._make_result(3, 2)
        failed = r.failed_checks
        assert len(failed) == 2
        assert all(not f.passed for f in failed)

    def test_fix_commands(self):
        r = self._make_result(3, 2)
        # Only fail_0 has fix_command ('fix-0'), fail_1 does not
        assert r.fix_commands == ['fix-0']

    def test_to_dict(self):
        r = self._make_result(2, 1)
        d = r.to_dict()
        assert d['name'] == 'myrepo'
        assert d['path'] == '/home/user/myrepo'
        assert d['passed'] == 2
        assert d['total'] == 3
        assert 'categories' in d
        assert 'failed' in d
        assert len(d['failed']) == 1
        assert 'fix_commands' in d


class TestAuditSummary:
    def test_to_dict(self):
        s = AuditSummary(
            total_repos=10,
            overall_score=0.756,
            checks={'readme': {'label': 'README', 'passed': 9, 'total': 10}},
            categories={'essentials': {'passed': 35, 'total': 40, 'score': 0.88}},
        )
        d = s.to_dict()
        assert d['type'] == 'summary'
        assert d['total_repos'] == 10
        assert d['overall_score'] == 0.76  # rounded
        assert 'checks' in d
        assert 'categories' in d


# ============================================================================
# Service Unit Tests
# ============================================================================

class TestAuditServiceCheckRegistry:
    def test_all_checks_count(self):
        assert len(CHECKS) == 19

    def test_checks_by_id_complete(self):
        assert len(_CHECKS_BY_ID) == 19
        for check in CHECKS:
            assert check.id in _CHECKS_BY_ID

    def test_get_checks_all(self):
        service = AuditService()
        all_checks = service.get_checks()
        assert len(all_checks) == 19

    def test_get_checks_by_category(self):
        service = AuditService()
        essentials = service.get_checks(category=Category.ESSENTIALS)
        assert len(essentials) == 4
        assert all(c.category == Category.ESSENTIALS for c in essentials)

    def test_get_checks_by_severity_critical(self):
        service = AuditService()
        critical = service.get_checks(severity=Severity.CRITICAL)
        assert all(c.severity == Severity.CRITICAL for c in critical)
        assert len(critical) == 3  # readme, license, gitignore

    def test_get_checks_by_severity_recommended(self):
        service = AuditService()
        rec = service.get_checks(severity=Severity.RECOMMENDED)
        # Should include critical + recommended
        severities = {c.severity for c in rec}
        assert Severity.CRITICAL in severities
        assert Severity.RECOMMENDED in severities
        assert Severity.SUGGESTED not in severities

    def test_get_checks_by_severity_suggested(self):
        service = AuditService()
        sug = service.get_checks(severity=Severity.SUGGESTED)
        assert len(sug) == 19  # all checks

    def test_get_checks_category_and_severity(self):
        service = AuditService()
        result = service.get_checks(
            category=Category.ESSENTIALS, severity=Severity.CRITICAL,
        )
        assert len(result) == 3  # readme, license, gitignore


class TestAuditServiceDBChecks:
    """Test DB-based check evaluation."""

    def _make_repo(self, **overrides):
        base = {
            'id': 1, 'name': 'testrepo', 'path': '/tmp/nonexistent',
            'has_readme': 0, 'has_license': 0, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 0, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }
        base.update(overrides)
        return base

    def _audit_single(self, repo, checks=None, published_ids=None):
        service = AuditService()
        if checks is None:
            checks = CHECKS
        if published_ids is None:
            published_ids = set()
        return service._audit_single_repo(repo, checks, published_ids)

    def test_readme_check(self):
        repo = self._make_repo(has_readme=1)
        result = self._audit_single(repo)
        readme_result = next(r for r in result.results if r.check_id == 'readme')
        assert readme_result.passed is True

    def test_readme_missing(self):
        repo = self._make_repo(has_readme=0)
        result = self._audit_single(repo)
        readme_result = next(r for r in result.results if r.check_id == 'readme')
        assert readme_result.passed is False

    def test_license_check(self):
        repo = self._make_repo(has_license=1)
        result = self._audit_single(repo)
        lic = next(r for r in result.results if r.check_id == 'license')
        assert lic.passed is True

    def test_ci_check(self):
        repo = self._make_repo(has_ci=1)
        result = self._audit_single(repo)
        ci = next(r for r in result.results if r.check_id == 'ci')
        assert ci.passed is True

    def test_citation_check(self):
        repo = self._make_repo(has_citation=1)
        result = self._audit_single(repo)
        cit = next(r for r in result.results if r.check_id == 'citation')
        assert cit.passed is True

    def test_doi_check(self):
        repo = self._make_repo(citation_doi='10.5281/zenodo.123')
        result = self._audit_single(repo)
        doi = next(r for r in result.results if r.check_id == 'doi')
        assert doi.passed is True

    def test_description_github(self):
        repo = self._make_repo(github_description='A cool project')
        result = self._audit_single(repo)
        desc = next(r for r in result.results if r.check_id == 'description')
        assert desc.passed is True

    def test_description_local(self):
        repo = self._make_repo(description='A cool project')
        result = self._audit_single(repo)
        desc = next(r for r in result.results if r.check_id == 'description')
        assert desc.passed is True

    def test_topics_check(self):
        repo = self._make_repo(github_topics='["python", "cli"]')
        result = self._audit_single(repo)
        topics = next(r for r in result.results if r.check_id == 'topics')
        assert topics.passed is True

    def test_topics_empty_list(self):
        repo = self._make_repo(github_topics='[]')
        result = self._audit_single(repo)
        topics = next(r for r in result.results if r.check_id == 'topics')
        assert topics.passed is False

    def test_clean_check(self):
        repo = self._make_repo(is_clean=1)
        result = self._audit_single(repo)
        clean = next(r for r in result.results if r.check_id == 'clean')
        assert clean.passed is True

    def test_synced_check(self):
        repo = self._make_repo(ahead=0)
        result = self._audit_single(repo)
        synced = next(r for r in result.results if r.check_id == 'synced')
        assert synced.passed is True

    def test_synced_check_behind(self):
        repo = self._make_repo(ahead=3)
        result = self._audit_single(repo)
        synced = next(r for r in result.results if r.check_id == 'synced')
        assert synced.passed is False

    def test_remote_check(self):
        repo = self._make_repo(remote_url='https://github.com/user/repo')
        result = self._audit_single(repo)
        remote = next(r for r in result.results if r.check_id == 'remote')
        assert remote.passed is True


class TestAuditServiceFSChecks:
    """Test filesystem-based check evaluation."""

    def _make_repo(self, tmp_path, **overrides):
        base = {
            'id': 1, 'name': 'testrepo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 1, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': 'https://example.com', 'is_clean': 1, 'ahead': 0,
            'github_description': 'desc', 'description': None,
            'github_topics': '["test"]',
        }
        base.update(overrides)
        return base

    def _audit_single(self, repo, published_ids=None):
        service = AuditService()
        if published_ids is None:
            published_ids = set()
        return service._audit_single_repo(repo, CHECKS, published_ids)

    def test_gitignore_present(self, tmp_path):
        (tmp_path / '.gitignore').write_text('*.pyc\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        gi = next(r for r in result.results if r.check_id == 'gitignore')
        assert gi.passed is True

    def test_gitignore_missing(self, tmp_path):
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        gi = next(r for r in result.results if r.check_id == 'gitignore')
        assert gi.passed is False

    def test_tests_directory(self, tmp_path):
        (tmp_path / 'tests').mkdir()
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        tests = next(r for r in result.results if r.check_id == 'tests')
        assert tests.passed is True

    def test_test_directory(self, tmp_path):
        (tmp_path / 'test').mkdir()
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        tests = next(r for r in result.results if r.check_id == 'tests')
        assert tests.passed is True

    def test_no_tests(self, tmp_path):
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        tests = next(r for r in result.results if r.check_id == 'tests')
        assert tests.passed is False

    def test_build_config_pyproject(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        bc = next(r for r in result.results if r.check_id == 'build_config')
        assert bc.passed is True

    def test_build_config_package_json(self, tmp_path):
        (tmp_path / 'package.json').write_text('{}\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        bc = next(r for r in result.results if r.check_id == 'build_config')
        assert bc.passed is True

    def test_build_config_missing(self, tmp_path):
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        bc = next(r for r in result.results if r.check_id == 'build_config')
        assert bc.passed is False

    def test_changelog_present(self, tmp_path):
        (tmp_path / 'CHANGELOG.md').write_text('# Changelog\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        cl = next(r for r in result.results if r.check_id == 'changelog')
        assert cl.passed is True

    def test_history_md(self, tmp_path):
        (tmp_path / 'HISTORY.md').write_text('# History\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        cl = next(r for r in result.results if r.check_id == 'changelog')
        assert cl.passed is True

    def test_docs_mkdocs(self, tmp_path):
        (tmp_path / 'mkdocs.yml').write_text('site_name: test\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        docs = next(r for r in result.results if r.check_id == 'docs')
        assert docs.passed is True

    def test_docs_directory(self, tmp_path):
        (tmp_path / 'docs').mkdir()
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        docs = next(r for r in result.results if r.check_id == 'docs')
        assert docs.passed is True

    def test_docs_missing(self, tmp_path):
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        docs = next(r for r in result.results if r.check_id == 'docs')
        assert docs.passed is False

    def test_contributing_present(self, tmp_path):
        (tmp_path / 'CONTRIBUTING.md').write_text('# Contributing\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        contrib = next(r for r in result.results if r.check_id == 'contributing')
        assert contrib.passed is True

    def test_code_of_conduct_present(self, tmp_path):
        (tmp_path / 'CODE_OF_CONDUCT.md').write_text('# Code of Conduct\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        coc = next(r for r in result.results if r.check_id == 'code_of_conduct')
        assert coc.passed is True

    def test_claude_md_present(self, tmp_path):
        (tmp_path / 'CLAUDE.md').write_text('# Claude\n')
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        cm = next(r for r in result.results if r.check_id == 'claude_md')
        assert cm.passed is True

    def test_claude_md_missing(self, tmp_path):
        repo = self._make_repo(tmp_path)
        result = self._audit_single(repo)
        cm = next(r for r in result.results if r.check_id == 'claude_md')
        assert cm.passed is False


class TestAuditServicePublishedCheck:
    """Test the published check logic."""

    def test_published_repo_in_set(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\n')
        repo = {
            'id': 42, 'name': 'published-repo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 1, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': 'https://example.com', 'is_clean': 1, 'ahead': 0,
            'github_description': 'desc', 'description': None,
            'github_topics': '["test"]',
        }
        service = AuditService()
        result = service._audit_single_repo(repo, CHECKS, published_ids={42})
        pub = next(r for r in result.results if r.check_id == 'published')
        assert pub.passed is True

    def test_unpublished_with_build_config(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\n')
        repo = {
            'id': 99, 'name': 'unpublished-repo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 1, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': 'https://example.com', 'is_clean': 1, 'ahead': 0,
            'github_description': 'desc', 'description': None,
            'github_topics': '["test"]',
        }
        service = AuditService()
        result = service._audit_single_repo(repo, CHECKS, published_ids=set())
        pub = next(r for r in result.results if r.check_id == 'published')
        assert pub.passed is False

    def test_no_build_config_passes(self, tmp_path):
        """Repos without build config aren't expected to be published."""
        repo = {
            'id': 99, 'name': 'no-build-repo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 1, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': 'https://example.com', 'is_clean': 1, 'ahead': 0,
            'github_description': 'desc', 'description': None,
            'github_topics': '["test"]',
        }
        service = AuditService()
        result = service._audit_single_repo(repo, CHECKS, published_ids=set())
        pub = next(r for r in result.results if r.check_id == 'published')
        assert pub.passed is True


class TestAuditServiceMissingPath:
    """Test that missing repo paths skip FS checks gracefully."""

    def test_nonexistent_path_skips_fs_checks(self):
        repo = {
            'id': 1, 'name': 'missing-repo', 'path': '/nonexistent/path/123',
            'has_readme': 0, 'has_license': 0, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 0, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }
        service = AuditService()
        result = service._audit_single_repo(repo, CHECKS, published_ids=set())

        # FS checks should all pass (skipped)
        fs_checks = {'gitignore', 'tests', 'build_config', 'changelog',
                      'docs', 'contributing', 'code_of_conduct', 'claude_md'}
        for cr in result.results:
            if cr.check_id in fs_checks:
                assert cr.passed is True, f"FS check {cr.check_id} should pass for missing path"


class TestAuditServiceFullAudit:
    """Test the full audit_repos flow."""

    def test_all_passing_repo(self, tmp_path):
        """A repo that passes everything should score 1.0."""
        # Create all expected files
        (tmp_path / '.gitignore').write_text('*.pyc\n')
        (tmp_path / 'tests').mkdir()
        (tmp_path / 'pyproject.toml').write_text('[project]\n')
        (tmp_path / 'CHANGELOG.md').write_text('# Changelog\n')
        (tmp_path / 'mkdocs.yml').write_text('site_name: test\n')
        (tmp_path / 'CONTRIBUTING.md').write_text('# Contributing\n')
        (tmp_path / 'CODE_OF_CONDUCT.md').write_text('# CoC\n')
        (tmp_path / 'CLAUDE.md').write_text('# Claude\n')

        repo = {
            'id': 1, 'name': 'perfect-repo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 1, 'has_ci': 1,
            'has_citation': 1, 'citation_doi': '10.5281/zenodo.123',
            'remote_url': 'https://github.com/user/repo',
            'is_clean': 1, 'ahead': 0,
            'github_description': 'A great repo',
            'description': None,
            'github_topics': '["python"]',
        }

        service = AuditService()
        mock_db = MagicMock()
        mock_db.execute = MagicMock()
        mock_db.fetchall = MagicMock(return_value=[{'repo_id': 1}])

        progress = list(service.audit_repos([repo], db=mock_db))
        assert len(progress) == 1

        results = service.last_results
        assert len(results) == 1
        assert results[0].score == 1.0
        assert len(results[0].failed_checks) == 0

    def test_minimal_repo(self, tmp_path):
        """A minimal repo should have a low score."""
        repo = {
            'id': 2, 'name': 'bare-repo', 'path': str(tmp_path),
            'has_readme': 0, 'has_license': 0, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 0, 'ahead': 5,
            'github_description': None, 'description': None,
            'github_topics': None,
        }

        service = AuditService()
        list(service.audit_repos([repo]))

        results = service.last_results
        assert len(results) == 1
        assert results[0].score < 0.5
        assert len(results[0].failed_checks) > 0

    def test_progress_messages_yielded(self, tmp_path):
        repo = {
            'id': 1, 'name': 'myrepo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 1, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 1, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }

        service = AuditService()
        messages = list(service.audit_repos([repo]))
        assert len(messages) == 1
        assert 'myrepo' in messages[0]
        assert '1/1' in messages[0]

    def test_last_results_populated(self, tmp_path):
        repo = {
            'id': 1, 'name': 'testrepo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 0, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 1, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }

        service = AuditService()
        list(service.audit_repos([repo]))

        assert service.last_results is not None
        assert service.last_summary is not None
        assert service.last_summary.total_repos == 1

    def test_category_scores_aggregated(self, tmp_path):
        repo = {
            'id': 1, 'name': 'testrepo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 1, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': 'https://example.com', 'is_clean': 1, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }

        service = AuditService()
        list(service.audit_repos([repo]))

        results = service.last_results
        assert len(results[0].category_scores) > 0

        # Check essentials category
        ess = next(cs for cs in results[0].category_scores
                   if cs.category == Category.ESSENTIALS)
        assert ess.total == 4  # readme, license, gitignore, remote

    def test_fix_commands_in_failed_checks(self, tmp_path):
        repo = {
            'id': 1, 'name': 'testrepo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 0, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 1, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }

        service = AuditService()
        list(service.audit_repos([repo]))

        result = service.last_results[0]
        # license check should fail with fix_command
        lic_result = next(r for r in result.results if r.check_id == 'license')
        assert lic_result.passed is False
        assert lic_result.fix_command is not None

    def test_category_filter(self, tmp_path):
        repo = {
            'id': 1, 'name': 'testrepo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 1, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 1, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }

        service = AuditService()
        list(service.audit_repos([repo], category=Category.ESSENTIALS))

        result = service.last_results[0]
        # Should only have essentials checks (4)
        assert result.total == 4
        check_ids = {r.check_id for r in result.results}
        assert check_ids == {'readme', 'license', 'gitignore', 'remote'}

    def test_severity_filter(self, tmp_path):
        repo = {
            'id': 1, 'name': 'testrepo', 'path': str(tmp_path),
            'has_readme': 1, 'has_license': 0, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 1, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }

        service = AuditService()
        list(service.audit_repos([repo], severity=Severity.CRITICAL))

        result = service.last_results[0]
        # Should only have critical checks (readme, license, gitignore)
        assert result.total == 3
        check_ids = {r.check_id for r in result.results}
        assert check_ids == {'readme', 'license', 'gitignore'}

    def test_summary_overall_score(self, tmp_path):
        repos = []
        for i in range(3):
            repos.append({
                'id': i, 'name': f'repo-{i}', 'path': str(tmp_path),
                'has_readme': 1, 'has_license': 1 if i == 0 else 0, 'has_ci': 0,
                'has_citation': 0, 'citation_doi': None,
                'remote_url': None, 'is_clean': 1, 'ahead': 0,
                'github_description': None, 'description': None,
                'github_topics': None,
            })

        service = AuditService()
        list(service.audit_repos(repos))

        summary = service.last_summary
        assert summary.total_repos == 3
        assert 0 < summary.overall_score < 1.0

    def test_load_published_ids(self):
        service = AuditService()
        mock_db = MagicMock()
        mock_db.execute = MagicMock()
        mock_db.fetchall = MagicMock(return_value=[
            {'repo_id': 1}, {'repo_id': 5}, {'repo_id': 10},
        ])

        ids = service._load_published_ids(mock_db)
        assert ids == {1, 5, 10}

    def test_load_published_ids_error(self):
        service = AuditService()
        mock_db = MagicMock()
        mock_db.execute = MagicMock(side_effect=Exception("no table"))

        ids = service._load_published_ids(mock_db)
        assert ids == set()


# ============================================================================
# CLI Integration Tests
# ============================================================================

class TestAuditCLI:
    """Test the ops audit CLI command."""

    def _run_audit(self, args, repos=None):
        """Helper to run the audit CLI command with mocked dependencies."""
        from click.testing import CliRunner
        from repoindex.commands.ops import ops_audit_handler, ops_cmd

        if repos is None:
            repos = [{
                'id': 1, 'name': 'test-repo', 'path': '/tmp/test-repo',
                'has_readme': 1, 'has_license': 0, 'has_ci': 0,
                'has_citation': 0, 'citation_doi': None,
                'remote_url': None, 'is_clean': 1, 'ahead': 0,
                'github_description': None, 'description': None,
                'github_topics': None,
            }]

        runner = CliRunner()
        with patch('repoindex.commands.ops._resolve_repos') as mock_resolve, \
             patch('repoindex.commands.ops.Database') as mock_db_cls:
            mock_resolve.return_value = ({}, repos)

            # Mock the DB context manager
            mock_db = MagicMock()
            mock_db.execute = MagicMock()
            mock_db.fetchall = MagicMock(return_value=[])
            mock_db_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_db_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = runner.invoke(ops_cmd, ['audit'] + args)

        return result

    def test_json_output_valid_jsonl(self):
        result = self._run_audit(['--json'])
        assert result.exit_code == 0
        lines = [l for l in result.output.strip().split('\n') if l]
        assert len(lines) >= 2  # at least 1 repo + summary
        # Verify each line is valid JSON
        for line in lines:
            data = json.loads(line)
            assert isinstance(data, dict)
        # Last line should be summary
        summary = json.loads(lines[-1])
        assert summary.get('type') == 'summary'

    def test_json_output_structure(self):
        result = self._run_audit(['--json'])
        assert result.exit_code == 0
        lines = result.output.strip().split('\n')
        repo_data = json.loads(lines[0])
        assert 'name' in repo_data
        assert 'score' in repo_data
        assert 'categories' in repo_data
        assert 'failed' in repo_data
        assert 'fix_commands' in repo_data

    def test_pretty_output_has_category_headers(self):
        result = self._run_audit(['--pretty'])
        assert result.exit_code == 0
        output = result.output
        assert 'Metadata Audit' in output
        assert 'Overall' in output

    def test_category_filter(self):
        result = self._run_audit(['--json', '--category', 'essentials'])
        assert result.exit_code == 0
        lines = result.output.strip().split('\n')
        repo_data = json.loads(lines[0])
        # Should only have essentials category
        assert 'essentials' in repo_data['categories']
        assert 'development' not in repo_data['categories']

    def test_severity_filter(self):
        result = self._run_audit(['--json', '--severity', 'critical'])
        assert result.exit_code == 0
        lines = result.output.strip().split('\n')
        repo_data = json.loads(lines[0])
        # Total should be 3 (readme, license, gitignore)
        assert repo_data['total'] == 3

    def test_query_flags_work(self):
        """Verify query flags pass through to _resolve_repos."""
        from click.testing import CliRunner
        from repoindex.commands.ops import ops_cmd

        repos = [{
            'id': 1, 'name': 'py-repo', 'path': '/tmp/py-repo',
            'has_readme': 1, 'has_license': 1, 'has_ci': 0,
            'has_citation': 0, 'citation_doi': None,
            'remote_url': None, 'is_clean': 1, 'ahead': 0,
            'github_description': None, 'description': None,
            'github_topics': None,
        }]

        runner = CliRunner()
        with patch('repoindex.commands.ops._resolve_repos') as mock_resolve, \
             patch('repoindex.commands.ops.Database') as mock_db_cls:
            mock_resolve.return_value = ({}, repos)
            mock_db = MagicMock()
            mock_db.execute = MagicMock()
            mock_db.fetchall = MagicMock(return_value=[])
            mock_db_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_db_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = runner.invoke(ops_cmd, ['audit', '--json', '--language', 'python'])

        assert result.exit_code == 0
        # Verify _resolve_repos was called with language='python'
        call_kwargs = mock_resolve.call_args
        assert call_kwargs[1]['language'] == 'python'
