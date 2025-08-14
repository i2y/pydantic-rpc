"""Tests for empty message handling."""

import pytest
from pydantic_rpc import Message, AsyncIOServer
from pydantic_rpc.core import (
    generate_message_definition,
    protobuf_type_mapping,
    generate_combined_proto,
)


class EmptyRequest(Message):
    """An empty request message."""

    pass


class EmptyResponse(Message):
    """An empty response message."""

    pass


class SimpleResponse(Message):
    """A simple response with a field."""

    value: str


class MessageWithEmptyField(Message):
    """A message that contains an empty message as a field."""

    name: str
    empty_field: EmptyRequest


def test_empty_message_detection():
    """Test that empty messages are detected correctly."""
    # Empty message should be detected
    assert not EmptyRequest.model_fields
    assert not EmptyResponse.model_fields

    # Non-empty message should have fields
    assert SimpleResponse.model_fields
    assert "value" in SimpleResponse.model_fields


def test_empty_message_proto_mapping():
    """Test that empty messages map to google.protobuf.Empty."""
    # Empty messages should map to google.protobuf.Empty
    assert protobuf_type_mapping(EmptyRequest) == "google.protobuf.Empty"
    assert protobuf_type_mapping(EmptyResponse) == "google.protobuf.Empty"

    # Non-empty messages should map to their class name
    assert protobuf_type_mapping(SimpleResponse) == "SimpleResponse"


def test_empty_message_definition_generation():
    """Test that empty messages generate special marker."""
    done_enums = set()
    done_messages = set()

    # Empty message should return special marker
    msg_def, refs = generate_message_definition(EmptyRequest, done_enums, done_messages)
    assert msg_def == "__EMPTY__"
    assert refs == []

    # Non-empty message should generate proper definition
    msg_def, refs = generate_message_definition(
        SimpleResponse, done_enums, done_messages
    )
    assert msg_def != "__EMPTY__"
    assert "string value = 1" in msg_def


def test_message_with_empty_field():
    """Test that messages containing empty message fields work correctly."""
    done_enums = set()
    done_messages = set()

    msg_def, refs = generate_message_definition(
        MessageWithEmptyField, done_enums, done_messages
    )
    assert msg_def != "__EMPTY__"
    assert "string name = 1" in msg_def
    # The empty_field should map to google.protobuf.Empty
    assert "google.protobuf.Empty empty_field = 2" in msg_def


def test_service_with_empty_messages():
    """Test that services with empty messages generate correct proto."""

    class TestService:
        """Service with empty message methods."""

        async def health_check(self, request: EmptyRequest) -> SimpleResponse:
            """Health check with empty request."""
            return SimpleResponse(value="healthy")

        async def void_operation(self, request: EmptyRequest) -> EmptyResponse:
            """Operation with empty request and response."""
            return EmptyResponse()

        async def get_status(self) -> SimpleResponse:
            """Method with no request (implicitly empty)."""
            return SimpleResponse(value="ok")

    service = TestService()
    proto = generate_combined_proto(service, package_name="test.v1")

    # Check that google.protobuf.Empty import is included
    assert 'import "google/protobuf/empty.proto"' in proto

    # Check RPC definitions use google.protobuf.Empty
    assert "rpc HealthCheck (google.protobuf.Empty) returns (SimpleResponse)" in proto
    assert (
        "rpc VoidOperation (google.protobuf.Empty) returns (google.protobuf.Empty)"
        in proto
    )
    assert "rpc GetStatus (google.protobuf.Empty) returns (SimpleResponse)" in proto

    # Empty message definitions should not be included
    assert "message EmptyRequest" not in proto
    assert "message EmptyResponse" not in proto

    # Non-empty message should be defined
    assert "message SimpleResponse" in proto


@pytest.mark.asyncio
async def test_empty_message_runtime():
    """Test that empty messages work at runtime with AsyncIOServer."""

    class RuntimeTestService:
        """Service for runtime testing."""

        async def echo_empty(self, request: EmptyRequest) -> EmptyResponse:
            """Echo empty messages."""
            assert isinstance(request, EmptyRequest)
            return EmptyResponse()

        async def get_value(self) -> SimpleResponse:
            """Get a value with no request."""
            return SimpleResponse(value="test")

    # This should not raise any errors
    server = AsyncIOServer()
    server.mount(RuntimeTestService())

    # Verify the service was mounted successfully
    assert len(server._service_names) == 1
    assert "RuntimeTestService" in server._service_names[0]


def test_error_on_direct_protobuf_usage():
    """Test that using protobuf messages directly raises an error."""

    # Mock a protobuf message (has DESCRIPTOR attribute)
    class FakeProtobufMessage:
        DESCRIPTOR = "fake_descriptor"
        __name__ = "FakeProtobufMessage"

    class BadService:
        """Service incorrectly using protobuf messages."""

        async def bad_method(self, request: FakeProtobufMessage) -> SimpleResponse:
            """Method using protobuf message directly."""
            return SimpleResponse(value="bad")

    service = BadService()

    # Should raise TypeError when generating proto
    with pytest.raises(TypeError) as exc_info:
        generate_combined_proto(service, package_name="test.v1")

    assert "uses protobuf message" in str(exc_info.value)
    assert "FakeProtobufMessage" in str(exc_info.value)
    assert "Please use Pydantic Message classes" in str(exc_info.value)
