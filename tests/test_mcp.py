"""
Tests for MCP server functionality.

Tests the refactored MCP server that uses the service layer
(RepositoryService, TagService, EventService).
"""

import pytest
import json
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

from repoindex.domain import Repository, Tag, TagSource, Event
from repoindex.domain.repository import GitStatus, PackageMetadata


class TestMCPServer:
    """Test MCP server core functionality."""

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_create_server(self, mock_ctx_create):
        """Test creating MCP server."""
        # Mock context
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()

        # Should have resources
        assert len(server.resources) > 0
        assert 'repo://list' in server.resources

        # Should have tools
        assert len(server.tools) > 0
        assert 'repoindex_tag' in server.tools

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_list_resources(self, mock_ctx_create):
        """Test listing resources."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        resources = server.list_resources()

        # Should return list of resource definitions
        assert isinstance(resources, list)
        assert len(resources) > 0

        # Each resource should have required fields
        for resource in resources:
            assert 'uri' in resource
            assert 'name' in resource
            assert 'description' in resource

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_list_tools(self, mock_ctx_create):
        """Test listing tools."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        tools = server.list_tools()

        # Should return list of tool definitions
        assert isinstance(tools, list)
        assert len(tools) > 0

        # Each tool should have required fields
        for tool in tools:
            assert 'name' in tool
            assert 'description' in tool
            assert 'inputSchema' in tool


class TestMCPResources:
    """Test MCP resource handlers."""

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_read_repo_list(self, mock_ctx_create):
        """Test reading repo://list resource."""
        # Create mock repositories
        repos = [
            Repository(path='/tmp/repos/project1', name='project1', language='Python'),
            Repository(path='/tmp/repos/project2', name='project2', language='Rust'),
        ]

        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = repos
        mock_ctx.tag_service.get_tag_strings.return_value = ['topic:ml']
        mock_ctx.tag_service.get_unique_tags.return_value = {'topic:ml'}
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.read_resource('repo://list')

        assert 'repositories' in result
        assert 'count' in result
        assert result['count'] == 2

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_read_tags_list(self, mock_ctx_create):
        """Test reading tags://list resource."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = {'topic:ml', 'work/active'}
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.read_resource('tags://list')

        assert 'tags' in result
        assert 'count' in result
        assert result['count'] == 2

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_read_stats_summary(self, mock_ctx_create):
        """Test reading stats://summary resource."""
        repos = [
            Repository(
                path='/tmp/repos/project1',
                name='project1',
                language='Python',
                package=PackageMetadata(name='project1', version='1.0.0', published=True, registry='pypi')
            ),
            Repository(path='/tmp/repos/project2', name='project2', language='Python'),
        ]

        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = repos
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.read_resource('stats://summary')

        assert 'total_repositories' in result
        assert 'languages' in result
        assert 'published_packages' in result
        assert result['total_repositories'] == 2
        assert result['published_packages'] == 1


class TestMCPTools:
    """Test MCP tool handlers."""

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_call_repoindex_tag(self, mock_ctx_create):
        """Test calling repoindex_tag tool."""
        repo = Repository(path='/tmp/repos/myproject', name='myproject')

        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = [repo]
        mock_ctx.find_repo_by_name.return_value = repo
        mock_ctx.tag_service.get_explicit_tags.return_value = set()
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.call_tool('repoindex_tag', {'repo': 'myproject', 'tag': 'topic:ml'})

        assert result['success'] is True
        assert result['action'] == 'added'
        mock_ctx.tag_service.add.assert_called_once()

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_call_repoindex_tag_already_exists(self, mock_ctx_create):
        """Test calling repoindex_tag when tag already exists."""
        repo = Repository(path='/tmp/repos/myproject', name='myproject')
        existing_tag = Tag.parse('topic:ml', TagSource.EXPLICIT)

        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = [repo]
        mock_ctx.find_repo_by_name.return_value = repo
        mock_ctx.tag_service.get_explicit_tags.return_value = {existing_tag}
        mock_ctx.tag_service.get_unique_tags.return_value = {'topic:ml'}
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.call_tool('repoindex_tag', {'repo': 'myproject', 'tag': 'topic:ml'})

        assert result['success'] is True
        assert result['action'] == 'already_exists'

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_call_repoindex_untag(self, mock_ctx_create):
        """Test calling repoindex_untag tool."""
        repo = Repository(path='/tmp/repos/myproject', name='myproject')

        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = [repo]
        mock_ctx.find_repo_by_name.return_value = repo
        mock_ctx.tag_service.remove.return_value = True
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.call_tool('repoindex_untag', {'repo': 'myproject', 'tag': 'topic:ml'})

        assert result['success'] is True
        assert result['action'] == 'removed'

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_call_repoindex_stats(self, mock_ctx_create):
        """Test calling repoindex_stats tool."""
        repos = [
            Repository(path='/tmp/repos/project1', name='project1', language='Python'),
            Repository(path='/tmp/repos/project2', name='project2', language='Python'),
        ]

        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = repos
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.call_tool('repoindex_stats', {'groupby': 'language'})

        assert 'groupby' in result
        assert 'groups' in result
        assert result['groupby'] == 'language'
        assert result['groups']['Python'] == 2

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_call_repoindex_refresh(self, mock_ctx_create):
        """Test calling repoindex_refresh tool."""
        repos = [
            Repository(path='/tmp/repos/project1', name='project1'),
            Repository(path='/tmp/repos/project2', name='project2'),
        ]

        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = repos
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.call_tool('repoindex_refresh', {})

        assert 'refreshed' in result
        assert 'count' in result
        assert result['count'] == 2

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_call_unknown_tool(self, mock_ctx_create):
        """Test calling unknown tool raises error."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()

        with pytest.raises(ValueError, match="Unknown tool"):
            server.call_tool('unknown_tool', {})

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_call_repoindex_tag_repo_not_found(self, mock_ctx_create):
        """Test calling repoindex_tag when repo not found."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.find_repo_by_name.return_value = None
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()
        result = server.call_tool('repoindex_tag', {'repo': 'nonexistent', 'tag': 'topic:ml'})

        assert result['success'] is False
        assert 'error' in result


