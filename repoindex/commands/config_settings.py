"""
Generic config set/get/unset commands.

Provides git-config-style dotted-path access to arbitrary config values.
"""

import json
import sys

import click

from ..config import (
    load_config,
    load_raw_config,
    save_config,
    config_get_path,
    config_set_path,
    config_unset_path,
    coerce_value,
)


@click.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value using dotted-path notation.

    \b
    Examples:
        repoindex config set author.name "Alex Towell"
        repoindex config set github.rate_limit.max_retries 5
        repoindex config set refresh.providers.pypi true
    """
    config = load_raw_config()
    config_set_path(config, key, coerce_value(value))
    save_config(config)
    click.echo(f"{key} = {coerce_value(value)!r}")


@click.command("get")
@click.argument("key")
def config_get(key):
    """Get a configuration value using dotted-path notation.

    Prints scalars as plain text, dicts/lists as JSON.
    Shows the effective value (config file merged with defaults).

    \b
    Examples:
        repoindex config get author.name
        repoindex config get author           # shows whole sub-dict
        repoindex config get github.rate_limit.max_retries
    """
    config = load_config()
    value, found = config_get_path(config, key)
    if not found:
        click.echo(f"Key not found: {key}", err=True)
        sys.exit(1)
    if isinstance(value, (dict, list)):
        click.echo(json.dumps(value, indent=2, ensure_ascii=False))
    else:
        click.echo(value)


@click.command("unset")
@click.argument("key")
def config_unset(key):
    """Remove a configuration value using dotted-path notation.

    \b
    Examples:
        repoindex config unset refresh.providers.npm
        repoindex config unset author.zenodo_token
    """
    config = load_raw_config()
    if config_unset_path(config, key):
        save_config(config)
        click.echo(f"Removed: {key}")
    else:
        click.echo(f"Key not found: {key}", err=True)
        sys.exit(1)
