"""
Output format utilities for repoindex CLI commands.

Provides functions to format data as CSV, TSV, YAML, JSON, and JSONL.
"""

import json
import csv
import io
from typing import Dict, List, Any, Iterator, Optional
import yaml


def format_output(data: Iterator[Dict[str, Any]], format: str, 
                 fields: Optional[List[str]] = None) -> Iterator[str]:
    """
    Format data according to the specified format.
    
    Args:
        data: Iterator of dictionaries to format
        format: Output format (json, jsonl, csv, tsv, yaml)
        fields: Optional list of fields to include (for CSV/TSV)
        
    Yields:
        Formatted strings for output
    """
    if format == "jsonl":
        yield from format_jsonl(data)
    elif format == "json":
        yield from format_json(data)
    elif format == "csv":
        yield from format_csv(data, fields)
    elif format == "tsv":
        yield from format_tsv(data, fields)
    elif format == "yaml":
        yield from format_yaml(data)
    else:
        raise ValueError(f"Unknown format: {format}")


def format_jsonl(data: Iterator[Dict[str, Any]]) -> Iterator[str]:
    """Format data as JSON Lines (one JSON object per line)."""
    for item in data:
        yield json.dumps(item, ensure_ascii=False)


def format_json(data: Iterator[Dict[str, Any]]) -> Iterator[str]:
    """Format data as a single JSON array."""
    # Collect all data (needed for JSON array)
    all_data = list(data)
    yield json.dumps(all_data, ensure_ascii=False, indent=2)


def format_yaml(data: Iterator[Dict[str, Any]]) -> Iterator[str]:
    """Format data as YAML."""
    # Collect all data (needed for YAML document)
    all_data = list(data)
    yield yaml.dump(all_data, default_flow_style=False, allow_unicode=True, sort_keys=False)


def format_csv(data: Iterator[Dict[str, Any]], fields: Optional[List[str]] = None) -> Iterator[str]:
    """
    Format data as CSV.
    
    Args:
        data: Iterator of dictionaries
        fields: Optional list of fields to include. If None, uses all fields from first item.
    """
    # Need to peek at first item to determine fields
    data_list = list(data)
    if not data_list:
        return
    
    # Determine fields
    if fields is None:
        # Get all unique fields from all items (in case they vary)
        all_fields: set[str] = set()
        for item in data_list:
            if isinstance(item, dict):
                all_fields.update(flatten_dict(item).keys())
        fields = sorted(all_fields)
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    
    # Write header
    writer.writeheader()
    
    # Write data
    for item in data_list:
        # Flatten nested structures
        flat_item = flatten_dict(item)
        writer.writerow(flat_item)
    
    # Return the CSV content
    yield output.getvalue()


def format_tsv(data: Iterator[Dict[str, Any]], fields: Optional[List[str]] = None) -> Iterator[str]:
    """
    Format data as TSV (Tab-Separated Values).
    
    Args:
        data: Iterator of dictionaries
        fields: Optional list of fields to include. If None, uses all fields from first item.
    """
    # Need to peek at first item to determine fields
    data_list = list(data)
    if not data_list:
        return
    
    # Determine fields
    if fields is None:
        # Get all unique fields from all items
        all_fields: set[str] = set()
        for item in data_list:
            if isinstance(item, dict):
                all_fields.update(flatten_dict(item).keys())
        fields = sorted(all_fields)
    
    # Create TSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, delimiter='\t', extrasaction='ignore')
    
    # Write header
    writer.writeheader()
    
    # Write data
    for item in data_list:
        # Flatten nested structures
        flat_item = flatten_dict(item)
        writer.writerow(flat_item)
    
    # Return the TSV content
    yield output.getvalue()


def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
    """
    Flatten a nested dictionary.
    
    Args:
        d: Dictionary to flatten
        parent_key: Parent key for recursion
        sep: Separator for nested keys
        
    Returns:
        Flattened dictionary
    
    Example:
        {'a': {'b': 1, 'c': 2}} -> {'a.b': 1, 'a.c': 2}
    """
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            # Convert lists to comma-separated strings
            if v and not isinstance(v[0], (dict, list)):
                items.append((new_key, ', '.join(str(item) for item in v)))
            else:
                # For complex lists, just use the count
                items.append((new_key + '_count', len(v)))
        else:
            items.append((new_key, v))
    
    return dict(items)


def get_format_from_env(default: str = 'jsonl') -> str:
    """
    Get output format from environment variable.
    
    Checks REPOINDEX_FORMAT environment variable.
    
    Args:
        default: Default format if not specified
        
    Returns:
        Format string
    """
    import os
    format = os.environ.get('REPOINDEX_FORMAT', default).lower()
    if format not in ('json', 'jsonl', 'csv', 'tsv', 'yaml', 'table'):
        return default
    return format