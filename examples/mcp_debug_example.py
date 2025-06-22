#!/usr/bin/env python3
"""Debug version of MCP server to test with Claude Code."""

import sys
import json
from datetime import datetime
from pydantic import BaseModel
from pydantic_rpc import Message
from pydantic_rpc.mcp import MCPExporter


# Add logging to stderr (stdout is used for MCP protocol)
def log(msg):
    """Log to stderr for debugging."""
    print(f"[{datetime.now().isoformat()}] {msg}", file=sys.stderr)


# Simple test service
class EchoRequest(Message):
    """Echo request."""

    message: str


class EchoResponse(Message):
    """Echo response."""

    echo: str
    timestamp: str


class TestService:
    """Simple test service for debugging."""

    def echo(self, request: EchoRequest) -> EchoResponse:
        """Echo a message back with timestamp."""
        log(f"echo() called with: {request.message}")
        response = EchoResponse(
            echo=f"Echo: {request.message}", timestamp=datetime.now().isoformat()
        )
        log(f"echo() returning: {response}")
        return response


def main():
    """Run the MCP server with debug logging."""
    log("Starting MCP Debug Server...")

    # Create service
    service = TestService()

    # Create MCP exporter
    mcp = MCPExporter(
        service, name="Debug MCP Server", description="Simple echo service for testing"
    )

    log(f"Registered tools: {list(mcp.tools.keys())}")

    # Log the tool schema
    for tool_name, (tool, _) in mcp.tools.items():
        log(f"Tool '{tool_name}': {json.dumps(tool.model_dump(), indent=2)}")

    log("Starting stdio server...")

    try:
        # Run in stdio mode
        mcp.run_stdio()
    except Exception as e:
        log(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
