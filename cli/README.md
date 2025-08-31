# pydantic-rpc-cli

CLI tool for [pydantic-rpc](https://github.com/yourusername/pydantic-rpc) with built-in server runtime support.

## Installation

```bash
pip install pydantic-rpc-cli
```

This will install:
- `pydantic-rpc` (core library)
- `hypercorn` (ASGI server)
- `gunicorn` (WSGI server)
- `uvloop` (optional asyncio performance improvement)

## Usage

### Generate Protobuf Files

```bash
# Generate .proto file from a service class
pydantic-rpc generate myapp.services.UserService --output ./proto/

# Also compile to Python code
pydantic-rpc generate myapp.services.UserService --compile
```

### Run Servers

#### gRPC Server (default)
```bash
# Start a gRPC server
pydantic-rpc serve myapp.services.UserService --port 50051

# The CLI automatically detects if your service has async methods
# and uses AsyncIOServer or Server accordingly
```

#### Connect RPC via ASGI (HTTP/2)
```bash
# Run with Hypercorn (built-in)
pydantic-rpc serve myapp.services.UserService --asgi --port 8000

# Service will be available at:
# http://localhost:8000/UserService/
```

#### Connect RPC via WSGI (HTTP/1.1)
```bash
# Run with Gunicorn (built-in)
pydantic-rpc serve myapp.services.UserService --wsgi --port 8000

# With multiple workers
pydantic-rpc serve myapp.services.UserService --wsgi --port 8000 --workers 4

# Service will be available at:
# http://localhost:8000/UserService/
```

## Example Service

```python
# myapp/services.py
from pydantic_rpc import Message, AsyncIOServer

class HelloRequest(Message):
    name: str

class HelloResponse(Message):
    message: str

class GreeterService:
    async def say_hello(self, request: HelloRequest) -> HelloResponse:
        return HelloResponse(message=f"Hello, {request.name}!")
```

Run it:
```bash
# As gRPC
pydantic-rpc serve myapp.services.GreeterService

# As Connect RPC (HTTP/2)
pydantic-rpc serve myapp.services.GreeterService --asgi --port 8000

# As Connect RPC (HTTP/1.1)
pydantic-rpc serve myapp.services.GreeterService --wsgi --port 8000
```

## Benefits of the Separated CLI

- **Lightweight Core**: The main `pydantic-rpc` package remains lightweight without server dependencies
- **Full Server Support**: When you install `pydantic-rpc-cli`, you get everything needed to run services
- **Flexibility**: Choose between gRPC, ASGI (HTTP/2), or WSGI (HTTP/1.1) at runtime

## License

Same as pydantic-rpc
