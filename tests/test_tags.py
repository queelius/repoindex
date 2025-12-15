"""
Comprehensive tests for ghops/tags.py tag management utilities.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from repoindex.tags import (
    parse_tag,
    format_tag,
    parse_tags,
    format_tags,
    merge_tags,
    filter_tags,
    get_tag_value,
    has_tag,
    is_hierarchical_tag,
    parse_hierarchical_tag,
    match_hierarchical_tag,
    filter_hierarchical_tags,
    github_metadata_to_tags,
    auto_detect_tags,
)


class TestParseTag:
    """Tests for parse_tag function."""

    def test_simple_tag_no_value(self):
        """Parse a simple tag without value."""
        key, value = parse_tag("deprecated")
        assert key == "deprecated"
        assert value is None

    def test_tag_with_value(self):
        """Parse a tag with key:value format."""
        key, value = parse_tag("org:torvalds")
        assert key == "org"
        assert value == "torvalds"

    def test_tag_with_colon_in_value(self):
        """Parse a tag where value contains colons."""
        key, value = parse_tag("url:https://example.com")
        assert key == "url"
        assert value == "https://example.com"

    def test_tag_with_empty_value(self):
        """Parse a tag with empty value after colon."""
        key, value = parse_tag("prefix:")
        assert key == "prefix"
        assert value == ""

    def test_empty_string(self):
        """Parse an empty string tag."""
        key, value = parse_tag("")
        assert key == ""
        assert value is None


class TestFormatTag:
    """Tests for format_tag function."""

    def test_format_simple_tag(self):
        """Format a simple tag without value."""
        result = format_tag("deprecated")
        assert result == "deprecated"

    def test_format_tag_with_value(self):
        """Format a tag with key and value."""
        result = format_tag("org", "torvalds")
        assert result == "org:torvalds"

    def test_format_tag_with_none_value(self):
        """Format a tag with None value."""
        result = format_tag("active", None)
        assert result == "active"

    def test_format_tag_with_empty_value(self):
        """Format a tag with empty string value."""
        result = format_tag("prefix", "")
        assert result == "prefix:"


class TestParseTags:
    """Tests for parse_tags function."""

    def test_parse_empty_list(self):
        """Parse empty tag list."""
        result = parse_tags([])
        assert result == {}

    def test_parse_mixed_tags(self):
        """Parse a mix of simple and key:value tags."""
        tags = ["org:torvalds", "deprecated", "lang:python"]
        result = parse_tags(tags)
        assert result == {
            "org": "torvalds",
            "deprecated": None,
            "lang": "python"
        }

    def test_parse_duplicate_keys_last_wins(self):
        """When duplicate keys exist, last one wins."""
        tags = ["lang:python", "lang:javascript"]
        result = parse_tags(tags)
        assert result == {"lang": "javascript"}


class TestFormatTags:
    """Tests for format_tags function."""

    def test_format_empty_dict(self):
        """Format empty tag dictionary."""
        result = format_tags({})
        assert result == []

    def test_format_mixed_tags(self):
        """Format a dictionary with mixed tags."""
        tag_dict = {"org": "torvalds", "deprecated": None, "lang": "python"}
        result = format_tags(tag_dict)
        # Check all expected tags are present (order may vary)
        assert set(result) == {"org:torvalds", "deprecated", "lang:python"}


class TestMergeTags:
    """Tests for merge_tags function."""

    def test_merge_empty_lists(self):
        """Merge two empty lists."""
        result = merge_tags([], [])
        assert result == []

    def test_merge_new_tags(self):
        """Merge new tags with existing."""
        existing = ["org:torvalds", "lang:c"]
        new = ["status:active"]
        result = merge_tags(existing, new)
        assert set(result) == {"org:torvalds", "lang:c", "status:active"}

    def test_merge_override_existing(self):
        """New tags override existing tags with same key."""
        existing = ["lang:python", "status:inactive"]
        new = ["lang:javascript", "new:tag"]
        result = merge_tags(existing, new)
        result_dict = parse_tags(result)
        assert result_dict["lang"] == "javascript"
        assert result_dict["status"] == "inactive"
        assert result_dict["new"] == "tag"


class TestFilterTags:
    """Tests for filter_tags function."""

    def test_filter_exact_match(self):
        """Filter with exact match pattern."""
        tags = ["org:torvalds", "org:linus", "lang:python"]
        result = filter_tags(tags, "org:torvalds")
        assert result == ["org:torvalds"]

    def test_filter_wildcard_suffix(self):
        """Filter with wildcard at end."""
        tags = ["org:torvalds", "org:linus", "lang:python"]
        result = filter_tags(tags, "org:*")
        assert set(result) == {"org:torvalds", "org:linus"}

    def test_filter_wildcard_prefix(self):
        """Filter with wildcard at start."""
        tags = ["topic:ml", "topic:ai", "lang:python"]
        result = filter_tags(tags, "*:python")
        assert result == ["lang:python"]

    def test_filter_no_matches(self):
        """Filter returns empty when no matches."""
        tags = ["org:torvalds", "lang:python"]
        result = filter_tags(tags, "status:*")
        assert result == []

    def test_filter_empty_tags(self):
        """Filter empty tag list."""
        result = filter_tags([], "org:*")
        assert result == []


class TestGetTagValue:
    """Tests for get_tag_value function."""

    def test_get_existing_key(self):
        """Get value for existing key."""
        tags = ["org:torvalds", "lang:python"]
        result = get_tag_value(tags, "org")
        assert result == "torvalds"

    def test_get_nonexistent_key(self):
        """Get value for nonexistent key returns None."""
        tags = ["org:torvalds", "lang:python"]
        result = get_tag_value(tags, "status")
        assert result is None

    def test_get_simple_tag_value(self):
        """Get value for simple tag (no value) returns None."""
        tags = ["deprecated", "org:torvalds"]
        result = get_tag_value(tags, "deprecated")
        assert result is None

    def test_get_from_empty_list(self):
        """Get value from empty tag list."""
        result = get_tag_value([], "org")
        assert result is None


class TestHasTag:
    """Tests for has_tag function."""

    def test_has_tag_key_only(self):
        """Check if tag key exists."""
        tags = ["org:torvalds", "deprecated"]
        assert has_tag(tags, "org") is True
        assert has_tag(tags, "deprecated") is True
        assert has_tag(tags, "missing") is False

    def test_has_tag_key_and_value(self):
        """Check if tag with specific value exists."""
        tags = ["org:torvalds", "lang:python"]
        assert has_tag(tags, "org", "torvalds") is True
        assert has_tag(tags, "org", "linus") is False

    def test_has_tag_simple_with_value_check(self):
        """Simple tag (no value) with value check."""
        tags = ["deprecated"]
        assert has_tag(tags, "deprecated") is True
        assert has_tag(tags, "deprecated", "true") is False


class TestIsHierarchicalTag:
    """Tests for is_hierarchical_tag function."""

    def test_hierarchical_tag(self):
        """Tag value with / is hierarchical."""
        assert is_hierarchical_tag("scientific/engineering/ai") is True

    def test_simple_tag_value(self):
        """Tag value without / is not hierarchical."""
        assert is_hierarchical_tag("python") is False

    def test_empty_value(self):
        """Empty value is not hierarchical."""
        assert is_hierarchical_tag("") is False

    def test_none_value(self):
        """None value is not hierarchical."""
        assert is_hierarchical_tag(None) is False


class TestParseHierarchicalTag:
    """Tests for parse_hierarchical_tag function."""

    def test_parse_hierarchical(self):
        """Parse hierarchical tag."""
        key, levels = parse_hierarchical_tag("topic:scientific/engineering/ai")
        assert key == "topic"
        assert levels == ["scientific", "engineering", "ai"]

    def test_parse_simple_tag(self):
        """Parse simple tag (not hierarchical)."""
        key, levels = parse_hierarchical_tag("lang:python")
        assert key == "lang"
        assert levels == ["python"]

    def test_parse_tag_without_value(self):
        """Parse tag without value."""
        key, levels = parse_hierarchical_tag("deprecated")
        assert key == "deprecated"
        assert levels == []


class TestMatchHierarchicalTag:
    """Tests for match_hierarchical_tag function."""

    def test_exact_match(self):
        """Exact hierarchical match."""
        assert match_hierarchical_tag(
            "topic:scientific/engineering/ai",
            "topic:scientific/engineering/ai"
        ) is True

    def test_key_only_match(self):
        """Match by key only."""
        assert match_hierarchical_tag("topic:scientific/engineering", "topic") is True

    def test_partial_hierarchy_match(self):
        """Match partial hierarchy (prefix)."""
        assert match_hierarchical_tag(
            "topic:scientific/engineering/ai",
            "topic:scientific"
        ) is True

    def test_wildcard_match(self):
        """Match with wildcard."""
        assert match_hierarchical_tag(
            "topic:scientific/engineering/ai",
            "topic:scientific/*"
        ) is True

    def test_key_mismatch(self):
        """Different keys don't match."""
        assert match_hierarchical_tag(
            "topic:scientific",
            "category:scientific"
        ) is False

    def test_value_mismatch(self):
        """Different values don't match."""
        assert match_hierarchical_tag(
            "topic:scientific/engineering",
            "topic:humanities"
        ) is False

    def test_pattern_longer_than_tag(self):
        """Pattern with more levels than tag doesn't match."""
        assert match_hierarchical_tag(
            "topic:scientific",
            "topic:scientific/engineering/ai"
        ) is False


