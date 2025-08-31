#!/usr/bin/env python3
"""
Example showcasing the enhanced API features of pydantic-rpc.

This example demonstrates:
1. Enhanced initialization API for servers
2. Error handling with decorators
3. CLI tool usage
"""

import asyncio
from typing import Optional
from pydantic import ValidationError
import grpc

from pydantic_rpc import (
    AsyncIOServer,
    ASGIApp,
    Message,
    error_handler,
)


# Define our message types
class User(Message):
    """User model."""

    id: str
    name: str
    email: str
    age: Optional[int] = None


class GetUserRequest(Message):
    """Request for getting a user."""

    id: str


class CreateUserRequest(Message):
    """Request for creating a user."""

    name: str
    email: str
    age: Optional[int] = None


class UpdateUserRequest(Message):
    """Request for updating a user."""

    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    age: Optional[int] = None


class DeleteUserRequest(Message):
    """Request for deleting a user."""

    id: str


class Empty(Message):
    """Empty response."""

    pass


# Mock database
users_db = {
    "1": User(id="1", name="Alice", email="alice@example.com", age=30),
    "2": User(id="2", name="Bob", email="bob@example.com", age=25),
}


class UserService:
    """User management service with enhanced error handling."""

    @error_handler(KeyError, status_code=grpc.StatusCode.NOT_FOUND)
    @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT)
    async def get_user(self, request: GetUserRequest) -> User:
        """Get a user by ID."""
        if request.id not in users_db:
            raise KeyError(f"User with ID {request.id} not found")
        return users_db[request.id]

    @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT)
    async def create_user(self, request: CreateUserRequest) -> User:
        """Create a new user."""
        # Generate a new ID
        new_id = str(len(users_db) + 1)

        # Validate age if provided
        if request.age is not None and request.age < 0:
            raise ValidationError("Age must be non-negative")

        # Create the user
        user = User(id=new_id, name=request.name, email=request.email, age=request.age)
        users_db[new_id] = user
        return user

    @error_handler(KeyError, status_code=grpc.StatusCode.NOT_FOUND)
    @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT)
    async def update_user(self, request: UpdateUserRequest) -> User:
        """Update an existing user."""
        if request.id not in users_db:
            raise KeyError(f"User with ID {request.id} not found")

        user = users_db[request.id]
        if request.name is not None:
            user.name = request.name
        if request.email is not None:
            user.email = request.email
        if request.age is not None:
            if request.age < 0:
                raise ValidationError("Age must be non-negative")
            user.age = request.age

        return user

    @error_handler(KeyError, status_code=grpc.StatusCode.NOT_FOUND)
    async def delete_user(self, request: DeleteUserRequest) -> Empty:
        """Delete a user."""
        if request.id not in users_db:
            raise KeyError(f"User with ID {request.id} not found")

        del users_db[request.id]
        return Empty()


async def run_grpc_server():
    """Run the service as a gRPC server with the enhanced API."""
    # Using the new enhanced initialization API
    server = AsyncIOServer(service=UserService(), port=50051, package_name="user.v1")

    print("Starting gRPC server with enhanced API...")
    print("Server initialized with:")
    print("  - Service: UserService")
    print("  - Port: 50051")
    print("  - Package: user.v1")
    print("\nThe server includes automatic error handling:")
    print("  - KeyError → NOT_FOUND")
    print("  - ValidationError → INVALID_ARGUMENT")

    await server.run()


def create_asgi_app():
    """Create an ASGI app with the enhanced API."""
    # Using the new enhanced initialization API for ASGI
    app = ASGIApp(service=UserService(), package_name="user.v1")

    print("ASGI app created with enhanced API")
    print("Run with: uvicorn enhanced_api_example:app")

    return app


# For ASGI servers
app = create_asgi_app()


if __name__ == "__main__":
    # Example of how to use the service
    print("""
Enhanced API Example
====================

This example demonstrates the new enhanced APIs:

1. Enhanced Initialization:
   - Server(service=MyService(), port=50051, package_name="my.package")
   - ASGIApp(service=MyService(), package_name="my.package")

2. Error Handling:
   - @error_handler decorator for automatic exception mapping

3. CLI Usage:
   # Generate proto file
   pydantic-rpc generate enhanced_api_example.UserService --output ./proto/
   
   # Start server directly
   pydantic-rpc serve enhanced_api_example.UserService --port 50051
   
   # Create ASGI app
   pydantic-rpc serve enhanced_api_example.UserService --asgi

====================
    """)

    # Run the gRPC server
    asyncio.run(run_grpc_server())
