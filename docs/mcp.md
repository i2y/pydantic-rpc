# MCP (Model Context Protocol) Support

pydantic-rpc provides built-in support for exposing your services as MCP servers, allowing them to be used as tools by AI assistants.

## Features

- **Automatic tool generation** from pydantic-rpc service methods
- **Type-safe** parameter and return value handling using Pydantic models
- **Multiple transport options**:
  - stdio (for Claude Desktop and other MCP clients)
  - HTTP/SSE (for web-based integrations)
- **Async and sync** method support

## Quick Start

### 1. Define your service

```python
from pydantic_rpc import Message
from pydantic_rpc.mcp import MCPExporter

class CalculateRequest(Message):
    expression: str

class CalculateResponse(Message):
    result: float

class CalculatorService:
    def calculate(self, request: CalculateRequest) -> CalculateResponse:
        result = eval(request.expression, {"__builtins__": {}}, {})
        return CalculateResponse(result=float(result))
```

### 2. Export as MCP server

```python
if __name__ == "__main__":
    service = CalculatorService()
    mcp = MCPExporter(service, name="Calculator")
    mcp.run_stdio()  # For stdio transport
```

### 3. Use with MCP clients

Configure your MCP client to run the Python script. The service methods will be automatically exposed as tools.

## Transport Options

### stdio Transport

For use with Claude Desktop and other stdio-based MCP clients:

```python
mcp = MCPExporter(service)
mcp.run_stdio()
```

### HTTP/SSE Transport

For web-based integrations:

```python
# Standalone HTTP server
app = mcp.get_asgi_app()
# Run with uvicorn or similar ASGI server

# Mount to existing ASGI app
from pydantic_rpc import ConnecpyASGIApp
connect_app = ConnecpyASGIApp()
connect_app.mount(service)
mcp.mount_to_asgi(connect_app, path="/mcp")
```

## Examples

See the `examples/` directory for complete examples:
- `mcp_example.py` - Calculator service with stdio transport
- `mcp_http_example.py` - HTTP/SSE transport with Connect-RPC integration
- `mcp_simple_calculator.py` - Minimal example

## How It Works

1. MCPExporter introspects your service class to find public methods
2. For each method, it extracts parameter and return type information
3. Pydantic models are converted to JSON Schema for tool descriptions
4. Methods are wrapped to handle MCP protocol messages
5. The resulting tools can be called by MCP clients

## Requirements

```bash
pip install pydantic-rpc[mcp]
```

This installs the official MCP SDK and required dependencies.