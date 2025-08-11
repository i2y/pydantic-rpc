"""Example demonstrating RequestContext usage with Connecpy."""

from typing import Any
from pydantic_rpc import ASGIApp, Message


class ContextRequest(Message):
    """Request for context-aware operations."""

    operation: str
    value: str


class ContextResponse(Message):
    """Response with context information."""

    result: str
    has_context: bool = False


class ContextAwareService:
    """Service that uses RequestContext for metadata and headers."""

    async def get_context_info(
        self, request: ContextRequest, context: Any
    ) -> ContextResponse:
        """Method that accesses context information.

        Args:
            request: The request message
            context: The RequestContext from Connecpy

        Returns:
            Response with context details
        """
        # In a real implementation, context would provide:
        # - Request headers via context.headers
        # - Ability to set response headers
        # - Request metadata
        # - Timeout information

        result = f"Operation: {request.operation}, Value: {request.value}"

        # Check if context is available and has expected properties
        has_context = context is not None and hasattr(context, "__class__")

        if has_context:
            result += " (with context)"

        return ContextResponse(result=result, has_context=has_context)

    async def simple_method(self, request: ContextRequest) -> ContextResponse:
        """Method without context parameter for comparison."""
        return ContextResponse(
            result=f"Simple: {request.operation} - {request.value}", has_context=False
        )


# Create the application
app = ASGIApp()
app.mount(ContextAwareService())


if __name__ == "__main__":
    import uvicorn

    print("Starting Context-aware Connecpy service on http://localhost:8000")
    print("\nAvailable endpoints:")
    print("  POST /context.v1.ContextAwareService/get_context_info - With context")
    print("  POST /context.v1.ContextAwareService/simple_method    - Without context")
    print(
        "\nThe get_context_info method can access RequestContext for headers and metadata."
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)
