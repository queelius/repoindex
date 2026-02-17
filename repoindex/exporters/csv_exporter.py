"""
CSV exporter for repoindex.

Exports repository data as a CSV file with configurable columns.
"""

import csv
from typing import IO, List, Optional

from . import Exporter

DEFAULT_COLUMNS = [
    'name', 'path', 'language', 'branch', 'is_clean',
    'remote_url', 'github_stars', 'license_key', 'description',
]


class CSVExporter(Exporter):
    """CSV table exporter."""
    format_id = "csv"
    name = "CSV"
    extension = ".csv"

    def export(self, repos: List[dict], output: IO[str],
               config: Optional[dict] = None) -> int:
        if not repos:
            return 0

        # Use default columns, filtered to keys that exist in the data
        available_keys = set()
        for repo in repos:
            available_keys.update(repo.keys())

        columns = [c for c in DEFAULT_COLUMNS if c in available_keys]
        # Add any remaining keys from default that might be missing from data
        if not columns:
            columns = sorted(available_keys)

        writer = csv.DictWriter(
            output, fieldnames=columns,
            extrasaction='ignore',
        )
        writer.writeheader()

        count = 0
        for repo in repos:
            writer.writerow(repo)
            count += 1

        return count


exporter = CSVExporter()
