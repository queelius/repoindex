"""
MCP Server implementation for repoindex.

Implements the Model Context Protocol (MCP) to expose repoindex functionality
to LLM tools like Claude Code.

Architecture:
    MCPServer uses service layer (RepositoryService, TagService, EventService)
    to provide consistent, well-abstracted access to repoindex functionality.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta

# Domain layer
from ..domain import Repository, Tag, TagSource, Event

# Service layer
from ..services import RepositoryService, TagService, EventService

# Infrastructure layer
from ..infra import GitClient, GitHubClient, FileStore

# Config
from ..config import load_config

# Events parsing
from ..events import parse_timespec

logger = logging.getLogger(__name__)


@dataclass
class Resource:
    """Represents an MCP resource (read-only data)."""
    uri: str
    name: str
    description: str
    mime_type: str = "application/json"


@dataclass
class Tool:
    """Represents an MCP tool (action)."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable


@dataclass
class MCPContext:
    """
    Shared context for MCP handlers.

    Holds service instances and configuration to avoid repetitive
    initialization in each handler.
    """
    config: Dict[str, Any]
    repo_service: RepositoryService
    tag_service: TagService
    event_service: EventService

    @classmethod
    def create(cls) -> 'MCPContext':
        """Create context with default services."""
        config = load_config()
        config_path = Path("~/.repoindex/config.json").expanduser()

        # Infrastructure
        git_client = GitClient()
        github_client = GitHubClient()
        file_store = FileStore(config_path)

        # Services
        repo_service = RepositoryService(
            config=config,
            git_client=git_client,
            github_client=github_client
        )
        tag_service = TagService(config_store=file_store)
        event_service = EventService(git_client=git_client)

        return cls(
            config=config,
            repo_service=repo_service,
            tag_service=tag_service,
            event_service=event_service
        )

    def discover_repos(self) -> List[Repository]:
        """Discover all repositories from config."""
        return list(self.repo_service.discover())

    def find_repo_by_name(self, name: str) -> Optional[Repository]:
        """Find a repository by name."""
        for repo in self.repo_service.discover():
            if repo.name == name:
                return repo
        return None


@dataclass
class MCPServer:
    """
    repoindex MCP Server.

    Exposes repoindex functionality as MCP resources and tools.
    """
    resources: Dict[str, Resource] = field(default_factory=dict)
    tools: Dict[str, Tool] = field(default_factory=dict)
    resource_handlers: Dict[str, Callable] = field(default_factory=dict)

    def register_resource(self, uri_pattern: str, name: str, description: str,
                         handler: Callable, mime_type: str = "application/json"):
        """Register a resource with its handler."""
        resource = Resource(
            uri=uri_pattern,
            name=name,
            description=description,
            mime_type=mime_type
        )
        self.resources[uri_pattern] = resource
        self.resource_handlers[uri_pattern] = handler
        logger.debug(f"Registered resource: {uri_pattern}")

    def register_tool(self, name: str, description: str,
                     input_schema: Dict[str, Any], handler: Callable):
        """Register a tool with its handler."""
        tool = Tool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler
        )
        self.tools[name] = tool
        logger.debug(f"Registered tool: {name}")

    def list_resources(self) -> List[Dict[str, Any]]:
        """List all available resources."""
        return [
            {
                "uri": r.uri,
                "name": r.name,
                "description": r.description,
                "mimeType": r.mime_type
            }
            for r in self.resources.values()
        ]

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema
            }
            for t in self.tools.values()
        ]

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource by URI."""
        # Try exact match first
        if uri in self.resource_handlers:
            return self.resource_handlers[uri]()

        # Try pattern matching
        for pattern, handler in self.resource_handlers.items():
            if self._match_uri_pattern(pattern, uri):
                params = self._extract_uri_params(pattern, uri)
                return handler(**params)

        raise ValueError(f"Unknown resource: {uri}")

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool by name with arguments."""
        if name not in self.tools:
            raise ValueError(f"Unknown tool: {name}")

        tool = self.tools[name]
        return tool.handler(**arguments)

    def _match_uri_pattern(self, pattern: str, uri: str) -> bool:
        """Check if a URI matches a pattern with {param} placeholders."""
        import re
        # Convert pattern to regex
        regex_pattern = re.sub(r'\{(\w+)\}', r'([^/]+)', pattern)
        regex_pattern = f"^{regex_pattern}$"
        return bool(re.match(regex_pattern, uri))

    def _extract_uri_params(self, pattern: str, uri: str) -> Dict[str, str]:
        """Extract parameters from a URI given a pattern."""
        import re
        # Find all parameter names
        param_names = re.findall(r'\{(\w+)\}', pattern)

        # Convert pattern to regex with capture groups
        regex_pattern = re.sub(r'\{(\w+)\}', r'([^/]+)', pattern)
        regex_pattern = f"^{regex_pattern}$"

        match = re.match(regex_pattern, uri)
        if not match:
            return {}

        return dict(zip(param_names, match.groups()))


