"""
MCP (Model Context Protocol) server for repoindex.

Exposes repoindex as an MCP server for integration with LLM tools like Claude Code.

Resources (read-only data):
    repo://list                 - All repositories with basic metadata
    repo://{name}               - Full metadata for one repository
    repo://{name}/status        - Git status for one repository
    repo://{name}/package       - Package info (PyPI/CRAN/npm)
    tags://list                 - All tags
    tags://tree                 - Hierarchical tag view
    tags://{tag}/repos          - Repositories with this tag
    stats://summary             - Overall statistics
    stats://languages           - Count by language
    stats://published           - Registry publication status
    events://recent             - Recent events
    events://repo/{name}        - Events for one repository
    events://type/{type}        - Events by type

Tools (actions):
    repoindex_tag(repo, tag)        - Add tag to repository
    repoindex_untag(repo, tag)      - Remove tag from repository
    repoindex_query(expression)     - Query repositories
    repoindex_refresh(repo?)        - Refresh metadata
    repoindex_stats(groupby)        - Get statistics
"""

from .server import create_mcp_server, run_mcp_server

__all__ = ['create_mcp_server', 'run_mcp_server']
