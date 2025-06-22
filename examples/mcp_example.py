#!/usr/bin/env python3
"""Example MCP server with pydantic-rpc."""

import sys
from datetime import datetime
from pydantic import BaseModel
from pydantic_rpc import Message
from pydantic_rpc.mcp import MCPExporter


# Optional: Add debug logging
DEBUG = False  # Set to True for debugging


def log(msg):
    """Log to stderr for debugging."""
    if DEBUG:
        print(f"[{datetime.now().isoformat()}] {msg}", file=sys.stderr)


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
        log(f"calculate() called with: {request.expression}")
        try:
            # Safe evaluation with limited scope
            result = eval(request.expression, {"__builtins__": {}}, {})
            response = CalculateResponse(
                result=float(result), expression=request.expression
            )
            log(f"calculate() returning: {response}")
            return response
        except Exception as e:
            log(f"calculate() error: {e}")
            return CalculateResponse(result=0.0, expression=f"Error: {str(e)}")

    async def add(self, request: AddRequest) -> AddResponse:
        """Add two numbers together."""
        return AddResponse(result=request.a + request.b)

    async def multiply(self, request: MultiplyRequest) -> MultiplyResponse:
        """Multiply two numbers."""
        return MultiplyResponse(result=request.x * request.y)


def main():
    """Run the MCP server."""
    log("Starting main()")

    # Create service
    service = CalculatorService()
    log(f"Created service: {service}")

    # Create MCP exporter with official MCP SDK
    mcp_exporter = MCPExporter(
        service,
        name="Calculator MCP Server",
        description="A calculator service exposed via MCP",
    )
    log(f"Created MCPExporter with tools: {list(mcp_exporter.tools.keys())}")

    # Run in stdio mode for MCP clients
    if not DEBUG:
        print("Starting Calculator MCP Server...", file=sys.stderr)
        print(
            "This server can be used with any MCP-compatible client.", file=sys.stderr
        )
        print(
            "For example, to use with Claude Desktop, add to claude_desktop_config.json:",
            file=sys.stderr,
        )
        print(f'  "calculator": {{', file=sys.stderr)
        print(f'    "command": "python",', file=sys.stderr)
        print(f'    "args": ["{__file__}"]', file=sys.stderr)
        print(f"  }}", file=sys.stderr)
        print("", file=sys.stderr)

    log("Starting stdio server...")
    mcp_exporter.run_stdio()


if __name__ == "__main__":
    main()
