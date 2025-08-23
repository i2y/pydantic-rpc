"""TLS configuration for gRPC servers."""

from dataclasses import dataclass
from typing import Optional, Any
import grpc


@dataclass
class GrpcTLSConfig:
    """Configuration for gRPC server TLS.

    Args:
        cert_chain: The PEM-encoded server certificate chain.
        private_key: The PEM-encoded private key for the server certificate.
        root_certs: Optional PEM-encoded root certificates for verifying client certificates.
                   If provided with require_client_cert=True, enables mTLS.
        require_client_cert: If True, requires and verifies client certificates (mTLS).
    """

    cert_chain: bytes
    private_key: bytes
    root_certs: Optional[bytes] = None
    require_client_cert: bool = False

    def to_server_credentials(self) -> grpc.ServerCredentials:
        """Convert to gRPC ServerCredentials."""
        private_key_certificate_chain_pairs = [(self.private_key, self.cert_chain)]

        if self.require_client_cert and self.root_certs:
            # mTLS: require and verify client certificates
            return grpc.ssl_server_credentials(
                private_key_certificate_chain_pairs,
                root_certificates=self.root_certs,
                require_client_auth=True,
            )
        elif self.root_certs:
            # Optional client certificates
            return grpc.ssl_server_credentials(
                private_key_certificate_chain_pairs,
                root_certificates=self.root_certs,
                require_client_auth=False,
            )
        else:
            # Server TLS only, no client certificate validation
            return grpc.ssl_server_credentials(private_key_certificate_chain_pairs)


def extract_peer_identity(context: grpc.ServicerContext) -> Optional[str]:
    """Extract the peer identity from the ServicerContext.

    For mTLS connections, this returns the client's certificate subject.

    Args:
        context: The gRPC ServicerContext from a request handler.

    Returns:
        The peer identity string if available, None otherwise.
    """
    auth_context: Any = context.auth_context()
    if auth_context:
        # The peer identity is typically stored under the 'x509_common_name' key
        # or 'x509_subject_alternative_name' for SANs
        identities = auth_context.get("x509_common_name")
        if identities and len(identities) > 0:
            # Return the first identity (there's usually only one CN)
            # gRPC returns bytes, so we decode to string
            identity_bytes: bytes = identities[0]
            return identity_bytes.decode("utf-8")

        # Fallback to SAN if CN is not available
        san_identities = auth_context.get("x509_subject_alternative_name")
        if san_identities and len(san_identities) > 0:
            # gRPC returns bytes, so we decode to string
            san_bytes: bytes = san_identities[0]
            return san_bytes.decode("utf-8")

    return None


def extract_peer_certificate_chain(context: grpc.ServicerContext) -> Optional[bytes]:
    """Extract the peer's certificate chain from the ServicerContext.

    Args:
        context: The gRPC ServicerContext from a request handler.

    Returns:
        The peer's certificate chain in PEM format if available, None otherwise.
    """
    auth_context: Any = context.auth_context()
    if auth_context:
        cert_chain = auth_context.get("x509_peer_certificate")
        if cert_chain and len(cert_chain) > 0:
            cert_bytes: bytes = cert_chain[0]
            return cert_bytes

    return None
