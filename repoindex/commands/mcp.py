"""
MCP server command.

Starts the ghops MCP (Model Context Protocol) server for integration
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
    """Start the ghops MCP server.

    The MCP (Model Context Protocol) server exposes ghops functionality
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
      ghops_tag             - Add tag to repository
      ghops_untag           - Remove tag from repository
      ghops_query           - Query repositories
      ghops_refresh         - Refresh metadata
      ghops_stats           - Get statistics

    \b
    Examples:
      ghops mcp                    # Start stdio server (for Claude Code)
      ghops mcp --transport http   # Start HTTP server (for testing)
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG)

    from ..mcp import run_mcp_server

    if transport == 'http':
        click.echo(f"Starting ghops MCP server on http://localhost:{port}")
        click.echo("Press Ctrl+C to stop")

    run_mcp_server(transport=transport)
