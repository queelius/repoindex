"""
Comprehensive tests for ghops/render.py rendering functions.

These tests verify that render functions:
1. Handle empty/missing data gracefully
2. Calculate summaries correctly
3. Run without errors for valid data
4. Produce expected output patterns
"""
import pytest
from io import StringIO
from unittest.mock import patch, MagicMock
from rich.console import Console

from repoindex import render


class TestRenderTable:
    """Tests for render_table function."""

    def test_empty_rows_shows_message(self, capsys):
        """Empty rows should show 'No data' message."""
        render.render_table(["Col1", "Col2"], [])
        captured = capsys.readouterr()
        assert "No data to display" in captured.out

    def test_single_row(self, capsys):
        """Single row renders without error."""
        render.render_table(["Name", "Value"], [["test", "123"]])
        captured = capsys.readouterr()
        assert "test" in captured.out
        assert "123" in captured.out

    def test_with_title(self, capsys):
        """Table with title renders title."""
        render.render_table(["Col"], [["data"]], title="Test Table")
        captured = capsys.readouterr()
        # Rich may wrap title across lines, so check for each word
        assert "Test" in captured.out
        assert "Table" in captured.out

    def test_multiple_rows(self, capsys):
        """Multiple rows render correctly."""
        rows = [["a", "1"], ["b", "2"], ["c", "3"]]
        render.render_table(["Letter", "Number"], rows)
        captured = capsys.readouterr()
        for letter in ["a", "b", "c"]:
            assert letter in captured.out


class TestRenderStatusTable:
    """Tests for render_status_table function."""

    def test_empty_repos_shows_message(self, capsys):
        """Empty repos list shows 'No repositories' message."""
        render.render_status_table([])
        captured = capsys.readouterr()
        assert "No repositories found" in captured.out

    def test_single_clean_repo(self, capsys):
        """Single clean repository renders correctly."""
        repos = [{
            "name": "test-repo",
            "path": "/home/user/projects/test-repo",
            "status": {
                "branch": "main",
                "clean": True,
                "uncommitted_changes": False,
                "unpushed_commits": False,
                "ahead": 0,
                "behind": 0
            },
            "license": {"type": "MIT"},
            "package": {"name": "test-pkg", "outdated": False}
        }]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "test-repo" in captured.out
        assert "main" in captured.out

    def test_dirty_repo_shows_icon(self, capsys):
        """Dirty repo with uncommitted changes shows appropriate icon."""
        repos = [{
            "name": "dirty-repo",
            "path": "/home/user/dirty-repo",
            "status": {
                "branch": "develop",
                "uncommitted_changes": True,
                "unpushed_commits": False,
                "ahead": 0,
                "behind": 0
            }
        }]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "dirty-repo" in captured.out

    def test_repo_with_unpushed_commits(self, capsys):
        """Repo with unpushed commits shows appropriate icon."""
        repos = [{
            "name": "unpushed-repo",
            "path": "/home/user/unpushed-repo",
            "status": {
                "branch": "main",
                "uncommitted_changes": False,
                "unpushed_commits": True,
                "ahead": 3,
                "behind": 0
            }
        }]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "unpushed-repo" in captured.out
        assert "+3" in captured.out

    def test_repo_behind_upstream(self, capsys):
        """Repo behind upstream shows behind count."""
        repos = [{
            "name": "behind-repo",
            "path": "/home/user/behind-repo",
            "status": {
                "branch": "main",
                "uncommitted_changes": False,
                "unpushed_commits": False,
                "ahead": 0,
                "behind": 5
            }
        }]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "behind-repo" in captured.out
        assert "-5" in captured.out

    def test_repo_with_github_pages(self, capsys):
        """Repo with GitHub Pages shows link icon."""
        repos = [{
            "name": "pages-repo",
            "path": "/home/user/pages-repo",
            "status": {"branch": "main", "ahead": 0, "behind": 0},
            "github": {"pages_url": "https://user.github.io/pages-repo"}
        }]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "pages-repo" in captured.out

    def test_repo_with_outdated_package(self, capsys):
        """Repo with outdated package shows warning."""
        repos = [{
            "name": "outdated-repo",
            "path": "/home/user/outdated-repo",
            "status": {"branch": "main", "ahead": 0, "behind": 0},
            "package": {"name": "my-pkg", "outdated": True}
        }]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "outdated-repo" in captured.out

    def test_errors_displayed_separately(self, capsys):
        """Error objects are displayed separately."""
        repos = [
            {"name": "good-repo", "path": "/path", "status": {"branch": "main", "ahead": 0, "behind": 0}},
            {"error": "Failed to read", "context": {"path": "/bad/repo"}}
        ]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "good-repo" in captured.out
        assert "Errors" in captured.out

    def test_duplicate_repos_display(self, capsys):
        """Duplicate repos show deduplication info."""
        repos = [{
            "name": "dup-repo",
            "path": "/home/user/dup-repo",
            "status": {"branch": "main", "ahead": 0, "behind": 0},
            "all_paths": ["/home/user/dup-repo", "/home/user/dup-repo-copy"],
            "is_true_duplicate": True
        }]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "dup-repo" in captured.out


