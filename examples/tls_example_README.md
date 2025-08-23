# TLS/mTLS Example for pydantic-rpc

This example demonstrates how to use TLS and mutual TLS (mTLS) with pydantic-rpc gRPC servers.

## Features

- **TLS (Transport Layer Security)**: Encrypts communication between client and server
- **mTLS (Mutual TLS)**: Both client and server authenticate each other using certificates
- **Client Identity Extraction**: Server can identify clients by their certificate CN (Common Name)

## Setup

### 1. Generate Test Certificates

First, generate the necessary certificates for testing:

```bash
# From the project root
cd tests/certs
bash generate_certs.sh
```

This creates:
- `ca.crt`, `ca.key`: Certificate Authority
- `server.crt`, `server.key`: Server certificate
- `client.crt`, `client.key`: Client certificate for mTLS
- `client2.crt`, `client2.key`: Additional client certificate

### 2. Generate Protocol Buffer Files (Optional)

This step is **optional** - pydantic-rpc automatically generates protobuf files when the server starts. You can also pre-generate them if you want:
- Faster server startup times
- Early error detection in proto definitions
- Explicit control over when files are generated

```bash
# From the examples directory
cd examples
uv run python -m pydantic_rpc.proto_gen tls_server:SecureGreeterService
```

**Note**: If you skip this step, the required files will be generated automatically when you first run the server. The Python client will work either way, as it can use the auto-generated files.

## Running the Examples

### Basic TLS Server (Server Authentication Only)

```bash
# Start server with TLS (clients don't need certificates)
uv run python tls_server.py --cert-dir ../tests/certs --port 50051

# Connect with client
uv run python tls_client.py --cert-dir ../tests/certs --port 50051 --name Alice
```

### mTLS Server (Mutual Authentication)

```bash
# Start server with mTLS (clients must provide certificates)
uv run python tls_server.py --cert-dir ../tests/certs --port 50051 --mtls

# Connect with client certificate
uv run python tls_client.py --cert-dir ../tests/certs --port 50051 --name Bob

# Try without client certificate (will fail)
uv run python tls_client.py --cert-dir ../tests/certs --port 50051 --name Charlie --no-client-cert
```

### Testing Multiple Client Certificates

```bash
# Start mTLS server
uv run python tls_server.py --cert-dir ../tests/certs --port 50051 --mtls

# Connect with first client certificate
uv run python tls_client.py --cert-dir ../tests/certs --port 50051 --client-name client

# Connect with second client certificate
uv run python tls_client.py --cert-dir ../tests/certs --port 50051 --client-name client2
```

### Insecure Mode (for Testing/Development)

```bash
# Start server without TLS
uv run python tls_server.py --insecure --port 50051

# Connect without TLS
uv run python tls_client.py --insecure --port 50051
```

## Code Structure

### Server Configuration

```python
from pydantic_rpc import AsyncIOServer, GrpcTLSConfig

# Basic TLS
tls_config = GrpcTLSConfig(
    cert_chain=server_cert,
    private_key=server_key,
    require_client_cert=False
)

# mTLS
tls_config = GrpcTLSConfig(
    cert_chain=server_cert,
    private_key=server_key,
    root_certs=ca_cert,  # CA to verify client certificates
    require_client_cert=True
)

server = AsyncIOServer(tls=tls_config)
```

### Extracting Client Identity

```python
from pydantic_rpc import extract_peer_identity
import grpc

async def greet(self, request, context: grpc.ServicerContext):
    client_identity = extract_peer_identity(context)
    if client_identity:
        print(f"Request from: {client_identity}")
```

## Security Considerations

1. **Test Certificates Only**: The certificates in `tests/certs/` are for testing only. Never use them in production.

2. **Production Certificates**: In production, use certificates from a trusted CA or your organization's PKI.

3. **Certificate Validation**: Always verify the server's certificate against a trusted CA.

4. **mTLS Benefits**:
   - Prevents unauthorized clients from connecting
   - Enables client identification and authorization
   - Provides mutual authentication

5. **Key Management**: Keep private keys secure and never commit them to version control in production.

## Troubleshooting

### Connection Refused
- Check that the server is running and listening on the correct port
- Verify firewall settings

### Certificate Verification Failed
- Ensure the CA certificate matches the one used to sign the server certificate
- Check that the server certificate CN or SAN includes the hostname you're connecting to

### mTLS Authentication Failed
- Verify the client certificate is signed by the same CA the server trusts
- Check that the client is providing both certificate and private key

### "Anonymous" Client Identity
- This is normal for TLS without client certificates
- For mTLS, ensure `require_client_cert=True` on the server
- Verify the client is sending its certificate