class TestFilterHierarchicalTags:
    """Tests for filter_hierarchical_tags function."""

    def test_filter_by_key(self):
        """Filter hierarchical tags by key."""
        tags = [
            "topic:scientific/engineering",
            "topic:humanities/history",
            "lang:python"
        ]
        result = filter_hierarchical_tags(tags, "topic")
        assert set(result) == {
            "topic:scientific/engineering",
            "topic:humanities/history"
        }

    def test_filter_by_hierarchy_prefix(self):
        """Filter by hierarchy prefix."""
        tags = [
            "topic:scientific/engineering/ai",
            "topic:scientific/engineering/ml",
            "topic:scientific/physics",
            "topic:humanities/history"
        ]
        result = filter_hierarchical_tags(tags, "topic:scientific/engineering")
        assert set(result) == {
            "topic:scientific/engineering/ai",
            "topic:scientific/engineering/ml"
        }

    def test_filter_with_wildcard(self):
        """Filter with wildcard pattern."""
        tags = [
            "topic:scientific/engineering/ai",
            "topic:scientific/physics",
            "topic:humanities"
        ]
        result = filter_hierarchical_tags(tags, "topic:scientific/*")
        assert set(result) == {
            "topic:scientific/engineering/ai",
            "topic:scientific/physics"
        }


