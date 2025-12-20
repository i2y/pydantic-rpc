from io import BytesIO
import pytest
from typing import Any, AsyncIterator
from concurrent import futures

from pydantic_rpc.core import ASGIApp, WSGIApp
from pydantic_rpc import Message

import random
import grpc
import grpc.aio
from pydantic_rpc.core import (
    AsyncIOServer,
    generate_and_compile_proto,
    generate_proto,
    is_skip_generation,
)
from tests.conftest import should_skip_connecpy_tests


class EchoRequest(Message):
    """Echo request message.

    Attributes:
        text (str): The text to echo.
    """

    text: str


class EchoResponse(Message):
    """Echo response message.

    Attributes:
        text (str): The echoed text.
    """

    text: str


class AsyncEchoService:
    """Echo service.
    A simple service that echoes messages back in uppercase.
    """

    async def echo(self, request: EchoRequest) -> EchoResponse:
        """Echo the message back in uppercase.

        Args:
            request (EchoRequest): The request message.

        Returns:
            EchoResponse: The response message.
        """
        return EchoResponse(text=request.text.upper())


class EchoService:
    """Echo service.
    A simple service that echoes messages back in uppercase.
    """

    def echo(self, request: EchoRequest) -> EchoResponse:
        """Echo the message back in uppercase.

        Args:
            request (EchoRequest): The request message.

        Returns:
            EchoResponse: The response message.
        """
        return EchoResponse(text=request.text.upper())


class UnaryStreamRequest(Message):
    text: str


class UnaryStreamResponse(Message):
    text: str


class UnaryStreamService:
    async def stream_response(
        self, request: UnaryStreamRequest
    ) -> AsyncIterator[UnaryStreamResponse]:
        yield UnaryStreamResponse(text=request.text.upper())
        yield UnaryStreamResponse(text=request.text.lower())


class StreamUnaryRequest(Message):
    text: str


class StreamUnaryResponse(Message):
    text: str


class StreamUnaryService:
    async def collect_requests(
        self, requests: AsyncIterator[StreamUnaryRequest]
    ) -> StreamUnaryResponse:
        collected: list[str] = []
        async for req in requests:
            collected.append(req.text)
        return StreamUnaryResponse(text=" ".join(collected))


class StreamStreamRequest(Message):
    text: str


class StreamStreamResponse(Message):
    text: str


class StreamStreamService:
    async def echo_stream(
        self, requests: AsyncIterator[StreamStreamRequest]
    ) -> AsyncIterator[StreamStreamResponse]:
        async for req in requests:
            yield StreamStreamResponse(text=req.text.upper())


@pytest.mark.skipif(
    should_skip_connecpy_tests(),
    reason="Skipping connect-python tests because connect-python is not installed",
)
@pytest.mark.asyncio
async def test_asgi():
    """Test ASGIApp with EchoService."""
    app = ASGIApp()
    echo_service = AsyncEchoService()
    app.mount(echo_service)

    sent_messages: list[dict[str, Any]] = []

    async def test_send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    async def test_receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b'{"text": "hello"}'}

    await app.__call__(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("localhost", 3000),
            "path": "/asyncecho.v1.AsyncEchoService/Echo",
            "client": ("127.0.0.1", 1234),
            "headers": [(b"content-type", b"application/json")],
        },
        test_receive,
        test_send,
    )

    assert len(sent_messages) > 0
    # Find the response body in sent messages
    response_body = None
    for msg in sent_messages:
        if msg.get("type") == "http.response.body":
            response_body = msg.get("body")
            break

    assert response_body is not None
    assert b"HELLO" in response_body  # Response should contain uppercased input


@pytest.mark.skipif(
    should_skip_connecpy_tests(),
    reason="Skipping connect-python tests because connect-python is not installed",
)
def test_wsgi():
    app = WSGIApp()
    echo_service = EchoService()
    app.mount(echo_service)

    body = b'{"text": "hello"}'
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/echo.v1.EchoService/Echo",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": BytesIO(body),
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
    }

    status_headers = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        _ = headers
        status_headers["status"] = status
        status_headers["headers"] = headers
        print(status, headers)

    result = app.__call__(environ, start_response)
    response_body = b"".join(result)

    assert status_headers.get("status") == "200 OK"
    print(response_body)
    assert b"HELLO" in response_body  # Response should contain uppercased input


def test_generate_proto_streaming():
    proto = generate_proto(UnaryStreamService())
    assert (
        "rpc StreamResponse (UnaryStreamRequest) returns (stream UnaryStreamResponse);"
        in proto
    )

    proto = generate_proto(StreamUnaryService())
    assert (
        "rpc CollectRequests (stream StreamUnaryRequest) returns (StreamUnaryResponse);"
        in proto
    )

    proto = generate_proto(StreamStreamService())
    assert (
        "rpc EchoStream (stream StreamStreamRequest) returns (stream StreamStreamResponse);"
        in proto
    )


@pytest.mark.asyncio
async def test_unary_stream_integration():
    if is_skip_generation():
        pytest.skip("Skipping generation tests")

    port = random.randint(50000, 60000)
    service = UnaryStreamService()
    pb2_grpc_module, pb2_module = generate_and_compile_proto(service)
    server = AsyncIOServer()
    server.mount_using_pb2_modules(pb2_grpc_module, pb2_module, service)
    _ = server._server.add_insecure_port(f"[::]:{port}")
    await server._server.start()

    try:
        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            stub_class = getattr(pb2_grpc_module, "UnaryStreamServiceStub")
            stub = stub_class(channel)
            responses = []
            async for resp in stub.StreamResponse(
                pb2_module.UnaryStreamRequest(text="Hello")
            ):  # type: ignore
                responses.append(resp.text)
            assert responses == ["HELLO", "hello"]
    finally:
        await server._server.stop(1)


