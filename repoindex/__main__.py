#!/usr/bin/env python3
"""
Main entry point for repoindex package when run as a module.
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main() or 0)