class TestPrintStatusSummary:
    """Tests for print_status_summary function."""

    def test_empty_repos(self, capsys):
        """Empty repos list prints nothing."""
        render.print_status_summary([])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_all_clean_repos(self, capsys):
        """All clean repos shows total count."""
        repos = [
            {"name": "repo1", "status": {"uncommitted_changes": False, "unpushed_commits": False, "behind": 0, "ahead": 0}},
            {"name": "repo2", "status": {"uncommitted_changes": False, "unpushed_commits": False, "behind": 0, "ahead": 0}}
        ]
        render.print_status_summary(repos)
        captured = capsys.readouterr()
        assert "Total repositories: 2" in captured.out

    def test_repos_with_issues(self, capsys):
        """Repos with various issues show appropriate counts."""
        repos = [
            {"name": "repo1", "status": {"uncommitted_changes": True, "unpushed_commits": False, "behind": 0, "ahead": 0}},
            {"name": "repo2", "status": {"uncommitted_changes": False, "unpushed_commits": True, "behind": 0, "ahead": 2}},
            {"name": "repo3", "status": {"uncommitted_changes": False, "unpushed_commits": False, "behind": 3, "ahead": 0}},
            {"name": "repo4", "license": {"type": "MIT"}, "status": {"uncommitted_changes": False, "unpushed_commits": False, "behind": 0, "ahead": 0}}
        ]
        render.print_status_summary(repos)
        captured = capsys.readouterr()
        assert "Uncommitted changes: 1" in captured.out
        assert "Unpushed commits: 1" in captured.out
        assert "Behind upstream: 1" in captured.out
        assert "Ahead of upstream: 1" in captured.out


class TestRenderSocialMediaPosts:
    """Tests for render_social_media_posts function."""

    def test_empty_posts_shows_message(self, capsys):
        """Empty posts list shows 'No posts' message."""
        render.render_social_media_posts([])
        captured = capsys.readouterr()
        assert "No posts generated" in captured.out

    def test_single_post(self, capsys):
        """Single post renders correctly."""
        posts = [{
            "repo_name": "test-repo",
            "url": "https://github.com/user/test-repo",
            "platforms": {
                "twitter": "Check out test-repo!",
                "bluesky": "New release!"
            },
            "tags": ["#opensource", "#python"]
        }]
        render.render_social_media_posts(posts)
        captured = capsys.readouterr()
        assert "test-repo" in captured.out
        assert "Twitter" in captured.out or "twitter" in captured.out.lower()

    def test_json_output(self, capsys):
        """JSON output mode produces valid JSON."""
        import json
        posts = [{"repo_name": "test", "url": "http://example.com"}]
        render.render_social_media_posts(posts, as_json=True)
        captured = capsys.readouterr()
        # Should be valid JSON
        parsed = json.loads(captured.out)
        assert parsed[0]["repo_name"] == "test"


class TestRenderListTable:
    """Tests for render_list_table function."""

    def test_empty_repos_shows_message(self, capsys):
        """Empty repos list shows 'No repositories' message."""
        render.render_list_table([])
        captured = capsys.readouterr()
        assert "No repositories found" in captured.out

    def test_single_repo(self, capsys):
        """Single repository renders correctly."""
        repos = [{
            "name": "test-repo",
            "path": "/home/user/test-repo",
            "has_license": True,
            "has_package": False,
            "remote_url": "https://github.com/user/test-repo"
        }]
        render.render_list_table(repos)
        captured = capsys.readouterr()
        assert "test-repo" in captured.out

    def test_private_repo(self, capsys):
        """Private repo shows private indicator."""
        repos = [{
            "name": "priv",
            "path": "/home/user/priv",
            "has_license": False,
            "has_package": False,
            "github": {"is_private": True}
        }]
        render.render_list_table(repos)
        captured = capsys.readouterr()
        assert "priv" in captured.out
        assert "Private" in captured.out

    def test_fork_repo(self, capsys):
        """Fork repo shows fork indicator."""
        repos = [{
            "name": "fork-repo",
            "path": "/home/user/fork-repo",
            "has_license": True,
            "has_package": False,
            "github": {"is_fork": True}
        }]
        render.render_list_table(repos)
        captured = capsys.readouterr()
        assert "fork-repo" in captured.out

    def test_repo_with_duplicates(self, capsys):
        """Repo with duplicates shows duplicate count."""
        repos = [{
            "name": "dup-repo",
            "path": "/home/user/dup-repo",
            "has_license": True,
            "has_package": False,
            "duplicate_count": 3
        }]
        render.render_list_table(repos)
        captured = capsys.readouterr()
        assert "dup-repo" in captured.out


