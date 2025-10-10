# 🚀 PydanticRPC

**PydanticRPC** is a Python library that enables you to rapidly expose [Pydantic](https://docs.pydantic.dev/) models via [gRPC](https://grpc.io/)/[Connect RPC](https://connectrpc.com/docs/protocol/) services without writing any protobuf files. Instead, it automatically generates protobuf files on the fly from the method signatures of your Python objects and the type signatures of your Pydantic models.


Below is an example of a simple gRPC service that exposes a [PydanticAI](https://ai.pydantic.dev/) agent:

```python
import asyncio

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_rpc import AsyncIOServer, Message


# `Message` is just an alias for Pydantic's `BaseModel` class.
class CityLocation(Message):
    city: str
    country: str


class Olympics(Message):
    year: int

    def prompt(self):
        return f"Where were the Olympics held in {self.year}?"


class OlympicsLocationAgent:
    def __init__(self):
        client = AsyncOpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama_api_key",
        )
        ollama_model = OpenAIModel(
            model_name="llama3.2",
            openai_client=client,
        )
        self._agent = Agent(ollama_model)

    async def ask(self, req: Olympics) -> CityLocation:
        result = await self._agent.run(req.prompt())
        return result.data


if __name__ == "__main__":
    # New enhanced initialization API (optional - backward compatible)
    s = AsyncIOServer(service=OlympicsLocationAgent(), port=50051)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(s.run())
```

And here is an example of a simple Connect RPC service that exposes the same agent as an ASGI application:

```python
import asyncio

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_rpc import ASGIApp, Message


class CityLocation(Message):
    city: str
    country: str


class Olympics(Message):
    year: int

    def prompt(self):
        return f"Where were the Olympics held in {self.year}?"


class OlympicsLocationAgent:
    def __init__(self):
        client = AsyncOpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama_api_key",
        )
        ollama_model = OpenAIModel(
            model_name="llama3.2",
            openai_client=client,
        )
        self._agent = Agent(ollama_model, result_type=CityLocation)

    async def ask(self, req: Olympics) -> CityLocation:
        result = await self._agent.run(req.prompt())
        return result.data

# New enhanced initialization API (optional - backward compatible)
app = ASGIApp(service=OlympicsLocationAgent())

```


## 💡 Key Features

- 🔄 **Automatic Protobuf Generation:** Automatically creates protobuf files matching the method signatures of your Python objects.
- ⚙️ **Dynamic Code Generation:** Generates server and client stubs using `grpcio-tools`.
- ✅ **Pydantic Integration:** Uses `pydantic` for robust type validation and serialization.
- 📄 **Pprotobuf File Export:** Exports the generated protobuf files for use in other languages.
- **For gRPC:**
  - 💚 **Health Checking:** Built-in support for gRPC health checks using `grpc_health.v1`.
  - 🔎 **Server Reflection:** Built-in support for gRPC server reflection.
  - ⚡ **Asynchronous Support:** Easily create asynchronous gRPC services with `AsyncIOServer`.
- **For Connect-RPC:**
  - 🌐 **Full Protocol Support:** Native Connect-RPC support via `connect-python`
  - 🔄 **All Streaming Patterns:** Unary, server streaming, client streaming, and bidirectional streaming
  - 🌐 **WSGI/ASGI Applications:** Run as standard WSGI or ASGI applications for easy deployment
- 🛠️ **Pre-generated Protobuf Files and Code:** Pre-generate proto files and corresponding code via the CLI. By setting the environment variable (PYDANTIC_RPC_SKIP_GENERATION), you can skip runtime generation.
- 🤖 **MCP (Model Context Protocol) Support:** Expose your services as tools for AI assistants using the official MCP SDK, supporting both stdio and HTTP/SSE transports.

## ⚠️ Important Notes for Connect-RPC

When using Connect-RPC with ASGIApp:

- **Endpoint Path Format**: Connect-RPC endpoints use CamelCase method names in the path: `/<package>.<service>/<Method>` (e.g., `/chat.v1.ChatService/SendMessage`)
- **Content-Type**: Set `Content-Type: application/json` or `application/connect+json` for requests
- **HTTP/2 Requirement**: Bidirectional streaming requires HTTP/2. Use Hypercorn instead of uvicorn for HTTP/2 support
- **Testing**: Use [buf curl](https://buf.build/docs/ecosystem/cli/curl) for testing Connect-RPC endpoints with proper streaming support

For detailed examples and testing instructions, see the [examples directory](examples/).

## 📦 Installation

Install PydanticRPC via pip:

```bash
pip install pydantic-rpc
```

For CLI support with built-in server runners:

```bash
pip install pydantic-rpc-cli  # Includes hypercorn and gunicorn
```

## 🆕 Enhanced Features (v0.10.0+)

**Note: All new features are fully backward compatible. Existing code continues to work without modification.**

### Enhanced Initialization API
All server classes now support optional initialization with services:

```python
# Traditional API (still works)
server = AsyncIOServer()
server.set_port(50051)
await server.run(MyService())

# New enhanced API (optional)
server = AsyncIOServer(
    service=MyService(),
    port=50051,
    package_name="my.package"
)
await server.run()

# Same for ASGI/WSGI apps
app = ASGIApp(service=MyService(), package_name="my.package")
```

### Error Handling with Decorators
Automatically map exceptions to gRPC/Connect status codes:

```python
from pydantic_rpc import error_handler
import grpc

class MyService:
    @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT)
    @error_handler(KeyError, status_code=grpc.StatusCode.NOT_FOUND)
    async def get_user(self, request: GetUserRequest) -> User:
        # Exceptions are automatically converted to proper status codes
        if request.id not in users_db:
            raise KeyError(f"User {request.id} not found")
        return users_db[request.id]
```

## 🚀 Getting Started

PydanticRPC supports two main protocols:
- **gRPC**: Traditional gRPC services with `Server` and `AsyncIOServer`
- **Connect-RPC**: Modern HTTP-based RPC with `ASGIApp` and `WSGIApp`

### 🔧 Synchronous gRPC Service Example

```python
from pydantic_rpc import Server, Message

class HelloRequest(Message):
    name: str

class HelloReply(Message):
    message: str

class Greeter:
    # Define methods that accepts a request and returns a response.
    def say_hello(self, request: HelloRequest) -> HelloReply:
        return HelloReply(message=f"Hello, {request.name}!")

if __name__ == "__main__":
    server = Server()
    server.run(Greeter())
```

### ⚙️ Asynchronous gRPC Service Example

```python
import asyncio

from pydantic_rpc import AsyncIOServer, Message


class HelloRequest(Message):
    name: str


class HelloReply(Message):
    message: str


class Greeter:
    async def say_hello(self, request: HelloRequest) -> HelloReply:
        return HelloReply(message=f"Hello, {request.name}!")


async def main():
    # You can specify a custom port (default is 50051)
    server = AsyncIOServer(port=50052)
    await server.run(Greeter())


if __name__ == "__main__":
    asyncio.run(main())
```

The AsyncIOServer automatically handles graceful shutdown on SIGTERM and SIGINT signals.

### 🌐 Connect-RPC ASGI Application Example

```python
from pydantic_rpc import ASGIApp, Message

class HelloRequest(Message):
    name: str

class HelloReply(Message):
    message: str

class Greeter:
    async def say_hello(self, request: HelloRequest) -> HelloReply:
        return HelloReply(message=f"Hello, {request.name}!")

app = ASGIApp()
app.mount(Greeter())

# Run with uvicorn:
# uvicorn script:app --host 0.0.0.0 --port 8000
```

### 🌐 Connect-RPC WSGI Application Example

```python
from pydantic_rpc import WSGIApp, Message

class HelloRequest(Message):
    name: str

class HelloReply(Message):
    message: str

class Greeter:
    def say_hello(self, request: HelloRequest) -> HelloReply:
        return HelloReply(message=f"Hello, {request.name}!")

app = WSGIApp()
app.mount(Greeter())

# Run with gunicorn:
# gunicorn script:app
```

### 🏆 Connect-RPC with Streaming Example

PydanticRPC provides native Connect-RPC support via connect-python, including full streaming capabilities and PEP 8 naming conventions. Check out our ASGI examples:

```bash
# Run with uvicorn
uv run uvicorn greeting_asgi:app --port 3000

# Or run streaming example
uv run python examples/streaming_connect_python.py
```

This will launch a connect-python-based ASGI application that uses the same Pydantic models to serve Connect-RPC requests.

#### Streaming Support with connect-python

connect-python provides full support for streaming RPCs with automatic PEP 8 naming (snake_case):

```python
from typing import AsyncIterator
from pydantic_rpc import ASGIApp, Message

class StreamRequest(Message):
    text: str
    count: int

class StreamResponse(Message):
    text: str
    index: int

class StreamingService:
    # Server streaming
    async def server_stream(self, request: StreamRequest) -> AsyncIterator[StreamResponse]:
        for i in range(request.count):
            yield StreamResponse(text=f"{request.text}_{i}", index=i)
    
    # Client streaming
    async def client_stream(self, requests: AsyncIterator[StreamRequest]) -> StreamResponse:
        texts = []
        async for req in requests:
            texts.append(req.text)
        return StreamResponse(text=" ".join(texts), index=len(texts))
    
    # Bidirectional streaming
    async def bidi_stream(
        self, requests: AsyncIterator[StreamRequest]
    ) -> AsyncIterator[StreamResponse]:
        idx = 0
        async for req in requests:
            yield StreamResponse(text=f"Echo: {req.text}", index=idx)
            idx += 1

app = ASGIApp()
app.mount(StreamingService())
```

> [!NOTE]
> Please install `protoc-gen-connect-python` to run the connect-python example.

## ♻️ Skipping Protobuf Generation
By default, PydanticRPC generates .proto files and code at runtime. If you wish to skip the code-generation step (for example, in production environment), set the environment variable below:

```bash
export PYDANTIC_RPC_SKIP_GENERATION=true
```

When this variable is set to "true", PydanticRPC will load existing pre-generated modules rather than generating theƒm on the fly.

## 🪧 Setting Protobuf and Connect RPC/gRPC generation directory
By default your files will be generated in the current working directory where you ran the code from, but you can set a custom specific directory by setting the environment variable below:

```bash
export PYDANTIC_RPC_PROTO_PATH=/your/path
```

## ⚠️ Reserved Fields

You can also set an environment variable to reserve a set number of fields for proto generation, for backward and forward compatibility.

```bash
export PYDANTIC_RPC_RESERVED_FIELDS=1
```

## 💎 Advanced Features

### 🌊 Response Streaming (gRPC)
PydanticRPC supports streaming responses for both gRPC and Connect-RPC services.
If a service class method's return type is `typing.AsyncIterator[T]`, the method is considered a streaming method.


Please see the sample code below:

```python
import asyncio
from typing import Annotated, AsyncIterator

from openai import AsyncOpenAI
from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_rpc import AsyncIOServer, Message


# `Message` is just a pydantic BaseModel alias
class CityLocation(Message):
    city: Annotated[str, Field(description="The city where the Olympics were held")]
    country: Annotated[
        str, Field(description="The country where the Olympics were held")
    ]


class OlympicsQuery(Message):
    year: Annotated[int, Field(description="The year of the Olympics", ge=1896)]

    def prompt(self):
        return f"Where were the Olympics held in {self.year}?"


class OlympicsDurationQuery(Message):
    start: Annotated[int, Field(description="The start year of the Olympics", ge=1896)]
    end: Annotated[int, Field(description="The end year of the Olympics", ge=1896)]

    def prompt(self):
        return f"From {self.start} to {self.end}, how many Olympics were held? Please provide the list of countries and cities."


class StreamingResult(Message):
    answer: Annotated[str, Field(description="The answer to the query")]


class OlympicsAgent:
    def __init__(self):
        client = AsyncOpenAI(
            base_url='http://localhost:11434/v1',
            api_key='ollama_api_key',
        )
        ollama_model = OpenAIModel(
            model_name='llama3.2',
            openai_client=client,
        )
        self._agent = Agent(ollama_model)

    async def ask(self, req: OlympicsQuery) -> CityLocation:
        result = await self._agent.run(req.prompt(), result_type=CityLocation)
        return result.data

    async def ask_stream(
        self, req: OlympicsDurationQuery
    ) -> AsyncIterator[StreamingResult]:
        async with self._agent.run_stream(req.prompt(), result_type=str) as result:
            async for data in result.stream_text(delta=True):
                yield StreamingResult(answer=data)


if __name__ == "__main__":
    s = AsyncIOServer()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(s.run(OlympicsAgent()))
```

In the example above, the `ask_stream` method returns an `AsyncIterator[StreamingResult]` object, which is considered a streaming method. The `StreamingResult` class is a Pydantic model that defines the response type of the streaming method. You can use any Pydantic model as the response type.

Now, you can call the `ask_stream` method of the server described above using your preferred gRPC client tool. The example below uses `buf curl`.


```console
% buf curl --data '{"start": 1980, "end": 2024}' -v http://localhost:50051/olympicsagent.v1.OlympicsAgent/AskStream --protocol grpc --http2-prior-knowledge 

buf: * Using server reflection to resolve "olympicsagent.v1.OlympicsAgent"
buf: * Dialing (tcp) localhost:50051...
buf: * Connected to [::1]:50051
buf: > (#1) POST /grpc.reflection.v1.ServerReflection/ServerReflectionInfo
buf: > (#1) Accept-Encoding: identity
buf: > (#1) Content-Type: application/grpc+proto
buf: > (#1) Grpc-Accept-Encoding: gzip
buf: > (#1) Grpc-Timeout: 119997m
buf: > (#1) Te: trailers
buf: > (#1) User-Agent: grpc-go-connect/1.12.0 (go1.21.4) buf/1.28.1
buf: > (#1)
buf: } (#1) [5 bytes data]
buf: } (#1) [32 bytes data]
buf: < (#1) HTTP/2.0 200 OK
buf: < (#1) Content-Type: application/grpc
buf: < (#1) Grpc-Message: Method not found!
buf: < (#1) Grpc-Status: 12
buf: < (#1)
buf: * (#1) Call complete
buf: > (#2) POST /grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo
buf: > (#2) Accept-Encoding: identity
buf: > (#2) Content-Type: application/grpc+proto
buf: > (#2) Grpc-Accept-Encoding: gzip
buf: > (#2) Grpc-Timeout: 119967m
buf: > (#2) Te: trailers
buf: > (#2) User-Agent: grpc-go-connect/1.12.0 (go1.21.4) buf/1.28.1
buf: > (#2)
buf: } (#2) [5 bytes data]
buf: } (#2) [32 bytes data]
buf: < (#2) HTTP/2.0 200 OK
buf: < (#2) Content-Type: application/grpc
buf: < (#2) Grpc-Accept-Encoding: identity, deflate, gzip
buf: < (#2)
buf: { (#2) [5 bytes data]
buf: { (#2) [434 bytes data]
buf: * Server reflection has resolved file "olympicsagent.proto"
buf: * Invoking RPC olympicsagent.v1.OlympicsAgent.AskStream
buf: > (#3) POST /olympicsagent.v1.OlympicsAgent/AskStream
buf: > (#3) Accept-Encoding: identity
buf: > (#3) Content-Type: application/grpc+proto
buf: > (#3) Grpc-Accept-Encoding: gzip
buf: > (#3) Grpc-Timeout: 119947m
buf: > (#3) Te: trailers
buf: > (#3) User-Agent: grpc-go-connect/1.12.0 (go1.21.4) buf/1.28.1
buf: > (#3)
buf: } (#3) [5 bytes data]
buf: } (#3) [6 bytes data]
buf: * (#3) Finished upload
buf: < (#3) HTTP/2.0 200 OK
buf: < (#3) Content-Type: application/grpc
buf: < (#3) Grpc-Accept-Encoding: identity, deflate, gzip
buf: < (#3)
buf: { (#3) [5 bytes data]
buf: { (#3) [25 bytes data]
{
 "answer": "Here's a list of Summer"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [31 bytes data]
{
  "answer": " and Winter Olympics from 198"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [29 bytes data]
{
  "answer": "0 to 2024:\n\nSummer Olympics"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [20 bytes data]
{
  "answer": ":\n1. 1980 - Moscow"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [20 bytes data]
{
  "answer": ", Soviet Union\n2. "
}
buf: { (#3) [5 bytes data]
buf: { (#3) [32 bytes data]
{
  "answer": "1984 - Los Angeles, California"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [15 bytes data]
{
  "answer": ", USA\n3. 1988"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [26 bytes data]
{
  "answer": " - Seoul, South Korea\n4."
}
buf: { (#3) [5 bytes data]
buf: { (#3) [27 bytes data]
{
  "answer": " 1992 - Barcelona, Spain\n"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [20 bytes data]
{
  "answer": "5. 1996 - Atlanta,"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [22 bytes data]
{
  "answer": " Georgia, USA\n6. 200"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [26 bytes data]
{
  "answer": "0 - Sydney, Australia\n7."
}
buf: { (#3) [5 bytes data]
buf: { (#3) [25 bytes data]
{
  "answer": " 2004 - Athens, Greece\n"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [20 bytes data]
{
  "answer": "8. 2008 - Beijing,"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [18 bytes data]
{
  "answer": " China\n9. 2012 -"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [29 bytes data]
{
  "answer": " London, United Kingdom\n10."
}
buf: { (#3) [5 bytes data]
buf: { (#3) [24 bytes data]
{
  "answer": " 2016 - Rio de Janeiro"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [18 bytes data]
{
  "answer": ", Brazil\n11. 202"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [24 bytes data]
{
  "answer": "0 - Tokyo, Japan (held"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [21 bytes data]
{
  "answer": " in 2021 due to the"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [26 bytes data]
{
  "answer": " COVID-19 pandemic)\n12. "
}
buf: { (#3) [5 bytes data]
buf: { (#3) [28 bytes data]
{
  "answer": "2024 - Paris, France\n\nNote"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [41 bytes data]
{
  "answer": ": The Olympics were held without a host"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [26 bytes data]
{
  "answer": " city for one year (2022"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [42 bytes data]
{
  "answer": ", due to the Russian invasion of Ukraine"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [29 bytes data]
{
  "answer": ").\n\nWinter Olympics:\n1. 198"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [27 bytes data]
{
  "answer": "0 - Lake Placid, New York"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [15 bytes data]
{
  "answer": ", USA\n2. 1984"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [27 bytes data]
{
  "answer": " - Sarajevo, Yugoslavia ("
}
buf: { (#3) [5 bytes data]
buf: { (#3) [30 bytes data]
{
  "answer": "now Bosnia and Herzegovina)\n"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [20 bytes data]
{
  "answer": "3. 1988 - Calgary,"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [25 bytes data]
{
  "answer": " Alberta, Canada\n4. 199"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [26 bytes data]
{
  "answer": "2 - Albertville, France\n"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [13 bytes data]
{
  "answer": "5. 1994 - L"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [24 bytes data]
{
  "answer": "illehammer, Norway\n6. "
}
buf: { (#3) [5 bytes data]
buf: { (#3) [23 bytes data]
{
  "answer": "1998 - Nagano, Japan\n"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [16 bytes data]
{
  "answer": "7. 2002 - Salt"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [24 bytes data]
{
  "answer": " Lake City, Utah, USA\n"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [18 bytes data]
{
  "answer": "8. 2006 - Torino"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [17 bytes data]
{
  "answer": ", Italy\n9. 2010"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [40 bytes data]
{
  "answer": " - Vancouver, British Columbia, Canada"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [13 bytes data]
{
  "answer": "\n10. 2014 -"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [20 bytes data]
{
  "answer": " Sochi, Russia\n11."
}
buf: { (#3) [5 bytes data]
buf: { (#3) [16 bytes data]
{
  "answer": " 2018 - Pyeong"
}
buf: { (#3) [5 bytes data]
buf: { (#3) [24 bytes data]
{
  "answer": "chang, South Korea\n12."
}
buf: < (#3)
buf: < (#3) Grpc-Message:
buf: < (#3) Grpc-Status: 0
buf: * (#3) Call complete
buf: < (#2)
buf: < (#2) Grpc-Message:
buf: < (#2) Grpc-Status: 0
buf: * (#2) Call complete
%
```

### 🪶 Empty Messages

Empty request/response messages are automatically mapped to `google.protobuf.Empty`:

```python
from pydantic_rpc import AsyncIOServer, Message


class EmptyRequest(Message):
    pass  # Automatically uses google.protobuf.Empty


class GreetingResponse(Message):
    message: str


class GreetingService:
    async def say_hello(self, request: EmptyRequest) -> GreetingResponse:
        return GreetingResponse(message="Hello!")
    
    async def get_default_greeting(self) -> GreetingResponse:
        # Method with no request parameter (implicitly empty)
        return GreetingResponse(message="Hello, World!")
```

### 🎨 Custom Serialization

Pydantic's serialization decorators are fully supported:

```python
from typing import Any
from pydantic import field_serializer, model_serializer
from pydantic_rpc import Message


class UserMessage(Message):
    name: str
    age: int
    
    @field_serializer('name')
    def serialize_name(self, name: str) -> str:
        """Always uppercase the name when serializing."""
        return name.upper()


class ComplexMessage(Message):
    value: int
    multiplier: int
    
    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        """Custom serialization with computed fields."""
        return {
            'value': self.value,
            'multiplier': self.multiplier,
            'result': self.value * self.multiplier  # Computed field
        }
```

The serializers are automatically applied when converting between Pydantic models and protobuf messages.

#### ⚠️ Limitations and Considerations

**1. Nested Message serializers are now supported (v0.8.0+)**
```python
class Address(Message):
    city: str
    
    @field_serializer("city")
    def serialize_city(self, city: str) -> str:
        return city.upper()

class User(Message):
    name: str
    address: Address  # ← Address's serializers ARE applied with DEEP strategy
    
    @field_serializer("name")
    def serialize_name(self, name: str) -> str:
        return name.upper()  # ← This IS applied
```

**Serializer Strategy Control:**
You can control how nested serializers are applied via environment variable:
```bash
# Apply serializers at all nesting levels (default)
export PYDANTIC_RPC_SERIALIZER_STRATEGY=deep

# Apply only top-level serializers
export PYDANTIC_RPC_SERIALIZER_STRATEGY=shallow

# Disable all serializers
export PYDANTIC_RPC_SERIALIZER_STRATEGY=none
```

**Performance Impact:**
- DEEP strategy: ~4% overhead for simple nested structures
- SHALLOW strategy: ~2% overhead (only top-level)
- NONE strategy: No overhead (serializers disabled)

**2. New fields added by serializers are ignored**
```python
class ComplexMessage(Message):
    value: int
    multiplier: int
    
    @model_serializer
    def serialize_model(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "multiplier": self.multiplier,
            "result": self.value * self.multiplier  # ← Won't appear in protobuf
        }
```
**Problem**: The `result` field doesn't exist in the Message definition, so it's not in the protobuf schema.

**3. Type must remain consistent**
```python
class BadExample(Message):
    number: int
    
    @field_serializer("number")
    def serialize_number(self, number: int) -> str:  # ❌ int → str
        return str(number)  # This will cause issues
```

**4. Union/Optional fields have limited support**
```python
class UnionExample(Message):
    data: str | int | None  # Union type
    
    @field_serializer("data")
    def serialize_data(self, data: str | int | None) -> str | int | None:
        # Serializer may not be applied to Union types
        return data
```

**5. Errors fail silently with fallback**
```python
class RiskyMessage(Message):
    value: int
    
    @field_serializer("value")
    def serialize_value(self, value: int) -> int:
        if value == 0:
            raise ValueError("Cannot serialize zero")
        return value * 2

# If error occurs, original value is used (silent fallback)
```

**6. Circular references are handled gracefully**
```python
class Node(Message):
    value: str
    child: "Node | None" = None
    
    @field_serializer("value")
    def serialize_value(self, v: str) -> str:
        return v.upper()

# Circular references are detected and prevented
node1 = Node(value="first")
node2 = Node(value="second")
node1.child = node2
node2.child = node1  # Circular reference

# When converting to protobuf:
# - Circular references are detected
# - Empty proto is returned for repeated objects
# - No infinite recursion occurs
# Note: Pydantic's model_dump() will fail on circular refs,
#       so serializers won't be applied in this case
```

**✅ Recommended Usage:**
```python
class GoodMessage(Message):
    # Use with primitive types
    name: str
    age: int
    
    @field_serializer("name")
    def normalize_name(self, name: str) -> str:
        return name.strip().title()  # Normalization
    
    @field_serializer("age")
    def clamp_age(self, age: int) -> int:
        return max(0, min(age, 150))  # Range limiting
```

**Best Practices:**
- Use serializers primarily for primitive types (str, int, float, bool)
- Keep type consistency (int → int, str → str)
- Avoid complex transformations or side effects
- Test error cases thoroughly
- Be aware that errors fail silently

### 🔒 TLS/mTLS Support

PydanticRPC provides built-in support for TLS (Transport Layer Security) and mTLS (mutual TLS) for secure gRPC communication.

```python
from pydantic_rpc import AsyncIOServer, GrpcTLSConfig, extract_peer_identity
import grpc

# Basic TLS (server authentication only)
tls_config = GrpcTLSConfig(
    cert_chain=server_cert_bytes,
    private_key=server_key_bytes,
    require_client_cert=False
)

# mTLS (mutual authentication)
tls_config = GrpcTLSConfig(
    cert_chain=server_cert_bytes,
    private_key=server_key_bytes,
    root_certs=ca_cert_bytes,  # CA to verify client certificates
    require_client_cert=True
)

# Create server with TLS
server = AsyncIOServer(tls=tls_config)

# Extract client identity in service methods
class SecureService:
    async def secure_method(self, request, context: grpc.ServicerContext):
        client_identity = extract_peer_identity(context)
        if client_identity:
            print(f"Authenticated client: {client_identity}")
```

For a complete example, see [examples/tls_server.py](examples/tls_server.py) and [examples/tls_client.py](examples/tls_client.py).

### 🔗 Multiple Services with Custom Interceptors

PydanticRPC supports defining and running multiple gRPC services in a single server:

```python
from datetime import datetime
import grpc
from grpc import ServicerContext

from pydantic_rpc import Server, Message


class FooRequest(Message):
    name: str
    age: int
    d: dict[str, str]


class FooResponse(Message):
    name: str
    age: int
    d: dict[str, str]


class BarRequest(Message):
    names: list[str]


class BarResponse(Message):
    names: list[str]


class FooService:
    def foo(self, request: FooRequest) -> FooResponse:
        return FooResponse(name=request.name, age=request.age, d=request.d)


class MyMessage(Message):
    name: str
    age: int
    o: int | datetime


class Request(Message):
    name: str
    age: int
    d: dict[str, str]
    m: MyMessage


class Response(Message):
    name: str
    age: int
    d: dict[str, str]
    m: MyMessage | str


class BarService:
    def bar(self, req: BarRequest, ctx: ServicerContext) -> BarResponse:
        return BarResponse(names=req.names)


class CustomInterceptor(grpc.ServerInterceptor):
    def intercept_service(self, continuation, handler_call_details):
        # do something
        print(handler_call_details.method)
        return continuation(handler_call_details)


async def app(scope, receive, send):
    pass


if __name__ == "__main__":
    s = Server(10, CustomInterceptor())
    s.run(
        FooService(),
        BarService(),
    )
```

### 🩺 [TODO] Custom Health Check

TODO

### 🤖 MCP (Model Context Protocol) Support

PydanticRPC can expose your services as MCP tools for AI assistants using FastMCP. This enables seamless integration with any MCP-compatible client.

#### Stdio Mode Example

```python
from pydantic_rpc import Message
from pydantic_rpc.mcp import MCPExporter

class CalculateRequest(Message):
    expression: str

class CalculateResponse(Message):
    result: float

class MathService:
    def calculate(self, req: CalculateRequest) -> CalculateResponse:
        result = eval(req.expression, {"__builtins__": {}}, {})
        return CalculateResponse(result=float(result))

# Run as MCP stdio server
if __name__ == "__main__":
    service = MathService()
    mcp = MCPExporter(service)
    mcp.run_stdio()
```

#### Configuring MCP Clients

Any MCP-compatible client can connect to your service. For example, to configure Claude Desktop:

```json
{
  "mcpServers": {
    "my-math-service": {
      "command": "python",
      "args": ["/path/to/math_mcp_server.py"]
    }
  }
}
```

#### HTTP/ASGI Mode Example

MCP can also be mounted to existing ASGI applications:

```python
from pydantic_rpc import ASGIApp
from pydantic_rpc.mcp import MCPExporter

# Create Connect-RPC ASGI app
app = ASGIApp()
app.mount(MathService())

# Add MCP support via HTTP/SSE
mcp = MCPExporter(MathService())
mcp.mount_to_asgi(app, path="/mcp")

# Run with uvicorn
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=8000)
```

MCP endpoints will be available at:
- SSE: `GET http://localhost:8000/mcp/sse`
- Messages: `POST http://localhost:8000/mcp/messages/`

### 🗄️ CLI Tool (pydantic-rpc-cli)

The CLI tool provides powerful features for generating protobuf files and running servers. Install it separately:

```bash
pip install pydantic-rpc-cli
```

#### Generate Protobuf Files

```bash
# Generate .proto file from a service class
pydantic-rpc generate myapp.services.UserService --output ./proto/

# Also compile to Python code
pydantic-rpc generate myapp.services.UserService --compile
```

#### Run Servers Directly

The CLI can run any type of server:

```bash
# Run as gRPC server (auto-detects async/sync)
pydantic-rpc serve myapp.services.UserService --port 50051

# Run as Connect-RPC with ASGI (HTTP/2, uses Hypercorn)
pydantic-rpc serve myapp.services.UserService --asgi --port 8000

# Run as Connect-RPC with WSGI (HTTP/1.1, uses Gunicorn)
pydantic-rpc serve myapp.services.UserService --wsgi --port 8000 --workers 4
```

Using the generated proto files with tools like `protoc`, `buf` and `BSR`, you can generate code for any desired language.


## 📖 Data Type Mapping

| Python Type                    | Protobuf Type             |
|--------------------------------|---------------------------|
| str                            | string                    |
| bytes                          | bytes                     |
| bool                           | bool                      |
| int                            | int32                     |
| float                          | float, double             |
| list[T], tuple[T]              | repeated T                |
| dict[K, V]                     | map<K, V>                 |
| datetime.datetime              | google.protobuf.Timestamp |
| datetime.timedelta             | google.protobuf.Duration  |
| typing.Union[A, B]             | oneof A, B                |
| subclass of enum.Enum          | enum                      |
| subclass of pydantic.BaseModel | message                   |


## ⚠️ Known Limitations

### Union Types with Collections

Due to protobuf's `oneof` restrictions, you cannot use `Union` types that contain `repeated` (list/tuple) or `map` (dict) fields directly. This is a limitation of the protobuf specification itself.

**❌ Not Supported:**
```python
from typing import Union, List, Dict
from pydantic_rpc import Message

# These will fail during proto compilation
class MyMessage(Message):
    # Union with list - NOT SUPPORTED
    field1: Union[List[int], str]

    # Union with dict - NOT SUPPORTED
    field2: Union[Dict[str, int], int]

    # Union with nested collections - NOT SUPPORTED
    field3: Union[List[Dict[str, int]], str]
```

**✅ Workaround - Use Message Wrappers:**
```python
from typing import Union, List, Dict
from pydantic_rpc import Message

# Wrap collections in Message types
class IntList(Message):
    values: List[int]

class StringIntMap(Message):
    values: Dict[str, int]

class MyMessage(Message):
    # Now these work!
    field1: Union[IntList, str]
    field2: Union[StringIntMap, int]
```

This approach works because protobuf allows message types within `oneof` fields, and the collections are contained within those messages.

## 🔧 Development

This project uses [`just`](https://github.com/casey/just) as a command runner for development tasks.

### Installing just

**macOS:**
```bash
brew install just
```

**Linux:**
```bash
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/bin
```

**Windows:**
Download from [GitHub releases](https://github.com/casey/just/releases)

### Quick Start

```bash
# Install dependencies
just install

# Run tests
just test  # or just t

# Format and lint code
just format  # or just f
just lint    # or just l

# Run all checks (lint + tests)
just check   # or just c

# See all available commands
just --list
```

### Running Examples

```bash
# Start servers
just greeting-server  # gRPC server on port 50051
just greeting-asgi    # Connect RPC ASGI on port 8000
just greeting-wsgi    # Connect RPC WSGI on port 3000

# Test with buf curl (in another terminal)
just greet            # gRPC request
just connect-greet    # Connect RPC request
just wsgi-greet       # WSGI request

# Custom names
just greet-name Alice
just connect-greet-name Bob
```

For more development commands and options, see the [Justfile](Justfile) or run `just --list`.

## TODO
- [x] Streaming Support
  - [x] unary-stream
  - [x] stream-unary
  - [x] stream-stream
- [x] Empty Message Support (automatic google.protobuf.Empty)
- [x] Pydantic Serializer Support (@model_serializer, @field_serializer)
- [ ] Custom Health Check Support
- [x] MCP (Model Context Protocol) Support via official MCP SDK
- [ ] Add more examples
- [x] Add tests

## 📜 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
