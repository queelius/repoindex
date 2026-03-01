"""MCP server command for repoindex."""
import click


@click.command('mcp')
def mcp_handler():
    """Start the MCP server (stdio transport).

    Provides LLM access to the repoindex database.
    Requires: pip install repoindex[mcp]
    """
    try:
        from ..mcp.server import create_server
    except ImportError:
        click.echo(
            "Error: MCP server requires the 'mcp' package.\n"
            "Install with: pip install repoindex[mcp]",
            err=True,
        )
        raise SystemExit(1)

    server = create_server()
    server.run()