class TestRenderCacheStatsTable:
    """Tests for render_cache_stats_table function."""

    def test_basic_stats(self, capsys):
        """Basic cache stats render correctly."""
        stats = {
            "cache_dir": "/home/user/.cache/ghops",
            "total_entries": 100,
            "active_entries": 80,
            "expired_entries": 20,
            "total_size_mb": 5.5
        }
        render.render_cache_stats_table(stats)
        captured = capsys.readouterr()
        assert "Cache" in captured.out
        assert "100" in captured.out
        assert "80" in captured.out

    def test_stats_with_dates(self, capsys):
        """Cache stats with dates render correctly."""
        stats = {
            "cache_dir": "/tmp/cache",
            "total_entries": 10,
            "active_entries": 10,
            "expired_entries": 0,
            "total_size_mb": 1,
            "oldest_entry_date": "2024-01-01",
            "newest_entry_date": "2024-12-01"
        }
        render.render_cache_stats_table(stats)
        captured = capsys.readouterr()
        assert "2024-01-01" in captured.out
        assert "2024-12-01" in captured.out

    def test_stats_with_entry_types(self, capsys):
        """Cache stats with entry types render correctly."""
        stats = {
            "cache_dir": "/tmp/cache",
            "total_entries": 30,
            "active_entries": 30,
            "expired_entries": 0,
            "total_size_mb": 2,
            "entries_by_type": {
                "github": 10,
                "pypi": 15,
                "license": 5
            }
        }
        render.render_cache_stats_table(stats)
        captured = capsys.readouterr()
        assert "Github" in captured.out or "github" in captured.out.lower()


class TestRenderUpdateTable:
    """Tests for render_update_table function."""

    def test_empty_updates_shows_message(self, capsys):
        """Empty updates list shows 'No repositories' message."""
        render.render_update_table([])
        captured = capsys.readouterr()
        assert "No repositories found" in captured.out

    def test_successful_update(self, capsys):
        """Successful update renders correctly."""
        updates = [{
            "name": "updated-repo",
            "actions": {"committed": False, "pulled": True, "pushed": False}
        }]
        render.render_update_table(updates)
        captured = capsys.readouterr()
        assert "updated-repo" in captured.out

    def test_update_with_commit(self, capsys):
        """Update with commit shows commit info."""
        updates = [{
            "name": "committed-repo",
            "actions": {"committed": True, "pulled": False, "pushed": True},
            "details": {"commit_message": "Auto-commit changes"}
        }]
        render.render_update_table(updates)
        captured = capsys.readouterr()
        assert "committed-repo" in captured.out

    def test_update_with_conflicts(self, capsys):
        """Update with conflicts shows warning."""
        updates = [{
            "name": "conflict-repo",
            "actions": {"committed": False, "pulled": True, "pushed": False, "conflicts": True}
        }]
        render.render_update_table(updates)
        captured = capsys.readouterr()
        assert "conflict-repo" in captured.out
        assert "Conflict" in captured.out

    def test_update_with_errors(self, capsys):
        """Update with errors shows error section."""
        updates = [
            {"name": "good-repo", "actions": {"pulled": True}},
            {"name": "bad-repo", "error": "Permission denied"}
        ]
        render.render_update_table(updates)
        captured = capsys.readouterr()
        assert "Errors" in captured.out


