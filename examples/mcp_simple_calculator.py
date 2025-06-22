#!/usr/bin/env python3
"""Simple synchronous MCP calculator for Claude Desktop."""

import sys
sys.path.insert(0, '/Users/i2y/pydantic-rpc/src')

from pydantic_rpc import Message
from pydantic_rpc.mcp import MCPExporter


class AddRequest(Message):
    """Request to add two numbers."""
    a: float
    b: float


class AddResponse(Message):
    """Response with the sum."""
    result: float


class SimpleCalculator:
    """Very simple calculator with just addition."""
    
    def add(self, request: AddRequest) -> AddResponse:
        """Add two numbers together."""
        return AddResponse(result=request.a + request.b)


if __name__ == "__main__":
    # Create service
    service = SimpleCalculator()
    
    # Create MCP exporter
    mcp = MCPExporter(
        service,
        name="Simple Calculator",
        description="A very simple calculator that can add numbers"
    )
    
    # Run stdio server
    mcp.run_stdio()
