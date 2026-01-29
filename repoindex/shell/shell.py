"""
Main shell implementation for repoindex.

Provides an interactive shell with VFS navigation and query commands.
Supports hierarchical tag-based virtual filesystem.
"""

import cmd
import sys
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
import shlex

from ..config import load_config, save_config
from ..utils import find_git_repos_from_config
from ..metadata import get_metadata_store
from ..commands.catalog import get_repository_tags


class RepoIndexShell(cmd.Cmd):
    """Interactive shell for repoindex repository management."""

    intro = """
╔═══════════════════════════════════════════════════════════════════╗
║                   repoindex Interactive Shell                     ║
║                                                                   ║
║  Navigate repositories with hierarchical tag filesystem          ║
║  - /repos/           All repositories                            ║
║  - /by-tag/          Hierarchical tag navigation                 ║
║  - /by-language/     Grouped by programming language             ║
║  - /by-status/       Grouped by git status                       ║
║                                                                   ║
║  VFS: cd, ls, pwd, cp, mv, rm, mkdir, refresh                    ║
║  Files: cat, head, tail, grep (within repos)                     ║
║  Commands: status, query, config                                 ║
║  Shell: !<command> to run bash commands in current directory     ║
║  Type 'help' for available commands, 'exit' or Ctrl+D to quit    ║
╚═══════════════════════════════════════════════════════════════════╝
"""

    def __init__(self):
        """Initialize the shell."""
        super().__init__()
        self.config = load_config()
        self.metadata_store = get_metadata_store()

        # Virtual filesystem state
        self.cwd = Path("/")
        self.repo_paths = []  # Cache repo paths
        self.vfs = self._build_vfs()

        # Real filesystem navigation state
        self.in_real_fs = False
        self.real_fs_path = None
        self.real_fs_repo = None  # Which repo we're browsing

        self.update_prompt()

    def update_prompt(self):
        """Update the shell prompt based on current directory."""
        self.prompt = f"repoindex:{self.cwd}> "

    def _build_vfs(self) -> Dict[str, Any]:
        """Build the virtual filesystem structure with hierarchical tags.

        Returns:
            VFS tree structure
        """
        # Get all repositories
        repo_dirs = self.config.get('repository_directories', [])
        if not repo_dirs:
            repo_dirs = ['.']

        self.repo_paths = find_git_repos_from_config(
            repo_dirs, recursive=False,
            exclude_dirs_config=self.config.get('exclude_directories', [])
        )

        # Build VFS structure
        vfs: Dict[str, Any] = {
            "/": {
                "type": "directory",
                "children": {
                    "repos": {"type": "directory", "children": {}},
                    "by-language": {"type": "directory", "children": {}},
                    "by-tag": {"type": "directory", "children": {}},
                    "by-status": {"type": "directory", "children": {}},
                }
            }
        }

        # Populate repos
        repos_node: Dict[str, Any] = vfs["/"]["children"]["repos"]["children"]
        by_lang_node: Dict[str, Any] = vfs["/"]["children"]["by-language"]["children"]
        by_tag_node: Dict[str, Any] = vfs["/"]["children"]["by-tag"]["children"]
        by_status_node: Dict[str, Any] = vfs["/"]["children"]["by-status"]["children"]

        for repo_path in self.repo_paths:
            repo_name = Path(repo_path).name

            # Add to /repos/
            repos_node[repo_name] = {
                "type": "repository",
                "path": repo_path,
                "children": {}  # Will be populated on-demand with actual files
            }

            # Get metadata for grouping
            metadata = self.metadata_store.get(repo_path)
            if metadata:
                # Group by language
                language = metadata.get('language', 'Unknown')
                if language not in by_lang_node:
                    by_lang_node[language] = {"type": "directory", "children": {}}
                by_lang_node[language]["children"][repo_name] = {
                    "type": "symlink",
                    "target": f"/repos/{repo_name}",
                    "repo_path": repo_path
                }

                # Group by status
                status = metadata.get('status', {})
                if status.get('has_uncommitted_changes'):
                    if "dirty" not in by_status_node:
                        by_status_node["dirty"] = {"type": "directory", "children": {}}
                    by_status_node["dirty"]["children"][repo_name] = {
                        "type": "symlink",
                        "target": f"/repos/{repo_name}",
                        "repo_path": repo_path
                    }
                else:
                    if "clean" not in by_status_node:
                        by_status_node["clean"] = {"type": "directory", "children": {}}
                    by_status_node["clean"]["children"][repo_name] = {
                        "type": "symlink",
                        "target": f"/repos/{repo_name}",
                        "repo_path": repo_path
                    }

            # Build hierarchical tag structure
            tags = get_repository_tags(repo_path, metadata)
            for tag in tags:
                self._add_tag_to_vfs(by_tag_node, tag, repo_name, repo_path)

        return vfs

    def _add_tag_to_vfs(self, tag_root: Dict[str, Any], tag: str, repo_name: str, repo_path: str):
        """Add a repository to the hierarchical tag VFS.

        Args:
            tag_root: Root node of the tag tree (/by-tag/)
            tag: Tag string (e.g., "alex/beta" or "topic:scientific/engineering/ai")
            repo_name: Name of the repository
            repo_path: Full path to repository
        """
        # Parse hierarchical tag
        levels = self._parse_tag_levels(tag)
        if not levels:
            return

        # Navigate/create directory structure
        current = tag_root
        for level in levels:
            if level not in current:
                current[level] = {
                    "type": "directory",
                    "children": {},
                    "tag_path": "/".join(levels[:levels.index(level) + 1])
                }
            current = current[level]["children"]

        # Add symlink to repository at leaf
        current[repo_name] = {
            "type": "symlink",
            "target": f"/repos/{repo_name}",
            "repo_path": repo_path,
            "tag": tag
        }

    def _parse_tag_levels(self, tag: str) -> List[str]:
        """Parse a tag into hierarchical levels.

        Args:
            tag: Tag string (e.g., "alex/beta", "topic:scientific/engineering/ai")

        Returns:
            List of hierarchical levels
        """
        # Handle empty string
        if not tag:
            return []

        # Handle key:value format
        if ':' in tag:
            key, value = tag.split(':', 1)
            if value and '/' in value:
                # Hierarchical: topic:scientific/engineering/ai
                return [key] + value.split('/')
            elif value:
                # Simple: lang:python
                return [key, value]
            else:
                # Just key with no value
                return [key]
        elif '/' in tag:
            # Hierarchical without key: alex/beta
            levels = tag.split('/')
            # Filter out empty parts
            return [level for level in levels if level]
        else:
            # Simple tag: deprecated
            return [tag]

    def _resolve_path(self, path: str) -> Optional[Path]:
        """Resolve a path in the VFS.

        Args:
            path: Path to resolve (absolute or relative)

        Returns:
            Resolved absolute path or None if invalid
        """
        if path.startswith('/'):
            # Absolute path
            resolved = Path(path)
        else:
            # Relative path
            resolved = self.cwd / path

        # Normalize (remove .. and .)
        try:
            resolved = resolved.resolve()
        except OSError:
            return None

        # Ensure it starts with /
        if not str(resolved).startswith('/'):
            resolved = Path('/') / resolved.relative_to(resolved.anchor)

        return resolved

    def _get_node(self, path: Path) -> Optional[Dict[str, Any]]:
        """Get VFS node at path.

        Args:
            path: Path to node

        Returns:
            Node dict or None if not found
        """
        if str(path) == "/":
            return self.vfs["/"]

        parts = str(path).strip('/').split('/')
        node = self.vfs["/"]

        for part in parts:
            if "children" not in node:
                return None
            if part not in node["children"]:
                return None
            node = node["children"][part]

        return node

    def do_pwd(self, arg):
        """Print current working directory."""
        print(self.cwd)

    def do_ls(self, arg):
        """List directory contents.

        Usage: ls [path] [--json]

        By default, shows a nice formatted view. Use --json for JSONL output.
        """
        args = arg.split()
        path_arg = None
        json_output = False

        # Parse arguments
        for a in args:
            if a == '--json':
                json_output = True
            elif not path_arg:
                path_arg = a

        # If in real filesystem mode and no path specified, list current real dir
        if self.in_real_fs and not path_arg:
            self._list_repository_contents(self.real_fs_path, json_output)
            return

        target = self._resolve_path(path_arg if path_arg else '.')
        if not target:
            print(f"ls: invalid path: {path_arg}")
            return

        node = self._get_node(target)

        # If no VFS node but in real filesystem, try real path
        if not node and self.in_real_fs:
            from pathlib import Path as RealPath
            real_target = RealPath(self.real_fs_path) / (path_arg or '.')
            if real_target.exists() and real_target.is_dir():
                self._list_repository_contents(str(real_target), json_output)
                return

        if not node:
            print(f"ls: {target}: No such file or directory")
            return

        # If it's a repository or symlink, show actual filesystem contents
        if node["type"] in ("repository", "symlink"):
            repo_path = node.get("path") or node.get("repo_path")
            if not repo_path:
                print("ls: could not determine repository path")
                return

            self._list_repository_contents(repo_path, json_output)
            return

        if node["type"] != "directory":
            print(f"ls: {target}: Not a directory")
            return

        # List VFS children
        children = node.get("children", {})
        if not children:
            return

        if json_output:
            # JSONL output (opt-in)
            for name, child in sorted(children.items()):
                icon = {
                    "directory": "📂",
                    "repository": "📁",
                    "symlink": "🔗",
                    "file": "📄"
                }.get(child["type"], "❓")

                output = {"name": name, "type": child["type"], "icon": icon}
                if child["type"] == "symlink":
                    output["target"] = child.get("target", "")

                print(json.dumps(output))
        else:
            # Nice formatted output (default)
            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Name", style="green")
            table.add_column("Type", style="yellow")
            table.add_column("Target", style="blue")

            for name, child in sorted(children.items()):
                icon = {
                    "directory": "📂",
                    "repository": "📁",
                    "symlink": "🔗",
                    "file": "📄"
                }.get(child["type"], "❓")

                target = child.get("target", "") if child["type"] == "symlink" else ""
                table.add_row(f"{icon} {name}", child["type"], target)

            console.print(table)

    def do_cd(self, arg):
        """Change directory.

        Usage: cd <path>
        """
        if not arg:
            # cd with no args goes to root VFS
            self.cwd = Path("/")
            self.in_real_fs = False
            self.real_fs_path = None
            self.real_fs_repo = None
            self.update_prompt()
            return

        # Handle relative paths in real filesystem mode
        if self.in_real_fs and not arg.startswith('/'):
            # Navigate within real filesystem
            from pathlib import Path as RealPath
            new_path = (RealPath(self.real_fs_path) / arg).resolve()

            if not new_path.exists():
                print(f"cd: {arg}: No such file or directory")
                return

            if not new_path.is_dir():
                print(f"cd: {arg}: Not a directory")
                return

            # Check if we're trying to navigate outside the repository
            try:
                relative = new_path.relative_to(self.real_fs_repo)
                # Still within repo - update paths
                self.real_fs_path = str(new_path)
                repo_name = RealPath(self.real_fs_repo).name
                self.cwd = Path(f"/repos/{repo_name}") / relative
                self.update_prompt()
                return
            except ValueError:
                # Trying to go outside repo - switch back to VFS mode
                # Go to /repos/ (parent of all repositories)
                self.in_real_fs = False
                self.real_fs_path = None
                self.real_fs_repo = None
                self.cwd = Path("/repos")
                self.update_prompt()
                return

        # VFS navigation
        target = self._resolve_path(arg)
        if not target:
            print(f"cd: {arg}: Invalid path")
            return

        node = self._get_node(target)

        # If no VFS node but we're in a repo, try real filesystem
        if not node and self.in_real_fs:
            from pathlib import Path as RealPath
            new_path = (RealPath(self.real_fs_path) / arg).resolve()

            if new_path.exists() and new_path.is_dir():
                self.real_fs_path = str(new_path)
                repo_name = RealPath(self.real_fs_repo).name
                relative = new_path.relative_to(self.real_fs_repo)
                self.cwd = Path(f"/repos/{repo_name}") / relative
                self.update_prompt()
                return

            print(f"cd: {target}: No such file or directory")
            return

        if not node:
            print(f"cd: {target}: No such file or directory")
            return

        if node["type"] == "symlink":
            # Follow symlink
            target = self._resolve_path(node["target"])
            if not target:
                print("cd: broken symlink")
                return
            node = self._get_node(target)

        # Check if it's a repository - enter real filesystem mode
        if node["type"] == "repository":
            repo_path = node.get("path")
            if repo_path:
                from pathlib import Path as RealPath
                if RealPath(repo_path).exists():
                    self.in_real_fs = True
                    self.real_fs_path = repo_path
                    self.real_fs_repo = repo_path
                    self.cwd = target
                    self.update_prompt()
                    return

        if node["type"] != "directory" and node["type"] != "repository":
            print(f"cd: {target}: Not a directory")
            return

        # Normal VFS navigation
        self.in_real_fs = False
        self.real_fs_path = None
        self.real_fs_repo = None
        self.cwd = target
        self.update_prompt()

    def do_query(self, arg):
        """Query repositories with expression.

        Usage: query <expression>

        Examples:
            query "stars > 10"
            query "language == 'Python'"
            query "stars > 10 and language ~= 'python'"
        """
        if not arg:
            print("Usage: query <expression>")
            return

        # Import query engine
        from ..query import query_repositories

        # Execute query
        try:
            results = query_repositories(arg, self.metadata_store, self.config)

            # Output as JSONL
            for result in results:
                print(json.dumps({
                    "name": Path(result).name,
                    "path": result
                }))
        except Exception as e:
            print(f"query error: {e}", file=sys.stderr)

    def do_find(self, arg):
        """Find repositories by criteria.

        Usage: find [options]

        Options:
            --language LANG     Filter by language
            --tag TAG          Filter by tag
            --dirty            Show repos with uncommitted changes
            --unpushed         Show repos with unpushed commits
        """
        # Parse arguments
        args = arg.split()
        filters = {}

        i = 0
        while i < len(args):
            if args[i] == '--language' and i + 1 < len(args):
                filters['language'] = args[i + 1]
                i += 2
            elif args[i] == '--tag' and i + 1 < len(args):
                filters['tag'] = args[i + 1]
                i += 2
            elif args[i] == '--dirty':
                filters['dirty'] = True
                i += 1
            elif args[i] == '--unpushed':
                filters['unpushed'] = True
                i += 1
            else:
                i += 1

        # TODO: Implement filtering logic
        print(f"find with filters: {filters}")

    def do_status(self, arg):
        """Show repository status.

        Usage: status [vfs_path] [--refresh]

        Examples:
            status                    # Status of all repos
            status /repos/repoindex       # Status of specific repo
            status --refresh          # Refresh metadata first
        """
        # Parse arguments
        args = arg.split()
        vfs_path = '/'
        refresh = False

        for i, a in enumerate(args):
            if a == '--refresh':
                refresh = True
            elif not a.startswith('-'):
                vfs_path = a

        # Import status command
        from ..commands.status import status_handler
        import click

        try:
            # Create minimal context and invoke
            status_handler.callback(
                vfs_path=vfs_path,
                dir=None,
                recursive=False,
                no_pages=False,
                no_pypi=False,
                no_dedup=False,
                tag_filters=(),
                all_tags=False,
                refresh=refresh,
                table=True,  # Shell always uses table format
                progress=False,
                quiet=False
            )
        except click.Abort:
            pass
        except Exception as e:
            print(f"status: error: {e}")


    def do_publish(self, arg):
        """Package publishing is handled by external tools.

        repoindex focuses on metadata and events - not publishing.

        Use your package manager directly:
        - Python: twine upload dist/*
        - npm: npm publish
        - Rust: cargo publish

        repoindex can detect when packages are published via the events system.
        """
        print("Package publishing is handled by external tools.")
        print()
        print("repoindex focuses on metadata and events - not publishing.")
        print("Use your package manager directly:")
        print("  - Python: twine upload dist/*")
        print("  - npm: npm publish")
        print("  - Rust: cargo publish")
        print()
        print("Tip: repoindex can detect when packages are published via 'events' command.")

    def do_export(self, arg):
        """Export repository metadata as JSON.

        Usage: export [path]

        repoindex provides metadata via the VFS - export as JSONL for integration.

        Examples:
            ls /repos --json          # List repos as JSON
            cat /repos/myproject      # View repo metadata as JSON
            ls /by-language/Python    # List Python repos

        For portfolio generation, use external tools that consume repoindex data.
        """
        print("Export via the VFS - repoindex metadata is available as JSON.")
        print()
        print("Examples:")
        print("  ls /repos --json          # List repos as JSON")
        print("  cat /repos/myproject      # View repo metadata as JSON")
        print("  ls /by-language/Python    # List Python repos")
        print()
        print("For portfolio generation, use external tools that consume repoindex data.")


    def do_config(self, arg):
        """Configuration management.

        Usage: config show
                config repos list
                config repos add <path>
                config repos remove <path>
                config repos clear

        Examples:
            config show                  # Show full configuration
            config repos list            # List repository directories
            config repos add ~/projects  # Add repository directory
            config repos remove ~/old    # Remove directory
        """
        if not arg:
            print("Usage: config <subcommand>")
            print("Subcommands: show, repos")
            return

        # Parse subcommand
        parts = arg.split(maxsplit=1)
        subcommand = parts[0]
        rest = parts[1] if len(parts) > 1 else ''

        if subcommand == 'show':
            # Show configuration
            from ..commands.config import show_config
            import click
            try:
                show_config.callback()
            except click.Abort:
                pass
            except Exception as e:
                print(f"config show: error: {e}")

        elif subcommand == 'repos':
            # Handle repos subcommands
            if not rest:
                print("Usage: config repos <add|remove|list|clear>")
                return

            repo_parts = rest.split(maxsplit=1)
            repo_cmd = repo_parts[0]
            repo_args = repo_parts[1] if len(repo_parts) > 1 else ''

            from ..commands.config_repos import repos_add, repos_remove, repos_list, repos_clear
            import click

            try:
                if repo_cmd == 'list':
                    repos_list.callback(json_output=False)
                elif repo_cmd == 'add':
                    if not repo_args:
                        print("Usage: config repos add <path>")
                        return
                    repos_add.callback(path=repo_args, refresh=False)
                    # Refresh VFS after adding
                    print("\n[yellow]Refreshing VFS...[/yellow]")
                    self.config = load_config()
                    self.vfs = self._build_vfs()
                    print("[green]✓[/green] VFS refreshed")
                elif repo_cmd == 'remove':
                    if not repo_args:
                        print("Usage: config repos remove <path>")
                        return
                    repos_remove.callback(path=repo_args)
                    # Refresh VFS after removing
                    print("\n[yellow]Refreshing VFS...[/yellow]")
                    self.config = load_config()
                    self.vfs = self._build_vfs()
                    print("[green]✓[/green] VFS refreshed")
                elif repo_cmd == 'clear':
                    repos_clear.callback(yes=False)
                    # Refresh VFS after clearing
                    print("\n[yellow]Refreshing VFS...[/yellow]")
                    self.config = load_config()
                    self.vfs = self._build_vfs()
                    print("[green]✓[/green] VFS refreshed")
                else:
                    print(f"Unknown repos subcommand: {repo_cmd}")
                    print("Available: add, remove, list, clear")
            except click.Abort:
                pass
            except Exception as e:
                print(f"config repos {repo_cmd}: error: {e}")
        else:
            print(f"Unknown config subcommand: {subcommand}")
            print("Available: show, repos")


    def do_cp(self, arg):
        """Copy/link repository to add tags.

        Usage: cp <source> <dest>

        Examples:
            cp /repos/myproject /by-tag/alex/beta
            cp myproject /by-tag/topic/ml/research

        This adds the tag to the repository without removing existing tags.
        """
        args = shlex.split(arg)
        if len(args) != 2:
            print("Usage: cp <source> <dest>")
            return

        source_path, dest_path = args

        # Resolve source
        source = self._resolve_path(source_path)
        if not source:
            print(f"cp: invalid source path: {source_path}")
            return

        source_node = self._get_node(source)
        if not source_node:
            print(f"cp: {source}: No such file or directory")
            return

        # Get repository path
        repo_path = None
        repo_name = None

        if source_node["type"] == "repository":
            repo_path = source_node.get("path")
            repo_name = Path(source).name
        elif source_node["type"] == "symlink":
            repo_path = source_node.get("repo_path")
            repo_name = Path(source).name
        else:
            print(f"cp: {source}: Not a repository")
            return

        if not repo_path:
            print("cp: could not determine repository path")
            return

        # Resolve destination
        dest = self._resolve_path(dest_path)
        if not dest:
            print(f"cp: invalid destination path: {dest_path}")
            return

        # Extract tag from destination path
        dest_str = str(dest)
        if not dest_str.startswith('/by-tag/'):
            print("cp: destination must be under /by-tag/")
            return

        # Parse tag from path
        tag = self._path_to_tag(dest_str)
        if not tag:
            print(f"cp: could not extract tag from path: {dest_str}")
            return

        # Add tag to repository
        self._add_tag_to_repo(repo_path, tag)
        print(f"Added tag '{tag}' to {repo_name}")

        # Rebuild VFS to reflect changes
        self.vfs = self._build_vfs()

    def do_mv(self, arg):
        """Move repository between tags (retag).

        Usage: mv <source> <dest>

        Examples:
            mv /by-tag/alex/beta/myproject /by-tag/alex/production
            mv /by-tag/topic/ml/myproject /by-tag/topic/nlp

        This removes the old tag and adds the new tag.
        """
        args = shlex.split(arg)
        if len(args) != 2:
            print("Usage: mv <source> <dest>")
            return

        source_path, dest_path = args

        # Resolve source
        source = self._resolve_path(source_path)
        if not source:
            print(f"mv: invalid source path: {source_path}")
            return

        source_node = self._get_node(source)
        if not source_node:
            print(f"mv: {source}: No such file or directory")
            return

        # Get repository path and current tag
        repo_path = source_node.get("repo_path")
        old_tag = source_node.get("tag")
        repo_name = Path(source).name

        if not repo_path:
            print("mv: could not determine repository path")
            return

        # Check source is in /by-tag/
        source_str = str(source)
        if not source_str.startswith('/by-tag/'):
            print("mv: source must be under /by-tag/")
            return

        # Resolve destination
        dest = self._resolve_path(dest_path)
        if not dest:
            print(f"mv: invalid destination path: {dest_path}")
            return

        dest_str = str(dest)
        if not dest_str.startswith('/by-tag/'):
            print("mv: destination must be under /by-tag/")
            return

        # Parse new tag from destination
        new_tag = self._path_to_tag(dest_str)
        if not new_tag:
            print(f"mv: could not extract tag from path: {dest_str}")
            return

        # Remove old tag and add new tag
        if old_tag:
            self._remove_tag_from_repo(repo_path, old_tag)
        self._add_tag_to_repo(repo_path, new_tag)
        print(f"Moved {repo_name} from '{old_tag}' to '{new_tag}'")

        # Rebuild VFS
        self.vfs = self._build_vfs()

    def do_rm(self, arg):
        """Remove repository from tag (unlink).

        Usage: rm <path>

        Examples:
            rm /by-tag/alex/beta/myproject
            rm /by-tag/topic/ml/research/myproject

        This removes the tag from the repository.
        """
        args = shlex.split(arg)
        if len(args) != 1:
            print("Usage: rm <path>")
            return

        path_arg = args[0]

        # Resolve path
        path = self._resolve_path(path_arg)
        if not path:
            print(f"rm: invalid path: {path_arg}")
            return

        node = self._get_node(path)
        if not node:
            print(f"rm: {path}: No such file or directory")
            return

        # Must be a symlink in /by-tag/
        if node["type"] != "symlink":
            print(f"rm: {path}: Not a tagged repository")
            return

        path_str = str(path)
        if not path_str.startswith('/by-tag/'):
            print("rm: can only remove tags under /by-tag/")
            return

        # Get repository path and tag
        repo_path = node.get("repo_path")
        tag = node.get("tag")
        repo_name = Path(path).name

        if not repo_path or not tag:
            print("rm: could not determine repository or tag")
            return

        # Remove tag
        self._remove_tag_from_repo(repo_path, tag)
        print(f"Removed tag '{tag}' from {repo_name}")

        # Rebuild VFS
        self.vfs = self._build_vfs()

    def do_mkdir(self, arg):
        """Create tag namespace.

        Usage: mkdir [-p] <path>

        Examples:
            mkdir /by-tag/alex/production
            mkdir -p /by-tag/work/client/acme

        Creates a tag hierarchy. Use -p to create parent directories.
        """
        args = shlex.split(arg)
        if not args:
            print("Usage: mkdir [-p] <path>")
            return

        _create_parents = False  # noqa: F841 - parsed but mkdir creates parents by default
        path_arg = None

        for arg in args:
            if arg == '-p':
                _create_parents = True
            else:
                path_arg = arg

        if not path_arg:
            print("Usage: mkdir [-p] <path>")
            return

        # Resolve path
        path = self._resolve_path(path_arg)
        if not path:
            print(f"mkdir: invalid path: {path_arg}")
            return

        path_str = str(path)
        if not path_str.startswith('/by-tag/'):
            print("mkdir: can only create directories under /by-tag/")
            return

        # Check if already exists
        if self._get_node(path):
            print(f"mkdir: {path}: Directory already exists")
            return

        # For now, just show success - the directory will be created
        # automatically when a repo is tagged
        print(f"Tag namespace '{path_str}' ready for use")

    def _list_repository_contents(self, repo_path: str, json_output: bool = False):
        """List actual filesystem contents of a repository.

        Args:
            repo_path: Absolute path to repository
            json_output: Whether to output as JSONL
        """

        repo_path_obj = Path(repo_path)

        if not repo_path_obj.exists():
            print(f"Error: Repository path does not exist: {repo_path}")
            return

        # Get directory contents
        try:
            entries = []
            for item in sorted(repo_path_obj.iterdir()):
                # Skip .git directory for cleaner output
                if item.name == '.git':
                    continue

                entry = {
                    'name': item.name,
                    'type': 'directory' if item.is_dir() else 'file',
                    'size': item.stat().st_size if item.is_file() else None
                }
                entries.append(entry)

            if json_output:
                for entry in entries:
                    print(json.dumps(entry))
            else:
                # Rich table output
                from rich.console import Console
                from rich.table import Table

                console = Console()
                table = Table(show_header=True, header_style="bold cyan",
                            title=f"Contents of {repo_path_obj.name}")
                table.add_column("Name", style="green")
                table.add_column("Type", style="blue")
                table.add_column("Size", justify="right", style="dim")

                for entry in entries:
                    icon = '📁' if entry['type'] == 'directory' else '📄'
                    size_str = ''
                    if entry['size'] is not None:
                        # Format size nicely
                        size = entry['size']
                        if size < 1024:
                            size_str = f"{size}B"
                        elif size < 1024 * 1024:
                            size_str = f"{size/1024:.1f}KB"
                        else:
                            size_str = f"{size/(1024*1024):.1f}MB"

                    table.add_row(
                        f"{icon} {entry['name']}",
                        entry['type'],
                        size_str
                    )

                console.print(table)

        except PermissionError:
            print(f"Error: Permission denied accessing {repo_path}")

    def _resolve_vfs_path_to_repos(self, vfs_path: str) -> List[str]:
        """Resolve a VFS path to repository paths.

        Args:
            vfs_path: VFS path (e.g., /repos/repoindex or /by-tag/alex/beta)

        Returns:
            List of repository absolute paths
        """
        from ..git_ops.utils import get_repos_from_vfs_path

        try:
            return get_repos_from_vfs_path(vfs_path)
        except Exception:
            # Fallback: try to resolve directly through VFS
            node = self._get_node(Path(vfs_path))
            if not node:
                return []

            if node["type"] == "repository":
                return [node.get("path")]
            elif node["type"] == "symlink":
                return [node.get("repo_path")]

            return []

    def _path_to_tag(self, vfs_path: str) -> Optional[str]:
        """Convert a VFS path to a tag.

        Args:
            vfs_path: VFS path (e.g., /by-tag/alex/beta or /by-tag/topic/scientific/ai)

        Returns:
            Tag string (e.g., "alex/beta" or "topic:scientific/ai")
        """
        if not vfs_path.startswith('/by-tag/'):
            return None

        # Remove /by-tag/ prefix and repo name (if present)
        parts = vfs_path[8:].rstrip('/').split('/')

        # Filter out empty parts
        parts = [p for p in parts if p]

        if not parts:
            return None

        # Check if this looks like a key:value hierarchy
        # Heuristic: if first part is a known tag key (repo, dir, lang, etc.)
        # treat as key:value format
        known_keys = {'repo', 'dir', 'lang', 'language', 'topic', 'status',
                      'license', 'org', 'type', 'has', 'ci', 'visibility',
                      'fork', 'archived', 'stars'}

        if parts[0] in known_keys and len(parts) > 1:
            # Format as key:value with hierarchical path
            key = parts[0]
            value = '/'.join(parts[1:])
            return f"{key}:{value}"
        else:
            # Simple hierarchical tag
            return '/'.join(parts)

    def _add_tag_to_repo(self, repo_path: str, tag: str):
        """Add a tag to a repository.

        Args:
            repo_path: Full path to repository
            tag: Tag to add
        """
        # Load config
        config = load_config()

        # Get existing tags
        repo_tags = config.get("repository_tags", {})
        existing_tags = repo_tags.get(repo_path, [])

        # Add new tag if not already present
        if tag not in existing_tags:
            existing_tags.append(tag)
            repo_tags[repo_path] = existing_tags
            config["repository_tags"] = repo_tags

            # Save config
            save_config(config)

    def _remove_tag_from_repo(self, repo_path: str, tag: str):
        """Remove a tag from a repository.

        Args:
            repo_path: Full path to repository
            tag: Tag to remove
        """
        # Load config
        config = load_config()

        # Get existing tags
        repo_tags = config.get("repository_tags", {})
        existing_tags = repo_tags.get(repo_path, [])

        # Remove tag if present
        if tag in existing_tags:
            existing_tags.remove(tag)
            if existing_tags:
                repo_tags[repo_path] = existing_tags
            else:
                # Remove repo entry if no tags left
                del repo_tags[repo_path]
            config["repository_tags"] = repo_tags

            # Save config
            save_config(config)

    def do_refresh(self, arg):
        """Refresh the VFS to reflect config changes.

        Usage: refresh
        """
        print("Refreshing VFS...")
        self.config = load_config()
        self.vfs = self._build_vfs()
        print("VFS refreshed")

    def do_exit(self, arg):
        """Exit the shell."""
        print("\nGoodbye!")
        return True

    def do_quit(self, arg):
        """Exit the shell."""
        return self.do_exit(arg)

    def do_EOF(self, arg):
        """Handle Ctrl+D to exit."""
        print()  # New line
        return self.do_exit(arg)

    def emptyline(self):
        """Do nothing on empty line."""
        pass

    def do_cat(self, arg):
        """Display file contents.

        Usage: cat <file>
        """
        if not arg:
            print("Usage: cat <file>")
            return

        if not self.in_real_fs:
            print("cat: only works within repository directories")
            return

        from pathlib import Path as RealPath
        file_path = RealPath(self.real_fs_path) / arg

        if not file_path.exists():
            print(f"cat: {arg}: No such file")
            return

        if not file_path.is_file():
            print(f"cat: {arg}: Is a directory")
            return

        try:
            with open(file_path, 'r') as f:
                print(f.read(), end='')
        except UnicodeDecodeError:
            print(f"cat: {arg}: Cannot display binary file")
        except PermissionError:
            print(f"cat: {arg}: Permission denied")

    def do_head(self, arg):
        """Display first lines of a file.

        Usage: head [-n NUM] <file>
        """
        import shlex
        args = shlex.split(arg)

        lines = 10
        file_arg = None

        i = 0
        while i < len(args):
            if args[i] == '-n' and i + 1 < len(args):
                try:
                    lines = int(args[i + 1])
                    i += 2
                except ValueError:
                    print(f"head: invalid line count: {args[i + 1]}")
                    return
            else:
                file_arg = args[i]
                i += 1

        if not file_arg:
            print("Usage: head [-n NUM] <file>")
            return

        if not self.in_real_fs:
            print("head: only works within repository directories")
            return

        from pathlib import Path as RealPath
        file_path = RealPath(self.real_fs_path) / file_arg

        if not file_path.exists():
            print(f"head: {file_arg}: No such file")
            return

        if not file_path.is_file():
            print(f"head: {file_arg}: Is a directory")
            return

        try:
            with open(file_path, 'r') as f:
                for i, line in enumerate(f):
                    if i >= lines:
                        break
                    print(line, end='')
        except UnicodeDecodeError:
            print(f"head: {file_arg}: Cannot display binary file")
        except PermissionError:
            print(f"head: {file_arg}: Permission denied")

    def do_tail(self, arg):
        """Display last lines of a file.

        Usage: tail [-n NUM] <file>
        """
        import shlex
        args = shlex.split(arg)

        lines = 10
        file_arg = None

        i = 0
        while i < len(args):
            if args[i] == '-n' and i + 1 < len(args):
                try:
                    lines = int(args[i + 1])
                    i += 2
                except ValueError:
                    print(f"tail: invalid line count: {args[i + 1]}")
                    return
            else:
                file_arg = args[i]
                i += 1

        if not file_arg:
            print("Usage: tail [-n NUM] <file>")
            return

        if not self.in_real_fs:
            print("tail: only works within repository directories")
            return

        from pathlib import Path as RealPath
        file_path = RealPath(self.real_fs_path) / file_arg

        if not file_path.exists():
            print(f"tail: {file_arg}: No such file")
            return

        if not file_path.is_file():
            print(f"tail: {file_arg}: Is a directory")
            return

        try:
            with open(file_path, 'r') as f:
                all_lines = f.readlines()
                for line in all_lines[-lines:]:
                    print(line, end='')
        except UnicodeDecodeError:
            print(f"tail: {file_arg}: Cannot display binary file")
        except PermissionError:
            print(f"tail: {file_arg}: Permission denied")

    def do_grep(self, arg):
        """Search for patterns in files.

        Usage: grep [-i] <pattern> <file>
        """
        import shlex
        args = shlex.split(arg)

        case_insensitive = False
        pattern = None
        file_arg = None

        i = 0
        while i < len(args):
            if args[i] == '-i':
                case_insensitive = True
                i += 1
            elif not pattern:
                pattern = args[i]
                i += 1
            elif not file_arg:
                file_arg = args[i]
                i += 1
            else:
                i += 1

        if not pattern or not file_arg:
            print("Usage: grep [-i] <pattern> <file>")
            return

        if not self.in_real_fs:
            print("grep: only works within repository directories")
            return

        from pathlib import Path as RealPath
        file_path = RealPath(self.real_fs_path) / file_arg

        if not file_path.exists():
            print(f"grep: {file_arg}: No such file")
            return

        if not file_path.is_file():
            print(f"grep: {file_arg}: Is a directory")
            return

        try:
            import re
            flags = re.IGNORECASE if case_insensitive else 0
            pattern_re = re.compile(pattern, flags)

            with open(file_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    if pattern_re.search(line):
                        print(f"{line_num}:{line}", end='')

        except re.error as e:
            print(f"grep: invalid pattern: {e}")
        except UnicodeDecodeError:
            print(f"grep: {file_arg}: Cannot search binary file")
        except PermissionError:
            print(f"grep: {file_arg}: Permission denied")


    def default(self, line):
        """Handle unknown commands."""
        # Check if this is a shell escape command
        if line.startswith('!'):
            self._execute_shell_command(line[1:].strip())
        # Check if this is a piped command
        elif '|' in line:
            self._execute_pipeline(line)
        else:
            print(f"Unknown command: {line}")
            print("Type 'help' for available commands")

    def _execute_shell_command(self, command):
        """Execute a shell command in the appropriate directory."""
        import subprocess

        if not command:
            print("Usage: !<command>")
            return

        # Determine working directory
        if self.in_real_fs and self.real_fs_path:
            cwd = self.real_fs_path
        else:
            # In VFS mode - use current actual directory
            import os
            cwd = os.getcwd()
            print("Note: Running in current directory (not in a repository)")

        try:
            # Run the command
            subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                text=True
            )
        except KeyboardInterrupt:
            print("\n^C")
        except Exception as e:
            print(f"Error executing command: {e}")

    def _execute_pipeline(self, line):
        """Execute a pipeline of commands."""
        import io
        import sys

        # Split by pipe
        commands = [cmd.strip() for cmd in line.split('|')]

        # Start with no input
        pipeline_input = None

        for i, command in enumerate(commands):
            # Parse command and arguments
            parts = command.split(maxsplit=1)
            cmd_name = parts[0] if parts else ''
            cmd_args = parts[1] if len(parts) > 1 else ''

            # Handle pipeline-aware commands (head, tail, grep)
            if cmd_name in ('head', 'tail', 'grep') and pipeline_input is not None:
                # Process pipeline input with the filter command
                pipeline_input = self._process_pipeline_filter(cmd_name, cmd_args, pipeline_input)

                # If this is the last command, print the result
                if i == len(commands) - 1:
                    print(pipeline_input)
                continue

            # For other commands, capture their output
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

            try:
                # Try to execute as a shell command
                method_name = f'do_{cmd_name}'
                if hasattr(self, method_name):
                    method = getattr(self, method_name)
                    method(cmd_args)
                else:
                    # Restore stdout and print error
                    output = sys.stdout.getvalue()
                    sys.stdout = old_stdout
                    print(f"Unknown command in pipeline: {cmd_name}")
                    return

                # Get the output
                output = sys.stdout.getvalue()
                sys.stdout = old_stdout

                # If this is the last command, print it
                if i == len(commands) - 1:
                    print(output, end='')
                else:
                    # Pass to next command
                    pipeline_input = output

            except Exception as e:
                sys.stdout = old_stdout
                print(f"Error in pipeline at '{command}': {e}")
                return

    def _process_pipeline_filter(self, cmd_name, args, input_text):
        """Process input text through a filter command (head/tail/grep)."""
        import shlex
        import re

        if cmd_name == 'head':
            # Parse -n argument
            lines = 10
            try:
                parsed_args = shlex.split(args)
                for i, arg in enumerate(parsed_args):
                    if arg == '-n' and i + 1 < len(parsed_args):
                        lines = int(parsed_args[i + 1])
            except (ValueError, IndexError):
                pass

            # Return first N lines
            input_lines = input_text.split('\n')
            return '\n'.join(input_lines[:lines])

        elif cmd_name == 'tail':
            # Parse -n argument
            lines = 10
            try:
                parsed_args = shlex.split(args)
                for i, arg in enumerate(parsed_args):
                    if arg == '-n' and i + 1 < len(parsed_args):
                        lines = int(parsed_args[i + 1])
            except (ValueError, IndexError):
                pass

            # Return last N lines
            input_lines = input_text.split('\n')
            return '\n'.join(input_lines[-lines:])

        elif cmd_name == 'grep':
            # Parse pattern and flags
            try:
                parsed_args = shlex.split(args)
                case_insensitive = '-i' in parsed_args
                pattern = None

                for arg in parsed_args:
                    if arg != '-i' and not pattern:
                        pattern = arg
                        break

                if pattern:
                    flags = re.IGNORECASE if case_insensitive else 0
                    pattern_re = re.compile(pattern, flags)

                    # Filter lines that match
                    result_lines = []
                    for line in input_text.split('\n'):
                        if pattern_re.search(line):
                            result_lines.append(line)

                    return '\n'.join(result_lines)
            except (re.error, ValueError):
                pass

            return input_text

        return input_text


def run_shell():
    """Run the interactive shell."""
    try:
        shell = RepoIndexShell()
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\n\nInterrupted. Goodbye!")
        sys.exit(0)
