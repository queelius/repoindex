"""Tests for gitignore.py module."""

import os
import tempfile
from pathlib import Path
from unittest import TestCase
from repoindex.gitignore import generate_gitignore_content, _get_language_patterns, _detect_project_structure_patterns


class TestGitignoreGeneration(TestCase):
    """Test .gitignore generation functionality."""
    
    def setUp(self):
        """Create a temporary directory for test repos."""
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test directory."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def create_test_repo(self, files_list):
        """Create a test repository with specified files.
        
        Args:
            files_list: List of file paths to create
        """
        repo_dir = os.path.join(self.test_dir, 'test_repo')
        os.makedirs(repo_dir, exist_ok=True)
        
        for filepath in files_list:
            full_path = os.path.join(repo_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(f"# {filepath}")
        
        return repo_dir
    
    def test_basic_gitignore_generation(self):
        """Test basic .gitignore generation with no languages."""
        content = generate_gitignore_content({})
        
        # Should always include common patterns
        self.assertIn('.DS_Store', content)
        self.assertIn('.vscode/', content)
        self.assertIn('*.log', content)
        self.assertIn('.env', content)
    
    def test_python_language_patterns(self):
        """Test Python-specific patterns are included."""
        languages = {'Python': {'files': 5, 'bytes': 1000}}
        content = generate_gitignore_content(languages)
        
        # Should include Python-specific patterns
        self.assertIn('__pycache__/', content)
        self.assertIn('*.py[cod]', content)
        self.assertIn('.pytest_cache/', content)
        self.assertIn('venv/', content)
        self.assertIn('*.egg-info/', content)
    
    def test_javascript_language_patterns(self):
        """Test JavaScript-specific patterns are included."""
        languages = {'JavaScript': {'files': 3, 'bytes': 500}}
        content = generate_gitignore_content(languages)
        
        # Should include JavaScript-specific patterns
        self.assertIn('node_modules/', content)
        self.assertIn('npm-debug.log*', content)
        self.assertIn('.npm', content)
        self.assertIn('*.tsbuildinfo', content)
    
    def test_multiple_languages(self):
        """Test .gitignore generation with multiple languages."""
        languages = {
            'Python': {'files': 5, 'bytes': 1000},
            'JavaScript': {'files': 3, 'bytes': 500},
            'Java': {'files': 2, 'bytes': 800}
        }
        content = generate_gitignore_content(languages)
        
        # Should include patterns from all languages
        self.assertIn('__pycache__/', content)  # Python
        self.assertIn('node_modules/', content)  # JavaScript
        self.assertIn('*.class', content)       # Java
        self.assertIn('target/', content)       # Java (Maven)
    
    def test_project_structure_detection(self):
        """Test detection of project structure patterns."""
        repo_dir = self.create_test_repo([
            'Dockerfile',
            'docker-compose.yml',
            'Makefile',
            'docs/index.md',
            'main.tf'
        ])
        
        patterns = _detect_project_structure_patterns(repo_dir)
        
        # Should detect Docker, Make, docs, and Terraform patterns
        self.assertIn('.dockerignore', patterns)
        self.assertIn('docker-compose.override.yml', patterns)
        self.assertIn('*.o', patterns)  # Make
        self.assertIn('docs/_build/', patterns)  # Docs
        self.assertIn('*.tfstate', patterns)  # Terraform
        self.assertIn('.terraform/', patterns)  # Terraform
    
    def test_gitignore_with_project_structure(self):
        """Test .gitignore generation includes project structure patterns."""
        repo_dir = self.create_test_repo(['package.json', 'Dockerfile'])
        
        languages = {'JavaScript': {'files': 1, 'bytes': 100}}
        content = generate_gitignore_content(languages, repo_dir)
        
        # Should include both language and project structure patterns
        self.assertIn('node_modules/', content)     # JavaScript
        self.assertIn('.dockerignore', content)     # Docker
    
    def test_get_language_patterns(self):
        """Test getting patterns for individual languages."""
        # Test Python patterns
        python_patterns = _get_language_patterns('Python')
        self.assertIn('__pycache__/', python_patterns)
        self.assertIn('*.py[cod]', python_patterns)
        
        # Test JavaScript patterns
        js_patterns = _get_language_patterns('JavaScript')
        self.assertIn('node_modules/', js_patterns)
        self.assertIn('npm-debug.log*', js_patterns)
        
        # Test unknown language
        unknown_patterns = _get_language_patterns('UnknownLanguage')
        self.assertEqual(unknown_patterns, [])
    
    def test_c_cpp_patterns(self):
        """Test C and C++ language patterns."""
        c_patterns = _get_language_patterns('C')
        self.assertIn('*.o', c_patterns)
        self.assertIn('*.so', c_patterns)
        self.assertIn('*.exe', c_patterns)
        
        cpp_patterns = _get_language_patterns('C++')
        self.assertIn('*.slo', cpp_patterns)
        self.assertIn('*.lo', cpp_patterns)
        self.assertIn('*.dylib', cpp_patterns)
    
    def test_rust_patterns(self):
        """Test Rust language patterns."""
        rust_patterns = _get_language_patterns('Rust')
        self.assertIn('/target/', rust_patterns)
        self.assertIn('Cargo.lock', rust_patterns)
        self.assertIn('**/*.rs.bk', rust_patterns)
    
    def test_go_patterns(self):
        """Test Go language patterns."""
        go_patterns = _get_language_patterns('Go')
        self.assertIn('*.exe', go_patterns)
        self.assertIn('*.test', go_patterns)
        self.assertIn('vendor/', go_patterns)
        self.assertIn('go.work', go_patterns)
    
    def test_java_patterns(self):
        """Test Java language patterns."""
        java_patterns = _get_language_patterns('Java')
        self.assertIn('*.class', java_patterns)
        self.assertIn('target/', java_patterns)  # Maven
        self.assertIn('.gradle', java_patterns)  # Gradle
        self.assertIn('*.jar', java_patterns)
    
    def test_ruby_patterns(self):
        """Test Ruby language patterns."""
        ruby_patterns = _get_language_patterns('Ruby')
        self.assertIn('*.gem', ruby_patterns)
        self.assertIn('.bundle/', ruby_patterns)
        self.assertIn('Gemfile.lock', ruby_patterns)
        self.assertIn('vendor/bundle/', ruby_patterns)
    
    def test_php_patterns(self):
        """Test PHP language patterns."""
        php_patterns = _get_language_patterns('PHP')
        self.assertIn('/vendor/', php_patterns)
        self.assertIn('composer.lock', php_patterns)
        self.assertIn('composer.phar', php_patterns)
    
    def test_swift_patterns(self):
        """Test Swift language patterns."""
        swift_patterns = _get_language_patterns('Swift')
        self.assertIn('xcuserdata/', swift_patterns)
        self.assertIn('*.xcworkspace', swift_patterns)
        self.assertIn('Pods/', swift_patterns)
        self.assertIn('Carthage/Build/', swift_patterns)
    
    def test_csharp_patterns(self):
        """Test C# language patterns."""
        csharp_patterns = _get_language_patterns('C#')
        self.assertIn('[Bb]in/', csharp_patterns)
        self.assertIn('[Oo]bj/', csharp_patterns)
        self.assertIn('*.suo', csharp_patterns)
        self.assertIn('*.pdb', csharp_patterns)
    
    def test_content_structure(self):
        """Test that generated content has proper structure."""
        languages = {'Python': {'files': 1, 'bytes': 100}}
        content = generate_gitignore_content(languages)
        
        # Should have proper sections
        self.assertIn('# OS generated files', content)
        self.assertIn('# Editor files', content)
        self.assertIn('# Language-specific files', content)
        
        # Should end with newline
        self.assertTrue(content.endswith('\n'))
    
    def test_empty_repo_path(self):
        """Test generation with None repo_path."""
        languages = {'Python': {'files': 1, 'bytes': 100}}
        content = generate_gitignore_content(languages, None)
        
        # Should still work without project structure detection
        self.assertIn('__pycache__/', content)
        self.assertIn('.DS_Store', content)
    
    def test_nonexistent_repo_path(self):
        """Test generation with nonexistent repo_path."""
        languages = {'JavaScript': {'files': 1, 'bytes': 100}}
        content = generate_gitignore_content(languages, '/nonexistent/path')
        
        # Should still work, just skip project structure detection
        self.assertIn('node_modules/', content)
        self.assertIn('.DS_Store', content)


if __name__ == '__main__':
    import unittest
    unittest.main()