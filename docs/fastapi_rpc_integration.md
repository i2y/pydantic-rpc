# FastAPI Integration Guide: gRPC, Connect RPC, and Hybrid Architectures

This guide explains different approaches for integrating RPC services with FastAPI, covering both gRPC and Connect RPC options.

## Understanding Your Requirements

Before choosing an architecture, consider these questions:

1. **Do you need real gRPC protocol support?**
   - Required for existing gRPC clients/services
   - Required for gRPC-specific features (bidirectional streaming, etc.)
   - Required for gRPC ecosystem tools

2. **Do you want everything in a single process?**
   - Simpler deployment and management
   - Shared memory and resources
   - Single port configuration

3. **What clients will access your service?**
   - Web browsers (JavaScript)
   - Mobile applications
   - Other microservices
   - gRPC clients

## Protocol Comparison

| Feature | gRPC | Connect RPC |
|---------|------|-------------|
| **Protocol** | HTTP/2 with binary framing | HTTP/1.1 or HTTP/2 |
| **Single process with FastAPI** | ❌ No | ✅ Yes |
| **Browser/curl compatible** | ❌ No | ✅ Yes |
| **gRPC client compatible** | ✅ Yes | ❌ No |
| **Streaming support** | ✅ Full bidirectional | ✅ Full bidirectional (coming soon in pydantic-rpc) |
| **Performance** | ⭐⭐⭐⭐⭐ Excellent | ⭐⭐⭐⭐ Very Good |
| **Ecosystem** | Mature, extensive | Growing |

## Architecture Options

### Option 1: Pure gRPC Service (Separate Process)

**Best for:** When you need true gRPC protocol support and don't require FastAPI integration.

```python
# grpc_service.py - Standalone gRPC server
from pydantic_rpc import AsyncIOServer, Message
import asyncio

class BookRequest(Message):
    id: str

class BookResponse(Message):
    id: str
    title: str
    author: str
    price: float

class BookService:
    async def get_book(self, request: BookRequest) -> BookResponse:
        # Business logic here
        return BookResponse(
            id=request.id,
            title=f"Book {request.id}",
            author="Author Name",
            price=29.99
        )
    
    async def create_book(self, request: BookResponse) -> BookResponse:
        # Save to database
        return request

if __name__ == "__main__":
    server = AsyncIOServer()
    print("Starting gRPC server on port 50051")
    asyncio.run(server.run(BookService()))  # Default port is 50051
```

**Access patterns:**
```python
# Python gRPC client
import grpc
import book_pb2
import book_pb2_grpc

async with grpc.aio.insecure_channel('localhost:50051') as channel:
    stub = book_pb2_grpc.BookServiceStub(channel)
    response = await stub.GetBook(book_pb2.BookRequest(id="123"))
```

**Pros:**
- Full gRPC protocol support
- Compatible with all gRPC clients and tools
- Excellent performance
- Supports all gRPC features

**Cons:**
- Requires separate process/port
- Not accessible from browsers
- More complex deployment

### Option 2: FastAPI + gRPC Backend (Microservices)

**Best for:** When you need both REST API and gRPC support with clear separation of concerns.

```python
# backend_grpc.py - gRPC backend service
from pydantic_rpc import AsyncIOServer, Message
import asyncio

class BookService:
    async def get_book(self, request: BookRequest) -> BookResponse:
        return BookResponse(...)

if __name__ == "__main__":
    server = AsyncIOServer()
    asyncio.run(server.run(BookService()))  # Default port is 50051
```

```python
# frontend_fastapi.py - FastAPI gateway
from fastapi import FastAPI, HTTPException
import grpc
import book_pb2
import book_pb2_grpc

app = FastAPI(title="API Gateway")

@app.get("/api/books/{book_id}")
async def get_book(book_id: str):
    """REST endpoint that calls gRPC backend"""
    try:
        async with grpc.aio.insecure_channel('localhost:50051') as channel:
            stub = book_pb2_grpc.BookServiceStub(channel)
            response = await stub.GetBook(
                book_pb2.BookRequest(id=book_id)
            )
            return {
                "id": response.id,
                "title": response.title,
                "author": response.author,
                "price": response.price
            }
    except grpc.RpcError as e:
        raise HTTPException(status_code=503, detail="Backend service unavailable")

@app.get("/health")
async def health():
    return {"status": "healthy"}

# Run both services:
# Terminal 1: python backend_grpc.py
# Terminal 2: python frontend_fastapi.py
```

**Architecture:**
```
Internet → FastAPI:8000 (HTTP/REST) → gRPC:50051 (internal)
         ↘ Direct gRPC clients      ↗
```

