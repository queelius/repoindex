"""
Documentation detection for repoindex.

This module provides documentation detection across repositories.
It detects which documentation tools are used (mkdocs, sphinx, jekyll, etc.)
without performing any build or deployment actions.
"""

import click
import json
import os
from pathlib import Path
from typing import Dict, Optional

from repoindex.config import load_config
from repoindex.utils import find_git_repos_from_config
from repoindex.render import render_docs_table
from repoindex.repo_filter import get_filtered_repos, add_common_repo_options


def detect_docs_tool(repo_path: str) -> Optional[Dict[str, any]]:
    """
    Detect which documentation tool is used in a repository.

    Returns dict with tool info or None if no docs found.
    """
    repo_path = Path(repo_path)

    # Check for MkDocs
    if (repo_path / "mkdocs.yml").exists() or (repo_path / "mkdocs.yaml").exists():
        config_file = "mkdocs.yml" if (repo_path / "mkdocs.yml").exists() else "mkdocs.yaml"
        return {
            "tool": "mkdocs",
            "config": config_file,
            "detected_files": [config_file]
        }

    # Check for Sphinx
    if (repo_path / "docs" / "conf.py").exists() or (repo_path / "doc" / "conf.py").exists():
        docs_dir = "docs" if (repo_path / "docs" / "conf.py").exists() else "doc"
        return {
            "tool": "sphinx",
            "config": f"{docs_dir}/conf.py",
            "detected_files": [f"{docs_dir}/conf.py"]
        }

    # Check for Jekyll
    jekyll_indicators = ["_config.yml", "_config.yaml", "_posts", "_layouts"]
    jekyll_files = []
    for indicator in jekyll_indicators:
        if (repo_path / indicator).exists():
            jekyll_files.append(indicator)

    if jekyll_files:
        config_file = "_config.yml" if "_config.yml" in jekyll_files else "_config.yaml" if "_config.yaml" in jekyll_files else None
        return {
            "tool": "jekyll",
            "config": config_file,
            "detected_files": jekyll_files
        }

    # Check for Docusaurus
    if (repo_path / "docusaurus.config.js").exists() or (repo_path / "website" / "docusaurus.config.js").exists():
        base_dir = "website" if (repo_path / "website" / "docusaurus.config.js").exists() else "."
        return {
            "tool": "docusaurus",
            "config": f"{base_dir}/docusaurus.config.js" if base_dir != "." else "docusaurus.config.js",
            "detected_files": [f"{base_dir}/docusaurus.config.js" if base_dir != "." else "docusaurus.config.js"]
        }

    # Check for VuePress
    if (repo_path / ".vuepress" / "config.js").exists() or (repo_path / "docs" / ".vuepress" / "config.js").exists():
        base_dir = "docs" if (repo_path / "docs" / ".vuepress" / "config.js").exists() else "."
        return {
            "tool": "vuepress",
            "config": f"{base_dir}/.vuepress/config.js" if base_dir != "." else ".vuepress/config.js",
            "detected_files": [f"{base_dir}/.vuepress/config.js" if base_dir != "." else ".vuepress/config.js"]
        }

    # Check for Hugo
    if (repo_path / "config.toml").exists() or (repo_path / "config.yaml").exists() or (repo_path / "config.json").exists():
        # Additional check for Hugo-specific directories
        if (repo_path / "content").exists() or (repo_path / "themes").exists():
            config_files = []
            for ext in ["toml", "yaml", "json"]:
                if (repo_path / f"config.{ext}").exists():
                    config_files.append(f"config.{ext}")
            return {
                "tool": "hugo",
                "config": config_files[0] if config_files else None,
                "detected_files": config_files
            }

    # Check for generic docs directory with markdown files
    for docs_dir in ["docs", "doc", "documentation"]:
        if (repo_path / docs_dir).exists():
            md_files = list((repo_path / docs_dir).glob("*.md"))
            if md_files:
                return {
                    "tool": "markdown",
                    "config": None,
                    "detected_files": [docs_dir]
                }

    return None


def get_docs_status(repo_path: str) -> Dict[str, any]:
    """Get documentation status for a repository."""
    repo_name = os.path.basename(repo_path)
    docs_info = detect_docs_tool(repo_path)

    status = {
        "path": os.path.abspath(repo_path),
        "name": repo_name,
        "has_docs": docs_info is not None,
        "docs_tool": docs_info.get("tool") if docs_info else None,
        "docs_config": docs_info.get("config") if docs_info else None,
        "detected_files": docs_info.get("detected_files") if docs_info else []
    }

    # Check if GitHub Pages is enabled (local detection only - no API calls)
    from repoindex.utils import get_remote_url, parse_repo_url, detect_github_pages_locally
    remote_url = get_remote_url(repo_path)
    if remote_url:
        owner, repo_name_parsed = parse_repo_url(remote_url)
        if owner and repo_name_parsed:
            pages_info = detect_github_pages_locally(repo_path)
            if pages_info and pages_info.get('likely_enabled'):
                status["pages_url"] = pages_info.get('pages_url')

    return status


@click.command("docs")
@add_common_repo_options
@click.option("--pretty", is_flag=True, help="Display as formatted table")
@click.option("--with-docs-only", is_flag=True, help="Only show repos with documentation")
def docs_handler(dir, recursive, tag_filters, all_tags, query, pretty, with_docs_only):
    """Detect documentation tools across repositories.

    Shows which documentation tools (mkdocs, sphinx, jekyll, etc.) are used
    in your repositories.

    Examples:

    \b
        repoindex docs                      # Check all repos
        repoindex docs --pretty             # Show as table
        repoindex docs --with-docs-only     # Only repos with docs
        repoindex docs -t lang:python       # Filter by tag
    """
    config = load_config()

    # Get filtered repositories
    repos, filter_desc = get_filtered_repos(
        dir=dir,
        recursive=recursive,
        tag_filters=tag_filters,
        all_tags=all_tags,
        query=query,
        config=config
    )

    if not repos:
        if pretty:
            from rich.console import Console
            console = Console()
            msg = "No repositories found"
            if filter_desc:
                msg += f" matching {filter_desc}"
            console.print(f"[yellow]{msg}[/yellow]")
        else:
            error = {"error": "No repositories found"}
            if filter_desc:
                error["filter"] = filter_desc
            print(json.dumps(error), flush=True)
        return

    # Get documentation status for each repo
    docs_statuses = []
    for repo_path in repos:
        status = get_docs_status(repo_path)
        if with_docs_only and not status["has_docs"]:
            continue
        if pretty:
            docs_statuses.append(status)
        else:
            print(json.dumps(status), flush=True)

    if pretty:
        if docs_statuses:
            render_docs_table(docs_statuses)
        else:
            from rich.console import Console
            console = Console()
            console.print("[yellow]No repositories with documentation found[/yellow]")
