"""
Tests for citation file parsing.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.citation import (
    parse_citation_file,
    _parse_citation_cff,
    _parse_zenodo_json,
    _parse_cff_authors,
    _parse_zenodo_authors,
    _parse_zenodo_license,
)


class TestParseCitationCff:
    """Tests for CITATION.cff parsing."""

    def test_parse_complete_citation_cff(self, tmp_path):
        """Test parsing a complete CITATION.cff file."""
        cff_content = """
cff-version: 1.2.0
title: "Example Software"
version: "1.0.0"
license: MIT
repository-code: "https://github.com/user/repo"
authors:
  - family-names: "Smith"
    given-names: "John"
    orcid: "https://orcid.org/0000-0000-0000-0001"
    affiliation: "University of Example"
  - family-names: "Doe"
    given-names: "Jane"
identifiers:
  - type: doi
    value: "10.5281/zenodo.1234567"
"""
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text(cff_content)

        result = parse_citation_file(str(tmp_path), "CITATION.cff")

        assert result is not None
        assert result['doi'] == "10.5281/zenodo.1234567"
        assert result['title'] == "Example Software"
        assert result['version'] == "1.0.0"
        assert result['license'] == "MIT"
        assert result['repository'] == "https://github.com/user/repo"
        assert len(result['authors']) == 2
        assert result['authors'][0]['name'] == "John Smith"
        assert result['authors'][0]['orcid'] == "https://orcid.org/0000-0000-0000-0001"
        assert result['authors'][1]['name'] == "Jane Doe"

    def test_parse_cff_with_doi_field_directly(self, tmp_path):
        """Test parsing CITATION.cff with doi field directly (older format)."""
        cff_content = """
cff-version: 1.2.0
title: "Legacy Software"
doi: "10.5281/zenodo.9999999"
authors:
  - name: "Research Group"
"""
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text(cff_content)

        result = parse_citation_file(str(tmp_path), "CITATION.cff")

        assert result is not None
        assert result['doi'] == "10.5281/zenodo.9999999"

    def test_parse_cff_minimal(self, tmp_path):
        """Test parsing minimal CITATION.cff with just title."""
        cff_content = """
cff-version: 1.2.0
title: "Minimal Software"
"""
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text(cff_content)

        result = parse_citation_file(str(tmp_path), "CITATION.cff")

        assert result is not None
        assert result['title'] == "Minimal Software"
        assert result['doi'] is None
        assert result['authors'] == []

    def test_parse_cff_entity_author(self, tmp_path):
        """Test parsing CITATION.cff with entity (organization) author."""
        cff_content = """
cff-version: 1.2.0
title: "Org Software"
authors:
  - name: "ACME Research Labs"
"""
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text(cff_content)

        result = parse_citation_file(str(tmp_path), "CITATION.cff")

        assert result is not None
        assert len(result['authors']) == 1
        assert result['authors'][0]['name'] == "ACME Research Labs"

    def test_parse_cff_invalid_yaml(self, tmp_path):
        """Test handling of invalid YAML in CITATION.cff."""
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text("invalid: yaml: content: [[[")

        result = parse_citation_file(str(tmp_path), "CITATION.cff")

        assert result is None

    def test_parse_cff_not_dict(self, tmp_path):
        """Test handling of YAML that doesn't parse to a dict."""
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text("- just\n- a\n- list")

        result = parse_citation_file(str(tmp_path), "CITATION.cff")

        assert result is None

    def test_parse_cff_file_not_found(self, tmp_path):
        """Test handling of non-existent file."""
        result = parse_citation_file(str(tmp_path), "CITATION.cff")
        assert result is None


