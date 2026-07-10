"""The refresh registry branch must not drop fields the source returned.

Regression test: publications.concept_doi was always NULL because
_process_repo rebuilt PackageMetadata from the source dict field-by-field
and omitted concept_doi.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from repoindex.sources import Registry


class _StubRegistry(Registry):
    source_id = 'zenodo'
    name = 'Zenodo'

    def detect(self, repo_path, repo_record=None):
        return True

    def fetch(self, repo_path, repo_record=None, config=None):
        return None


def test_registry_result_preserves_concept_doi():
    from repoindex.commands.refresh import _process_repo

    data = {
        'registry': 'zenodo',
        'name': 'pkg',
        'version': '1.2',
        'published': True,
        'url': 'https://zenodo.org/record/123',
        'doi': '10.5281/zenodo.123',
        'concept_doi': '10.5281/zenodo.100',
        'last_updated': '2026-01-01',
    }
    db = MagicMock()
    repo = MagicMock()
    repo.path = '/tmp/x'
    repo.name = 'x'
    stats = {'scanned': 0, 'updated': 0, 'skipped': 0,
             'events_added': 0, 'errors': 0}
    service = MagicMock()
    service.config = {}

    captured = {}

    def capture_upsert(db_, repo_id, pkg):
        captured['pkg'] = pkg

    with patch('repoindex.commands.refresh.needs_refresh', return_value=True), \
            patch('repoindex.commands.refresh.upsert_repo', return_value=7), \
            patch('repoindex.commands.refresh.resolve_forge', return_value=None), \
            patch('repoindex.commands.refresh._run_sources_parallel',
                  return_value=[(_StubRegistry(), data)]), \
            patch('repoindex.commands.refresh.scan_events', return_value=[]), \
            patch('repoindex.database.repository._upsert_publication',
                  side_effect=capture_upsert):
        _process_repo(db, service, repo, stats, full=False,
                      since=datetime(2026, 1, 1),
                      sources=[_StubRegistry()], config={},
                      dry_run=False, quiet=True, forge_events=False)

    pkg = captured['pkg']
    assert pkg.doi == '10.5281/zenodo.123'
    assert pkg.concept_doi == '10.5281/zenodo.100'
    assert pkg.version == '1.2'
    assert pkg.published is True