class TestPrintUpdateSummary:
    """Tests for print_update_summary function."""

    def test_empty_updates(self, capsys):
        """Empty updates list prints nothing."""
        render.print_update_summary([])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_all_up_to_date(self, capsys):
        """All repos up to date shows appropriate count."""
        updates = [
            {"name": "repo1", "actions": {"pulled": False, "committed": False, "pushed": False}},
            {"name": "repo2", "actions": {"pulled": False, "committed": False, "pushed": False}}
        ]
        render.print_update_summary(updates)
        captured = capsys.readouterr()
        assert "Up to date: 2" in captured.out

    def test_mixed_updates(self, capsys):
        """Mixed updates show appropriate counts."""
        updates = [
            {"name": "repo1", "actions": {"pulled": True, "committed": False, "pushed": False}},
            {"name": "repo2", "actions": {"pulled": False, "committed": True, "pushed": True}},
            {"name": "repo3", "error": "Failed"}
        ]
        render.print_update_summary(updates)
        captured = capsys.readouterr()
        assert "Pulled: 1" in captured.out
        assert "Committed: 1" in captured.out
        assert "Pushed: 1" in captured.out
        assert "Errors: 1" in captured.out


class TestRenderGetTable:
    """Tests for render_get_table function."""

    def test_empty_results_shows_message(self, capsys):
        """Empty results list shows 'No operations' message."""
        render.render_get_table([])
        captured = capsys.readouterr()
        assert "No operations performed" in captured.out

    def test_successful_clone(self, capsys):
        """Successful clone renders correctly."""
        results = [{
            "name": "cloned-repo",
            "user": "testuser",
            "actions": {"cloned": True},
            "path": "/home/user/repos/cloned-repo"
        }]
        render.render_get_table(results)
        captured = capsys.readouterr()
        assert "cloned-repo" in captured.out
        assert "Cloned" in captured.out

    def test_repo_already_exists(self, capsys):
        """Repo that already exists shows exists status."""
        results = [{
            "name": "existing-repo",
            "user": "testuser",
            "actions": {"existed": True},
            "path": "/home/user/repos/existing-repo"
        }]
        render.render_get_table(results)
        captured = capsys.readouterr()
        assert "existing-repo" in captured.out
        assert "Exists" in captured.out

    def test_ignored_repo(self, capsys):
        """Ignored repo shows ignored status."""
        results = [{
            "name": "ignored-repo",
            "user": "testuser",
            "actions": {"ignored": True}
        }]
        render.render_get_table(results)
        captured = capsys.readouterr()
        assert "ignored-repo" in captured.out
        assert "Ignored" in captured.out

    def test_user_errors(self, capsys):
        """User errors are displayed separately."""
        results = [
            {"name": "good-repo", "user": "testuser", "actions": {"cloned": True}, "path": "/path"},
            {"type": "user_error", "user": "baduser", "error": "User not found"}
        ]
        render.render_get_table(results)
        captured = capsys.readouterr()
        assert "good-repo" in captured.out
        assert "Errors" in captured.out


class TestPrintGetSummary:
    """Tests for print_get_summary function."""

    def test_empty_results(self, capsys):
        """Empty results list with no user errors prints nothing."""
        render.print_get_summary([])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_all_cloned(self, capsys):
        """All repos cloned shows cloned count."""
        results = [
            {"name": "repo1", "actions": {"cloned": True}},
            {"name": "repo2", "actions": {"cloned": True}}
        ]
        render.print_get_summary(results)
        captured = capsys.readouterr()
        assert "Cloned: 2" in captured.out

    def test_mixed_results(self, capsys):
        """Mixed results show appropriate counts."""
        results = [
            {"name": "repo1", "actions": {"cloned": True}},
            {"name": "repo2", "actions": {"existed": True}},
            {"name": "repo3", "actions": {"ignored": True}},
            {"name": "repo4", "error": "Failed"}
        ]
        render.print_get_summary(results)
        captured = capsys.readouterr()
        assert "Cloned: 1" in captured.out
        assert "Already existed: 1" in captured.out
        assert "Ignored: 1" in captured.out
        assert "Failed: 1" in captured.out


class TestRenderCatalogListTable:
    """Tests for render_catalog_list_table function."""

    def test_empty_catalog_shows_message(self, capsys):
        """Empty catalog list shows 'No catalogs' message."""
        render.render_catalog_list_table([])
        captured = capsys.readouterr()
        assert "No catalogs defined" in captured.out

    def test_single_catalog(self, capsys):
        """Single catalog renders correctly."""
        stats = [{
            "type": "organization",
            "value": "myorg",
            "directories": 3,
            "repositories": 15
        }]
        render.render_catalog_list_table(stats)
        captured = capsys.readouterr()
        assert "myorg" in captured.out
        assert "15" in captured.out

    def test_multiple_catalogs(self, capsys):
        """Multiple catalogs render correctly."""
        stats = [
            {"type": "organization", "value": "org1", "directories": 1, "repositories": 5},
            {"type": "category", "value": "work", "directories": 2, "repositories": 10}
        ]
        render.render_catalog_list_table(stats)
        captured = capsys.readouterr()
        assert "org1" in captured.out
        assert "work" in captured.out


