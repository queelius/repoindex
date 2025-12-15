"""
Output module for repoindex.

Provides consistent output formatting across all commands:
- JSONL (default): Newline-delimited JSON for piping
- Pretty: Human-readable tables using Rich

Usage:
    from repoindex.output import emit, emit_error

    # Stream items as JSONL (default) or pretty table
    emit(repos, pretty=args.pretty)

    # Emit error to stderr
    emit_error("Not found", type="not_found", context={"path": "/foo"})
"""

import json
import sys
from typing import Iterable, Any, Dict, Optional, List


def emit(
    items: Iterable[Any],
    pretty: bool = False,
    columns: Optional[List[str]] = None,
    err: bool = False
) -> None:
    """
    Emit items as JSONL or pretty table.

    Args:
        items: Items to emit (should have to_dict() method or be dicts)
        pretty: If True, render as table. If False, output JSONL
        columns: Column names for table (auto-detected if None)
        err: If True, output to stderr instead of stdout
    """
    stream = sys.stderr if err else sys.stdout

    if pretty:
        _emit_table(items, columns)
    else:
        _emit_jsonl(items, stream)


def _emit_jsonl(items: Iterable[Any], stream=sys.stdout) -> None:
    """Emit items as JSONL."""
    for item in items:
        if hasattr(item, 'to_dict'):
            data = item.to_dict()
        elif hasattr(item, 'to_jsonl'):
            print(item.to_jsonl(), file=stream, flush=True)
            continue
        elif isinstance(item, dict):
            data = item
        else:
            data = {'value': str(item)}

        print(json.dumps(data, ensure_ascii=False), file=stream, flush=True)


def _emit_table(items: Iterable[Any], columns: Optional[List[str]] = None) -> None:
    """Emit items as a Rich table."""
    items_list = list(items)

    if not items_list:
        print("No results found")
        return

    # Convert to dicts
    rows = []
    for item in items_list:
        if hasattr(item, 'to_dict'):
            rows.append(item.to_dict())
        elif isinstance(item, dict):
            rows.append(item)
        else:
            rows.append({'value': str(item)})

    # Auto-detect columns if not provided
    if not columns:
        columns = _auto_columns(rows)

    # Try Rich, fall back to simple table
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(show_header=True, header_style="bold")

        for col in columns:
            table.add_column(col)

        for row in rows:
            values = [_format_value(row.get(col, '')) for col in columns]
            table.add_row(*values)

        console.print(table)

    except ImportError:
        # Fallback to simple text table
        _simple_table(columns, rows)


def _auto_columns(rows: List[Dict]) -> List[str]:
    """Auto-detect columns from rows."""
    if not rows:
        return []

    # Common column order preference
    preferred = ['name', 'path', 'status', 'branch', 'language', 'type', 'timestamp', 'repo']

    # Get all keys from first row
    all_keys = set(rows[0].keys())

    # Start with preferred columns that exist
    columns = [col for col in preferred if col in all_keys]

    # Add remaining columns
    for key in sorted(all_keys):
        if key not in columns:
            columns.append(key)

    # Limit to reasonable number
    return columns[:8]


def _format_value(value: Any, max_len: int = 50) -> str:
    """Format a value for table display."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, list):
        s = ', '.join(str(v) for v in value[:3])
        if len(value) > 3:
            s += f' (+{len(value) - 3} more)'
        return s
    if isinstance(value, dict):
        return '{...}'

    s = str(value)
    if len(s) > max_len:
        return s[:max_len-3] + '...'
    return s


def _simple_table(columns: List[str], rows: List[Dict]) -> None:
    """Simple text table without Rich."""
    if not rows:
        return

    # Calculate column widths
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            val = _format_value(row.get(col, ''))
            widths[col] = max(widths[col], len(val))

    # Print header
    header = ' | '.join(col.ljust(widths[col]) for col in columns)
    print(header)
    print('-' * len(header))

    # Print rows
    for row in rows:
        values = [_format_value(row.get(col, '')).ljust(widths[col]) for col in columns]
        print(' | '.join(values))


def emit_error(
    error: str,
    type: str = "error",
    context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Emit error to stderr as JSON.

    Args:
        error: Error message
        type: Error type (e.g., "not_found", "config_error")
        context: Additional context dict
    """
    obj = {
        'error': error,
        'type': type
    }
    if context:
        obj['context'] = context

    print(json.dumps(obj, ensure_ascii=False), file=sys.stderr, flush=True)


def emit_count(count: int, label: str = "items", pretty: bool = False) -> None:
    """
    Emit a count summary.

    Args:
        count: Number of items
        label: Label for items (e.g., "repositories", "events")
        pretty: If True, print human-readable message
    """
    if pretty:
        print(f"Found {count} {label}")
    else:
        print(json.dumps({'count': count, 'label': label}), flush=True)


def emit_success(message: str, data: Optional[Dict] = None, pretty: bool = False) -> None:
    """
    Emit success message.

    Args:
        message: Success message
        data: Optional additional data
        pretty: If True, print human-readable message
    """
    if pretty:
        print(f"Success: {message}")
    else:
        obj = {'success': True, 'message': message}
        if data:
            obj['data'] = data
        print(json.dumps(obj, ensure_ascii=False), flush=True)