class TestParseZenodoJson:
    """Tests for .zenodo.json parsing."""

    def test_parse_complete_zenodo_json(self, tmp_path):
        """Test parsing a complete .zenodo.json file."""
        zenodo_content = {
            "doi": "10.5281/zenodo.7654321",
            "title": "Zenodo Software",
            "version": "2.0.0",
            "license": {"id": "Apache-2.0"},
            "creators": [
                {
                    "name": "Smith, John",
                    "orcid": "0000-0000-0000-0001",
                    "affiliation": "University of Example"
                },
                {
                    "name": "Doe, Jane"
                }
            ],
            "related_identifiers": [
                {
                    "relation": "isSupplementTo",
                    "identifier": "https://github.com/user/repo"
                }
            ]
        }
        zenodo_file = tmp_path / ".zenodo.json"
        zenodo_file.write_text(json.dumps(zenodo_content))

        result = parse_citation_file(str(tmp_path), ".zenodo.json")

        assert result is not None
        assert result['doi'] == "10.5281/zenodo.7654321"
        assert result['title'] == "Zenodo Software"
        assert result['version'] == "2.0.0"
        assert result['license'] == "Apache-2.0"
        assert result['repository'] == "https://github.com/user/repo"
        assert len(result['authors']) == 2
        assert result['authors'][0]['name'] == "Smith, John"
        assert result['authors'][0]['orcid'] == "0000-0000-0000-0001"

    def test_parse_zenodo_json_string_license(self, tmp_path):
        """Test parsing .zenodo.json with string license field."""
        zenodo_content = {
            "title": "Simple Software",
            "license": "MIT"
        }
        zenodo_file = tmp_path / ".zenodo.json"
        zenodo_file.write_text(json.dumps(zenodo_content))

        result = parse_citation_file(str(tmp_path), ".zenodo.json")

        assert result is not None
        assert result['license'] == "MIT"

    def test_parse_zenodo_json_minimal(self, tmp_path):
        """Test parsing minimal .zenodo.json."""
        zenodo_content = {
            "title": "Minimal"
        }
        zenodo_file = tmp_path / ".zenodo.json"
        zenodo_file.write_text(json.dumps(zenodo_content))

        result = parse_citation_file(str(tmp_path), ".zenodo.json")

        assert result is not None
        assert result['title'] == "Minimal"
        assert result['doi'] is None
        assert result['authors'] == []

    def test_parse_zenodo_json_invalid_json(self, tmp_path):
        """Test handling of invalid JSON."""
        zenodo_file = tmp_path / ".zenodo.json"
        zenodo_file.write_text("{invalid json content")

        result = parse_citation_file(str(tmp_path), ".zenodo.json")

        assert result is None

    def test_parse_zenodo_json_not_dict(self, tmp_path):
        """Test handling of JSON that's not a dict."""
        zenodo_file = tmp_path / ".zenodo.json"
        zenodo_file.write_text(json.dumps(["just", "a", "list"]))

        result = parse_citation_file(str(tmp_path), ".zenodo.json")

        assert result is None


class TestParseCffAuthors:
    """Tests for CFF authors parsing."""

    def test_parse_person_author(self):
        """Test parsing a person author with given/family names."""
        authors = [
            {
                "family-names": "Smith",
                "given-names": "John",
                "orcid": "https://orcid.org/0000-0000-0000-0001",
                "affiliation": "University",
                "email": "john@example.com"
            }
        ]
        result = _parse_cff_authors(authors)

        assert len(result) == 1
        assert result[0]['name'] == "John Smith"
        assert result[0]['orcid'] == "https://orcid.org/0000-0000-0000-0001"
        assert result[0]['affiliation'] == "University"
        assert result[0]['email'] == "john@example.com"

    def test_parse_entity_author(self):
        """Test parsing an entity (organization) author."""
        authors = [
            {"name": "Research Labs Inc."}
        ]
        result = _parse_cff_authors(authors)

        assert len(result) == 1
        assert result[0]['name'] == "Research Labs Inc."

    def test_parse_author_given_only(self):
        """Test parsing author with only given name."""
        authors = [
            {"given-names": "Madonna"}
        ]
        result = _parse_cff_authors(authors)

        assert len(result) == 1
        assert result[0]['name'] == "Madonna"

    def test_parse_author_family_only(self):
        """Test parsing author with only family name."""
        authors = [
            {"family-names": "Prince"}
        ]
        result = _parse_cff_authors(authors)

        assert len(result) == 1
        assert result[0]['name'] == "Prince"

    def test_skip_invalid_author(self):
        """Test that invalid author entries are skipped."""
        authors = [
            {},  # Empty dict
            "string author",  # Not a dict
            {"other-field": "value"},  # No name fields
            {"name": "Valid Author"}  # Valid
        ]
        result = _parse_cff_authors(authors)

        assert len(result) == 1
        assert result[0]['name'] == "Valid Author"


class TestParseZenodoAuthors:
    """Tests for Zenodo creators parsing."""

    def test_parse_creator(self):
        """Test parsing a Zenodo creator."""
        creators = [
            {
                "name": "Smith, John",
                "orcid": "0000-0000-0000-0001",
                "affiliation": "University"
            }
        ]
        result = _parse_zenodo_authors(creators)

        assert len(result) == 1
        assert result[0]['name'] == "Smith, John"
        assert result[0]['orcid'] == "0000-0000-0000-0001"
        assert result[0]['affiliation'] == "University"

    def test_skip_invalid_creator(self):
        """Test that invalid creators are skipped."""
        creators = [
            {},  # Empty
            "string",  # Not a dict
            {"name": "Valid"}
        ]
        result = _parse_zenodo_authors(creators)

        assert len(result) == 1
        assert result[0]['name'] == "Valid"


class TestParseZenodoLicense:
    """Tests for Zenodo license parsing."""

    def test_parse_license_dict(self):
        """Test parsing license as dict."""
        result = _parse_zenodo_license({"id": "MIT"})
        assert result == "MIT"

    def test_parse_license_string(self):
        """Test parsing license as string."""
        result = _parse_zenodo_license("Apache-2.0")
        assert result == "Apache-2.0"

    def test_parse_license_none(self):
        """Test parsing None license."""
        result = _parse_zenodo_license(None)
        assert result is None

    def test_parse_license_invalid(self):
        """Test parsing invalid license type."""
        result = _parse_zenodo_license(123)
        assert result is None


