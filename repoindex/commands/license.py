"""
Handles the 'license' command for managing LICENSE files.
"""
import json
import click
from datetime import datetime
from ..config import logger, stats
from pathlib import Path
from repoindex.core import get_available_licenses, get_license_template, add_license_to_repo
from repoindex.config import load_config

@click.group("license")
def license_cmd():
    """Manage LICENSE files."""
    pass


@license_cmd.command("list")
def list_licenses_handler():
    """List available licenses from the GitHub API."""
    licenses = get_available_licenses()
    print(json.dumps(licenses, indent=2))


@license_cmd.command("show")
@click.argument("license_key")
def show_license_handler(license_key):
    """Show the template for a specific license."""
    template = get_license_template(license_key)
    print(json.dumps(template, indent=2))


@license_cmd.command("add")
@click.argument("license_key")
@click.option("--repo-path", default=".", help="Path to the repository.")
@click.option("--author", help="Author's name for the license.")
@click.option("--email", help="Author's email for the license.")
@click.option("--year", default=str(datetime.now().year), help="Copyright year.")
@click.option("--force", is_flag=True, help="Overwrite existing LICENSE file.")
@click.option("--dry-run", is_flag=True, help="Simulate without making changes.")
def add_license_handler(license_key, repo_path, author, email, year, force, dry_run):
    """Add a LICENSE file to a repository."""
    config = load_config()
    author_name = author or config.get("general", {}).get("git_user_name")
    author_email = email or config.get("general", {}).get("git_user_email")

    if not author_name:
        logger.error("Error: Author name not provided and not found in config.")
        return

    result = add_license_to_repo(
        repo_path, license_key, author_name, author_email, year, force, dry_run
    )
    print(json.dumps(result, indent=2))
