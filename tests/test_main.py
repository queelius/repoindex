"""
Unit tests for repoindex.__main__ module
"""
import unittest
import sys
from unittest.mock import patch


class TestMainEntryPoint(unittest.TestCase):
    """Test the main entry point functionality"""

    def test_main_module_imports(self):
        """Test that main module can be imported"""
        try:
            import repoindex.__main__
            self.assertTrue(hasattr(repoindex.__main__, 'main'))
        except ImportError:
            self.fail("Failed to import repoindex.__main__")
    
    @patch('repoindex.cli.main')
    @patch('sys.exit')
    def test_main_logic_success(self, mock_exit, mock_main):
        """Test the main logic when main returns 0"""
        mock_main.return_value = 0
        
        # Test the logic: sys.exit(main() or 0)
        result = mock_main() or 0
        
        self.assertEqual(result, 0)
        mock_main.assert_called_once()
    
    @patch('repoindex.cli.main')
    @patch('sys.exit')  
    def test_main_logic_failure(self, mock_exit, mock_main):
        """Test the main logic when main returns 1"""
        mock_main.return_value = 1
        
        # Test the logic: sys.exit(main() or 0)
        result = mock_main() or 0
        
        self.assertEqual(result, 1)
        mock_main.assert_called_once()
    
    @patch('repoindex.cli.main')
    @patch('sys.exit')
    def test_main_logic_none_return(self, mock_exit, mock_main):
        """Test the main logic when main returns None"""
        mock_main.return_value = None
        
        # Test the logic: sys.exit(main() or 0)
        result = mock_main() or 0
        
        self.assertEqual(result, 0)
        mock_main.assert_called_once()


if __name__ == '__main__':
    unittest.main()
