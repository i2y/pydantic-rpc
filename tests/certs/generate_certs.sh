#!/bin/bash

# Create a directory for certificates
mkdir -p tests/certs

cd tests/certs

# Generate CA private key
openssl genrsa -out ca.key 4096

# Generate CA certificate
openssl req -new -x509 -key ca.key -out ca.crt -days 3650 -subj "/C=US/ST=Test/L=Test/O=Test CA/CN=Test CA"

# Generate server private key
openssl genrsa -out server.key 4096

# Generate server certificate signing request
openssl req -new -key server.key -out server.csr -subj "/C=US/ST=Test/L=Test/O=Test Server/CN=localhost"

# Create extensions file for server certificate (for SAN)
cat > server_ext.cnf <<EOF
subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1
EOF

# Sign server certificate with CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -extfile server_ext.cnf

# Generate client private key (for mTLS testing)
openssl genrsa -out client.key 4096

# Generate client certificate signing request
openssl req -new -key client.key -out client.csr -subj "/C=US/ST=Test/L=Test/O=Test Client/CN=testclient"

# Sign client certificate with CA
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365

# Generate another client certificate for testing multiple clients
openssl genrsa -out client2.key 4096
openssl req -new -key client2.key -out client2.csr -subj "/C=US/ST=Test/L=Test/O=Test Client 2/CN=testclient2"
openssl x509 -req -in client2.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client2.crt -days 365

# Clean up CSR files
rm *.csr server_ext.cnf

echo "Certificates generated successfully:"
echo "  CA: ca.crt, ca.key"
echo "  Server: server.crt, server.key"
echo "  Client 1: client.crt, client.key"
echo "  Client 2: client2.crt, client2.key"
