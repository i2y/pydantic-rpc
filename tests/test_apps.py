from io import BytesIO
import pytest
from typing import Any, AsyncIterator

from pydantic_rpc.core import ASGIApp, WSGIApp
from pydantic_rpc import Message

import random
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
