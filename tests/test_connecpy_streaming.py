"""Tests for Connecpy streaming RPC support."""

import pytest
from typing import AsyncIterator
from pydantic_rpc import Message, ASGIApp
from tests.conftest import should_skip_connecpy_tests


class StreamRequest(Message):
    """Request message for streaming tests."""

    text: str
    count: int = 1


class StreamResponse(Message):
    """Response message for streaming tests."""

    text: str
    index: int


class StreamingService:
    """Service with various streaming RPC methods."""

    async def server_stream(
        self, request: StreamRequest
    ) -> AsyncIterator[StreamResponse]:
        """Server streaming RPC - unary request, stream response."""
        for i in range(request.count):
            yield StreamResponse(text=f"{request.text}_{i}", index=i)

    async def client_stream(
        self, requests: AsyncIterator[StreamRequest]
    ) -> StreamResponse:
        """Client streaming RPC - stream request, unary response."""
        texts = []
        total_count = 0
        async for req in requests:
            texts.append(req.text)
            total_count += req.count
        return StreamResponse(text=" ".join(texts), index=total_count)

    async def bidi_stream(
        self, requests: AsyncIterator[StreamRequest]
    ) -> AsyncIterator[StreamResponse]:
        """Bidirectional streaming RPC - stream request, stream response."""
        idx = 0
        async for req in requests:
            for i in range(req.count):
                yield StreamResponse(text=f"{req.text}_{idx}_{i}", index=idx)
                idx += 1


@pytest.mark.skipif(
    should_skip_connecpy_tests(),
    reason="Skipping connecpy tests because connecpy is not installed",
)
@pytest.mark.asyncio
async def test_connecpy_server_streaming():
    """Test server streaming RPC with ASGIApp."""
    app = ASGIApp()
    service = StreamingService()
    app.mount(service)

    # Note: Full integration testing would require a proper ASGI test client
    # This test primarily validates that the mounting and stub generation work
    assert len(app._services) == 1
    # Service name includes package prefix
    assert app._service_names[0].endswith(StreamingService.__name__)


@pytest.mark.skipif(
    should_skip_connecpy_tests(),
    reason="Skipping connecpy tests because connecpy is not installed",
)
@pytest.mark.asyncio
async def test_connecpy_client_streaming():
    """Test client streaming RPC with ASGIApp."""
    app = ASGIApp()
    service = StreamingService()
    app.mount(service)

    # Validate service is mounted correctly
    assert len(app._services) == 1
    assert app._service_names[0].endswith(StreamingService.__name__)


@pytest.mark.skipif(
    should_skip_connecpy_tests(),
    reason="Skipping connecpy tests because connecpy is not installed",
)
@pytest.mark.asyncio
async def test_connecpy_bidi_streaming():
    """Test bidirectional streaming RPC with ASGIApp."""
    app = ASGIApp()
    service = StreamingService()
    app.mount(service)

    # Validate service is mounted correctly
    assert len(app._services) == 1
    assert app._service_names[0].endswith(StreamingService.__name__)


@pytest.mark.skipif(
    should_skip_connecpy_tests(),
    reason="Skipping connecpy tests because connecpy is not installed",
)
@pytest.mark.asyncio
async def test_mixed_streaming_service():
    """Test a service with both streaming and unary methods."""

    class MixedService:
        """Service with mixed RPC types."""

        async def unary_method(self, request: StreamRequest) -> StreamResponse:
            """Standard unary RPC."""
            return StreamResponse(text=request.text, index=0)

        async def stream_method(
            self, request: StreamRequest
        ) -> AsyncIterator[StreamResponse]:
            """Server streaming RPC."""
            for i in range(request.count):
                yield StreamResponse(text=f"{request.text}_{i}", index=i)

    app = ASGIApp()
    service = MixedService()
    app.mount(service)

    # Validate service is mounted correctly
    assert len(app._services) == 1
    assert app._service_names[0].endswith(MixedService.__name__)
