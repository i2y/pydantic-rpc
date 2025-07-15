from importlib.util import find_spec

from .core import (
    Server,
    AsyncIOServer,
    WSGIApp,
    ASGIApp,
    ConnecpyASGIApp,
    ConnecpyWSGIApp,
    Message,
)

__all__ = [
    "Server",
    "AsyncIOServer",
    "WSGIApp",
    "ASGIApp",
    "ConnecpyWSGIApp",
    "ConnecpyASGIApp",
    "Message",
]

# Optional MCP support
if find_spec("mcp"):
    from .mcp import MCPExporter  # noqa: F401

    __all__.append("MCPExporter")