**Pros:**
- Clear separation of concerns
- Can scale independently
- Supports both REST and gRPC clients
- FastAPI provides REST API with OpenAPI docs

**Cons:**
- Requires multiple processes
- Network latency between services
- More complex deployment and monitoring

### Option 3: Connect RPC Standalone

**Best for:** When you need RPC that works with HTTP/1.1 and don't need gRPC compatibility.

```python
# connect_rpc_service.py
from pydantic_rpc import ASGIApp, Message
import uvicorn

class BookRequest(Message):
    id: str

class BookResponse(Message):
    id: str
    title: str
    author: str
    price: float

class BookService:
    async def get_book(self, request: BookRequest) -> BookResponse:
        return BookResponse(
            id=request.id,
            title=f"Book {request.id}",
            author="Author Name",
            price=29.99
        )

app = ASGIApp()
app.mount(BookService())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Access patterns:**
```bash
# Works with any HTTP client
curl -X POST http://localhost:8000/BookService/GetBook \
  -H "Content-Type: application/json" \
  -d '{"id": "123"}'
```

**Pros:**
- Simple, single process
- Works with any HTTP client
- Browser compatible
- Easy deployment

**Cons:**
- Not compatible with gRPC clients
- Different protocol from gRPC

### Option 4: FastAPI + Connect RPC (Single Process)

**Best for:** When you want REST and RPC in a single process without gRPC requirements.

```python
# fastapi_with_connect.py
from fastapi import FastAPI, HTTPException
from pydantic_rpc import ASGIApp, Message
from pydantic import BaseModel
from typing import Dict
import uvicorn

# Shared data store
class BookStore:
    def __init__(self):
        self.books: Dict[str, dict] = {
            "1": {"id": "1", "title": "Clean Code", "author": "Martin", "price": 42.99}
        }
    
    async def get_book(self, book_id: str) -> dict:
        if book_id not in self.books:
            raise ValueError(f"Book {book_id} not found")
        return self.books[book_id]

# Connect RPC Service
class BookRequest(Message):
    id: str

class BookResponse(Message):
    id: str
    title: str
    author: str
    price: float

class BookRPCService:
    def __init__(self, store: BookStore):
        self.store = store
    
    async def get_book(self, request: BookRequest) -> BookResponse:
        data = await self.store.get_book(request.id)
        return BookResponse(**data)

# FastAPI app
app = FastAPI()
store = BookStore()

