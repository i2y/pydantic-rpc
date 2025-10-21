# Error Handler Example

This example demonstrates how to use the `@error_handler` decorator to customize error handling in pydantic-rpc services across **all 4 server types**.

## Server Types Comparison

| Server | File | Protocol | Async/Sync | Port | Error Code | Start Command |
|--------|------|----------|-------|------|------------|---------------|
| AsyncIOServer | server.py | gRPC | Async | 50051 | grpc.StatusCode | `uv run python server.py` |
| Server | server_sync.py | gRPC | Sync | 50052 | grpc.StatusCode | `uv run python server_sync.py` |
| ASGIApp | server_asgi.py | Connect RPC | Async | 8000 | Code | `uvicorn server_asgi:app --port 8000` |
| WSGIApp | server_wsgi.py | Connect RPC | Sync | 3000 | Code | `uv run python server_wsgi.py` |

## Features Demonstrated

1. **Custom Validation Error Handler**: Access failed request data and provide detailed error messages
2. **Default Error Handler**: Use the decorator without a custom handler
3. **No Error Handler**: Compare with default behavior
4. **All Server Types**: Works with gRPC and Connect RPC, both sync and async

## Running the Examples

### 1. AsyncIOServer (Async gRPC) - Port 50051

```bash
uv run python server.py
```

### 2. Server (Sync gRPC) - Port 50052

```bash
uv run python server_sync.py
```

### 3. ASGIApp (Async Connect RPC) - Port 8000

```bash
uvicorn server_asgi:app --port 8000
```

### 4. WSGIApp (Sync Connect RPC) - Port 3000

```bash
uv run python server_wsgi.py
```

## Testing the Servers

### Testing gRPC Servers (AsyncIOServer / Server)

Use `buf curl` for gRPC servers:

#### Valid Request (should succeed)

```bash
# AsyncIOServer (port 50051)
buf curl --http2-prior-knowledge \
  --schema=./service.proto \
  -d '{"name": "Alice", "age": 30, "email": "alice@example.com"}' \
  http://localhost:50051/examples.error_handler.v1.UserService/CreateUser

# Server (port 50052)
buf curl --http2-prior-knowledge \
  --schema=./service.proto \
  -d '{"name": "Alice", "age": 30, "email": "alice@example.com"}' \
  http://localhost:50052/examples.error_handler.v1.UserService/CreateUser
```

#### Invalid Age - Custom Error Handler

```bash
# AsyncIOServer (port 50051)
buf curl --http2-prior-knowledge \
  --schema=./service.proto \
  -d '{"name": "Bob", "age": 150, "email": "bob@example.com"}' \
  http://localhost:50051/examples.error_handler.v1.UserService/CreateUser
```

**Expected**: Custom error message with detailed validation errors

#### Invalid Email - Default Error Handler

```bash
# AsyncIOServer (port 50051)
buf curl --http2-prior-knowledge \
  --schema=./service.proto \
  -d '{"name": "Charlie", "age": 25, "email": "invalid-email"}' \
  http://localhost:50051/examples.error_handler.v1.UserService/UpdateUser
```

**Expected**: Standard validation error message

#### No Error Handler

```bash
# AsyncIOServer (port 50051)
buf curl --http2-prior-knowledge \
  --schema=./service.proto \
  -d '{"name": "David", "age": -5, "email": "david@example.com"}' \
  http://localhost:50051/examples.error_handler.v1.UserService/DeleteUser
```

**Expected**: Default pydantic-rpc validation error

### Testing Connect RPC Servers (ASGIApp / WSGIApp)

Use `curl` for Connect RPC servers (HTTP/JSON):

#### Valid Request (should succeed)

```bash
# ASGIApp (port 8000)
curl -X POST http://localhost:8000/examples.error_handler.v1.UserService/CreateUser \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice", "age": 30, "email": "alice@example.com"}'

# WSGIApp (port 3000)
curl -X POST http://localhost:3000/examples.error_handler.v1.UserService/CreateUser \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice", "age": 30, "email": "alice@example.com"}'
```

#### Invalid Age - Custom Error Handler

```bash
# ASGIApp (port 8000)
curl -X POST http://localhost:8000/examples.error_handler.v1.UserService/CreateUser \
  -H "Content-Type: application/json" \
  -d '{"name": "Bob", "age": 150, "email": "bob@example.com"}'
```

**Expected**: Custom error message with detailed validation errors in JSON format

#### Invalid Email - Default Error Handler

```bash
# WSGIApp (port 3000)
curl -X POST http://localhost:3000/examples.error_handler.v1.UserService/UpdateUser \
  -H "Content-Type: application/json" \
  -d '{"name": "Charlie", "age": 25, "email": "invalid-email"}'
```

**Expected**: Standard validation error message in JSON format

#### No Error Handler

```bash
# ASGIApp (port 8000)
curl -X POST http://localhost:8000/examples.error_handler.v1.UserService/DeleteUser \
  -H "Content-Type: application/json" \
  -d '{"name": "David", "age": -5, "email": "david@example.com"}'
```

**Expected**: Default pydantic-rpc validation error in JSON format

## Key Concepts

### Custom Handler Function

The custom handler function can accept either:
- Just the exception: `handler(exc: Exception) -> tuple[str, dict]`
- Exception and request data: `handler(exc: Exception, request_data: Any) -> tuple[str, dict]`

Example:

```python
def validation_error_handler(exc: ValidationError, request_data) -> tuple[str, dict]:
    """Custom handler with access to failed request data."""
    errors = exc.errors()
    return f"Validation failed: {len(errors)} error(s)", {"errors": errors}

@error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT, handler=validation_error_handler)
async def create_user(self, request: UserRequest) -> UserResponse:
    ...
```

### gRPC vs Connect RPC Error Codes

**Important**: Use the correct error code parameter for each server type!

#### gRPC Servers (AsyncIOServer / Server)

```python
import grpc

@error_handler(
    ValidationError,
    status_code=grpc.StatusCode.INVALID_ARGUMENT,  # Use status_code
    handler=validation_error_handler
)
```

#### Connect RPC Servers (ASGIApp / WSGIApp)

```python
from connectrpc.code import Code

@error_handler(
    ValidationError,
    connect_code=Code.INVALID_ARGUMENT,  # Use connect_code
    handler=validation_error_handler
)
```

### Sync vs Async Methods

#### Synchronous (Server / WSGIApp)

```python
def create_user(self, request: UserRequest) -> UserResponse:  # No async
    return UserResponse(...)
```

#### Asynchronous (AsyncIOServer / ASGIApp)

```python
async def create_user(self, request: UserRequest) -> UserResponse:  # async
    return UserResponse(...)
```
