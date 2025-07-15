from io import BytesIO
import pytest
from pydantic_rpc.core import ASGIApp, WSGIApp, ConnecpyWSGIApp, ConnecpyASGIApp
from pydantic_rpc import Message


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


def base_wsgi_app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"Hello, world!"]


async def base_asgi_app(scope, receive, send):
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

    sent_messages = []

    async def test_send(message):
        sent_messages.append(message)

    async def test_receive():
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

    def start_response(status, headers):
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
    app.mount(echo_service)

    sent_messages = []

    async def test_send(message):
        sent_messages.append(message)

    async def test_receive():
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

    def start_response(status, headers):
        status_headers["status"] = status
        status_headers["headers"] = headers
        print(status, headers)

    result = app.__call__(environ, start_response)
    response_body = b"".join(result)

    assert status_headers.get("status") == "200 OK"
    print(response_body)
    assert b"HELLO" in response_body  # Response should contain uppercased input