class TestGitHubMetadataToTags:
    """Tests for github_metadata_to_tags function."""

    def test_basic_metadata(self):
        """Convert basic GitHub metadata to tags."""
        repo_data = {
            "owner": {"login": "torvalds"},
            "private": False,
            "language": "C",
            "stargazers_count": 150000
        }
        tags = github_metadata_to_tags(repo_data)
        assert "org:torvalds" in tags
        assert "visibility:public" in tags
        assert "language:c" in tags
        assert "stars:1000+" in tags

    def test_private_repo(self):
        """Private repo gets visibility:private tag."""
        repo_data = {"private": True}
        tags = github_metadata_to_tags(repo_data)
        assert "visibility:private" in tags

    def test_fork_and_archived(self):
        """Fork and archived repos get appropriate tags."""
        repo_data = {"fork": True, "archived": True}
        tags = github_metadata_to_tags(repo_data)
        assert "fork:true" in tags
        assert "archived:true" in tags

    def test_license_tag(self):
        """License info creates license tag."""
        repo_data = {"license": {"key": "mit"}}
        tags = github_metadata_to_tags(repo_data)
        assert "license:mit" in tags

    def test_topics_tags(self):
        """GitHub topics become topic tags."""
        repo_data = {"topics": ["machine-learning", "python", "deep-learning"]}
        tags = github_metadata_to_tags(repo_data)
        assert "topic:machine-learning" in tags
        assert "topic:python" in tags
        assert "topic:deep-learning" in tags

    def test_has_features_tags(self):
        """Feature flags become has: tags."""
        repo_data = {
            "has_issues": True,
            "has_wiki": True,
            "has_pages": True
        }
        tags = github_metadata_to_tags(repo_data)
        assert "has:issues" in tags
        assert "has:wiki" in tags
        assert "has:pages" in tags

    def test_star_buckets(self):
        """Stars are bucketed correctly."""
        # 0 stars
        tags = github_metadata_to_tags({"stargazers_count": 0})
        assert "stars:0" in tags

        # 1-9 stars
        tags = github_metadata_to_tags({"stargazers_count": 5})
        assert "stars:1+" in tags

        # 10-99 stars
        tags = github_metadata_to_tags({"stargazers_count": 50})
        assert "stars:10+" in tags

        # 100-999 stars
        tags = github_metadata_to_tags({"stargazers_count": 500})
        assert "stars:100+" in tags

        # 1000+ stars
        tags = github_metadata_to_tags({"stargazers_count": 5000})
        assert "stars:1000+" in tags

    def test_owner_string_format(self):
        """Owner can be a string instead of dict."""
        repo_data = {"owner": "torvalds"}
        tags = github_metadata_to_tags(repo_data)
        # When owner is a string, it should handle gracefully
        # The current implementation expects dict, but should not crash
        assert isinstance(tags, list)

    def test_empty_metadata(self):
        """Empty metadata returns empty tags."""
        tags = github_metadata_to_tags({})
        assert tags == []


