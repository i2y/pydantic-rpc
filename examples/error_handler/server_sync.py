"""
Error Handler Example for pydantic-rpc (Synchronous gRPC Server)

This example demonstrates how to use the @error_handler decorator with
the synchronous Server class (gRPC with ThreadPoolExecutor).
"""

import grpc
from pydantic import ValidationError, field_validator

from pydantic_rpc import Server, Message, error_handler


class UserRequest(Message):
    """User request with validation rules."""

    name: str
    age: int
    email: str

    @field_validator("age")
    @classmethod
    def validate_age(cls, v):
        if v < 0 or v > 120:
            raise ValueError("Age must be between 0 and 120")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if "@" not in v:
            raise ValueError("Invalid email format")
        return v


class UserResponse(Message):
    """User response message."""

    message: str
    user_id: int


def validation_error_handler(exc: ValidationError, request_data) -> tuple[str, dict]:
    """
    Custom handler for validation errors (synchronous version).

    Args:
        exc: The ValidationError that was raised
        request_data: The raw protobuf request (optional)

    Returns:
        Tuple of (error_message, error_details)
    """
    errors = exc.errors()
    error_msg = f"Validation failed: {len(errors)} error(s) found"

    details = {
        "error_count": len(errors),
        "errors": [
            {
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in errors
        ],
    }

    if request_data:
        error_msg += " (request received)"

    return error_msg, details


class UserService:
    """Synchronous service for managing users with custom error handling."""

    @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT, handler=validation_error_handler)
    def create_user(self, request: UserRequest) -> UserResponse:
        """
        Create a new user (synchronous).

        This method uses @error_handler to customize validation error responses.
        """
        return UserResponse(
            message=f"User {request.name} created successfully",
            user_id=12345,
        )

    @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT)
    def update_user(self, request: UserRequest) -> UserResponse:
        """
        Update an existing user (synchronous).

        Uses @error_handler with default error handling.
        """
        return UserResponse(
            message=f"User {request.name} updated successfully",
            user_id=12345,
        )

    def delete_user(self, request: UserRequest) -> UserResponse:
        """
        Delete a user (synchronous).

        No @error_handler - uses default behavior.
        """
        return UserResponse(
            message=f"User {request.name} deleted successfully",
            user_id=12345,
        )


if __name__ == "__main__":
    print("Starting synchronous gRPC server on port 50052...")
    print("\nThis server demonstrates error_handler decorator with:")
    print("- Server (synchronous gRPC)")
    print("- ThreadPoolExecutor for concurrency")
    print("- Same error handling features as async version")
    print("\nTry sending invalid requests to see error responses!")

    server = Server(
        port=50052,
        package_name="examples.error_handler.v1",
        max_workers=10,
    )

    server.run(UserService())
