"""Tests for TLS support in pydantic-rpc."""

import asyncio
from pathlib import Path
import pytest
import grpc

from pydantic_rpc import AsyncIOServer, Message, GrpcTLSConfig, extract_peer_identity


# Path to test certificates
CERTS_DIR = Path(__file__).parent / "certs"


# Skip tests if certificates don't exist
pytestmark = pytest.mark.skipif(
    not CERTS_DIR.exists() or not (CERTS_DIR / "server.crt").exists(),
    reason="TLS certificates not found. Run tests/certs/generate_certs.sh to generate them.",
)


def read_cert_file(filename: str) -> bytes:
    """Read a certificate file from the certs directory."""
    with open(CERTS_DIR / filename, "rb") as f:
        return f.read()


class HelloRequest(Message):
    name: str


class HelloResponse(Message):
    message: str
    client_identity: str


class TLSTestService:
    """Test service that can access client identity."""

    async def say_hello(
        self, request: HelloRequest, context: grpc.ServicerContext
    ) -> HelloResponse:
        # Extract client identity for mTLS tests
        client_id = extract_peer_identity(context) or "anonymous"

        return HelloResponse(
            message=f"Hello, {request.name}!", client_identity=client_id
        )


@pytest.mark.asyncio
async def test_basic_tls():
    """Test basic TLS connection without client certificates."""
    # Load server certificates
    server_cert = read_cert_file("server.crt")
    server_key = read_cert_file("server.key")

    # Create TLS config without client verification
    tls_config = GrpcTLSConfig(
        cert_chain=server_cert, private_key=server_key, require_client_cert=False
    )

    # Create and start server with service mounted
    server = AsyncIOServer(tls=tls_config)
    server.set_port(50052)  # Use different port for testing
    server.mount(TLSTestService())  # Mount service to generate proto

    # Start server in background
    server_task = asyncio.create_task(server.run())

    try:
        # Give server time to start
        await asyncio.sleep(1.0)

        # Create client with TLS
        ca_cert = read_cert_file("ca.crt")
        credentials = grpc.ssl_channel_credentials(root_certificates=ca_cert)

        async with grpc.aio.secure_channel("localhost:50052", credentials) as channel:
            # Import generated stub (created by pydantic-rpc when service is mounted)
            from tlstestservice_pb2_grpc import TLSTestServiceStub
            from tlstestservice_pb2 import HelloRequest as PbHelloRequest

            stub = TLSTestServiceStub(channel)
            response = await stub.SayHello(PbHelloRequest(name="TLS Test"))

            assert response.message == "Hello, TLS Test!"
            assert response.client_identity == "anonymous"  # No client cert

    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_mtls():
    """Test mTLS with client certificate verification."""
    # Load server certificates
    server_cert = read_cert_file("server.crt")
    server_key = read_cert_file("server.key")
    ca_cert = read_cert_file("ca.crt")

    # Create TLS config with client verification (mTLS)
    tls_config = GrpcTLSConfig(
        cert_chain=server_cert,
        private_key=server_key,
        root_certs=ca_cert,
        require_client_cert=True,
    )

    # Create and start server
    server = AsyncIOServer(tls=tls_config)
    server.set_port(50053)  # Use different port for testing
    server.mount(TLSTestService())  # Mount service to generate proto

    # Start server in background
    server_task = asyncio.create_task(server.run())

    try:
        # Give server time to start
        await asyncio.sleep(1.0)

        # Create client with mTLS
        client_cert = read_cert_file("client.crt")
        client_key = read_cert_file("client.key")

        credentials = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=client_key,
            certificate_chain=client_cert,
        )

        async with grpc.aio.secure_channel("localhost:50053", credentials) as channel:
            # Import generated stub
            from tlstestservice_pb2_grpc import TLSTestServiceStub
            from tlstestservice_pb2 import HelloRequest as PbHelloRequest

            stub = TLSTestServiceStub(channel)
            response = await stub.SayHello(PbHelloRequest(name="mTLS Test"))

            assert response.message == "Hello, mTLS Test!"
            assert (
                response.client_identity == "testclient"
            )  # Client CN from certificate

    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_mtls_client_rejection():
    """Test that server rejects connections without client certificates when mTLS is required."""
    # Load server certificates
    server_cert = read_cert_file("server.crt")
    server_key = read_cert_file("server.key")
    ca_cert = read_cert_file("ca.crt")

    # Create TLS config requiring client certificates
    tls_config = GrpcTLSConfig(
        cert_chain=server_cert,
        private_key=server_key,
        root_certs=ca_cert,
        require_client_cert=True,
    )

    # Create and start server
    server = AsyncIOServer(tls=tls_config)
    server.set_port(50054)  # Use different port for testing
    server.mount(TLSTestService())  # Mount service to generate proto

    # Start server in background
    server_task = asyncio.create_task(server.run())

    try:
        # Give server time to start
        await asyncio.sleep(1.0)

        # Create client WITHOUT client certificate
        credentials = grpc.ssl_channel_credentials(root_certificates=ca_cert)

        async with grpc.aio.secure_channel("localhost:50054", credentials) as channel:
            # Import generated stub
            from tlstestservice_pb2_grpc import TLSTestServiceStub
            from tlstestservice_pb2 import HelloRequest as PbHelloRequest

            stub = TLSTestServiceStub(channel)

            # This should fail because no client certificate is provided
            with pytest.raises(grpc.RpcError) as exc_info:
                await stub.SayHello(PbHelloRequest(name="Should Fail"))

            # Check that it's an authentication error
            assert exc_info.value.code() == grpc.StatusCode.UNAVAILABLE

    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_multiple_clients_mtls():
    """Test mTLS with multiple different client certificates."""
    # Load server certificates
    server_cert = read_cert_file("server.crt")
    server_key = read_cert_file("server.key")
    ca_cert = read_cert_file("ca.crt")

    # Create TLS config with client verification
    tls_config = GrpcTLSConfig(
        cert_chain=server_cert,
        private_key=server_key,
        root_certs=ca_cert,
        require_client_cert=True,
    )

    # Create and start server
    server = AsyncIOServer(tls=tls_config)
    server.set_port(50055)  # Use different port for testing
    server.mount(TLSTestService())  # Mount service to generate proto

    # Start server in background
    server_task = asyncio.create_task(server.run())

    try:
        # Give server time to start
        await asyncio.sleep(1.0)

        # Test with first client certificate
        client1_cert = read_cert_file("client.crt")
        client1_key = read_cert_file("client.key")

        credentials1 = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=client1_key,
            certificate_chain=client1_cert,
        )

        async with grpc.aio.secure_channel("localhost:50055", credentials1) as channel:
            from tlstestservice_pb2_grpc import TLSTestServiceStub
            from tlstestservice_pb2 import HelloRequest as PbHelloRequest

            stub = TLSTestServiceStub(channel)
            response = await stub.SayHello(PbHelloRequest(name="Client 1"))
            assert response.client_identity == "testclient"

        # Test with second client certificate
        client2_cert = read_cert_file("client2.crt")
        client2_key = read_cert_file("client2.key")

        credentials2 = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=client2_key,
            certificate_chain=client2_cert,
        )

        async with grpc.aio.secure_channel("localhost:50055", credentials2) as channel:
            stub = TLSTestServiceStub(channel)
            response = await stub.SayHello(PbHelloRequest(name="Client 2"))
            assert response.client_identity == "testclient2"

    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
