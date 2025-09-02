#!/usr/bin/env python
"""Simple gRPC client for the greeting service."""

import grpc
from greeter_pb2 import HelloRequest
from greeter_pb2_grpc import GreeterStub


def run():
    """Run the greeter client."""
    # Create a channel and stub
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = GreeterStub(channel)

        # Make a request
        response = stub.SayHello(HelloRequest(name="World"))
        print(f"Greeter client received: {response.message}")


if __name__ == "__main__":
    run()