# REST endpoint
@app.get("/api/books/{book_id}")
async def get_book_rest(book_id: str):
    try:
        return await store.get_book(book_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# Mount Connect RPC
rpc_service = BookRPCService(store)
rpc_app = ASGIApp()
rpc_app.mount(rpc_service)
app.mount("/rpc", rpc_app)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Access both endpoints:**
```bash
# REST
curl http://localhost:8000/api/books/1

# RPC
curl -X POST http://localhost:8000/rpc/BookRPCService/GetBook \
  -H "Content-Type: application/json" \
  -d '{"id": "1"}'
```

**Pros:**
- Single process/port
- Shared business logic
- Simple deployment
- Both REST and RPC APIs

**Cons:**
- Not gRPC compatible
- Limited to Connect RPC features

### Option 5: gRPC with HTTP Gateway

**Best for:** When you need both gRPC and HTTP/REST access to the same service.

**Note:** pydantic-rpc provides the `@http_option` decorator that adds HTTP annotations to the generated proto file. These annotations can be used by tools like grpc-gateway to expose HTTP endpoints.

```python
# service_with_http_options.py
from pydantic_rpc import AsyncIOServer, Message, http_option, generate_proto
import asyncio

class BookRequest(Message):
    id: str

class BookResponse(Message):
    id: str
    title: str
    author: str
    price: float

class BookService:
    @http_option(method="GET", path="/v1/books/{id}")
    async def get_book(self, request: BookRequest) -> BookResponse:
        return BookResponse(
            id=request.id,
            title="Example Book",
            author="Example Author",
            price=29.99
        )
    
    @http_option(method="POST", path="/v1/books", body="*")
    async def create_book(self, request: BookResponse) -> BookResponse:
        return request

if __name__ == "__main__":
    service = BookService()
    
    # Generate proto with HTTP annotations
    proto = generate_proto(service)
    with open("book.proto", "w") as f:
        f.write(proto)
    
    # Run gRPC server
    server = AsyncIOServer()
    asyncio.run(server.run(service))  # Default port is 50051
```

Then use grpc-gateway to expose HTTP endpoints:

```yaml
# docker-compose.yml
version: '3'
services:
  grpc-server:
    build: .
    ports:
      - "50051:50051"
  
  grpc-gateway:
    image: grpc-gateway
    ports:
      - "8080:8080"
    depends_on:
      - grpc-server
    environment:
      - BACKEND_ADDR=grpc-server:50051
```

**Access patterns:**
```bash
# Direct gRPC
grpcurl -plaintext localhost:50051 BookService/GetBook

# HTTP via gateway
curl http://localhost:8080/v1/books/123
```

**Pros:**
- Full gRPC support
- HTTP/REST access via gateway
- Works with all clients
- Industry standard approach

**Cons:**
- Requires multiple processes
- More complex setup
- Gateway adds latency

## Decision Guide

### Choose Pure gRPC if:
- You have existing gRPC clients/services
- Performance is critical
- You need gRPC-specific features
- You don't need browser access

### Choose FastAPI + gRPC Backend if:
- You need clear API gateway pattern
- You want to aggregate multiple backend services
- You need both REST and gRPC support
- Services should scale independently

### Choose Connect RPC if:
- You need browser/HTTP client compatibility
- You want single process simplicity
- You don't have existing gRPC clients
- HTTP/1.1 support is important

### Choose FastAPI + Connect RPC if:
- You want everything in one process
- You need both REST and RPC APIs
- You don't need gRPC protocol compatibility
- Simplicity is a priority

### Choose gRPC + Gateway if:
- You need both gRPC and HTTP access
- You want to follow industry standards
- You can handle multi-service deployment
- You need full protocol support

## Testing Different Approaches

### Testing gRPC

```python
# test_grpc.py
import grpc
import asyncio
import book_pb2
import book_pb2_grpc

async def test_grpc():
    async with grpc.aio.insecure_channel('localhost:50051') as channel:
        stub = book_pb2_grpc.BookServiceStub(channel)
        response = await stub.GetBook(book_pb2.BookRequest(id="123"))
        print(f"gRPC Response: {response}")

asyncio.run(test_grpc())
```

### Testing Connect RPC

```python
# test_connect.py
import requests

response = requests.post(
    "http://localhost:8000/BookService/GetBook",
    json={"id": "123"}
)
print(f"Connect RPC Response: {response.json()}")
```

### Testing from Browser

```javascript
// Works only with Connect RPC or REST APIs
fetch('http://localhost:8000/rpc/BookService/GetBook', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: '123'})
})
.then(r => r.json())
.then(console.log);
```

## Performance Considerations

| Metric | gRPC | Connect RPC | REST |
|--------|------|-------------|------|
| Latency | ⭐⭐⭐⭐⭐ Lowest | ⭐⭐⭐⭐ Low | ⭐⭐⭐ Moderate |
| Throughput | ⭐⭐⭐⭐⭐ Highest | ⭐⭐⭐⭐ High | ⭐⭐⭐ Good |
| CPU Usage | ⭐⭐⭐⭐ Efficient | ⭐⭐⭐ Good | ⭐⭐⭐ Good |
| Memory | ⭐⭐⭐⭐ Efficient | ⭐⭐⭐ Good | ⭐⭐⭐ Good |

## Deployment Considerations

### Single Process Deployment

```dockerfile
# For Connect RPC or FastAPI + Connect RPC
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Multi-Process Deployment

```yaml
# docker-compose.yml for gRPC + FastAPI
version: '3'
services:
  grpc:
    build: ./grpc
    ports:
      - "50051:50051"
  
  fastapi:
    build: ./fastapi
    ports:
      - "8000:8000"
    depends_on:
      - grpc
    environment:
      - GRPC_HOST=grpc
      - GRPC_PORT=50051
```

## Common Issues and Solutions

### Issue: "Need both gRPC and browser access"

**Solutions:**
1. Use gRPC + grpc-gateway (standard approach)
2. Run both gRPC and Connect RPC services
3. Use FastAPI as a translation layer

### Issue: "Want single process but need gRPC"

**Solution:** Not possible - gRPC requires its own server. Consider:
1. Using Connect RPC instead
2. Running gRPC as a sidecar container
3. Accepting multi-process architecture

### Issue: "Existing gRPC clients must work"

**Solution:** You must use real gRPC. Options:
1. Pure gRPC service
2. gRPC with gateway for HTTP access
3. Run gRPC alongside other services

### Issue: "Need maximum simplicity"

**Solution:** Use Connect RPC standalone or with FastAPI:
1. Single process
2. Single port
3. Works with any HTTP client

## Summary

The choice between gRPC and Connect RPC depends on your specific requirements:

- **Use gRPC** when you need protocol compatibility with existing gRPC services or maximum performance
- **Use Connect RPC** when you need simplicity, browser compatibility, or single-process deployment
- **Use both** when different clients have different requirements

There's no universally "best" choice - it depends on your specific use case, existing infrastructure, and client requirements.
