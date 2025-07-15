"""MCP exporter for pydantic-rpc services using the official MCP SDK."""

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

try:
    from mcp.server import InitializationOptions, Server
    from mcp.server.sse import SseServerTransport
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Content,
        ServerCapabilities,
        TextContent,
        Tool,
    )
except ImportError:
    raise ImportError("mcp is required for MCP support. Install with: pip install mcp")

from .converter import extract_method_info


class MCPExporter:
    """Export pydantic-rpc services as MCP tools using the official MCP SDK."""

    def __init__(
        self,
        service_obj: object,
        name: str | None = None,
        description: str | None = None,
    ):
        """Initialize MCPExporter with a service object.

        Args:
            service_obj: The service object containing RPC methods to export as MCP tools.
            name: Name for the MCP server (defaults to service class name)
            description: Description for the MCP server
        """
        self.service: object = service_obj
        self.name: str = name or service_obj.__class__.__name__
        self.description: str = (
            description or f"MCP tools from {service_obj.__class__.__name__}"
        )

        # Create MCP Server instance
        self.server: Server[Any] = Server(
            self.name, version="1.0.0", instructions=self.description
        )

        # Store tools for later reference
        self.tools: dict[str, tuple[Tool, Any]] = {}

        # SSE transport instance (created lazily)
        self._sse_transport: SseServerTransport | None = None

        # Register handlers
        self._register_handlers()

        # Extract and store tools
        self._extract_tools()

    def _register_handlers(self):
        """Register MCP protocol handlers."""

        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:  # pyright:ignore[reportUnusedFunction]
            """List all available tools."""
            return [tool for tool, _ in self.tools.values()]

        @self.server.call_tool()
        async def handle_call_tool(  # pyright:ignore[reportUnusedFunction]
            name: str, arguments: dict[str, Any] | None
        ) -> list[Content]:
            """Execute a tool."""
            if name not in self.tools:
                raise ValueError(f"Unknown tool: {name}")

            _, method = self.tools[name]

            # Extract arguments from the request
            args = arguments or {}

            # Call the method
            if inspect.iscoroutinefunction(method):
                result = await method(**args)
            else:
                result = method(**args)

            # Convert result to TextContent
            if isinstance(result, BaseModel):
                content = result.model_dump_json(indent=2)
            else:
                content = str(result)

            return [TextContent(type="text", text=content)]

    def _extract_tools(self):
        """Extract tools from the service object."""
        for method_name, method in inspect.getmembers(self.service, inspect.ismethod):
            # Skip private methods
            if method_name.startswith("_"):
                continue

            # Exclude methods from external modules (like pytest fixtures)
            method_module = inspect.getmodule(method)
            if method_module and not method_module.__name__.startswith(
                self.service.__class__.__module__
            ):
                continue

            tool_name = method_name.lower()

            # Get method info
            try:
                method_info = extract_method_info(method)
            except Exception:
                # Skip methods that can't be processed
                continue

            # Create Tool definition
            tool = Tool(
                name=tool_name,
                description=method_info["description"] or f"Execute {method_name}",
                inputSchema=method_info["parameters"],
            )

            # Create a wrapper that handles Pydantic model parameters
            sig = inspect.signature(method)
            params = list(sig.parameters.values())
            if params and params[0].name in ("self", "cls"):
                params = params[1:]

            if params and params[0].annotation != inspect._empty:
                param_type = params[0].annotation
                if inspect.isclass(param_type) and issubclass(param_type, BaseModel):
                    # For Pydantic models, create a wrapper that constructs the model
                    if inspect.iscoroutinefunction(method):

                        def make_async_wrapper(
                            m: Callable[..., Any], pt: type[BaseModel]
                        ) -> Callable[..., Any]:
                            async def wrapped_method(**kwargs: Any) -> Any:
                                request = pt(**kwargs)
                                return await m(request)

                            return wrapped_method

                        self.tools[tool_name] = (
                            tool,
                            make_async_wrapper(method, param_type),
                        )
                    else:

                        def make_sync_wrapper(
                            m: Callable[..., Any], pt: type[BaseModel]
                        ) -> Callable[..., Any]:
                            def wrapped_method(**kwargs: Any) -> Any:
                                request = pt(**kwargs)
                                return m(request)

                            return wrapped_method

                        self.tools[tool_name] = (
                            tool,
                            make_sync_wrapper(method, param_type),
                        )
                else:
                    # For non-Pydantic types, use the method directly
                    self.tools[tool_name] = (tool, method)
            else:
                # No parameters
                self.tools[tool_name] = (tool, method)

    def run_stdio(self):
        """Run the MCP server in stdio mode."""
        asyncio.run(self._run_stdio())

    async def _run_stdio(self):
        """Async implementation of stdio server."""
        async with stdio_server() as (read_stream, write_stream):
            init_options = InitializationOptions(
                server_name=self.name,
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            )
            await self.server.run(read_stream, write_stream, init_options)

    def get_asgi_app(self, path: str = "/mcp"):
        """Get the ASGI app for HTTP/SSE transport.

        Args:
            path: The base path for MCP endpoints (default: "/mcp")

        Returns:
            An ASGI application that can be mounted or run directly.
        """
        _ = path
        try:
            from starlette.applications import Starlette
            from starlette.routing import Mount, Route
        except ImportError:
            raise ImportError(
                "starlette is required for HTTP/SSE transport. "
                "Install with: pip install starlette"
            )

        # Create SSE transport if not already created
        if self._sse_transport is None:
            self._sse_transport = SseServerTransport("/messages/")

        # Get transport (guaranteed to be non-None after above check)
        sse_transport = self._sse_transport

        # Create SSE endpoint handler
        async def handle_sse(request: Any) -> None:
            # Use ASGI interface directly
            scope = request.scope
            receive = request.receive
            send = request._send

            async with sse_transport.connect_sse(scope, receive, send) as (
                read_stream,
                write_stream,
            ):
                init_options = InitializationOptions(
                    server_name=self.name,
                    server_version="1.0.0",
                    capabilities=ServerCapabilities(),
                )
                await self.server.run(read_stream, write_stream, init_options)

        # Create Starlette app with routes
        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse_transport.handle_post_message),
            ]
        )

        return app

    def mount_to_asgi(self, asgi_app: Any, path: str = "/mcp"):
        """Mount MCP endpoints to an existing ASGI application.

        Works with Starlette/FastAPI applications and pydantic-rpc ASGI apps.

        Args:
            asgi_app: The ASGI application to mount to
            path: The path prefix for MCP endpoints (default: "/mcp")
        """
        mcp_asgi = self.get_asgi_app(path)

        # Check if the app has a mount method (Starlette/FastAPI)
        if hasattr(asgi_app, "mount"):
            asgi_app.mount(path, mcp_asgi)
        # Check if it's a pydantic-rpc ASGI app (ASGIApp/ConnecpyASGIApp)
        elif hasattr(asgi_app, "_app"):
            original_app = asgi_app._app

            async def wrapped_app(
                scope: dict[str, Any],
                receive: Callable[[], Any],
                send: Callable[[Any], Any],
            ) -> None:
                if scope["type"] == "http" and scope["path"].startswith(path):
                    # Create a new scope with adjusted path
                    scope = dict(scope)
                    scope["path"] = scope["path"][len(path) :]
                    if not scope["path"]:
                        scope["path"] = "/"
                    await mcp_asgi(scope, receive, send)
                else:
                    await original_app(scope, receive, send)

            asgi_app._app = wrapped_app
        else:
            raise ValueError(
                "Unable to mount MCP to the provided ASGI app. "
                "The app must have either a 'mount' method or '_app' attribute."
            )
