"""
Test runner script for all ghops tests
"""
import unittest
import sys
import os
from pathlib import Path

# Add the parent directory to the Python path so we can import repoindex
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import all test modules
from tests.test_utils import *
from tests.test_status import *
from tests.test_pypi import *
from tests.test_config import *
from tests.test_social import *
from tests.test_integration import *


def run_all_tests():
    """Run all tests and return the result"""
    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test modules
    test_modules = [
        'tests.test_utils',
        'tests.test_status', 
        'tests.test_pypi',
        'tests.test_config',
        'tests.test_social',
        'tests.test_integration'
    ]
    
    for module in test_modules:
        try:
            tests = loader.loadTestsFromName(module)
            suite.addTests(tests)
        except Exception as e:
            print(f"Warning: Could not load tests from {module}: {e}")
    
    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


def run_specific_test_module(module_name):
    """Run tests from a specific module"""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(f'tests.test_{module_name}')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # Run specific test module
        module = sys.argv[1]
        success = run_specific_test_module(module)
    else:
        # Run all tests
        success = run_all_tests()
    
    sys.exit(0 if success else 1)
