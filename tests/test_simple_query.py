"""Tests for query.py module."""

import pytest
from repoindex.query import Query, query_repositories


class TestQuery:
    """Test the Query class."""
    
    @pytest.fixture
    def sample_repo(self):
        """Sample repository data for testing."""
        return {
            "name": "test-repo",
            "path": "/home/user/repos/test-repo",
            "language": "Python",
            "languages": {
                "Python": {"files": 10, "bytes": 5000},
                "JavaScript": {"files": 2, "bytes": 1000}
            },
            "owner": "testuser",
            "stars": 42,
            "private": False,
            "topics": ["testing", "python", "cli"],
            "tags": ["lang:python", "type:library", "status:active"],
            "license": {
                "key": "mit",
                "name": "MIT License"
            },
            "has_issues": True,
            "archived": False
        }
    
    def test_exact_match(self, sample_repo):
        """Test exact match operator ==."""
        # String match (case insensitive)
        query = Query("language == 'Python'")
        assert query.evaluate(sample_repo)
        
        query = Query("language == 'python'")
        assert query.evaluate(sample_repo)
        
        query = Query("language == 'JavaScript'")
        assert not query.evaluate(sample_repo)
        
        # Number match
        query = Query("stars == 42")
        assert query.evaluate(sample_repo)
        
        query = Query("stars == 100")
        assert not query.evaluate(sample_repo)
        
        # Boolean match
        query = Query("private == false")
        assert query.evaluate(sample_repo)
        
        query = Query("private == true")
        assert not query.evaluate(sample_repo)
    
    def test_not_equal(self, sample_repo):
        """Test not equal operator !=."""
        query = Query("language != 'Ruby'")
        assert query.evaluate(sample_repo)
        
        query = Query("language != 'Python'")
        assert not query.evaluate(sample_repo)
    
    def test_fuzzy_match(self, sample_repo):
        """Test fuzzy match operator ~=."""
        # Typo tolerance
        query = Query("language ~= 'Pyton'")
        assert query.evaluate(sample_repo)
        
        query = Query("language ~= 'Pythoon'")
        assert query.evaluate(sample_repo)
        
        query = Query("language ~= 'Ruby'")
        assert not query.evaluate(sample_repo)
    
    def test_regex_match(self, sample_repo):
        """Test regex match operator =~."""
        query = Query("language =~ '^Py.*'")
        assert query.evaluate(sample_repo)
        
        query = Query("language =~ 'thon$'")
        assert query.evaluate(sample_repo)
        
        query = Query("language =~ '^Java'")
        assert not query.evaluate(sample_repo)
        
        # Invalid regex should return False
        query = Query("language =~ '[invalid'")
        assert not query.evaluate(sample_repo)
    
    def test_comparison_operators(self, sample_repo):
        """Test comparison operators >, <, >=, <=."""
        query = Query("stars > 40")
        assert query.evaluate(sample_repo)
        
        query = Query("stars > 50")
        assert not query.evaluate(sample_repo)
        
        query = Query("stars < 50")
        assert query.evaluate(sample_repo)
        
        query = Query("stars >= 42")
        assert query.evaluate(sample_repo)
        
        query = Query("stars <= 42")
        assert query.evaluate(sample_repo)
    
    def test_contains_operator(self, sample_repo):
        """Test contains operator."""
        query = Query("topics contains 'python'")
        assert query.evaluate(sample_repo)
        
        query = Query("topics contains 'ruby'")
        assert not query.evaluate(sample_repo)
        
        # Fuzzy contains
        query = Query("topics contains 'pythn'")
        assert query.evaluate(sample_repo, threshold=80)
    
    def test_in_operator(self, sample_repo):
        """Test in operator."""
        query = Query("'python' in topics")
        assert query.evaluate(sample_repo)
        
        query = Query("'lang:python' in tags")
        assert query.evaluate(sample_repo)
        
        query = Query("'ruby' in topics")
        assert not query.evaluate(sample_repo)
    
    def test_boolean_operators(self, sample_repo):
        """Test boolean operators and, or, not."""
        # AND
        query = Query("language == 'Python' and stars > 40")
        assert query.evaluate(sample_repo)
        
        query = Query("language == 'Python' and stars > 50")
        assert not query.evaluate(sample_repo)
        
        # OR
        query = Query("language == 'Python' or language == 'Ruby'")
        assert query.evaluate(sample_repo)
        
        query = Query("language == 'JavaScript' or language == 'Ruby'")
        assert not query.evaluate(sample_repo)
        
        # NOT
        query = Query("not private")
        assert query.evaluate(sample_repo)
        
        query = Query("not archived")
        assert query.evaluate(sample_repo)
        
        query = Query("not has_issues")
        assert not query.evaluate(sample_repo)
    
    def test_nested_fields(self, sample_repo):
        """Test dot notation for nested fields."""
        query = Query("license.key == 'mit'")
        assert query.evaluate(sample_repo)
        
        query = Query("license.name == 'MIT License'")
        assert query.evaluate(sample_repo)
        
        query = Query("license.key == 'gpl'")
        assert not query.evaluate(sample_repo)
    
    def test_simple_text_search(self, sample_repo):
        """Test simple text search without operators."""
        query = Query("python")
        assert query.evaluate(sample_repo)
        
        query = Query("test")
        assert query.evaluate(sample_repo)
        
        query = Query("nonexistent")
        assert not query.evaluate(sample_repo)
    
    def test_fuzzy_field_names(self, sample_repo):
        """Test fuzzy matching on field names."""
        # Typo in field name should still work
        query = Query("languge == 'Python'")  # typo: languge
        assert query.evaluate(sample_repo)
        
        query = Query("ownr == 'testuser'")  # typo: ownr
        assert query.evaluate(sample_repo)
    
    def test_complex_queries(self, sample_repo):
        """Test complex queries with multiple conditions."""
        query = Query("(language == 'Python' or language == 'JavaScript') and stars > 30")
        assert query.evaluate(sample_repo)
        
        query = Query("not private and 'python' in topics and stars >= 42")
        assert query.evaluate(sample_repo)
        
        query = Query("license.key == 'mit' and language ~= 'Pyton'")
        assert query.evaluate(sample_repo)
    
    def test_type_conversions(self, sample_repo):
        """Test automatic type conversions."""
        # None/null
        sample_repo["description"] = None
        query = Query("description == null")
        assert query.evaluate(sample_repo)
        
        query = Query("description == none")
        assert query.evaluate(sample_repo)
        
        # List parsing
        query = Query("topics == ['testing', 'python', 'cli']")
        assert query.evaluate(sample_repo)
    
    def test_quoted_strings_with_operators(self, sample_repo):
        """Test handling of quoted strings containing operators."""
        sample_repo["description"] = "A project with 'and' in the name"
        query = Query("description contains 'with \\'and\\' in'")
        assert query.evaluate(sample_repo)
    
    def test_invalid_queries(self):
        """Test that invalid queries raise ValueError."""
        # Empty query
        with pytest.raises(ValueError):
            Query("")
        
        # Invalid operator placement
        with pytest.raises(ValueError):
            Query("== 'value'")


