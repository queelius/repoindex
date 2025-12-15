#!/usr/bin/env python3

import click
from pathlib import Path
import sys

from repoindex.config import load_config
from repoindex.commands.status import status_handler
from repoindex.commands.clone import clone_handler
from repoindex.commands.config import config_cmd
from repoindex.commands.tag import tag_cmd
from repoindex.commands.query import query_handler
from repoindex.commands.metadata import metadata_cmd
from repoindex.commands.docs import docs_handler
from repoindex.commands.shell import shell_handler

# Command groups
from repoindex.commands.fs import fs_cmd
from repoindex.commands.git import git_cmd

# Individual commands
from repoindex.commands.audit import audit_cmd
from repoindex.commands.poll import events_handler
from repoindex.commands.mcp import mcp_handler


@click.group()
@click.version_option()
def cli():
    """repoindex - Collection-aware metadata index for git repositories.

    Provides a unified view across all your repositories, enabling queries,
    organization, and integration with LLM tools like Claude Code.
    """
    pass


# Core commands (flat, top-level)
cli.add_command(clone_handler, name='clone')
cli.add_command(status_handler)
cli.add_command(query_handler, name='query')
cli.add_command(shell_handler, name='shell')
cli.add_command(events_handler, name='events')
cli.add_command(metadata_cmd)
cli.add_command(audit_cmd)
cli.add_command(mcp_handler, name='mcp')

# Command groups
cli.add_command(tag_cmd)
cli.add_command(docs_handler)
cli.add_command(fs_cmd)
cli.add_command(git_cmd)
cli.add_command(config_cmd)

# Note: catalog command group removed in v0.8.2 (use 'tag' instead)


# Deprecated aliases
def create_deprecated_alias(original_cmd, old_name, new_name):
    """Create a deprecated alias that forwards to the new command."""
    import copy

    if hasattr(original_cmd, 'callback'):
        # It's a single command
        original_callback = original_cmd.callback

        def wrapper(*args, **kwargs):
            click.echo(f"Warning: 'repoindex {old_name}' is deprecated, use 'repoindex {new_name}' instead", err=True)
            return original_callback(*args, **kwargs)

        deprecated_cmd = copy.deepcopy(original_cmd)
        deprecated_cmd.name = old_name
        deprecated_cmd.hidden = True
        deprecated_cmd.callback = wrapper
        deprecated_cmd.help = f"[DEPRECATED] Use 'repoindex {new_name}' instead.\n\n" + (original_cmd.help or "")
        return deprecated_cmd
    else:
        # It's a command group - just rename it and mark deprecated
        deprecated_cmd = copy.deepcopy(original_cmd)
        deprecated_cmd.name = old_name
        deprecated_cmd.hidden = True
        if hasattr(deprecated_cmd, 'help'):
            deprecated_cmd.help = f"[DEPRECATED] Use 'repoindex {new_name}' instead.\n\n" + (deprecated_cmd.help or "")
        return deprecated_cmd


# get → clone
cli.add_command(create_deprecated_alias(clone_handler, 'get', 'clone'))


def main():
    cli()

if __name__ == "__main__":
    main()
