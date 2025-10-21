"""
Error Handler Example for pydantic-rpc

This example demonstrates how to use the @error_handler decorator to:
1. Customize error handling for validation errors
2. Access the failed request data
3. Return custom error messages
"""

import grpc
from pydantic import ValidationError, field_validator

from pydantic_rpc import AsyncIOServer, Message, error_handler


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
    Custom handler for validation errors that accesses the failed request data.

    Args:
        exc: The ValidationError that was raised
        request_data: The raw protobuf request (optional)

    Returns:
        Tuple of (error_message, error_details)
    """
    errors = exc.errors()
    error_msg = f"Validation failed: {len(errors)} error(s) found"

    # Build detailed error information
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

    # If we have request_data, we could log it or include it in the response
    # (but be careful not to expose sensitive data)
    if request_data:
        error_msg += " (request received)"

    return error_msg, details


class UserService:
    """Service for managing users with custom error handling."""

    @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT, handler=validation_error_handler)
    async def create_user(self, request: UserRequest) -> UserResponse:
        """
        Create a new user.

        This method uses @error_handler to customize validation error responses.
        If the request fails validation, the custom handler will be called
        with access to both the ValidationError and the raw request data.
        """
        # Simulate user creation
        return UserResponse(
            message=f"User {request.name} created successfully",
            user_id=12345,
        )

    @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT)
    async def update_user(self, request: UserRequest) -> UserResponse:
        """
        Update an existing user.

        This method uses @error_handler with default error handling
        (no custom handler function).
        """
        return UserResponse(
            message=f"User {request.name} updated successfully",
            user_id=12345,
        )

    async def delete_user(self, request: UserRequest) -> UserResponse:
        """
        Delete a user.

        This method does NOT use @error_handler, so validation errors
        will be handled with the default behavior.
        """
        return UserResponse(
            message=f"User {request.name} deleted successfully",
            user_id=12345,
        )


if __name__ == "__main__":
    import asyncio

    print("Starting server on port 50051...")
    print("\nThis server demonstrates error_handler decorator:")
    print("- create_user: Uses custom validation error handler")
    print("- update_user: Uses default validation error handling")
    print("- delete_user: No error handler (default behavior)")
    print("\nTry sending invalid requests to see different error responses!")

    server = AsyncIOServer(
        port=50051,
        package_name="examples.error_handler.v1",
    )

    loop = asyncio.get_event_loop()
    loop.run_until_complete(server.run(UserService()))