class TestQueryRepositories:
    """Test the query_repositories function."""
    
    def test_query_multiple_repos(self):
        """Test querying multiple repositories."""
        repos = [
            {"name": "repo1", "language": "Python", "stars": 10},
            {"name": "repo2", "language": "JavaScript", "stars": 20},
            {"name": "repo3", "language": "Python", "stars": 30},
            {"name": "repo4", "language": "Ruby", "stars": 40}
        ]
        
        # Filter by language
        result = query_repositories(repos, "language == 'Python'")
        assert len(result) == 2
        assert all(r["language"] == "Python" for r in result)
        
        # Filter by stars
        result = query_repositories(repos, "stars > 15")
        assert len(result) == 3
        assert all(r["stars"] > 15 for r in result)
        
        # Complex query
        result = query_repositories(repos, "language == 'Python' and stars > 15")
        assert len(result) == 1
        assert result[0]["name"] == "repo3"
    
    def test_empty_query(self):
        """Test that empty query returns all repos."""
        repos = [
            {"name": "repo1"},
            {"name": "repo2"}
        ]
        
        result = query_repositories(repos, "")
        assert len(result) == 2
        assert result == repos
    
    def test_custom_threshold(self):
        """Test custom fuzzy matching threshold."""
        repos = [
            {"name": "python-project", "language": "Python"},
            {"name": "java-project", "language": "Java"}
        ]
        
        # Low threshold - more permissive
        result = query_repositories(repos, "language ~= 'Pyton'", threshold=60)
        assert len(result) == 1
        
        # High threshold - more strict
        result = query_repositories(repos, "language ~= 'Pyton'", threshold=95)
        assert len(result) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])