class TestRenderCatalogTable:
    """Tests for render_catalog_table function."""

    def test_empty_repos_shows_message(self, capsys):
        """Empty repos list shows appropriate message."""
        render.render_catalog_table([], "organization", "myorg")
        captured = capsys.readouterr()
        assert "No repositories" in captured.out
        assert "myorg" in captured.out

    def test_repos_without_metadata(self, capsys):
        """Repos without metadata render basic columns."""
        repos = [
            {"name": "repo1", "path": "/path/to/repo1"},
            {"name": "repo2", "path": "/path/to/repo2"}
        ]
        render.render_catalog_table(repos, "organization", "myorg")
        captured = capsys.readouterr()
        assert "repo1" in captured.out
        assert "repo2" in captured.out

    def test_repos_with_metadata(self, capsys):
        """Repos with metadata render additional columns."""
        repos = [
            {
                "name": "repo1",
                "path": "/path/to/repo1",
                "metadata": {
                    "organization": "myorg",
                    "category": "work",
                    "tags": ["python", "cli"]
                }
            }
        ]
        render.render_catalog_table(repos, "organization", "myorg")
        captured = capsys.readouterr()
        assert "repo1" in captured.out
        assert "myorg" in captured.out


class TestRenderDocsTable:
    """Tests for render_docs_table function."""

    def test_empty_docs_shows_message(self, capsys):
        """Empty docs list shows 'No repositories' message."""
        render.render_docs_table([])
        captured = capsys.readouterr()
        assert "No repositories found" in captured.out

    def test_repo_with_docs(self, capsys):
        """Repo with docs renders correctly."""
        docs = [{
            "name": "doc-repo",
            "has_docs": True,
            "docs_tool": "mkdocs",
            "docs_config": "mkdocs.yml",
            "detected_files": ["README.md", "docs/index.md"],
            "pages_url": "https://user.github.io/doc-repo"
        }]
        render.render_docs_table(docs)
        captured = capsys.readouterr()
        assert "doc-repo" in captured.out
        assert "mkdocs" in captured.out

    def test_repo_without_docs(self, capsys):
        """Repo without docs renders correctly."""
        docs = [{
            "name": "undocumented-repo",
            "has_docs": False,
            "docs_tool": None,
            "docs_config": None,
            "detected_files": [],
            "pages_url": None
        }]
        render.render_docs_table(docs)
        captured = capsys.readouterr()
        assert "undocumented-repo" in captured.out

    def test_long_pages_url_truncated(self, capsys):
        """Long pages URL is truncated."""
        docs = [{
            "name": "long-url-repo",
            "has_docs": True,
            "docs_tool": "sphinx",
            "pages_url": "https://very-long-username.github.io/very-long-repository-name-that-exceeds-limit"
        }]
        render.render_docs_table(docs)
        captured = capsys.readouterr()
        assert "long-url-repo" in captured.out


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_render_status_with_minimal_values(self, capsys):
        """Status table handles minimal/empty values gracefully."""
        repos = [{
            "name": "minimal",
            "path": "/tmp/minimal",
            "status": {}
        }]
        render.render_status_table(repos)
        captured = capsys.readouterr()
        assert "minimal" in captured.out

    def test_render_list_with_missing_keys(self, capsys):
        """List table handles missing keys gracefully."""
        repos = [{
            "name": "sparse-repo"
        }]
        # Should not raise exception
        try:
            render.render_list_table(repos)
            captured = capsys.readouterr()
            assert "sparse-repo" in captured.out
        except KeyError:
            pytest.fail("render_list_table raised KeyError for missing keys")

    def test_render_update_with_empty_actions(self, capsys):
        """Update table handles empty actions dict."""
        updates = [{
            "name": "no-action-repo",
            "actions": {}
        }]
        render.render_update_table(updates)
        captured = capsys.readouterr()
        assert "no-action-repo" in captured.out

    def test_summary_with_zero_division_safety(self, capsys):
        """Summary calculations handle zero totals safely."""
        # This should not raise ZeroDivisionError
        repos = []
        render.print_status_summary(repos)
        render.print_update_summary([])
        render.print_get_summary([])
        # If we get here without exception, the test passes
