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
