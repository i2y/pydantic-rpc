"""Tests for MCP functionality."""

import json
import pytest
from pydantic import BaseModel

from pydantic_rpc import Message

# Only run these tests if MCP dependencies are available
pytest.importorskip("mcp")

from pydantic_rpc.mcp import MCPExporter
from pydantic_rpc.mcp.converter import extract_method_info, python_type_to_json_type


class MCPTestRequest(Message):
    """Test request model."""

    value: int
    name: str


class MCPTestResponse(Message):
    """Test response model."""

    result: str
    count: int


class TestService:
    """Test service for MCP export."""

    def process(self, request: MCPTestRequest) -> MCPTestResponse:
        """Process a test request."""
        return MCPTestResponse(
            result=f"Processed {request.name}", count=request.value * 2
        )

    async def async_process(self, request: MCPTestRequest) -> MCPTestResponse:
        """Async process method."""
        return MCPTestResponse(
            result=f"Async processed {request.name}", count=request.value * 3
        )


class TestTypeConversion:
    """Test type conversion utilities."""

    def test_basic_types(self):
        """Test conversion of basic Python types to JSON schema."""
        assert python_type_to_json_type(int) == {"type": "integer"}
        assert python_type_to_json_type(float) == {"type": "number"}
        assert python_type_to_json_type(str) == {"type": "string"}
        assert python_type_to_json_type(bool) == {"type": "boolean"}
        assert python_type_to_json_type(bytes) == {"type": "string", "format": "byte"}

    def test_pydantic_model(self):
        """Test conversion of Pydantic models."""
        schema = python_type_to_json_type(MCPTestRequest)
        assert "properties" in schema
        assert "value" in schema["properties"]
        assert "name" in schema["properties"]

    def test_extract_method_info(self):
        """Test extraction of method information."""
        service = TestService()
        info = extract_method_info(service.process)

        assert info["description"] == "Process a test request."
        assert "properties" in info["parameters"]
        assert "properties" in info["response"]
        assert info["is_streaming"] is False


class TestMCPExporter:
    """Test MCPExporter functionality."""

    def test_exporter_initialization(self):
        """Test that MCPExporter properly extracts tools."""
        service = TestService()
        exporter = MCPExporter(service)

        # Check that MCP Server instance was created
        assert exporter.server is not None
        assert exporter.name == "TestService"

        # Check that tools were extracted
        assert "process" in exporter.tools
        assert "asyncprocess" in exporter.tools

        # Check tool properties
        process_tool, _ = exporter.tools["process"]
        assert process_tool.name == "process"
        assert process_tool.description == "Process a test request."

    def test_mcp_sdk_integration(self):
        """Test MCP SDK integration."""
        service = TestService()
        exporter = MCPExporter(service)

        # Verify MCP server was created
        assert hasattr(exporter, "server")
        assert hasattr(exporter, "run_stdio")  # Has run_stdio method

        # Check registered tools count
        assert len(exporter.tools) == 2

    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Test that tools can be executed through the wrapper."""
        service = TestService()
        exporter = MCPExporter(service)

        # Get the wrapped method for process
        _, wrapped_method = exporter.tools["process"]

        # Call it with kwargs
        result = wrapped_method(value=5, name="test")

        assert isinstance(result, MCPTestResponse)
        assert result.result == "Processed test"
        assert result.count == 10

    @pytest.mark.asyncio
    async def test_async_tool_execution(self):
        """Test that async tools can be executed through the wrapper."""
        service = TestService()
        exporter = MCPExporter(service)

        # Get the wrapped method for async_process
        _, wrapped_method = exporter.tools["asyncprocess"]

        # Call it with kwargs
        result = await wrapped_method(value=5, name="test")

        assert isinstance(result, MCPTestResponse)
        assert result.result == "Async processed test"
        assert result.count == 15

    def test_http_transport_available(self):
        """Test that HTTP transport is available."""
        service = TestService()
        exporter = MCPExporter(service)

        # Should not raise an error
        try:
            app = exporter.get_asgi_app()
            assert app is not None
        except ImportError as e:
            # Skip if starlette is not installed
            if "starlette" in str(e):
                pytest.skip("starlette not installed")
            else:
                raise

    def test_mount_to_asgi_with_mock_app(self):
        """Test mounting to an ASGI app."""
        service = TestService()
        exporter = MCPExporter(service)

        # Mock ASGI app with mount method
        class MockApp:
            def __init__(self):
                self.mounted = {}

            def mount(self, path, app):
                self.mounted[path] = app

        mock_app = MockApp()

        try:
            exporter.mount_to_asgi(mock_app, "/mcp")
            assert "/mcp" in mock_app.mounted
        except ImportError as e:
            # Skip if starlette is not installed
            if "starlette" in str(e):
                pytest.skip("starlette not installed")
            else:
                raise
