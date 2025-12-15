"""Tests for the domain layer."""

import pytest
from datetime import datetime
from repoindex.domain import Repository, Tag, TagSource, Event
from repoindex.domain.repository import GitStatus, GitHubMetadata, PackageMetadata, LicenseInfo


class TestTag:
    """Tests for Tag domain object."""

    def test_parse_simple_tag(self):
        """Test parsing simple tag without value."""
        tag = Tag.parse("deprecated")
        assert tag.value == "deprecated"
        assert tag.key is None
        assert tag.segments == ()

    def test_parse_key_value_tag(self):
        """Test parsing key:value tag."""
        tag = Tag.parse("lang:python")
        assert tag.value == "lang:python"
        assert tag.key == "lang"
        assert tag.segments == ("python",)

    def test_parse_hierarchical_tag(self):
        """Test parsing hierarchical tag."""
        tag = Tag.parse("topic:ml/research/deep-learning")
        assert tag.value == "topic:ml/research/deep-learning"
        assert tag.key == "topic"
        assert tag.segments == ("ml", "research", "deep-learning")

    def test_parse_with_source(self):
        """Test parsing with explicit source."""
        tag = Tag.parse("org:torvalds", source=TagSource.PROVIDER)
        assert tag.source == TagSource.PROVIDER

    def test_matches_exact(self):
        """Test exact match."""
        tag = Tag.parse("lang:python")
        assert tag.matches("lang:python")
        assert not tag.matches("lang:rust")

    def test_matches_key_wildcard(self):
        """Test key:* wildcard match."""
        tag = Tag.parse("lang:python")
        assert tag.matches("lang:*")
        assert not tag.matches("topic:*")

    def test_matches_hierarchy_prefix(self):
        """Test hierarchy prefix match."""
        tag = Tag.parse("topic:ml/research/deep-learning")
        assert tag.matches("topic:ml/*")
        assert tag.matches("topic:ml/research/*")
        assert not tag.matches("topic:nlp/*")

    def test_matches_wildcard_all(self):
        """Test * matches everything."""
        tag = Tag.parse("anything:value")
        assert tag.matches("*")

    def test_to_dict(self):
        """Test serialization to dict."""
        tag = Tag.parse("lang:python", source=TagSource.IMPLICIT)
        d = tag.to_dict()
        assert d['value'] == "lang:python"
        assert d['key'] == "lang"
        assert d['segments'] == ["python"]
        assert d['source'] == "implicit"

    def test_str(self):
        """Test string representation."""
        tag = Tag.parse("lang:python")
        assert str(tag) == "lang:python"


class TestRepository:
    """Tests for Repository domain object."""

    def test_from_path(self):
        """Test creating repository from path."""
        repo = Repository.from_path("/home/user/projects/myrepo")
        assert repo.path == "/home/user/projects/myrepo"
        assert repo.name == "myrepo"

    def test_to_dict(self):
        """Test serialization to dict."""
        repo = Repository(
            path="/path/to/repo",
            name="myrepo",
            remote_url="https://github.com/user/myrepo",
            owner="user",
            language="Python"
        )
        d = repo.to_dict()
        assert d['path'] == "/path/to/repo"
        assert d['name'] == "myrepo"
        assert d['remote_url'] == "https://github.com/user/myrepo"
        assert d['owner'] == "user"
        assert d['language'] == "Python"

    def test_to_dict_excludes_none(self):
        """Test that None values are excluded from dict."""
        repo = Repository(path="/path", name="repo")
        d = repo.to_dict()
        assert 'github' not in d
        assert 'package' not in d

    def test_has_tag(self):
        """Test tag matching on repository."""
        repo = Repository(
            path="/path",
            name="repo",
            tags=frozenset(["lang:python", "topic:ml"])
        )
        assert repo.has_tag("lang:python")
        assert repo.has_tag("lang:*")
        assert repo.has_tag("topic:ml")
        assert not repo.has_tag("lang:rust")

    def test_with_status(self):
        """Test creating repository with updated status."""
        repo = Repository(path="/path", name="repo")
        status = GitStatus(branch="develop", clean=False)
        updated = repo.with_status(status)

        assert updated.status.branch == "develop"
        assert not updated.status.clean
        assert repo.status.branch == "main"  # Original unchanged

    def test_is_clean_property(self):
        """Test is_clean convenience property."""
        clean_repo = Repository(
            path="/path",
            name="repo",
            status=GitStatus(clean=True)
        )
        dirty_repo = Repository(
            path="/path",
            name="repo",
            status=GitStatus(clean=False)
        )
        assert clean_repo.is_clean
        assert not dirty_repo.is_clean

    def test_branch_property(self):
        """Test branch convenience property."""
        repo = Repository(
            path="/path",
            name="repo",
            status=GitStatus(branch="feature/new-thing")
        )
        assert repo.branch == "feature/new-thing"


