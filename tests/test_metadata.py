"""Tests for metadata.py module."""

import os
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from repoindex.metadata import detect_languages, MetadataStore


class TestLanguageDetection(TestCase):
    """Test language detection functionality."""
    
    def setUp(self):
        """Create a temporary directory for test repos."""
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test directory."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def create_test_repo(self, files_dict):
        """Create a test repository with specified files.
        
        Args:
            files_dict: Dict mapping file paths to contents
        """
        repo_dir = os.path.join(self.test_dir, 'test_repo')
        os.makedirs(repo_dir, exist_ok=True)
        
        for filepath, content in files_dict.items():
            full_path = os.path.join(repo_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            if isinstance(content, bytes):
                with open(full_path, 'wb') as f:
                    f.write(content)
            else:
                with open(full_path, 'w') as f:
                    f.write(content)
        
        return repo_dir
    
    def test_basic_language_detection(self):
        """Test detection of common languages."""
        repo_dir = self.create_test_repo({
            'main.py': 'print("Hello World")',
            'utils.py': 'def helper(): pass',
            'README.md': '# Test Project',
            'index.js': 'console.log("test");',
            'style.css': 'body { color: red; }'
        })
        
        languages = detect_languages(repo_dir)
        
        self.assertIn('Python', languages)
        self.assertEqual(languages['Python']['files'], 2)
        self.assertIn('JavaScript', languages)
        self.assertEqual(languages['JavaScript']['files'], 1)
        self.assertIn('Markdown', languages)
        self.assertEqual(languages['Markdown']['files'], 1)
        self.assertIn('CSS', languages)
        self.assertEqual(languages['CSS']['files'], 1)
    
    def test_shebang_detection(self):
        """Test language detection from shebang lines."""
        repo_dir = self.create_test_repo({
            'script': '#!/usr/bin/env python3\nprint("Hello")',
            'deploy': '#!/bin/bash\necho "Deploying"',
            'tool': '#!/usr/bin/env node\nconsole.log("Tool");'
        })
        
        languages = detect_languages(repo_dir)
        
        self.assertIn('Python', languages)
        self.assertEqual(languages['Python']['files'], 1)
        self.assertIn('Shell', languages)
        self.assertEqual(languages['Shell']['files'], 1)
        self.assertIn('JavaScript', languages)
        self.assertEqual(languages['JavaScript']['files'], 1)
    
    def test_skip_hidden_directories(self):
        """Test that hidden directories are skipped by default."""
        repo_dir = self.create_test_repo({
            'main.py': 'print("visible")',
            '.hidden/secret.py': 'print("hidden")',
            '.git/config': '[core]\nrepositoryformatversion = 0',
            'normal/test.py': 'print("normal")'
        })
        
        languages = detect_languages(repo_dir)
        
        self.assertIn('Python', languages)
        # Should only count main.py and normal/test.py, not .hidden/secret.py
        self.assertEqual(languages['Python']['files'], 2)
        # Git config should not be counted
        self.assertNotIn('Git', languages)
    
    def test_skip_vendor_directories(self):
        """Test that vendor directories are skipped."""
        repo_dir = self.create_test_repo({
            'app.py': 'print("app")',
            'node_modules/lib/index.js': 'module.exports = {}',
            'venv/lib/python3.9/site.py': 'import sys',
            '.venv/lib/python3.9/os.py': 'import os',
            'vendor/package/code.py': 'vendor_code',
            'src/main.py': 'print("main")'
        })
        
        languages = detect_languages(repo_dir)
        
        # Should only count app.py and src/main.py
        self.assertEqual(languages['Python']['files'], 2)
        # No JavaScript from node_modules
        self.assertNotIn('JavaScript', languages)
    
    def test_custom_skip_patterns(self):
        """Test custom skip patterns from config."""
        repo_dir = self.create_test_repo({
            'main.py': 'print("main")',
            'custom_skip/test.py': 'print("skip me")',
            'dist/bundle.js': 'minified code',
            'app.min.js': 'minified',
            'app.js': 'console.log("normal");',
            'styles.min.css': 'body{color:red}',
            'styles.css': 'body { color: red; }'
        })
        
        # Test with custom config
        config = {
            'language_detection': {
                'skip_directories': ['custom_skip', 'dist'],
                'skip_hidden_directories': True,
                'skip_file_extensions': ['.min.js', '.min.css'],
                'max_file_size_kb': 1024
            }
        }
        
        languages = detect_languages(repo_dir, config)
        
        # Should only count main.py
        self.assertEqual(languages['Python']['files'], 1)
        # Should count app.js but not app.min.js or dist/bundle.js
        self.assertEqual(languages['JavaScript']['files'], 1)
        # Should count styles.css but not styles.min.css
        self.assertEqual(languages['CSS']['files'], 1)
    
    def test_file_size_limit(self):
        """Test that large files are skipped."""
        repo_dir = self.create_test_repo({
            'small.py': 'print("small")',
            'large.py': 'x = 1\n' * 100000  # Create a large file
        })
        
        # Test with 10KB limit
        config = {
            'language_detection': {
                'skip_directories': [],
                'skip_hidden_directories': True,
                'skip_file_extensions': [],
                'max_file_size_kb': 10  # 10KB limit
            }
        }
        
        languages = detect_languages(repo_dir, config)
        
        # Should only count small.py
        self.assertEqual(languages['Python']['files'], 1)
    
    def test_byte_counting(self):
        """Test that byte counts are accurate."""
        content1 = 'print("Hello World")'
        content2 = 'def longer_function():\n    return "This is a longer file"'
        
        repo_dir = self.create_test_repo({
            'short.py': content1,
            'long.py': content2
        })
        
        languages = detect_languages(repo_dir)
        
        self.assertEqual(languages['Python']['files'], 2)
        expected_bytes = len(content1.encode()) + len(content2.encode())
        self.assertEqual(languages['Python']['bytes'], expected_bytes)
    
    def test_multiple_language_extensions(self):
        """Test detection of languages with multiple extensions."""
        repo_dir = self.create_test_repo({
            'main.c': '#include <stdio.h>',
            'header.h': '#ifndef HEADER_H',
            'app.cpp': '#include <iostream>',
            'class.cc': 'class Test {};',
            'header.hpp': '#ifndef HPP_HEADER',
            'module.py': 'import os',
            'stub.pyi': 'def func() -> int: ...',
            'cython.pyx': 'def cy_func(): pass'
        })
        
        languages = detect_languages(repo_dir)
        
        # C files (.c and .h)
        self.assertEqual(languages['C']['files'], 2)
        # C++ files (.cpp, .cc, .hpp)
        self.assertEqual(languages['C++']['files'], 3)
        # Python files (.py, .pyi, .pyx)
        self.assertEqual(languages['Python']['files'], 3)
    
    def test_empty_repository(self):
        """Test detection in empty repository."""
        repo_dir = self.create_test_repo({})
        
        languages = detect_languages(repo_dir)
        
        self.assertEqual(languages, {})
    
    def test_binary_files_skipped(self):
        """Test that binary files are skipped."""
        repo_dir = self.create_test_repo({
            'main.py': 'print("source")',
            'compiled.pyc': b'\x00\x01\x02\x03',  # Binary content
            'image.png': b'PNG\x89',  # Binary content
            'data.json': '{"key": "value"}'
        })
        
        languages = detect_languages(repo_dir)
        
        self.assertEqual(languages['Python']['files'], 1)
        self.assertEqual(languages['JSON']['files'], 1)
        # Binary files should not be counted
        self.assertEqual(len(languages), 2)


class TestMetadataStore(TestCase):
    """Test MetadataStore functionality."""
    
    def setUp(self):
        """Create temporary directory for metadata store."""
        self.test_dir = tempfile.mkdtemp()
        self.store_path = Path(self.test_dir) / 'metadata.json'
        self.store = MetadataStore(self.store_path)
    
    def tearDown(self):
        """Clean up test directory."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_language_detection_integration(self):
        """Test that language detection works within MetadataStore."""
        # Create a test repo
        repo_dir = os.path.join(self.test_dir, 'test_repo')
        os.makedirs(repo_dir)
        
        # Initialize as git repo
        import subprocess
        subprocess.run(['git', 'init'], cwd=repo_dir, capture_output=True)
        
        # Add some files
        with open(os.path.join(repo_dir, 'main.py'), 'w') as f:
            f.write('print("Hello")')
        with open(os.path.join(repo_dir, 'README.md'), 'w') as f:
            f.write('# Test')
        
        # Refresh metadata
        metadata = self.store.refresh(repo_dir)
        
        # Check language detection
        self.assertIn('languages', metadata)
        self.assertIn('Python', metadata['languages'])
        self.assertEqual(metadata['language'], 'Python')
        self.assertIn('Markdown', metadata['languages'])
    
    def test_custom_config_in_store(self):
        """Test that MetadataStore uses custom config for language detection."""
        # Create store with custom config
        config = {
            'language_detection': {
                'skip_directories': ['test_skip'],
                'skip_hidden_directories': False,  # Allow hidden dirs
                'skip_file_extensions': ['.test'],
                'max_file_size_kb': 1
            }
        }
        store = MetadataStore(self.store_path, config)
        
        # Create test repo
        repo_dir = os.path.join(self.test_dir, 'test_repo')
        os.makedirs(repo_dir)
        
        # Initialize as git repo
        import subprocess
        subprocess.run(['git', 'init'], cwd=repo_dir, capture_output=True)
        
        # Add files
        os.makedirs(os.path.join(repo_dir, '.hidden'))
        with open(os.path.join(repo_dir, '.hidden', 'script.py'), 'w') as f:
            f.write('print("hidden")')
        
        os.makedirs(os.path.join(repo_dir, 'test_skip'))
        with open(os.path.join(repo_dir, 'test_skip', 'skip.py'), 'w') as f:
            f.write('print("skip")')
        
        with open(os.path.join(repo_dir, 'file.test'), 'w') as f:
            f.write('test content')
        
        # Refresh metadata
        metadata = store.refresh(repo_dir)
        
        # Should count .hidden/script.py since skip_hidden_directories=False
        self.assertIn('Python', metadata['languages'])
        self.assertEqual(metadata['languages']['Python']['files'], 1)


if __name__ == '__main__':
    import unittest
    unittest.main()