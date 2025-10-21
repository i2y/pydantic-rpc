"""
Error Handler Example for pydantic-rpc (Sync Connect RPC - WSGI)

This example demonstrates how to use the @error_handler decorator with
WSGIApp for synchronous Connect RPC over HTTP/JSON.
"""

from wsgiref.simple_server import make_server

from connectrpc.code import Code
from pydantic import ValidationError, field_validator

from pydantic_rpc import WSGIApp, Message, error_handler


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
    Custom handler for validation errors (sync Connect RPC version).

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
    """Synchronous service for managing users with custom error handling (Connect RPC)."""

    @error_handler(ValidationError, connect_code=Code.INVALID_ARGUMENT, handler=validation_error_handler)
    def create_user(self, request: UserRequest) -> UserResponse:
        """
        Create a new user (synchronous).

        This method uses @error_handler with Connect RPC error codes.
        Note: connect_code instead of status_code for Connect RPC!
        """
        return UserResponse(
            message=f"User {request.name} created successfully",
            user_id=12345,
        )

    @error_handler(ValidationError, connect_code=Code.INVALID_ARGUMENT)
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


# Create WSGI app
app = WSGIApp(package_name="examples.error_handler.v1")
app.mount_objs(UserService())


if __name__ == "__main__":
    print("Starting synchronous Connect RPC server (WSGI) on port 3000...")
    print("\nThis server demonstrates error_handler decorator with:")
    print("- WSGIApp (synchronous Connect RPC)")
    print("- HTTP/JSON protocol")
    print("- Same error handling features as other versions")
    print("\nTest with:")
    print('  curl -X POST http://localhost:3000/examples.error_handler.v1.UserService/CreateUser \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"name": "Bob", "age": 150, "email": "bob@example.com"}\'')

    with make_server("", 3000, app) as httpd:
        print("\nServer is running on http://localhost:3000")
        httpd.serve_forever()
