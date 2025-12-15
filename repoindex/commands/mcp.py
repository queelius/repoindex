"""
MCP server command.

Starts the repoindex MCP (Model Context Protocol) server for integration
with LLM tools like Claude Code.
"""

import click
import logging

logger = logging.getLogger(__name__)


@click.command('mcp')
@click.option('--transport', '-t', default='stdio',
              type=click.Choice(['stdio', 'http']),
              help='Transport type (stdio for Claude Code, http for testing)')
@click.option('--port', '-p', default=8765, type=int,
              help='Port for HTTP transport (default: 8765)')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def mcp_handler(transport, port, debug):
    """Start the repoindex MCP server.

    The MCP (Model Context Protocol) server exposes repoindex functionality
    to LLM tools like Claude Code.

    \b
    Resources (read-only):
      repo://list           - All repositories with basic metadata
      repo://{name}         - Full metadata for one repository
      tags://list           - All tags
      stats://summary       - Overall statistics
      events://recent       - Recent events

    \b
    Tools (actions):
      repoindex_tag             - Add tag to repository
      repoindex_untag           - Remove tag from repository
      repoindex_query           - Query repositories
      repoindex_refresh         - Refresh metadata
      repoindex_stats           - Get statistics

    \b
    Examples:
      repoindex mcp                    # Start stdio server (for Claude Code)
      repoindex mcp --transport http   # Start HTTP server (for testing)
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG)

    from ..mcp import run_mcp_server

    if transport == 'http':
        click.echo(f"Starting repoindex MCP server on http://localhost:{port}")
        click.echo("Press Ctrl+C to stop")

    run_mcp_server(transport=transport)