def create_mcp_server() -> MCPServer:
    """
    Create and configure the repoindex MCP server.

    Returns:
        Configured MCPServer instance
    """
    server = MCPServer()
    ctx = MCPContext.create()

    # === RESOURCE HANDLERS ===

    def list_repos():
        """List all repositories with basic metadata."""
        repos = ctx.discover_repos()
        result = []

        for repo in repos:
            # Get tags via service
            tags = ctx.tag_service.get_tag_strings(repo)

            result.append({
                'path': repo.path,
                'name': repo.name,
                'language': repo.language,
                'tags': tags,
                'has_package': repo.package is not None and repo.package.published
            })

        return {'repositories': result, 'count': len(result)}

    def get_repo(name: str):
        """Get full metadata for one repository."""
        repo = ctx.find_repo_by_name(name)

        if not repo:
            return {'error': f'Repository not found: {name}'}

        # Enrich with status and tags
        repo = ctx.repo_service.get_status(repo)
        tags = ctx.tag_service.get_tag_strings(repo)

        result = repo.to_dict()
        result['tags'] = tags
        return result

    def get_repo_status(name: str):
        """Get git status for one repository."""
        repo = ctx.find_repo_by_name(name)

        if not repo:
            return {'error': f'Repository not found: {name}'}

        repo = ctx.repo_service.get_status(repo)
        return {
            'name': name,
            'path': repo.path,
            'status': repo.status.to_dict()
        }

    def get_repo_package(name: str):
        """Get package info for one repository."""
        repo = ctx.find_repo_by_name(name)

        if not repo:
            return {'error': f'Repository not found: {name}'}

        return {
            'name': name,
            'path': repo.path,
            'package': repo.package.to_dict() if repo.package else {}
        }

    def list_tags():
        """List all tags."""
        repos = ctx.discover_repos()
        all_tags = ctx.tag_service.get_unique_tags(repos)
        return {'tags': sorted(list(all_tags)), 'count': len(all_tags)}

    def get_tag_tree():
        """Get hierarchical tag view."""
        repos = ctx.discover_repos()
        all_tags = ctx.tag_service.get_unique_tags(repos)

        # Build tree structure
        tree: Dict[str, Any] = {}
        for tag_str in sorted(all_tags):
            parts = tag_str.replace(':', '/').split('/')
            node = tree
            for part in parts:
                if part not in node:
                    node[part] = {}
                node = node[part]

        return {'tree': tree}

    def get_repos_by_tag(tag: str):
        """Get repositories with a specific tag."""
        repos = ctx.discover_repos()
        matching = []

        for repo in ctx.tag_service.query(repos, tag):
            tags = ctx.tag_service.get_tag_strings(repo)
            matching.append({
                'path': repo.path,
                'name': repo.name,
                'tags': tags
            })

        # Also match prefix patterns (tag/*)
        if not matching:
            for repo in ctx.tag_service.query(repos, f"{tag}/*"):
                tags = ctx.tag_service.get_tag_strings(repo)
                matching.append({
                    'path': repo.path,
                    'name': repo.name,
                    'tags': tags
                })

        return {'tag': tag, 'repositories': matching, 'count': len(matching)}

    def get_stats_summary():
        """Get overall statistics."""
        repos = ctx.discover_repos()

        languages: Dict[str, int] = {}
        published = 0
        total = len(repos)

        for repo in repos:
            lang = repo.language or 'Unknown'
            languages[lang] = languages.get(lang, 0) + 1
            if repo.package and repo.package.published:
                published += 1

        return {
            'total_repositories': total,
            'languages': languages,
            'published_packages': published,
            'unpublished_packages': total - published
        }

    def get_stats_languages():
        """Get repository count by language."""
        repos = ctx.discover_repos()

        languages: Dict[str, int] = {}
        for repo in repos:
            lang = repo.language or 'Unknown'
            languages[lang] = languages.get(lang, 0) + 1

        return {'languages': languages}

    def get_stats_published():
        """Get registry publication status."""
        repos = ctx.discover_repos()

        by_registry: Dict[str, int] = {'pypi': 0, 'cran': 0, 'npm': 0, 'unpublished': 0}

        for repo in repos:
            if repo.package and repo.package.published:
                registry = repo.package.registry or 'unknown'
                by_registry[registry] = by_registry.get(registry, 0) + 1
            else:
                by_registry['unpublished'] += 1

        return {'by_registry': by_registry}

    def get_recent_events_resource():
        """Get recent events (last 7 days)."""
        try:
            repos = ctx.discover_repos()
            events = ctx.event_service.get_recent(repos, days=7, limit=20)
            return {
                'events': [e.to_dict() for e in events],
                'count': len(events)
            }
        except Exception as e:
            logger.warning(f"Could not get events: {e}")
            return {'events': [], 'error': str(e)}

    def get_events_by_repo(name: str):
        """Get events for one repository."""
        try:
            repo = ctx.find_repo_by_name(name)

            if not repo:
                return {'error': f'Repository not found: {name}'}

            events = ctx.event_service.get_recent([repo], days=30, limit=50)
            return {
                'name': name,
                'events': [e.to_dict() for e in events],
                'count': len(events)
            }
        except Exception as e:
            return {'error': str(e)}

    def get_events_by_type(event_type: str):
        """Get events by type."""
        try:
            repos = ctx.discover_repos()
            events = list(ctx.event_service.scan(
                repos,
                types=[event_type],
                limit=50
            ))
            return {
                'type': event_type,
                'events': [e.to_dict() for e in events],
                'count': len(events)
            }
        except Exception as e:
            return {'error': str(e)}

    def get_events_since(timespec: str):
        """Get events since a time specification."""
        try:
            since = parse_timespec(timespec)
            repos = ctx.discover_repos()

            events = list(ctx.event_service.scan(
                repos,
                since=since,
                limit=100
            ))
            return {
                'since': timespec,
                'events': [e.to_dict() for e in events],
                'count': len(events)
            }
        except ValueError as e:
            return {'error': f'Invalid time specification: {e}'}
        except Exception as e:
            return {'error': str(e)}

    # === REGISTER RESOURCES ===

    server.register_resource(
        "repo://list",
        "Repository List",
        "List all repositories with basic metadata",
        list_repos
    )

    server.register_resource(
        "repo://{name}",
        "Repository Details",
        "Get full metadata for one repository",
        get_repo
    )

    server.register_resource(
        "repo://{name}/status",
        "Repository Status",
        "Get git status for one repository",
        get_repo_status
    )

    server.register_resource(
        "repo://{name}/package",
        "Repository Package",
        "Get package info (PyPI/CRAN/npm) for one repository",
        get_repo_package
    )

    server.register_resource(
        "tags://list",
        "Tags List",
        "List all tags",
        list_tags
    )

    server.register_resource(
        "tags://tree",
        "Tags Tree",
        "Get hierarchical tag view",
        get_tag_tree
    )

    server.register_resource(
        "tags://{tag}/repos",
        "Repositories by Tag",
        "Get repositories with a specific tag",
        get_repos_by_tag
    )

    server.register_resource(
        "stats://summary",
        "Statistics Summary",
        "Get overall statistics",
        get_stats_summary
    )

    server.register_resource(
        "stats://languages",
        "Language Statistics",
        "Get repository count by language",
        get_stats_languages
    )

    server.register_resource(
        "stats://published",
        "Publication Statistics",
        "Get registry publication status",
        get_stats_published
    )

    server.register_resource(
        "events://recent",
        "Recent Events",
        "Get recent events (last 7 days)",
        get_recent_events_resource
    )

    server.register_resource(
        "events://since/{timespec}",
        "Events Since",
        "Get events since a time (e.g., 1d, 7d, 2024-01-01)",
        get_events_since
    )

    server.register_resource(
        "events://repo/{name}",
        "Repository Events",
        "Get events for one repository",
        get_events_by_repo
    )

    server.register_resource(
        "events://type/{event_type}",
        "Events by Type",
        "Get events by type (git_tag, commit)",
        get_events_by_type
    )

    # === TOOL HANDLERS ===

    def tool_tag(repo: str, tag: str) -> Dict[str, Any]:
        """Add a tag to a repository."""
        repository = ctx.find_repo_by_name(repo)

        if not repository:
            return {'success': False, 'error': f'Repository not found: {repo}'}

        # Parse and validate tag
        tag_obj = Tag.parse(tag, TagSource.EXPLICIT)

        # Check if already has tag
        existing_tags = ctx.tag_service.get_explicit_tags(repository)
        if tag_obj in existing_tags:
            return {
                'success': True,
                'repo': repo,
                'tag': tag,
                'action': 'already_exists'
            }

        # Add tag
        ctx.tag_service.add(repository, tag_obj)

        return {
            'success': True,
            'repo': repo,
            'tag': tag,
            'action': 'added'
        }

    def tool_untag(repo: str, tag: str) -> Dict[str, Any]:
        """Remove a tag from a repository."""
        repository = ctx.find_repo_by_name(repo)

        if not repository:
            return {'success': False, 'error': f'Repository not found: {repo}'}

        # Parse tag
        tag_obj = Tag.parse(tag)

        # Remove tag
        removed = ctx.tag_service.remove(repository, tag_obj)

        return {
            'success': True,
            'repo': repo,
            'tag': tag,
            'action': 'removed' if removed else 'not_found'
        }

    def tool_query(expression: str) -> Dict[str, Any]:
        """Query repositories using the query language."""
        try:
            repos = ctx.discover_repos()
            results = []

            for repo in ctx.repo_service.filter_by_query(repos, expression):
                tags = ctx.tag_service.get_tag_strings(repo)
                result = repo.to_dict()
                result['tags'] = tags
                results.append(result)

            return {
                'query': expression,
                'results': results,
                'count': len(results)
            }
        except Exception as e:
            return {'query': expression, 'error': str(e)}

    def tool_refresh(repo: Optional[str] = None) -> Dict[str, Any]:
        """Refresh metadata for one or all repositories."""
        refreshed = []

        if repo:
            # Refresh single repo
            repository = ctx.find_repo_by_name(repo)
            if repository:
                ctx.repo_service.get_status(repository, fetch_github=True)
                refreshed.append(repo)
        else:
            # Refresh all repos
            for repository in ctx.discover_repos():
                ctx.repo_service.get_status(repository, fetch_github=True)
                refreshed.append(repository.name)

        return {
            'refreshed': refreshed,
            'count': len(refreshed)
        }

    def tool_stats(groupby: str = 'language') -> Dict[str, Any]:
        """Get statistics grouped by a field."""
        repos = ctx.discover_repos()

        groups: Dict[str, int] = {}
        for repo in repos:
            if groupby == 'language':
                key = repo.language or 'Unknown'
            elif groupby == 'published':
                key = 'published' if (repo.package and repo.package.published) else 'unpublished'
            elif groupby == 'registry':
                if repo.package and repo.package.published:
                    key = repo.package.registry or 'unknown'
                else:
                    key = 'none'
            else:
                # Try to get from repo dict
                repo_dict = repo.to_dict()
                key = str(repo_dict.get(groupby, 'Unknown'))

            groups[key] = groups.get(key, 0) + 1

        return {'groupby': groupby, 'groups': groups}

    # === REGISTER TOOLS ===

    server.register_tool(
        "repoindex_tag",
        "Add a tag to a repository",
        {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "tag": {"type": "string", "description": "Tag to add (e.g., 'topic:ml')"}
            },
            "required": ["repo", "tag"]
        },
        tool_tag
    )

    server.register_tool(
        "repoindex_untag",
        "Remove a tag from a repository",
        {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "tag": {"type": "string", "description": "Tag to remove"}
            },
            "required": ["repo", "tag"]
        },
        tool_untag
    )

    server.register_tool(
        "repoindex_query",
        "Query repositories using the repoindex query language",
        {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Query expression (e.g., \"language == 'Python' and 'ml' in tags\")"
                }
            },
            "required": ["expression"]
        },
        tool_query
    )

    server.register_tool(
        "repoindex_refresh",
        "Refresh metadata for repositories",
        {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name (optional, refreshes all if not specified)"
                }
            },
            "required": []
        },
        tool_refresh
    )

    server.register_tool(
        "repoindex_stats",
        "Get repository statistics",
        {
            "type": "object",
            "properties": {
                "groupby": {
                    "type": "string",
                    "description": "Field to group by (language, published, registry)",
                    "default": "language"
                }
            },
            "required": []
        },
        tool_stats
    )

    return server


