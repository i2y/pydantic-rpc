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
    s = AsyncIOServer()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(s.run(OlympicsLocationAgent()))
```

And here is an example of a simple Connect RPC service that exposes the same agent as an ASGI application:

```python
import asyncio

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_rpc import ConnecpyASGIApp, Message


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

app = ConnecpyASGIApp()
app.mount(OlympicsLocationAgent())

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
- **For gRPC-Web:**
  - 🌐 **WSGI/ASGI Support:** Create gRPC-Web services that can run as WSGI or ASGI applications powered by `Sonora`.
- **For Connect-RPC:**
  - 🌐 **Connecpy Support:** Partially supports Connect-RPC via `Connecpy`.
- 🛠️ **Pre-generated Protobuf Files and Code:** Pre-generate proto files and corresponding code via the CLI. By setting the environment variable (PYDANTIC_RPC_SKIP_GENERATION), you can skip runtime generation.
- 🤖 **MCP (Model Context Protocol) Support:** Expose your services as tools for AI assistants using the official MCP SDK, supporting both stdio and HTTP/SSE transports.

## 📦 Installation

Install PydanticRPC via pip:

```bash
pip install pydantic-rpc
```

## 🚀 Getting Started

### 🔧 Synchronous Service Example

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

### ⚙️ Asynchronous Service Example

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

### 🌐 ASGI Application Example

```python
from pydantic_rpc import ASGIApp, Message

class HelloRequest(Message):
    name: str

class HelloReply(Message):
    message: str

class Greeter:
    def say_hello(self, request: HelloRequest) -> HelloReply:
        return HelloReply(message=f"Hello, {request.name}!")


async def app(scope, receive, send):
    """ASGI application.

    Args:
        scope (dict): The ASGI scope.
        receive (callable): The receive function.
        send (callable): The send function.
    """
    pass

# Please note that `app` is any ASGI application, such as FastAPI or Starlette.

app = ASGIApp(app)
app.mount(Greeter())
```

### 🌐 WSGI Application Example

```python
from pydantic_rpc import WSGIApp, Message

class HelloRequest(Message):
    name: str

class HelloReply(Message):
    message: str

class Greeter:
    def say_hello(self, request: HelloRequest) -> HelloReply:
        return HelloReply(message=f"Hello, {request.name}!")

def app(environ, start_response):
    """WSGI application.

    Args:
        environ (dict): The WSGI environment.
        start_response (callable): The start_response function.
    """
    pass

# Please note that `app` is any WSGI application, such as Flask or Django.

app = WSGIApp(app)
app.mount(Greeter())
```

### 🏆 Connecpy (Connect-RPC) Example

PydanticRPC also partially supports Connect-RPC via connecpy. Check out “greeting_connecpy.py” for an example:

```bash
uv run greeting_connecpy.py
```

This will launch a Connecpy-based ASGI application that uses the same Pydantic models to serve Connect-RPC requests.

> [!NOTE]
> Please install `protoc-gen-connecpy` to run the Connecpy example.
>
> 1. Install Go.
>     - Please follow the instruction described in https://go.dev/doc/install.
> 2. Install `protoc-gen-connecpy`:
>     ```bash
>     go install github.com/connecpy/protoc-gen-connecpy@latest
>     ```

## ♻️ Skipping Protobuf Generation
By default, PydanticRPC generates .proto files and code at runtime. If you wish to skip the code-generation step (for example, in production environment), set the environment variable below:

```bash
export PYDANTIC_RPC_SKIP_GENERATION=true
```

When this variable is set to "true", PydanticRPC will load existing pre-generated modules rather than generating them on the fly.

## 💎 Advanced Features

### 🌊 Response Streaming
PydanticRPC supports streaming responses only for asynchronous gRPC and gRPC-Web services.
If a service class method’s return type is `typing.AsyncIterator[T]`, the method is considered a streaming method.


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

### 🔗 Multiple Services with Custom Interceptors

PydanticRPC supports defining and running multiple services in a single server:

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
from pydantic_rpc import ConnecpyASGIApp
from pydantic_rpc.mcp import MCPExporter

# Create Connect-RPC ASGI app
app = ConnecpyASGIApp()
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

### 🗄️ Protobuf file and code (Python files) generation using CLI

You can genereate protobuf files and code for a given module and a specified class using `pydantic-rpc` CLI command:

```bash
pydantic-rpc a_module.py aClassName
```

Using this generated proto file and tools as `protoc`, `buf` and `BSR`, you could generate code for any desired language other than Python.


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


## TODO
- [ ] Streaming Support
  - [x] unary-stream
  - [ ] stream-unary
  - [ ] stream-stream
- [ ] Betterproto Support
- [ ] Sonora-connect Support
- [ ] Custom Health Check Support
- [x] MCP (Model Context Protocol) Support via official MCP SDK
- [ ] Add more examples
- [ ] Add tests

## 📜 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
