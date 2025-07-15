from io import BytesIO
import pytest
from collections.abc import Callable, Awaitable
from typing import Any

from pydantic_rpc.core import ASGIApp, WSGIApp, ConnecpyWSGIApp, ConnecpyASGIApp
from pydantic_rpc import Message

import tests.asyncechoservice_pb2_grpc as async_pb2_grpc
import tests.asyncechoservice_pb2 as async_pb2
import tests.echoservice_pb2_grpc as sync_pb2_grpc
import tests.echoservice_pb2 as sync_pb2
import tests.asyncechoservice_connecpy as async_connecpy
import tests.echoservice_connecpy as sync_connecpy


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


def base_wsgi_app(environ: dict[str, Any], start_response: Callable[[str, list[tuple[str, str]]], None]) -> list[bytes]:
    _ = environ
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"Hello, world!"]


async def base_asgi_app(scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    _ = scope
    _ = receive
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": b"Hello, world!"})


@pytest.mark.asyncio
async def test_asgi():
    app = ASGIApp(base_asgi_app)
    echo_service = AsyncEchoService()
    app.mount(echo_service)

    sent_messages: list[dict[str, Any]] = []

    async def test_send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    async def test_receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    await app.__call__(
        {
            "type": "http",
            "method": "POST",
            "path": "/EchoService/echo",
        },
        test_receive,
        test_send,
    )

    assert len(sent_messages) > 0


def test_wsgi():
    app = WSGIApp(base_wsgi_app)
    echo_service = EchoService()
    app.mount(echo_service)

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        _ = headers
        assert status == "200 OK"

    app.__call__(
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/EchoService/echo",
            "SERVER_PROTOCOL": "HTTP/1.1",
        },
        start_response,
    )


@pytest.mark.asyncio
async def test_connecpy_asgi():
    """Test ConnecpyASGIApp with EchoService."""
    app = ConnecpyASGIApp()
    echo_service = AsyncEchoService()
    app.mount_using_pb2_modules(async_connecpy, async_pb2, echo_service)

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


def test_connecpy_wsgi():
    app = ConnecpyWSGIApp()
    echo_service = EchoService()
    app.mount_using_pb2_modules(sync_connecpy, sync_pb2, echo_service)

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
