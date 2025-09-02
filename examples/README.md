# 📚 Examples

## 📝 Prerequisites

Ensure you have [uv](https://docs.astral.sh/uv/) installed on your system. If not, you can install it using the following command:

### Linux/macOS

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 🔧 Setup

1. **Clone the Repository:**

    ```bash
    git clone https://github.com/i2y/pydantic-rpc.git
    cd pydantic-rpc/examples
    ```

2. **Install Dependencies with Rye:**

    ```bash
    uv sync
    ```

## 🖥️ gRPC Server Example

### 🔧 Server (`greeting.py`)

A simple gRPC server.

**Usage:**

```bash
uv run greeting.py
```

### 🔗 Client (`greeter_client.py`)

A gRPC client to interact with the server.

**Usage:**

```bash
uv run greeter_client.py
```

## ⚡ Asyncio gRPC Server Example

### 🔧 Asyncio Server (`asyncio_greeting.py`)

An asyncio gRPC server using `AsyncIOServer`.

**Usage:**

```bash
uv run asyncio_greeting.py
```

## 🌐 ASGI Integration (gRPC-Web)

### 🌐 ASGI Application (`greeting_asgi.py`)

Integrate **PydanticRPC** (gRPC-Web) with an ASGI-compatible framework.

**Usage:**

```bash
uv run hypercorn -bind :3000 greeting_asgi:app
```

### 🔗 Client (`greeter_sonora_client.py`)
A gRPC-Web client to interact with the server.

**Usage:**

```bash
uv run greeter_sonora_client.py
```


## 🌐 WSGI Integration

### 🌐 WSGI Application (`greeting_wsgi.py`)

Integrate **PydanticRPC** (gRPC-Web) with a WSGI-compatible framework.

**Usage:**

```bash
uv run greeting_wsgi.py
```

### 🔗 Client (`greeter_sonora_client.py`)
A gRPC-Web client to interact with the server.

**Usage:**

```bash
uv run greeter_sonora_client.py
```


## 🛡️ Custom Interceptor and Running Multiple Services Exxample

### 🔧 Server (`foobar.py`)
A simple gRPC server with custom interceptor and running multiple services.

**Usage:**

```bash
uv run foobar.py
```

### 🔗 Client (`foobar_client.py`)
A gRPC client to interact with the server.

**Usage:**

```bash
uv run foobar_client.py
```

## 🤝 Connecpy (Connect-RPC) Example

### 🔧 Server (`greeting_asgi.py`)

A Connect-RPC ASGI application using PydanticRPC + connecpy.

**Usage:**

```bash
uv run hypercorn --bind :3000 greeting_asgi:app
```

Or using uvicorn:

```bash
uv run uvicorn greeting_asgi:app --port 3000
```

### 🔗 Client (`greeter_connecpy_client.py`)

A Connect-RPC client to interact with the server.

**Usage:**

```bash
uv run greeter_connecpy_client.py
```

## 🛡️ Enhanced API Example

### 🔧 Server with Error Handling (`enhanced_api_example.py`)

Demonstrates the enhanced API features including error handling decorators that automatically convert Python exceptions to appropriate gRPC status codes.

**Features:**
- Error handler decorators for automatic exception mapping
- ValidationError → INVALID_ARGUMENT
- KeyError → NOT_FOUND
- Custom error handling

**Usage:**

```bash
uv run enhanced_api_example.py
```

**Testing:**

```python
# Test with generated client
uv run python test_enhanced_api.py
```

## 🌐 Hybrid Service Example

### 🔧 Multi-Protocol Server (`hybrid_service_working.py`)

Demonstrates running three protocols simultaneously:
- **FastAPI REST API** on port 8000 (public endpoints)
- **Connect-RPC** mounted on FastAPI at `/partner` path
- **gRPC server** on port 50051 (internal services)

**Important Note:** The gRPC server runs in a separate thread. The example includes a workaround for signal handling issues when running AsyncIOServer in a thread.

**Usage:**

```bash
uv run hybrid_service_working.py
```

**Testing:**

```bash
# Test REST endpoint
curl -X POST http://localhost:8000/api/v1/process \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer demo-token" \
  -d '{"data": {"content": "Test data", "metadata": "meta1"}, "priority": "high"}'

# Test gRPC endpoint (requires generated client)
uv run python test_hybrid_grpc.py

# Test Connect-RPC endpoint (note: currently has mounting issues)
curl -X POST http://localhost:8000/partner/PartnerConnectService/ProcessPartner \
  -H "Content-Type: application/json" \
  -d '{"data": {"content": "Partner test", "metadata": "meta1"}, "priority": "high"}'
```

## 🔄 Streaming Connect-RPC Example

### 🔧 Streaming Server (`streaming_connecpy.py`)

Demonstrates all four RPC patterns with Connect-RPC:

1. **Unary RPC**: Single request, single response
2. **Server Streaming**: Single request, stream of responses
3. **Client Streaming**: Stream of requests, single response
4. **Bidirectional Streaming**: Stream of requests and responses

**Usage with HTTP/1.1 (uvicorn):**

```bash
uv run streaming_connecpy.py
```

**Usage with HTTP/2 (Hypercorn - required for bidirectional streaming):**

```bash
hypercorn streaming_connecpy:app --bind 0.0.0.0:8000
```

### 🧪 Testing with buf curl

**Important:** Connect-RPC endpoints use CamelCase method names (e.g., `SendMessage` not `send_message`).

**Unary RPC:**
```bash
buf curl \
  --schema chatservice.proto \
  --protocol connect \
  -d '{"user": "TestUser", "text": "Hello"}' \
  http://localhost:8000/chat.v1.ChatService/SendMessage
```

**Server Streaming:**
```bash
buf curl \
  --schema chatservice.proto \
  --protocol connect \
  -d '{"user": "TestUser", "text": "Stream test"}' \
  http://localhost:8000/chat.v1.ChatService/StreamUpdates
```

**Client Streaming (use heredoc for multiple messages):**
```bash
buf curl \
  --schema chatservice.proto \
  --protocol connect \
  --data @- \
  http://localhost:8000/chat.v1.ChatService/BatchSend <<EOF
{"user": "Alice", "text": "First message"}
{"user": "Bob", "text": "Second message"}
{"user": "Charlie", "text": "Third message"}
EOF
```

**Bidirectional Streaming (requires HTTP/2):**
```bash
# First start server with Hypercorn for HTTP/2 support
hypercorn streaming_connecpy:app --bind 0.0.0.0:8000

# Then test with buf curl
buf curl \
  --schema chatservice.proto \
  --protocol connect \
  --http2-prior-knowledge \
  --data @- \
  http://localhost:8000/chat.v1.ChatService/ChatSession <<EOF
{"user": "Alice", "text": "Hello"}
{"user": "Bob", "text": "Hi there"}
EOF
```

## ⚠️ Important Notes for Connect-RPC

### Endpoint Path Format
- Connect-RPC endpoints follow the pattern: `/<package>.<service>/<Method>`
- Method names are **CamelCase** (e.g., `SendMessage`, not `send_message`)
- Example: `/chat.v1.ChatService/SendMessage`

### Content-Type Requirements
- Use `Content-Type: application/json` for JSON payloads
- Use `Content-Type: application/connect+json` for streaming RPCs with Connect protocol

### HTTP/2 Requirements
- **Bidirectional streaming** requires HTTP/2
- Use Hypercorn instead of uvicorn for HTTP/2 support
- Add `--http2-prior-knowledge` flag when using buf curl with HTTP/2

### Testing with buf curl
- For streaming RPCs with multiple messages, use `--data @-` with heredoc
- Each JSON message should be on a separate line
- No commas between messages (not a JSON array)
