"""Tests for Pydantic serializer support."""

from typing import Any
from pydantic import field_serializer, model_serializer, model_validator
from pydantic_rpc import Message
from pydantic_rpc.core import (
    convert_python_message_to_proto,
    generate_message_converter,
)
import types


class MessageWithFieldSerializer(Message):
    """Message with custom field serializer."""

    name: str
    value: int

    @field_serializer("name")
    def serialize_name(self, name: str) -> str:
        """Always uppercase the name."""
        return name.upper()

    @field_serializer("value")
    def serialize_value(self, value: int) -> int:
        """Double the value."""
        return value * 2


class MessageWithModelSerializer(Message):
    """Message with custom model serializer."""

    x: int
    y: int

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        """Custom model serialization."""
        return {
            "x": self.x * 10,
            "y": self.y * 10,
        }


class MessageWithValidator(Message):
    """Message with custom validator."""

    value: int

    @model_validator(mode="after")
    def validate_value(self) -> "MessageWithValidator":
        """Ensure value is positive."""
        if self.value < 0:
            self.value = abs(self.value)
        return self


def test_field_serializer_applied():
    """Test that field serializers are applied during proto conversion."""
    msg = MessageWithFieldSerializer(name="hello", value=5)

    # Create a mock pb2 module
    pb2_module = types.ModuleType("test_pb2")

    # Create a mock protobuf class
    class MockProto:
        def __init__(self, **kwargs):
            self.name = kwargs.get("name")
            self.value = kwargs.get("value")

    setattr(pb2_module, "MessageWithFieldSerializer", MockProto)

    # Convert to proto
    proto_msg = convert_python_message_to_proto(
        msg, MessageWithFieldSerializer, pb2_module
    )

    # Field serializers should have been applied
    assert proto_msg.name == "HELLO"  # Uppercased
    assert proto_msg.value == 10  # Doubled


def test_model_serializer_applied():
    """Test that model serializers are applied during proto conversion."""
    msg = MessageWithModelSerializer(x=2, y=3)

    # Create a mock pb2 module
    pb2_module = types.ModuleType("test_pb2")

    # Create a mock protobuf class
    class MockProto:
        def __init__(self, **kwargs):
            self.x = kwargs.get("x")
            self.y = kwargs.get("y")

    setattr(pb2_module, "MessageWithModelSerializer", MockProto)

    # Convert to proto
    proto_msg = convert_python_message_to_proto(
        msg, MessageWithModelSerializer, pb2_module
    )

    # Model serializer should have been applied
    assert proto_msg.x == 20  # x * 10
    assert proto_msg.y == 30  # y * 10


def test_model_validator_applied():
    """Test that model validators are applied during deserialization."""
    # The validator should convert negative values to positive
    converter = generate_message_converter(MessageWithValidator)

    # Create a mock protobuf message with negative value
    class MockProtoRequest:
        value = -42

    # Convert from proto to Python
    result = converter(MockProtoRequest())

    # Validator should have been applied
    assert isinstance(result, MessageWithValidator)
    assert result.value == 42  # Absolute value applied by validator


def test_serializer_with_optional_fields():
    """Test serializers work with optional fields."""

    class OptionalMessage(Message):
        """Message with optional field and serializer."""

        name: str | None = None

        @field_serializer("name")
        def serialize_name(self, name: str | None) -> str | None:
            """Uppercase if present."""
            return name.upper() if name else None

    # Test with value
    msg_with_value = OptionalMessage(name="test")
    pb2_module = types.ModuleType("test_pb2")

    class MockProto:
        def __init__(self, **kwargs):
            self.name = kwargs.get("name")

    setattr(pb2_module, "OptionalMessage", MockProto)

    proto_msg = convert_python_message_to_proto(
        msg_with_value, OptionalMessage, pb2_module
    )
    assert proto_msg.name == "TEST"

    # Test without value
    msg_without_value = OptionalMessage()
    proto_msg2 = convert_python_message_to_proto(
        msg_without_value, OptionalMessage, pb2_module
    )
    assert proto_msg2.name is None


def test_multiple_serializers():
    """Test that multiple serializers can be combined."""

    class ComplexMessage(Message):
        """Message with multiple serializers."""

        first_name: str
        last_name: str
        age: int

        @field_serializer("first_name", "last_name")
        def serialize_names(self, value: str) -> str:
            """Capitalize names."""
            return value.capitalize()

        @field_serializer("age")
        def serialize_age(self, age: int) -> int:
            """Round age to nearest 10."""
            return round(age / 10) * 10

    msg = ComplexMessage(first_name="john", last_name="DOE", age=27)

    pb2_module = types.ModuleType("test_pb2")

    class MockProto:
        def __init__(self, **kwargs):
            self.first_name = kwargs.get("first_name")
            self.last_name = kwargs.get("last_name")
            self.age = kwargs.get("age")

    setattr(pb2_module, "ComplexMessage", MockProto)

    proto_msg = convert_python_message_to_proto(msg, ComplexMessage, pb2_module)

    assert proto_msg.first_name == "John"  # Capitalized
    assert proto_msg.last_name == "Doe"  # Capitalized
    assert proto_msg.age == 30  # Rounded to nearest 10


def test_serializer_error_handling():
    """Test that serialization errors are handled gracefully."""

    class ErrorMessage(Message):
        """Message with a problematic serializer."""

        value: int

        @field_serializer("value")
        def serialize_value(self, value: int) -> int:
            """Serializer that might fail."""
            if value == 0:
                raise ValueError("Cannot serialize zero")
            return value

    # This should work
    msg_ok = ErrorMessage(value=5)
    pb2_module = types.ModuleType("test_pb2")

    class MockProto:
        def __init__(self, **kwargs):
            self.value = kwargs.get("value")

    setattr(pb2_module, "ErrorMessage", MockProto)

    proto_msg = convert_python_message_to_proto(msg_ok, ErrorMessage, pb2_module)
    assert proto_msg.value == 5

    # This should fall back to direct attribute access
    msg_error = ErrorMessage(value=0)
    # The serializer will raise an error, but we should fall back
    # Since we catch exceptions in convert_python_message_to_proto
    proto_msg2 = convert_python_message_to_proto(msg_error, ErrorMessage, pb2_module)
    assert proto_msg2.value == 0  # Falls back to original value
