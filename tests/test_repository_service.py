"""Tests for repoindex.services.repository_service (zenodo dual-DOI mapping)."""


class TestRepositoryServiceZenodoDualDoi:
    def test_zenodo_metadata_keeps_both_dois(self):
        from repoindex.services.repository_service import RepositoryService
        from repoindex.infra.zenodo_client import ZenodoRecord
        svc = RepositoryService(config={})
        record = ZenodoRecord(
            doi="10.5281/zenodo.456",
            concept_doi="10.5281/zenodo.400",
            title="demo",
            version="2.0.0",
            url="https://zenodo.org/records/456",
        )
        meta = svc._zenodo_record_to_metadata(record)
        assert meta.doi == "10.5281/zenodo.456"
        assert meta.concept_doi == "10.5281/zenodo.400"
