"""Tests for the GitForge.fetch_events capability and forge event fetching."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from repoindex.sources import GitForge


class TestFetchEventsDefault:
    def test_default_raises_not_implemented(self):
        class BareForge(GitForge):
            source_id = "bare"
            name = "Bare"

            def detect(self, repo_path, repo_record=None):
                return True

            def fetch(self, repo_path, repo_record=None, config=None):
                return None

        forge = BareForge()
        with pytest.raises(NotImplementedError):
            list(forge.fetch_events({"forge_owner": "o", "forge_name": "n"},
                                    datetime(2026, 1, 1), {}))