class TestAutoDetectTags:
    """Tests for auto_detect_tags function using pyfakefs."""

    @pytest.fixture
    def fake_repo(self, fs):
        """Create a fake repository structure."""
        repo_path = "/fake/repo"
        fs.create_dir(repo_path)
        return repo_path

    def test_detect_python_language(self, fs, fake_repo):
        """Detect Python language from .py files."""
        fs.create_file(f"{fake_repo}/main.py", contents="print('hello')")
        tags = auto_detect_tags(fake_repo)
        assert "lang:python" in tags

    def test_detect_javascript_language(self, fs, fake_repo):
        """Detect JavaScript language from .js files."""
        fs.create_file(f"{fake_repo}/app.js", contents="console.log('hello')")
        tags = auto_detect_tags(fake_repo)
        assert "lang:javascript" in tags

    def test_detect_multiple_languages(self, fs, fake_repo):
        """Detect multiple languages."""
        fs.create_file(f"{fake_repo}/main.py", contents="")
        fs.create_file(f"{fake_repo}/app.js", contents="")
        fs.create_file(f"{fake_repo}/lib.go", contents="")
        tags = auto_detect_tags(fake_repo)
        assert "lang:python" in tags
        assert "lang:javascript" in tags
        assert "lang:go" in tags

    def test_detect_python_project_type(self, fs, fake_repo):
        """Detect Python project type from pyproject.toml."""
        fs.create_file(f"{fake_repo}/pyproject.toml", contents="[project]")
        tags = auto_detect_tags(fake_repo)
        assert "type:python" in tags

    def test_detect_node_project_type(self, fs, fake_repo):
        """Detect Node project type from package.json."""
        fs.create_file(f"{fake_repo}/package.json", contents="{}")
        tags = auto_detect_tags(fake_repo)
        assert "type:node" in tags

    def test_detect_rust_project_type(self, fs, fake_repo):
        """Detect Rust project type from Cargo.toml."""
        fs.create_file(f"{fake_repo}/Cargo.toml", contents="")
        tags = auto_detect_tags(fake_repo)
        assert "type:rust" in tags

    def test_detect_go_project_type(self, fs, fake_repo):
        """Detect Go project type from go.mod."""
        fs.create_file(f"{fake_repo}/go.mod", contents="")
        tags = auto_detect_tags(fake_repo)
        assert "type:go" in tags

    def test_detect_java_project_type(self, fs, fake_repo):
        """Detect Java project type from pom.xml."""
        fs.create_file(f"{fake_repo}/pom.xml", contents="")
        tags = auto_detect_tags(fake_repo)
        assert "type:java" in tags

    def test_detect_readme(self, fs, fake_repo):
        """Detect readme file."""
        fs.create_file(f"{fake_repo}/README.md", contents="# Project")
        tags = auto_detect_tags(fake_repo)
        assert "has:readme" in tags

    def test_detect_docs_directory(self, fs, fake_repo):
        """Detect docs directory."""
        fs.create_dir(f"{fake_repo}/docs")
        tags = auto_detect_tags(fake_repo)
        assert "has:docs" in tags

    def test_detect_tests_directory(self, fs, fake_repo):
        """Detect tests directory."""
        fs.create_dir(f"{fake_repo}/tests")
        tags = auto_detect_tags(fake_repo)
        assert "has:tests" in tags

    def test_detect_github_actions(self, fs, fake_repo):
        """Detect GitHub Actions CI."""
        fs.create_dir(f"{fake_repo}/.github/workflows")
        tags = auto_detect_tags(fake_repo)
        assert "ci:github-actions" in tags

    def test_detect_travis_ci(self, fs, fake_repo):
        """Detect Travis CI."""
        fs.create_file(f"{fake_repo}/.travis.yml", contents="")
        tags = auto_detect_tags(fake_repo)
        assert "ci:travis" in tags

    def test_detect_dockerfile(self, fs, fake_repo):
        """Detect Dockerfile."""
        fs.create_file(f"{fake_repo}/Dockerfile", contents="FROM python:3.9")
        tags = auto_detect_tags(fake_repo)
        assert "has:dockerfile" in tags

    def test_detect_docker_compose(self, fs, fake_repo):
        """Detect docker-compose.yml."""
        fs.create_file(f"{fake_repo}/docker-compose.yml", contents="")
        tags = auto_detect_tags(fake_repo)
        assert "has:docker-compose" in tags

    def test_detect_nested_language_files(self, fs, fake_repo):
        """Detect language files in nested directories."""
        fs.create_file(f"{fake_repo}/src/app/main.py", contents="")
        tags = auto_detect_tags(fake_repo)
        assert "lang:python" in tags

    def test_empty_repo(self, fs, fake_repo):
        """Empty repo returns empty tags."""
        tags = auto_detect_tags(fake_repo)
        assert tags == []


