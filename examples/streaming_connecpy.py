"""Example of streaming RPCs using Connecpy with pydantic-rpc."""

from typing import AsyncIterator
from pydantic_rpc import ASGIApp, Message


class ChatMessage(Message):
    """A chat message."""

    user: str
    text: str


class ChatResponse(Message):
    """A response from the chat service."""

    message: str
    timestamp: str


class ChatService:
    """A chat service demonstrating various streaming patterns."""

    async def send_message(self, request: ChatMessage) -> ChatResponse:
        """Unary RPC: Send a single message and get a response."""
        import datetime

        return ChatResponse(
            message=f"Received from {request.user}: {request.text}",
            timestamp=datetime.datetime.now().isoformat(),
        )

    async def stream_updates(self, request: ChatMessage) -> AsyncIterator[ChatResponse]:
        """Server streaming: Send a message and receive a stream of updates."""
        import datetime
        import asyncio

        # Simulate streaming updates
        for i in range(5):
            await asyncio.sleep(0.1)  # Simulate processing
            yield ChatResponse(
                message=f"Update {i + 1} for {request.user}: Processing '{request.text}'",
                timestamp=datetime.datetime.now().isoformat(),
            )

    async def batch_send(self, requests: AsyncIterator[ChatMessage]) -> ChatResponse:
        """Client streaming: Send multiple messages and get a summary response."""
        import datetime

        messages = []
        users = set()

        async for msg in requests:
            messages.append(msg.text)
            users.add(msg.user)

        return ChatResponse(
            message=f"Received {len(messages)} messages from {len(users)} users",
            timestamp=datetime.datetime.now().isoformat(),
        )

    async def chat_session(
        self, requests: AsyncIterator[ChatMessage]
    ) -> AsyncIterator[ChatResponse]:
        """Bidirectional streaming: Real-time chat session."""
        import datetime

        async for msg in requests:
            # Echo each message back with a response
            yield ChatResponse(
                message=f"Echo from server: {msg.user} said '{msg.text}'",
                timestamp=datetime.datetime.now().isoformat(),
            )

            # Send a follow-up message
            yield ChatResponse(
                message=f"Server acknowledges message from {msg.user}",
                timestamp=datetime.datetime.now().isoformat(),
            )


# Create the Connecpy ASGI application
app = ASGIApp()
app.mount(ChatService())


if __name__ == "__main__":
    import uvicorn

    print("Starting Connecpy streaming service on http://localhost:8000")
    print("\nAvailable endpoints:")
    print("  POST /chat.v1.ChatService/send_message       - Unary RPC")
    print("  POST /chat.v1.ChatService/stream_updates     - Server streaming")
    print("  POST /chat.v1.ChatService/batch_send         - Client streaming")
    print("  POST /chat.v1.ChatService/chat_session       - Bidirectional streaming")
    print("\nUse a Connect RPC client to interact with these endpoints.")

    uvicorn.run(app, host="0.0.0.0", port=8000)