def run_mcp_server(transport: str = "stdio"):
    """
    Run the MCP server.

    Args:
        transport: Transport type ("stdio" or "http")
    """
    server = create_mcp_server()

    if transport == "stdio":
        _run_stdio_server(server)
    elif transport == "http":
        _run_http_server(server)
    else:
        raise ValueError(f"Unknown transport: {transport}")


def _run_stdio_server(server: MCPServer):
    """Run MCP server over stdio (JSON-RPC)."""
    import sys

    logger.info("Starting repoindex MCP server (stdio)")

    # Read JSON-RPC requests from stdin, write responses to stdout
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = _handle_jsonrpc_request(server, request)
            print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            error_response = {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None
            }
            print(json.dumps(error_response), flush=True)
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": str(e)},
                "id": request.get("id") if 'request' in dir() else None
            }
            print(json.dumps(error_response), flush=True)


def _handle_jsonrpc_request(server: MCPServer, request: Dict[str, Any]) -> Dict[str, Any]:
    """Handle a JSON-RPC request."""
    method = request.get("method")
    params = request.get("params", {})
    request_id = request.get("id")

    result = None
    error = None

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "resources": {"listChanged": True},
                    "tools": {}
                },
                "serverInfo": {
                    "name": "repoindex",
                    "version": "0.9.0"
                }
            }

        elif method == "resources/list":
            result = {"resources": server.list_resources()}

        elif method == "resources/read":
            uri = params.get("uri")
            content = server.read_resource(uri)
            result = {
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(content, indent=2)
                }]
            }

        elif method == "tools/list":
            result = {"tools": server.list_tools()}

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            tool_result = server.call_tool(tool_name, arguments)
            result = {
                "content": [{
                    "type": "text",
                    "text": json.dumps(tool_result, indent=2)
                }]
            }

        else:
            error = {"code": -32601, "message": f"Method not found: {method}"}

    except Exception as e:
        error = {"code": -32603, "message": str(e)}

    response = {"jsonrpc": "2.0", "id": request_id}
    if error:
        response["error"] = error
    else:
        response["result"] = result

    return response


def _run_http_server(server: MCPServer, host: str = "localhost", port: int = 8765):
    """Run MCP server over HTTP (for testing/debugging)."""
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class MCPHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers['Content-Length'])
                body = self.rfile.read(content_length)

                try:
                    request = json.loads(body)
                    response = _handle_jsonrpc_request(server, request)

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(response).encode())

                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    error = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": None}
                    self.wfile.write(json.dumps(error).encode())

            def log_message(self, format, *args):
                logger.debug(format % args)

        httpd = HTTPServer((host, port), MCPHandler)
        logger.info(f"Starting repoindex MCP server (HTTP) on {host}:{port}")
        httpd.serve_forever()

    except ImportError:
        raise RuntimeError("HTTP server not available")