class TestMCPJSONRPC:
    """Test JSON-RPC request handling."""

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_handle_initialize(self, mock_ctx_create):
        """Test handling initialize request."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server, _handle_jsonrpc_request

        server = create_mcp_server()
        request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1
        }

        response = _handle_jsonrpc_request(server, request)

        assert response['jsonrpc'] == '2.0'
        assert response['id'] == 1
        assert 'result' in response
        assert 'serverInfo' in response['result']
        assert response['result']['serverInfo']['name'] == 'repoindex'

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_handle_resources_list(self, mock_ctx_create):
        """Test handling resources/list request."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server, _handle_jsonrpc_request

        server = create_mcp_server()
        request = {
            "jsonrpc": "2.0",
            "method": "resources/list",
            "id": 2
        }

        response = _handle_jsonrpc_request(server, request)

        assert 'result' in response
        assert 'resources' in response['result']
        assert len(response['result']['resources']) > 0

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_handle_tools_list(self, mock_ctx_create):
        """Test handling tools/list request."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server, _handle_jsonrpc_request

        server = create_mcp_server()
        request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 3
        }

        response = _handle_jsonrpc_request(server, request)

        assert 'result' in response
        assert 'tools' in response['result']
        assert len(response['result']['tools']) > 0

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_handle_unknown_method(self, mock_ctx_create):
        """Test handling unknown method returns error."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server, _handle_jsonrpc_request

        server = create_mcp_server()
        request = {
            "jsonrpc": "2.0",
            "method": "unknown/method",
            "id": 4
        }

        response = _handle_jsonrpc_request(server, request)

        assert 'error' in response
        assert response['error']['code'] == -32601


class TestURIPatternMatching:
    """Test URI pattern matching for resources."""

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_match_simple_uri(self, mock_ctx_create):
        """Test matching simple URI pattern."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()

        # Should match exact pattern
        assert server._match_uri_pattern('repo://list', 'repo://list')

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_match_parameterized_uri(self, mock_ctx_create):
        """Test matching URI with parameters."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()

        # Should match parameterized pattern
        assert server._match_uri_pattern('repo://{name}', 'repo://myproject')
        assert server._match_uri_pattern('repo://{name}/status', 'repo://myproject/status')

    @patch('repoindex.mcp.server.MCPContext.create')
    def test_extract_uri_params(self, mock_ctx_create):
        """Test extracting parameters from URI."""
        mock_ctx = MagicMock()
        mock_ctx.discover_repos.return_value = []
        mock_ctx.tag_service.get_unique_tags.return_value = set()
        mock_ctx_create.return_value = mock_ctx

        from repoindex.mcp.server import create_mcp_server

        server = create_mcp_server()

        params = server._extract_uri_params('repo://{name}', 'repo://myproject')
        assert params == {'name': 'myproject'}

        params = server._extract_uri_params('tags://{tag}/repos', 'tags://topic:ml/repos')
        assert params == {'tag': 'topic:ml'}


class TestMCPContext:
    """Test MCPContext functionality."""

    @patch('repoindex.mcp.server.load_config')
    @patch('repoindex.mcp.server.FileStore')
    @patch('repoindex.mcp.server.GitClient')
    @patch('repoindex.mcp.server.GitHubClient')
    @patch('repoindex.mcp.server.RepositoryService')
    @patch('repoindex.mcp.server.TagService')
    @patch('repoindex.mcp.server.EventService')
    def test_create_context(self, mock_event_svc, mock_tag_svc, mock_repo_svc,
                           mock_gh_client, mock_git_client, mock_file_store,
                           mock_load_config):
        """Test creating MCPContext."""
        mock_load_config.return_value = {
            'general': {'repository_directories': ['/tmp/repos']}
        }

        from repoindex.mcp.server import MCPContext

        ctx = MCPContext.create()

        assert ctx.config is not None
        assert ctx.repo_service is not None
        assert ctx.tag_service is not None
        assert ctx.event_service is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