class TestTagRoundTrip:
    """Integration tests for tag parsing/formatting round trips."""

    def test_simple_tag_round_trip(self):
        """Simple tag survives parse/format round trip."""
        original = "deprecated"
        key, value = parse_tag(original)
        result = format_tag(key, value)
        assert result == original

    def test_key_value_tag_round_trip(self):
        """Key:value tag survives parse/format round trip."""
        original = "org:torvalds"
        key, value = parse_tag(original)
        result = format_tag(key, value)
        assert result == original

    def test_tags_list_round_trip(self):
        """Tag list survives parse_tags/format_tags round trip."""
        original = ["org:torvalds", "deprecated", "lang:python"]
        tag_dict = parse_tags(original)
        result = format_tags(tag_dict)
        assert set(result) == set(original)

    def test_hierarchical_tag_round_trip(self):
        """Hierarchical tag survives parse/match operations."""
        tag = "topic:scientific/engineering/ai"
        key, levels = parse_hierarchical_tag(tag)
        assert match_hierarchical_tag(tag, f"{key}:{'/'.join(levels)}") is True


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_tag_with_unicode(self):
        """Tags with unicode characters."""
        key, value = parse_tag("emoji:🚀")
        assert key == "emoji"
        assert value == "🚀"

    def test_tag_with_spaces_in_value(self):
        """Tags with spaces in value (though not recommended)."""
        key, value = parse_tag("title:Hello World")
        assert key == "title"
        assert value == "Hello World"

    def test_filter_with_multiple_wildcards(self):
        """Filter pattern with multiple wildcards."""
        tags = ["org:torvalds", "org:linus", "lang:python"]
        result = filter_tags(tags, "*:*")
        # All tags with : should match
        assert set(result) == {"org:torvalds", "org:linus", "lang:python"}

    def test_very_long_tag(self):
        """Very long tag handling."""
        long_value = "a" * 1000
        tag = f"long:{long_value}"
        key, value = parse_tag(tag)
        assert key == "long"
        assert value == long_value

    def test_special_regex_chars_in_filter(self):
        """Special regex characters in filter pattern."""
        tags = ["version:1.2.3", "version:2.0.0"]
        # The . in the pattern should be treated as literal when not part of *
        result = filter_tags(tags, "version:1.2.*")
        assert result == ["version:1.2.3"]
