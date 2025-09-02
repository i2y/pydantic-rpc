# import grpc
# from greeter_pb2 import HelloRequest
# from greeter_pb2_grpc import GreeterStub


# def run():
#     with grpc.insecure_channel("localhost:50051") as channel:
#         stub = GreeterStub(channel)
#         response = stub.SayHello(HelloRequest(name="World"))
#         print(response.message)


# if __name__ == "__main__":
#     run()

from connecpy.exceptions import ConnecpyException

import greeter_connecpy
import greeter_pb2


server_url = "http://localhost:3000"
timeout_ms = 5000  # Changed to milliseconds


async def main():
    client = greeter_connecpy.GreeterClient(server_url)

    try:
        response = await client.say_hello(
            request=greeter_pb2.HelloRequest(name="World"),
            timeout_ms=timeout_ms,
        )
        print(response)
    except ConnecpyException as e:
        print(e.code, e.message, e.to_dict())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
