"""
Shell command for repoindex.
"""

import click
import sys


@click.command()
def shell_handler():
    """Launch interactive shell with VFS navigation.

    The shell provides a filesystem-like interface for repository management:

    VFS Structure:
      /repos/              - All repositories (actual files)
      /by-language/        - Grouped by programming language
      /by-tag/             - Grouped by tags
      /by-status/          - Grouped by git status (clean/dirty/unpushed)

    Navigation Commands:
      cd <path>            - Change directory
      ls [path]            - List directory contents
      pwd                  - Print working directory

    Query Commands:
      query <expr>         - Query repositories with expression
      find [options]       - Find repositories by criteria

    Repository Commands:
      status               - Show repository status
      update               - Update repositories

    Other:
      help                 - Show available commands
      exit                 - Exit shell (or Ctrl+D)

    Examples:
        repoindex shell

        repoindex:/> ls
        repoindex:/> cd by-language/Python
        repoindex:/by-language/Python> ls
        repoindex:/by-language/Python> query "stars > 10"
        repoindex:/by-language/Python> cd /repos/myproject
        repoindex:/repos/myproject> ls
    """
    try:
        from repoindex.shell import run_shell
    except ImportError as e:
        click.echo(f"Error: Could not import shell: {e}", err=True)
        sys.exit(1)

    try:
        run_shell()
    except KeyboardInterrupt:
        click.echo("\nShell closed.")
    except Exception as e:
        click.echo(f"Error running shell: {e}", err=True)
        sys.exit(1)
