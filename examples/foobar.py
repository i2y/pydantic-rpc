from datetime import datetime

from pydantic import BaseModel
import grpc
from grpc import ServicerContext

from pydantic_rpc import Server, Message


class FooRequest(BaseModel):
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
    s = Server(max_workers=10, interceptors=[CustomInterceptor()])
    s.run(
        FooService(),
        BarService(),
    )
