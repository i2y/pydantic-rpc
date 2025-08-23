#!/usr/bin/env python
"""Example of gRPC client with TLS/mTLS support."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import grpc


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def make_secure_request(
    host: str = "localhost",
    port: int = 50051,
    ca_cert: Optional[bytes] = None,
    client_cert: Optional[bytes] = None,
    client_key: Optional[bytes] = None,
    name: str = "World",
    language: str = "en",
):
    """Make a secure request to the gRPC server.

    Args:
        host: Server hostname
        port: Server port
        ca_cert: CA certificate to verify server
        client_cert: Client certificate for mTLS
        client_key: Client private key for mTLS
        name: Name to greet
        language: Language for greeting
    """
    # Import generated protobuf modules (will be created by pydantic-rpc)
    from securegreeterservice_pb2 import GreetingRequest
    from securegreeterservice_pb2_grpc import SecureGreeterServiceStub

    # Create channel credentials
    if client_cert and client_key:
        # mTLS - provide client certificate
        credentials = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=client_key,
            certificate_chain=client_cert,
        )
        logger.info("Connecting with mTLS (client certificate provided)")
    elif ca_cert:
        # Basic TLS - verify server certificate only
        credentials = grpc.ssl_channel_credentials(root_certificates=ca_cert)
        logger.info("Connecting with TLS (server verification only)")
    else:
        # Use system root certificates
        credentials = grpc.ssl_channel_credentials()
        logger.info("Connecting with TLS (system certificates)")

    # Create secure channel and make request
    target = f"{host}:{port}"
    async with grpc.aio.secure_channel(target, credentials) as channel:
        stub = SecureGreeterServiceStub(channel)

        # Make the request
        request = GreetingRequest(name=name, language=language)
        logger.info(f"Sending request: name='{name}', language='{language}'")

        try:
            response = await stub.Greet(request)
            logger.info(f"Response: {response.message}")
            if response.client_identity:
                logger.info(f"Server identified client as: {response.client_identity}")
            else:
                logger.info("Server did not identify client (anonymous)")
            return response
        except grpc.RpcError as e:
            if (
                e.code() == grpc.StatusCode.UNAVAILABLE
                and "PEER_DID_NOT_RETURN_A_CERTIFICATE" in str(e)
            ):
                logger.error(
                    "Connection rejected: Server requires client certificate (mTLS) but none was provided"
                )
            else:
                logger.error(f"RPC failed: {e.code()} - {e.details()}")
            raise


async def make_insecure_request(
    host: str = "localhost",
    port: int = 50051,
    name: str = "World",
    language: str = "en",
):
    """Make an insecure request to the gRPC server (for testing).

    Args:
        host: Server hostname
        port: Server port
        name: Name to greet
        language: Language for greeting
    """
    # Import generated protobuf modules
    from securegreeterservice_pb2 import GreetingRequest
    from securegreeterservice_pb2_grpc import SecureGreeterServiceStub

    logger.info("Connecting without TLS (insecure)")

    # Create insecure channel and make request
    target = f"{host}:{port}"
    async with grpc.aio.insecure_channel(target) as channel:
        stub = SecureGreeterServiceStub(channel)

        # Make the request
        request = GreetingRequest(name=name, language=language)
        logger.info(f"Sending request: name='{name}', language='{language}'")

        try:
            response = await stub.Greet(request)
            logger.info(f"Response: {response.message}")
            return response
        except grpc.RpcError as e:
            logger.error(f"RPC failed: {e.code()} - {e.details()}")
            raise


def load_certificates(
    cert_dir: Path, client_name: str = "client"
) -> tuple[bytes, Optional[bytes], Optional[bytes]]:
    """Load certificates from a directory.

    Args:
        cert_dir: Directory containing certificate files
        client_name: Base name for client certificate files (e.g., "client" for client.crt/client.key)

    Returns:
        Tuple of (ca_cert, client_cert, client_key)
    """
    ca_cert = (cert_dir / "ca.crt").read_bytes()

    client_cert_path = cert_dir / f"{client_name}.crt"
    client_key_path = cert_dir / f"{client_name}.key"

    client_cert = client_cert_path.read_bytes() if client_cert_path.exists() else None
    client_key = client_key_path.read_bytes() if client_key_path.exists() else None

    return ca_cert, client_cert, client_key


def main():
    """Main entry point with CLI argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(description="gRPC client with TLS/mTLS support")
    parser.add_argument(
        "--host", default="localhost", help="Server hostname (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=50051, help="Server port (default: 50051)"
    )
    parser.add_argument(
        "--cert-dir",
        type=Path,
        help="Directory containing certificates (ca.crt, and optionally client.crt/client.key)",
    )
    parser.add_argument(
        "--client-name",
        default="client",
        help="Base name for client certificate files (default: 'client' for client.crt/client.key)",
    )
    parser.add_argument(
        "--no-client-cert",
        action="store_true",
        help="Don't use client certificate even if available (TLS only, no mTLS)",
    )
    parser.add_argument(
        "--insecure", action="store_true", help="Connect without TLS (for testing)"
    )
    parser.add_argument(
        "--name", default="World", help="Name to greet (default: World)"
    )
    parser.add_argument(
        "--language",
        default="en",
        choices=["en", "es", "fr", "de", "ja"],
        help="Language for greeting (default: en)",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.insecure and not args.cert_dir:
        parser.error("Either --cert-dir or --insecure must be specified")

    if args.insecure and args.cert_dir:
        parser.error("Cannot specify both --cert-dir and --insecure")

    # Run the client
    try:
        if args.insecure:
            asyncio.run(
                make_insecure_request(
                    host=args.host,
                    port=args.port,
                    name=args.name,
                    language=args.language,
                )
            )
        else:
            ca_cert, client_cert, client_key = load_certificates(
                args.cert_dir, args.client_name
            )

            # Use client certificate unless explicitly disabled
            if args.no_client_cert:
                client_cert = None
                client_key = None

            asyncio.run(
                make_secure_request(
                    host=args.host,
                    port=args.port,
                    ca_cert=ca_cert,
                    client_cert=client_cert,
                    client_key=client_key,
                    name=args.name,
                    language=args.language,
                )
            )
    except KeyboardInterrupt:
        logger.info("Client stopped by user")
    except Exception as e:
        logger.error(f"Client error: {e}")
        raise


if __name__ == "__main__":
    main()
