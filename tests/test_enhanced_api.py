"""Tests for enhanced API features."""

import pytest
import grpc
from pydantic import ValidationError

from pydantic_rpc import (
    Server,
    AsyncIOServer,
    ASGIApp,
    WSGIApp,
    Message,
    error_handler,
    get_error_handlers,
)


class SampleRequest(Message):
    """Sample request message."""

    value: str


class SampleResponse(Message):
    """Sample response message."""

    result: str


class TestService:
    """Test service for enhanced API testing."""

    def echo(self, request: SampleRequest) -> SampleResponse:
        return SampleResponse(result=f"Echo: {request.value}")


class AsyncTestService:
    """Async test service for enhanced API testing."""

    async def echo(self, request: SampleRequest) -> SampleResponse:
        return SampleResponse(result=f"Echo: {request.value}")


def test_server_enhanced_init():
    """Test enhanced initialization for Server."""
    service = TestService()

    # Test with all parameters
    server = Server(service=service, port=50052, package_name="test.v1", max_workers=4)

    assert server._initial_service == service
    assert server._port == 50052
    assert server._package_name == "test.v1"

    # Test with minimal parameters
    server2 = Server()
    assert server2._initial_service is None
    assert server2._port == 50051  # default
    assert server2._package_name == ""  # default


def test_asyncio_server_enhanced_init():
    """Test enhanced initialization for AsyncIOServer."""
    service = AsyncTestService()

    # Test with all parameters
    server = AsyncIOServer(service=service, port=50053, package_name="test.async.v1")

    assert server._initial_service == service
    assert server._port == 50053
    assert server._package_name == "test.async.v1"

    # Test with minimal parameters
    server2 = AsyncIOServer()
    assert server2._initial_service is None
    assert server2._port == 50051  # default
    assert server2._package_name == ""  # default


def test_asgi_app_enhanced_init():
    """Test enhanced initialization for ASGIApp."""
    service = AsyncTestService()

    # Test with all parameters
    app = ASGIApp(service=service, package_name="test.asgi.v1")

    assert app._initial_service == service
    assert app._package_name == "test.asgi.v1"

    # Test with minimal parameters
    app2 = ASGIApp()
    assert app2._initial_service is None
    assert app2._package_name == ""  # default


def test_wsgi_app_enhanced_init():
    """Test enhanced initialization for WSGIApp."""
    service = TestService()

    # Test with all parameters
    app = WSGIApp(service=service, package_name="test.wsgi.v1")

    assert app._initial_service == service
    assert app._package_name == "test.wsgi.v1"

    # Test with minimal parameters
    app2 = WSGIApp()
    assert app2._initial_service is None
    assert app2._package_name == ""  # default


def test_error_handler_decorator():
    """Test error_handler decorator functionality."""

    class ServiceWithErrorHandling:
        @error_handler(KeyError, status_code=grpc.StatusCode.NOT_FOUND)
        @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT)
        def get_item(self, request: SampleRequest) -> SampleResponse:
            if request.value == "missing":
                raise KeyError("Item not found")
            if request.value == "invalid":
                raise ValidationError("Invalid request")
            return SampleResponse(result=request.value)

    service = ServiceWithErrorHandling()

    # Test that error handlers are attached
    handlers = get_error_handlers(service.get_item)
    assert handlers is not None
    assert len(handlers) == 2

    # Check KeyError handler
    key_error_handler = next(h for h in handlers if h["exception_type"] is KeyError)
    assert key_error_handler["status_code"] == grpc.StatusCode.NOT_FOUND

    # Check ValidationError handler
    validation_handler = next(
        h for h in handlers if h["exception_type"] == ValidationError
    )
    assert validation_handler["status_code"] == grpc.StatusCode.INVALID_ARGUMENT


def test_error_handler_with_custom_handler():
    """Test error_handler decorator with custom handler function."""

    def custom_handler(exc: Exception) -> tuple[str, dict]:
        return f"Custom error: {str(exc)}", {"code": "CUSTOM_001"}

    class ServiceWithCustomHandler:
        @error_handler(
            RuntimeError, status_code=grpc.StatusCode.INTERNAL, handler=custom_handler
        )
        def process(self, request: SampleRequest) -> SampleResponse:
            raise RuntimeError("Something went wrong")

    service = ServiceWithCustomHandler()

    # Test that custom handler is attached
    handlers = get_error_handlers(service.process)
    assert handlers is not None
    assert len(handlers) == 1

    handler = handlers[0]
    assert handler["exception_type"] is RuntimeError
    assert handler["status_code"] == grpc.StatusCode.INTERNAL
    assert handler["handler"] == custom_handler


@pytest.mark.asyncio
async def test_async_error_handler():
    """Test error_handler decorator with async methods."""

    class AsyncServiceWithErrorHandling:
        @error_handler(ValueError, status_code=grpc.StatusCode.OUT_OF_RANGE)
        async def calculate(self, request: SampleRequest) -> SampleResponse:
            if request.value == "zero":
                raise ValueError("Cannot divide by zero")
            return SampleResponse(result=f"Result: {request.value}")

    service = AsyncServiceWithErrorHandling()

    # Test that error handlers work with async methods
    handlers = get_error_handlers(service.calculate)
    assert handlers is not None
    assert len(handlers) == 1

    handler = handlers[0]
    assert handler["exception_type"] is ValueError
    assert handler["status_code"] == grpc.StatusCode.OUT_OF_RANGE

    # Test the actual method still works
    result = await service.calculate(SampleRequest(value="test"))
    assert result.result == "Result: test"

    # Test that the exception is still raised (decorator doesn't catch)
    with pytest.raises(ValueError):
        await service.calculate(SampleRequest(value="zero"))


def test_server_production_parameters():
    """Test Server constructor with production-ready parameters."""
    # Test with production parameters
    options = [
        ('grpc.keepalive_time_ms', 10000),
        ('grpc.keepalive_timeout_ms', 5000),
        ('grpc.keepalive_permit_without_calls', True),
    ]

    server = Server(
        max_workers=10,
        options=options,
        maximum_concurrent_rpcs=100,
        compression=grpc.Compression.Gzip,
    )

    assert server._server is not None
    assert server._port == 50051  # default port

    # Test with minimal parameters
    server2 = Server(
        max_workers=5,
    )
    assert server2._server is not None