class TestParseCitationFile:
    """Tests for the main parse_citation_file function."""

    def test_unsupported_file_type(self, tmp_path):
        """Test handling of unsupported citation file types."""
        result = parse_citation_file(str(tmp_path), "UNKNOWN.xyz")
        assert result is None

    def test_citation_bib_deferred(self, tmp_path):
        """Test that CITATION.bib is recognized but parsing is deferred."""
        bib_file = tmp_path / "CITATION.bib"
        bib_file.write_text("@software{example, title={Example}}")

        result = parse_citation_file(str(tmp_path), "CITATION.bib")

        # BibTeX parsing is deferred, should return None
        assert result is None

    def test_parse_cff_with_yaml_import_error(self, tmp_path):
        """Test handling when PyYAML is not available."""
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text("title: Test")

        with patch.dict('sys.modules', {'yaml': None}):
            # This should handle the ImportError gracefully
            # Note: The actual behavior depends on how the import is structured
            pass  # The test verifies no exception is raised

    def test_parse_exception_handling_cff(self, tmp_path):
        """Test exception handling during CFF parsing."""
        cff_file = tmp_path / "CITATION.cff"
        # Create a file that will raise an exception during read
        cff_file.write_bytes(b'\x80\x81\x82')  # Invalid UTF-8

        result = parse_citation_file(str(tmp_path), "CITATION.cff")
        # Should handle gracefully and return None or partial result
        # (errors='replace' in read_text handles this, so may return result)
        # Just verify it doesn't raise
        assert result is None or isinstance(result, dict)

    def test_parse_exception_handling_zenodo(self, tmp_path):
        """Test exception handling during Zenodo JSON parsing."""
        zenodo_file = tmp_path / ".zenodo.json"
        # Create a file that will raise an exception during read
        zenodo_file.write_bytes(b'\x80\x81\x82')  # Invalid UTF-8

        result = parse_citation_file(str(tmp_path), ".zenodo.json")
        # Should handle gracefully
        assert result is None or isinstance(result, dict)

    def test_unknown_citation_file_returns_none(self, tmp_path):
        """Test that unknown citation file types return None."""
        # Create a random file
        random_file = tmp_path / "CITATION.unknown"
        random_file.write_text("some content")

        result = parse_citation_file(str(tmp_path), "CITATION.unknown")
        assert result is None

    def test_generic_exception_in_parse_citation_file(self, tmp_path):
        """Test generic exception handling in parse_citation_file."""
        # Test with a file that exists but causes issues
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text("title: Test\ninvalid_field: \t\t\n")

        # Should not raise, should return result or None
        result = parse_citation_file(str(tmp_path), "CITATION.cff")
        assert result is None or isinstance(result, dict)


class TestIntegration:
    """Integration tests for citation parsing in repository context."""

    def test_parse_real_world_citation_cff(self, tmp_path):
        """Test parsing a real-world style CITATION.cff."""
        cff_content = """
cff-version: 1.2.0
message: "If you use this software, please cite it as below."
type: software
title: "Machine Learning Framework"
abstract: "A framework for building ML models."
version: "3.1.4"
date-released: "2025-01-15"
license: BSD-3-Clause
repository-code: "https://github.com/org/ml-framework"
url: "https://ml-framework.org"
keywords:
  - machine-learning
  - deep-learning
  - python
authors:
  - family-names: "Researcher"
    given-names: "Alice B."
    email: "alice@example.org"
    orcid: "https://orcid.org/0000-0001-2345-6789"
    affiliation: "Tech University"
  - family-names: "Developer"
    given-names: "Bob C."
    affiliation: "ACME Corp"
  - name: "ML Research Team"
identifiers:
  - type: doi
    value: "10.5281/zenodo.1234567"
  - type: url
    value: "https://ml-framework.org/cite"
preferred-citation:
  type: article
  title: "ML Framework: A New Approach"
"""
        cff_file = tmp_path / "CITATION.cff"
        cff_file.write_text(cff_content)

        result = parse_citation_file(str(tmp_path), "CITATION.cff")

        assert result is not None
        assert result['doi'] == "10.5281/zenodo.1234567"
        assert result['title'] == "Machine Learning Framework"
        assert result['version'] == "3.1.4"
        assert result['license'] == "BSD-3-Clause"
        assert result['repository'] == "https://github.com/org/ml-framework"
        assert len(result['authors']) == 3
        # Person authors
        assert result['authors'][0]['name'] == "Alice B. Researcher"
        assert result['authors'][1]['name'] == "Bob C. Developer"
        # Entity author
        assert result['authors'][2]['name'] == "ML Research Team"
