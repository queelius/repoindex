#!/usr/bin/env python3

import click

from repoindex.commands.status import status_handler
from repoindex.commands.config import config_cmd
from repoindex.commands.tag import tag_cmd
from repoindex.commands.view import view_cmd
from repoindex.commands.query import query_handler
from repoindex.commands.shell import shell_handler
from repoindex.commands.events import events_handler
from repoindex.commands.refresh import refresh_handler, db_handler, sql_handler
from repoindex.commands.claude import claude_handler
from repoindex.commands.export import export_handler
from repoindex.commands.copy import copy_handler
from repoindex.commands.link import link_cmd


@click.group()
@click.version_option()
@click.option('--config', 'config_path', type=click.Path(exists=True),
              envvar='REPOINDEX_CONFIG',
              help='Path to configuration file (default: ~/.repoindex/config.json)')
@click.pass_context
def cli(ctx, config_path):
    """repoindex - Collection-aware metadata index for git repositories.

    Provides a unified view across all your repositories, enabling queries,
    organization, and integration with LLM tools like Claude Code.
    """
    import os
    ctx.ensure_object(dict)

    # Set environment variable so all config loads use this path
    if config_path:
        os.environ['REPOINDEX_CONFIG'] = config_path
        ctx.obj['config_path'] = config_path


# Core commands
cli.add_command(status_handler)
cli.add_command(query_handler, name='query')
cli.add_command(events_handler, name='events')
cli.add_command(sql_handler, name='sql')
cli.add_command(refresh_handler, name='refresh')
cli.add_command(export_handler, name='export')
cli.add_command(copy_handler, name='copy')
cli.add_command(shell_handler, name='shell')

# Command groups
cli.add_command(tag_cmd)
cli.add_command(view_cmd)
cli.add_command(link_cmd)
cli.add_command(config_cmd)
cli.add_command(claude_handler, name='claude')

# Deprecated: db is now absorbed into sql command (--info, --path, --reset, --schema)
# Keep as hidden for backward compatibility
import copy  # noqa: E402
_db_deprecated = copy.copy(db_handler)
_db_deprecated.hidden = True
_db_deprecated.deprecated = True
cli.add_command(_db_deprecated, name='db')


def main():
    cli()

if __name__ == "__main__":
    main()
