from importlib.util import find_spec

from .core import (
    Server,
    AsyncIOServer,
    WSGIApp,
    ASGIApp,
    Message,
    generate_proto,
)
from .decorators import (
    http_option,
    proto_option,
    get_method_options,
    has_http_option,
    error_handler,
    get_error_handlers,
    invoke_error_handler,
)
from .tls import (
    GrpcTLSConfig,
    extract_peer_identity,
    extract_peer_certificate_chain,
)

__all__ = [
    "Server",
    "AsyncIOServer",
    "WSGIApp",
    "ASGIApp",
    "Message",
    "generate_proto",
    "http_option",
    "proto_option",
    "get_method_options",
    "has_http_option",
    "error_handler",
    "get_error_handlers",
    "invoke_error_handler",
    "GrpcTLSConfig",
    "extract_peer_identity",
    "extract_peer_certificate_chain",
]

# Optional MCP support
if find_spec("mcp"):
    from .mcp import MCPExporter  # noqa: F401

    __all__.append("MCPExporter")
