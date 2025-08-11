from typing import AsyncIterator
from pydantic_rpc import ASGIApp, Message


class HelloRequest(Message):
    """Request message.
    This is a simple example of a request message.

    Attributes:
        name (str): The name of the person to greet.
    """

    name: str


class HelloReply(Message):
    """Reply message.
    This is a simple example of a reply message.

    Attributes:
        message (str): The message to be sent.
    """

    message: str


class Greeter:
    """Greeter service.
    This is a simple example of a service that greets you.
    """

    async def say_hello(self, request: HelloRequest) -> HelloReply:
        """Says hello to the user.

        Args:
            request (HelloRequest): The request message.

        Returns:
            HelloReply: The reply message.
        """
        return HelloReply(message=f"Hello, {request.name}!")

    async def say_hello_stream(
        self, request: HelloRequest
    ) -> AsyncIterator[HelloReply]:
        """Says hello multiple times with streaming.

        This demonstrates server-side streaming in Connect RPC.

        Args:
            request (HelloRequest): The request message.

        Yields:
            HelloReply: Multiple greeting messages.
        """
        greetings = [
            f"Hello, {request.name}!",
            f"Nice to meet you, {request.name}!",
            f"How are you today, {request.name}?",
            f"Have a great day, {request.name}!",
        ]

        for greeting in greetings:
            yield HelloReply(message=greeting)


app = ASGIApp()
app.mount(Greeter())
