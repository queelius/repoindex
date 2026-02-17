"""
Audit domain objects for repoindex.

Provides structured types for repository metadata auditing:
- Severity/Category enums for classifying checks
- AuditCheck: definition of a single audit check
- CheckResult: result of running a check against a repo
- CategoryScore: aggregated score for a category
- RepoAuditResult: full audit result for one repository
- AuditSummary: collection-wide audit summary
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


class Severity(Enum):
    """Severity level for audit checks."""
    CRITICAL = "critical"
    RECOMMENDED = "recommended"
    SUGGESTED = "suggested"


class Category(Enum):
    """Category grouping for audit checks."""
    ESSENTIALS = "essentials"
    DEVELOPMENT = "development"
    DISCOVERABILITY = "discoverability"
    DOCUMENTATION = "documentation"
    IDENTITY = "identity"


@dataclass(frozen=True)
class AuditCheck:
    """Definition of a single audit check.

    Immutable — check definitions are constants.
    """
    id: str
    label: str
    category: Category
    severity: Severity
    fix_hint: Optional[str] = None
    fix_command: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'id': self.id,
            'label': self.label,
            'category': self.category.value,
            'severity': self.severity.value,
        }
        if self.fix_hint:
            result['fix_hint'] = self.fix_hint
        if self.fix_command:
            result['fix_command'] = self.fix_command
        return result


@dataclass
class CheckResult:
    """Result of running a single check against a repository."""
    check_id: str
    passed: bool
    fix_hint: Optional[str] = None
    fix_command: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'check_id': self.check_id,
            'passed': self.passed,
        }
        if not self.passed:
            if self.fix_hint:
                result['fix_hint'] = self.fix_hint
            if self.fix_command:
                result['fix_command'] = self.fix_command
        return result


@dataclass
class CategoryScore:
    """Aggregated score for one category."""
    category: Category
    passed: int = 0
    total: int = 0

    @property
    def score(self) -> float:
        if self.total == 0:
            return 1.0
        return self.passed / self.total

    def to_dict(self) -> Dict[str, Any]:
        return {
            'category': self.category.value,
            'passed': self.passed,
            'total': self.total,
            'score': round(self.score, 2),
        }


@dataclass
class RepoAuditResult:
    """Full audit result for one repository."""
    name: str
    path: str
    results: List[CheckResult] = field(default_factory=list)
    category_scores: List[CategoryScore] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def score(self) -> float:
        if self.total == 0:
            return 1.0
        return self.passed / self.total

    @property
    def failed_checks(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed]

    @property
    def fix_commands(self) -> List[str]:
        return [r.fix_command for r in self.results
                if not r.passed and r.fix_command]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'path': self.path,
            'score': round(self.score, 2),
            'passed': self.passed,
            'total': self.total,
            'categories': {
                cs.category.value: cs.to_dict()
                for cs in self.category_scores
            },
            'failed': [r.to_dict() for r in self.failed_checks],
            'fix_commands': self.fix_commands,
        }


@dataclass
class AuditSummary:
    """Collection-wide audit summary."""
    total_repos: int = 0
    overall_score: float = 0.0
    checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    categories: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'summary',
            'total_repos': self.total_repos,
            'overall_score': round(self.overall_score, 2),
            'checks': self.checks,
            'categories': self.categories,
        }
