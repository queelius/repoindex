"""
Documentation management commands for ghops.

This module provides commands for detecting, building, serving, and deploying
documentation for repositories.
"""

import click
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Generator

from repoindex.config import load_config, logger
from repoindex.utils import run_command, find_git_repos_from_config
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
            "build_cmd": "mkdocs build",
            "serve_cmd": "mkdocs serve",
            "output_dir": "site",
            "detected_files": [config_file]
        }
    
    # Check for Sphinx
    if (repo_path / "docs" / "conf.py").exists() or (repo_path / "doc" / "conf.py").exists():
        docs_dir = "docs" if (repo_path / "docs" / "conf.py").exists() else "doc"
        return {
            "tool": "sphinx",
            "config": f"{docs_dir}/conf.py",
            "build_cmd": f"sphinx-build -b html {docs_dir} {docs_dir}/_build/html",
            "serve_cmd": f"python -m http.server 8000 --directory {docs_dir}/_build/html",
            "output_dir": f"{docs_dir}/_build/html",
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
            "build_cmd": "bundle exec jekyll build",
            "serve_cmd": "bundle exec jekyll serve",
            "output_dir": "_site",
            "detected_files": jekyll_files
        }
    
    # Check for Docusaurus
    if (repo_path / "docusaurus.config.js").exists() or (repo_path / "website" / "docusaurus.config.js").exists():
        base_dir = "website" if (repo_path / "website" / "docusaurus.config.js").exists() else "."
        return {
            "tool": "docusaurus",
            "config": f"{base_dir}/docusaurus.config.js" if base_dir != "." else "docusaurus.config.js",
            "build_cmd": f"cd {base_dir} && npm run build" if base_dir != "." else "npm run build",
            "serve_cmd": f"cd {base_dir} && npm run serve" if base_dir != "." else "npm run serve",
            "output_dir": f"{base_dir}/build" if base_dir != "." else "build",
            "detected_files": [f"{base_dir}/docusaurus.config.js" if base_dir != "." else "docusaurus.config.js"]
        }
    
    # Check for VuePress
    if (repo_path / ".vuepress" / "config.js").exists() or (repo_path / "docs" / ".vuepress" / "config.js").exists():
        base_dir = "docs" if (repo_path / "docs" / ".vuepress" / "config.js").exists() else "."
        return {
            "tool": "vuepress",
            "config": f"{base_dir}/.vuepress/config.js" if base_dir != "." else ".vuepress/config.js",
            "build_cmd": f"vuepress build {base_dir}" if base_dir != "." else "vuepress build",
            "serve_cmd": f"vuepress dev {base_dir}" if base_dir != "." else "vuepress dev",
            "output_dir": f"{base_dir}/.vuepress/dist" if base_dir != "." else ".vuepress/dist",
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
                "build_cmd": "hugo",
                "serve_cmd": "hugo server",
                "output_dir": "public",
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
                    "build_cmd": None,
                    "serve_cmd": f"python -m http.server 8000 --directory {docs_dir}",
                    "output_dir": docs_dir,
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
    
    # Check if GitHub Pages is enabled
    from repoindex.utils import get_remote_url, parse_repo_url, detect_github_pages_locally
    remote_url = get_remote_url(repo_path)
    if remote_url:
        owner, repo_name_parsed = parse_repo_url(remote_url)
        if owner and repo_name_parsed:
            pages_info = detect_github_pages_locally(repo_path)
            if pages_info and pages_info.get('likely_enabled'):
                status["pages_url"] = pages_info.get('pages_url')
            else:
                # Try GitHub API
                pages_result, _ = run_command(
                    f"gh api repos/{owner}/{repo_name_parsed}/pages --silent",
                    capture_output=True,
                    check=False
                )
                if pages_result:
                    try:
                        pages_data = json.loads(pages_result)
                        status["pages_url"] = pages_data.get('html_url')
                    except json.JSONDecodeError:
                        pass
    
    return status


def build_docs(repo_path: str, tool_info: Dict[str, any]) -> Dict[str, any]:
    """Build documentation for a repository."""
    result = {
        "path": repo_path,
        "tool": tool_info["tool"],
        "success": False,
        "output": None,
        "error": None
    }
    
    if not tool_info.get("build_cmd"):
        result["error"] = f"No build command available for {tool_info['tool']}"
        return result
    
    try:
        output, _ = run_command(
            tool_info["build_cmd"],
            cwd=repo_path,
            capture_output=True,
            check=True
        )
        result["success"] = True
        result["output"] = output
        result["output_dir"] = os.path.join(repo_path, tool_info["output_dir"])
    except Exception as e:
        result["error"] = str(e)
    
    return result


@click.group("docs")
def docs_group():
    """Manage project documentation."""
    pass


@docs_group.command("status")
@add_common_repo_options
@click.option("--pretty", is_flag=True, help="Display as formatted table")
def docs_status(dir, recursive, tag_filters, all_tags, query, pretty):
    """Show documentation status for repositories."""
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
        if pretty:
            docs_statuses.append(status)
        else:
            print(json.dumps(status), flush=True)
    
    if pretty:
        render_docs_table(docs_statuses)


@docs_group.command("build")
@click.argument("repo_path", required=False)
@add_common_repo_options
@click.option("--tool", help="Filter by documentation tool")
@click.option("--dry-run", is_flag=True, help="Show what would be built")
def docs_build(repo_path, dir, recursive, tag_filters, all_tags, query, tool, dry_run):
    """Build documentation for repositories."""
    repos_to_build = []
    config = load_config()
    
    # Get target repositories
    filter_desc = None
    if repo_path:
        # Single repo specified
        target_repos = [repo_path]
    else:
        # Use common filtering
        target_repos, filter_desc = get_filtered_repos(
            dir=dir,
            recursive=recursive,
            tag_filters=tag_filters,
            all_tags=all_tags,
            query=query,
            config=config
        )
        
        if not target_repos:
            msg = "No repositories found"
            if filter_desc:
                msg += f" matching {filter_desc}"
            error = {"error": msg}
            print(json.dumps(error), flush=True)
            return
    
    # Check each repo for docs
    for repo in target_repos:
        docs_info = detect_docs_tool(repo)
        if docs_info and (not tool or docs_info["tool"] == tool):
            repos_to_build.append((repo, docs_info))
    
    if not repos_to_build:
        msg = "No documentation found"
        if filter_desc:
            msg += f" matching {filter_desc}"
        if tool:
            msg += f" with tool: {tool}"
            
        error = {"error": msg}
        print(json.dumps(error), flush=True)
        return
    
    # Build documentation
    for repo, tool_info in repos_to_build:
        if dry_run:
            result = {
                "path": repo,
                "tool": tool_info["tool"],
                "command": tool_info.get("build_cmd", "N/A"),
                "dry_run": True
            }
            print(json.dumps(result), flush=True)
        else:
            result = build_docs(repo, tool_info)
            print(json.dumps(result), flush=True)


@docs_group.command("serve")
@click.argument("repo_path")
@click.option("--port", default=8000, help="Port to serve on")
@click.option("--open", "open_browser", is_flag=True, help="Open browser automatically")
def docs_serve(repo_path, port, open_browser):
    """Serve documentation locally for preview."""
    docs_info = detect_docs_tool(repo_path)
    
    if not docs_info:
        error = {"error": f"No documentation detected in {repo_path}"}
        print(json.dumps(error), flush=True)
        return
    
    if not docs_info.get("serve_cmd"):
        error = {"error": f"No serve command available for {docs_info['tool']}"}
        print(json.dumps(error), flush=True)
        return
    
    # Update serve command with custom port if needed
    serve_cmd = docs_info["serve_cmd"]
    if "8000" in serve_cmd and port != 8000:
        serve_cmd = serve_cmd.replace("8000", str(port))
    elif docs_info["tool"] == "mkdocs":
        serve_cmd = f"mkdocs serve -a localhost:{port}"
    elif docs_info["tool"] == "hugo":
        serve_cmd = f"hugo server -p {port}"
    
    info = {
        "status": "serving",
        "tool": docs_info["tool"],
        "url": f"http://localhost:{port}",
        "command": serve_cmd
    }
    print(json.dumps(info), flush=True)
    
    # Open browser if requested
    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    
    # Run the serve command
    try:
        run_command(serve_cmd, cwd=repo_path, check=True)
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped"}), flush=True)
    except Exception as e:
        error = {"error": str(e)}
        print(json.dumps(error), flush=True)


@docs_group.command("deploy")
@click.argument("repo_path")
@click.option("--branch", default="gh-pages", help="Branch to deploy to")
@click.option("--message", default="Deploy documentation", help="Commit message")
@click.option("--dry-run", is_flag=True, help="Show what would be deployed")
def docs_deploy(repo_path, branch, message, dry_run):
    """Deploy documentation to GitHub Pages."""
    docs_info = detect_docs_tool(repo_path)
    
    if not docs_info:
        error = {"error": f"No documentation detected in {repo_path}"}
        print(json.dumps(error), flush=True)
        return
    
    # Build docs first
    if not dry_run and docs_info.get("build_cmd"):
        build_result = build_docs(repo_path, docs_info)
        if not build_result["success"]:
            error = {"error": f"Build failed: {build_result['error']}"}
            print(json.dumps(error), flush=True)
            return
    
    output_dir = docs_info.get("output_dir")
    if not output_dir:
        error = {"error": "No output directory configured"}
        print(json.dumps(error), flush=True)
        return
    
    if dry_run:
        result = {
            "status": "dry_run",
            "tool": docs_info["tool"],
            "output_dir": output_dir,
            "branch": branch,
            "message": message
        }
        print(json.dumps(result), flush=True)
        return
    
    # Deploy using ghp-import or git subtree
    try:
        # Check if ghp-import is available
        ghp_check, _ = run_command("which ghp-import", capture_output=True, check=False)
        
        if ghp_check:
            # Use ghp-import
            deploy_cmd = f"ghp-import -n -p -f -m '{message}' -b {branch} {output_dir}"
            run_command(deploy_cmd, cwd=repo_path, check=True)
            method = "ghp-import"
        else:
            # Fallback to git commands
            # This is a simplified version - real implementation would be more robust
            commands = [
                f"git checkout -B {branch}",
                f"git add -f {output_dir}",
                f"git commit -m '{message}'",
                f"git push origin {branch} --force",
                "git checkout -"
            ]
            for cmd in commands:
                run_command(cmd, cwd=repo_path, check=True)
            method = "git"
        
        # Get the deployed URL
        from repoindex.utils import get_remote_url, parse_repo_url
        remote_url = get_remote_url(repo_path)
        owner, repo_name = parse_repo_url(remote_url) if remote_url else (None, None)
        
        result = {
            "status": "deployed",
            "tool": docs_info["tool"],
            "branch": branch,
            "method": method,
            "url": f"https://{owner}.github.io/{repo_name}" if owner and repo_name else None
        }
        print(json.dumps(result), flush=True)
        
    except Exception as e:
        error = {"error": f"Deployment failed: {str(e)}"}
        print(json.dumps(error), flush=True)


@docs_group.command("detect")
@click.argument("repo_path")
def docs_detect(repo_path):
    """Detect documentation tool used in a repository."""
    docs_info = detect_docs_tool(repo_path)
    
    if docs_info:
        print(json.dumps(docs_info), flush=True)
    else:
        result = {
            "path": repo_path,
            "has_docs": False,
            "tool": None
        }
        print(json.dumps(result), flush=True)