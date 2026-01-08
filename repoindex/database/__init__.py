"""
Database module for repoindex.

Provides SQLite-based persistence and querying for repository metadata.
The database serves as a queryable cache/index of filesystem data.

Key components:
- connection: Database connection management
- schema: Table definitions and schema versioning
- repository: Repository CRUD operations
- events: Event CRUD operations
- query: Query compilation (DSL -> SQL)
"""

from .connection import (
    get_connection,
    get_db_path,
    Database,
    get_database_info,
    reset_database,
    transaction,
)
from .schema import CURRENT_VERSION, ensure_schema
from .repository import (
    upsert_repo,
    get_repo_by_path,
    get_repo_by_name,
    get_repo_by_id,
    get_all_repos,
    get_repos_with_tags,
    delete_repo,
    needs_refresh,
    get_stale_repos,
    cleanup_missing_repos,
    get_repo_count,
    search_repos,
    get_repos_by_language,
    get_repos_by_tag,
    record_to_domain,
)
from .events import (
    insert_event,
    insert_events,
    get_events,
    get_events_for_repo,
    get_recent_events,
    count_events,
    get_event_summary,
    has_event,
    event_count,
    last_event_timestamp,
)
from .query_compiler import (
    compile_query,
    CompiledQuery,
    QueryCompiler,
    QueryCompileError,
)
from .errors import (
    ensure_scan_errors_table,
    record_scan_error,
    get_scan_errors,
    get_scan_error_count,
    clear_scan_errors,
    clear_scan_error_for_path,
)

__all__ = [
    # Connection
    'get_connection',
    'get_db_path',
    'Database',
    'get_database_info',
    'reset_database',
    'transaction',
    # Schema
    'ensure_schema',
    'CURRENT_VERSION',
    # Repository
    'upsert_repo',
    'get_repo_by_path',
    'get_repo_by_name',
    'get_repo_by_id',
    'get_all_repos',
    'get_repos_with_tags',
    'delete_repo',
    'needs_refresh',
    'get_stale_repos',
    'cleanup_missing_repos',
    'get_repo_count',
    'search_repos',
    'get_repos_by_language',
    'get_repos_by_tag',
    'record_to_domain',
    # Events
    'insert_event',
    'insert_events',
    'get_events',
    'get_events_for_repo',
    'get_recent_events',
    'count_events',
    'get_event_summary',
    'has_event',
    'event_count',
    'last_event_timestamp',
    # Query compiler
    'compile_query',
    'CompiledQuery',
    'QueryCompiler',
    'QueryCompileError',
    # Scan errors
    'ensure_scan_errors_table',
    'record_scan_error',
    'get_scan_errors',
    'get_scan_error_count',
    'clear_scan_errors',
    'clear_scan_error_for_path',
]
