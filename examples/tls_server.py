#!/usr/bin/env python
"""Example of gRPC server with TLS/mTLS support using pydantic-rpc."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import grpc
from pydantic_rpc import AsyncIOServer, Message, GrpcTLSConfig, extract_peer_identity


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Define request/response messages
class GreetingRequest(Message):
    name: str
    language: str = "en"


class GreetingResponse(Message):
    message: str
    client_identity: Optional[str] = None


# Service implementation
class SecureGreeterService:
    """A greeting service that can identify TLS clients."""

    async def greet(
        self, request: GreetingRequest, context: grpc.ServicerContext
    ) -> GreetingResponse:
        """Greet the user and identify the client if using mTLS."""
        # Extract client identity from TLS certificate (if mTLS is enabled)
        client_identity = extract_peer_identity(context)

        # Create greeting based on language
        greetings = {
            "en": f"Hello, {request.name}!",
            "es": f"¡Hola, {request.name}!",
            "fr": f"Bonjour, {request.name}!",
            "de": f"Hallo, {request.name}!",
            "ja": f"こんにちは、{request.name}!",
        }

        message = greetings.get(request.language, greetings["en"])

        # Log the request with client identity if available
        if client_identity:
            logger.info(
                f"Request from authenticated client '{client_identity}': {request.name}"
            )
        else:
            logger.info(f"Request from anonymous client: {request.name}")

        return GreetingResponse(message=message, client_identity=client_identity)


def load_certificates(cert_dir: Path) -> tuple[bytes, bytes, bytes]:
    """Load TLS certificates from a directory.

    Args:
        cert_dir: Directory containing the certificate files

    Returns:
        Tuple of (server_cert, server_key, ca_cert)
    """
    server_cert = (cert_dir / "server.crt").read_bytes()
    server_key = (cert_dir / "server.key").read_bytes()
    ca_cert = (cert_dir / "ca.crt").read_bytes()

    return server_cert, server_key, ca_cert


async def run_tls_server(
    cert_dir: Path, port: int = 50051, require_client_cert: bool = False
):
    """Run a gRPC server with TLS support.

    Args:
        cert_dir: Directory containing TLS certificates
        port: Port to listen on
        require_client_cert: Whether to require client certificates (mTLS)
    """
    # Load certificates
    server_cert, server_key, ca_cert = load_certificates(cert_dir)

    # Create TLS configuration
    if require_client_cert:
        # mTLS configuration - require and verify client certificates
        tls_config = GrpcTLSConfig(
            cert_chain=server_cert,
            private_key=server_key,
            root_certs=ca_cert,  # CA certificate to verify clients
            require_client_cert=True,
        )
        logger.info(
            f"Starting mTLS server on port {port} (client certificates required)"
        )
    else:
        # Basic TLS configuration - no client certificate required
        tls_config = GrpcTLSConfig(
            cert_chain=server_cert, private_key=server_key, require_client_cert=False
        )
        logger.info(
            f"Starting TLS server on port {port} (client certificates optional)"
        )

    # Create and configure server with TLS
    server = AsyncIOServer(tls=tls_config)
    server.set_port(port)

    # Run the server
    logger.info("Server is ready to accept connections")
    await server.run(SecureGreeterService())


async def run_insecure_server(port: int = 50051):
    """Run a gRPC server without TLS (for comparison/testing).

    Args:
        port: Port to listen on
    """
    logger.info(f"Starting insecure server on port {port}")

    # Create server without TLS
    server = AsyncIOServer()
    server.set_port(port)

    # Run the server
    logger.info("Server is ready to accept connections")
    await server.run(SecureGreeterService())


def main():
    """Main entry point with CLI argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(description="gRPC server with TLS/mTLS support")
    parser.add_argument(
        "--port", type=int, default=50051, help="Port to listen on (default: 50051)"
    )
    parser.add_argument(
        "--cert-dir",
        type=Path,
        help="Directory containing TLS certificates (server.crt, server.key, ca.crt)",
    )
    parser.add_argument(
        "--mtls", action="store_true", help="Enable mTLS (require client certificates)"
    )
    parser.add_argument(
        "--insecure", action="store_true", help="Run without TLS (for testing)"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.insecure and not args.cert_dir:
        parser.error("Either --cert-dir or --insecure must be specified")

    if args.insecure and args.cert_dir:
        parser.error("Cannot specify both --cert-dir and --insecure")

    if args.mtls and args.insecure:
        parser.error("Cannot enable mTLS with --insecure")

    # Run the appropriate server configuration
    try:
        if args.insecure:
            asyncio.run(run_insecure_server(args.port))
        else:
            asyncio.run(run_tls_server(args.cert_dir, args.port, args.mtls))
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


if __name__ == "__main__":
    main()