@pytest.mark.asyncio
async def test_stream_unary_integration():
    if is_skip_generation():
        pytest.skip("Skipping generation tests")

    port = random.randint(50000, 60000)
    service = StreamUnaryService()
    pb2_grpc_module, pb2_module = generate_and_compile_proto(service)
    server = AsyncIOServer()
    server.mount_using_pb2_modules(pb2_grpc_module, pb2_module, service)
    _ = server._server.add_insecure_port(f"[::]:{port}")
    await server._server.start()

    try:
        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            stub_class = getattr(pb2_grpc_module, "StreamUnaryServiceStub")
            stub = stub_class(channel)

            async def request_gen():
                yield pb2_module.StreamUnaryRequest(text="Hello")
                yield pb2_module.StreamUnaryRequest(text="World")

            response = await stub.CollectRequests(request_gen())  # type: ignore
            assert response.text == "Hello World"
    finally:
        await server._server.stop(1)


@pytest.mark.asyncio
async def test_stream_stream_integration():
    if is_skip_generation():
        pytest.skip("Skipping generation tests")

    port = random.randint(50000, 60000)
    service = StreamStreamService()
    pb2_grpc_module, pb2_module = generate_and_compile_proto(service)
    server = AsyncIOServer()
    server.mount_using_pb2_modules(pb2_grpc_module, pb2_module, service)
    _ = server._server.add_insecure_port(f"[::]:{port}")
    await server._server.start()

    try:
        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            stub_class = getattr(pb2_grpc_module, "StreamStreamServiceStub")
            stub = stub_class(channel)

            async def request_gen():
                yield pb2_module.StreamStreamRequest(text="Hello")
                yield pb2_module.StreamStreamRequest(text="World")

            responses = []
            async for resp in stub.EchoStream(request_gen()):  # type: ignore
                responses.append(resp.text)
            assert responses == ["HELLO", "WORLD"]
    finally:
        await server._server.stop(1)


@pytest.mark.asyncio
async def test_asyncio_server_production_parameters():
    """Test AsyncIOServer constructor with production-ready parameters."""
    if is_skip_generation():
        pytest.skip("Skipping generation tests")

    # Test with production parameters
    thread_pool = futures.ThreadPoolExecutor(max_workers=4)
    options = [
        ("grpc.keepalive_time_ms", 10000),
        ("grpc.keepalive_timeout_ms", 5000),
        ("grpc.keepalive_permit_without_calls", True),
    ]

    try:
        server = AsyncIOServer(
            migration_thread_pool=thread_pool,
            options=options,
            maximum_concurrent_rpcs=100,
            compression=grpc.Compression.Gzip,
        )

        # Mount a simple service for testing
        service = AsyncEchoService()
        server.mount(service)

        port = random.randint(50000, 60000)
        _ = server._server.add_insecure_port(f"[::]:{port}")
        await server._server.start()

        # Simple connectivity test
        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            # Just verify the server is running and accessible
            await channel.channel_ready()

    finally:
        await server._server.stop(1)
        thread_pool.shutdown(wait=True)


def test_asyncio_server_shutdown_uses_threadsafe():
    """Shutdown handler must use call_soon_threadsafe.
    This test ensures that the AsyncIOServer.run() method uses
    call_soon_threadsafe for signal handling to avoid shutdown hangs.
    """
    import inspect

    source = inspect.getsource(AsyncIOServer.run)
    assert "call_soon_threadsafe" in source, (
        "AsyncIOServer.run() must use call_soon_threadsafe for signal handling. "
        "This fix was added in PR #12 and must not be removed. "
        "See Issue #51 for details."
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    __import__("sys").platform == "win32",
    reason="Signal handling test not supported on Windows",
)
async def test_asyncio_server_shutdown_with_signal():
    """Integration test: server must shutdown cleanly on SIGINT.

    This test verifies that the AsyncIOServer properly handles shutdown signals
    without hanging. It starts a server in a subprocess and sends SIGINT.
    """
    import subprocess
    import sys
    import signal
    import time

    if is_skip_generation():
        pytest.skip("Skipping generation tests")

    # Server code to run in subprocess
    server_code = """
import asyncio
from pydantic_rpc import AsyncIOServer, Message

class Req(Message):
    name: str

class Resp(Message):
    message: str

class TestService:
    async def greet(self, req: Req) -> Resp:
        return Resp(message=f"Hello, {req.name}")

async def main():
    server = AsyncIOServer(port=59999)
    await server.run(TestService())

asyncio.run(main())
"""

    # Start server in subprocess
    proc = subprocess.Popen(
        [sys.executable, "-c", server_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for server to start
        time.sleep(3)

        # Send SIGINT
        proc.send_signal(signal.SIGINT)

        # Server should shutdown within 15 seconds (10s grace period + buffer)
        proc.wait(timeout=15)

        # Check that it exited (any exit is fine, just not hanging)
        assert proc.returncode is not None, "Server process should have exited"

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail("Server did not shutdown within 15 seconds after SIGINT. ")
