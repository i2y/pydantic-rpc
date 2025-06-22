#!/usr/bin/env python3
"""Example MCP server using HTTP/SSE transport with the official MCP SDK."""

import asyncio
import uvicorn
from pydantic import BaseModel
from pydantic_rpc import Message, ConnecpyASGIApp
from pydantic_rpc.mcp import MCPExporter


# Define request/response models
class CalculateRequest(Message):
    """Request for mathematical calculation."""
    expression: str


class CalculateResponse(Message):
    """Response with calculation result."""
    result: float
    expression: str


class AddRequest(Message):
    """Request to add two numbers."""
    a: float
    b: float


class AddResponse(Message):
    """Response with the sum."""
    result: float


class MultiplyRequest(Message):
    """Request to multiply two numbers."""
    x: float
    y: float


class MultiplyResponse(Message):
    """Response with the product."""
    result: float


class CalculatorService:
    """Calculator service with mathematical operations."""
    
    async def calculate(self, request: CalculateRequest) -> CalculateResponse:
        """Evaluate a mathematical expression.
        
        Supports basic operations: +, -, *, /, **, (, )
        Examples: "2 + 2", "10 * 5", "(3 + 4) * 2"
        """
        try:
            # Safe evaluation with limited scope
            result = eval(request.expression, {"__builtins__": {}}, {})
            return CalculateResponse(
                result=float(result),
                expression=request.expression
            )
        except Exception as e:
            return CalculateResponse(
                result=0.0,
                expression=f"Error: {str(e)}"
            )
    
    async def add(self, request: AddRequest) -> AddResponse:
        """Add two numbers together."""
        return AddResponse(result=request.a + request.b)
    
    async def multiply(self, request: MultiplyRequest) -> MultiplyResponse:
        """Multiply two numbers."""
        return MultiplyResponse(result=request.x * request.y)


def create_app():
    """Create the ASGI application with both Connect-RPC and MCP endpoints."""
    # Create service
    service = CalculatorService()
    
    # Create Connect-RPC ASGI app
    connect_app = ConnecpyASGIApp()
    connect_app.mount(service)
    
    # Add MCP support
    mcp_exporter = MCPExporter(
        service,
        name="Calculator MCP Server",
        description="A calculator service exposed via MCP over HTTP/SSE"
    )
    mcp_exporter.mount_to_asgi(connect_app, path="/mcp")
    
    return connect_app


async def main():
    """Run the HTTP server."""
    app = create_app()
    
    print("Starting Calculator MCP Server with HTTP/SSE transport...")
    print()
    print("Available endpoints:")
    print("- Connect-RPC: POST http://localhost:8000/calculator.v1.CalculatorService/*")
    print("- MCP SSE: GET http://localhost:8000/mcp/sse")
    print("- MCP Messages: POST http://localhost:8000/mcp/messages/")
    print()
    print("To test with an MCP client, configure it to connect to:")
    print("  http://localhost:8000/mcp")
    print()
    
    # Run with uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


# Create app at module level for uvicorn
# Only create if running as main module to avoid import errors
app = None

if __name__ == "__main__":
    app = create_app()
    asyncio.run(main())
