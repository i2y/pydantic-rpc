"""Example demonstrating empty messages and Pydantic serializers with pydantic-rpc."""

from typing import Any
from pydantic import field_serializer, model_serializer
from pydantic_rpc import AsyncIOServer, Message
import asyncio


# Example 1: Empty Request/Response Messages
class EmptyRequest(Message):
    """An empty request message that will automatically use google.protobuf.Empty."""

    pass


class EmptyResponse(Message):
    """An empty response message that will automatically use google.protobuf.Empty."""

    pass


class GreetingResponse(Message):
    """A simple greeting response."""

    message: str


# Example 2: Custom Serialization with @field_serializer
class UserMessage(Message):
    """A message with custom field serialization."""

    name: str
    age: int

    @field_serializer("name")
    def serialize_name(self, name: str) -> str:
        """Always uppercase the name when serializing."""
        return name.upper()

    @field_serializer("age")
    def serialize_age(self, age: int) -> int:
        """Double the age for some reason (example only)."""
        return age * 2


# Example 3: Custom Model Serialization with @model_serializer
class ComplexMessage(Message):
    """A message with custom model-level serialization."""

    value: int
    multiplier: int

    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        """Custom serialization that computes a result field."""
        return {
            "value": self.value,
            "multiplier": self.multiplier,
            "result": self.value * self.multiplier,  # Computed field
        }


class StatusMessage(Message):
    """Response message with status information."""

    status: str
    details: str | None = None


# Service demonstrating all features
class ExampleService:
    """Service demonstrating empty messages and custom serializers."""

    async def health_check(self, request: EmptyRequest) -> StatusMessage:
        """Health check with empty request."""
        return StatusMessage(status="healthy", details="All systems operational")

    async def get_default_greeting(self) -> GreetingResponse:
        """Method with no request parameter (implicitly empty)."""
        return GreetingResponse(message="Hello, World!")

    async def process_user(self, request: UserMessage) -> UserMessage:
        """Process user with custom field serialization.

        The name will be uppercased and age doubled due to serializers.
        """
        # The serializers will be applied when converting to protobuf
        return UserMessage(name=request.name, age=request.age)

    async def calculate(self, request: ComplexMessage) -> ComplexMessage:
        """Calculate with custom model serialization.

        The response will include a computed 'result' field.
        """
        # The model serializer will add a 'result' field
        return ComplexMessage(value=request.value, multiplier=request.multiplier)

    async def void_operation(self, request: EmptyRequest) -> EmptyResponse:
        """An operation that takes nothing and returns nothing."""
        # Do some work here...
        print("Performing void operation")
        return EmptyResponse()


async def main():
    """Run the example service."""
    server = AsyncIOServer()

    port = 50051
    server.set_port(port)

    print(f"Starting gRPC server on port {port}")
    print("\nAvailable methods:")
    print("  - health_check: Empty request -> Status response")
    print("  - get_default_greeting: No parameters -> Greeting")
    print("  - process_user: User with custom serialization")
    print("  - calculate: Complex message with model serializer")
    print("  - void_operation: Empty -> Empty")
    print("\nEmpty messages automatically use google.protobuf.Empty")
    print("Custom serializers are applied during protobuf conversion")

    await server.run(ExampleService())


if __name__ == "__main__":
    asyncio.run(main())