class TestGitStatus:
    """Tests for GitStatus domain object."""

    def test_defaults(self):
        """Test default values."""
        status = GitStatus()
        assert status.branch == "main"
        assert status.clean is True
        assert status.ahead == 0
        assert status.behind == 0

    def test_to_dict(self):
        """Test serialization."""
        status = GitStatus(branch="develop", clean=False, ahead=2, behind=1)
        d = status.to_dict()
        assert d['branch'] == "develop"
        assert d['clean'] is False
        assert d['ahead'] == 2
        assert d['behind'] == 1


class TestGitHubMetadata:
    """Tests for GitHubMetadata domain object."""

    def test_creation(self):
        """Test creating GitHub metadata."""
        gh = GitHubMetadata(
            owner="user",
            name="repo",
            description="A test repo",
            stars=42,
            is_fork=False
        )
        assert gh.owner == "user"
        assert gh.name == "repo"
        assert gh.stars == 42

    def test_to_dict(self):
        """Test serialization."""
        gh = GitHubMetadata(
            owner="user",
            name="repo",
            topics=("ml", "python")
        )
        d = gh.to_dict()
        assert d['owner'] == "user"
        assert d['topics'] == ["ml", "python"]  # Tuple converted to list


class TestEvent:
    """Tests for Event domain object."""

    def test_creation(self):
        """Test creating event."""
        event = Event(
            type="git_tag",
            timestamp=datetime(2024, 1, 15, 10, 30),
            repo_name="myrepo",
            repo_path="/path/to/myrepo",
            data={"tag": "v1.0.0", "message": "Release 1.0"}
        )
        assert event.type == "git_tag"
        assert event.repo_name == "myrepo"
        assert event.data['tag'] == "v1.0.0"

    def test_id_git_tag(self):
        """Test stable ID for git_tag event."""
        event = Event(
            type="git_tag",
            timestamp=datetime.now(),
            repo_name="myrepo",
            repo_path="/path",
            data={"tag": "v1.0.0"}
        )
        assert event.id == "git_tag_myrepo_v1.0.0"

    def test_id_commit(self):
        """Test stable ID for commit event."""
        event = Event(
            type="commit",
            timestamp=datetime.now(),
            repo_name="myrepo",
            repo_path="/path",
            data={"hash": "abc123def456"}
        )
        assert event.id == "commit_myrepo_abc123de"

    def test_to_dict(self):
        """Test serialization."""
        event = Event(
            type="git_tag",
            timestamp=datetime(2024, 1, 15, 10, 30),
            repo_name="myrepo",
            repo_path="/path",
            data={"tag": "v1.0.0"}
        )
        d = event.to_dict()
        assert d['type'] == "git_tag"
        assert d['repo'] == "myrepo"
        assert d['timestamp'] == "2024-01-15T10:30:00"
        assert 'id' in d

    def test_to_jsonl(self):
        """Test JSONL output."""
        event = Event(
            type="git_tag",
            timestamp=datetime(2024, 1, 15, 10, 30),
            repo_name="myrepo",
            repo_path="/path",
            data={"tag": "v1.0.0"}
        )
        jsonl = event.to_jsonl()
        assert '"type": "git_tag"' in jsonl
        assert '\n' not in jsonl

    def test_equality_by_id(self):
        """Test events are equal if IDs match."""
        e1 = Event(
            type="git_tag",
            timestamp=datetime(2024, 1, 15),
            repo_name="repo",
            repo_path="/path",
            data={"tag": "v1.0"}
        )
        e2 = Event(
            type="git_tag",
            timestamp=datetime(2024, 1, 16),  # Different timestamp
            repo_name="repo",
            repo_path="/other/path",  # Different path
            data={"tag": "v1.0"}
        )
        assert e1 == e2  # Same ID
        assert hash(e1) == hash(e2)

    def test_hashable_for_sets(self):
        """Test events can be used in sets."""
        e1 = Event(
            type="git_tag",
            timestamp=datetime.now(),
            repo_name="repo",
            repo_path="/path",
            data={"tag": "v1.0"}
        )
        e2 = Event(
            type="git_tag",
            timestamp=datetime.now(),
            repo_name="repo",
            repo_path="/path",
            data={"tag": "v2.0"}
        )
        events = {e1, e2}
        assert len(events) == 2
