# pydantic-rpc Development Tasks
# Run `just` to see all available recipes

# Set default shell for recipes
set shell := ["bash", "-c"]

# Default recipe - show help
default:
    @just --list

# Install dependencies
install:
    uv sync

# Run all tests
test:
    uv run pytest

# Run tests with coverage
coverage:
    uv run pytest --cov=src/pydantic_rpc --cov-report=term-missing --cov-report=html

# Run specific test file (e.g., just test-file test_core)
test-file name:
    uv run pytest tests/{{name}}.py -v

# Run specific test function (e.g., just test-func test_core test_server_creation)
test-func file func:
    uv run pytest tests/{{file}}.py::{{func}} -v

# Run tests matching pattern
test-match pattern:
    uv run pytest -k "{{pattern}}" -v

# Check code with ruff
lint:
    uv run ruff check src/ tests/

# Format code with ruff
format:
    uv run ruff format src/ tests/

# Fix linting issues automatically
fix:
    uv run ruff check --fix src/ tests/

# Run all checks (lint + format check + tests)
check: lint
    uv run ruff format --check src/ tests/
    uv run pytest

# Clean build artifacts and cache
clean:
    rm -rf build/ dist/ *.egg-info .pytest_cache/ .coverage htmlcov/
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete

# Build the package
build: clean
    uv build

# List all examples
example-list:
    @ls -1 examples/*.py | grep -v __pycache__ | sed 's/examples\///' | sed 's/\.py//'

# Run a specific example (e.g., just example greeting)
example name:
    cd examples && uv run python {{name}}.py

# Run example with arguments
example-args name *args:
    cd examples && uv run python {{name}}.py {{args}}

# Generate protobuf files from a service module
proto-gen module:
    uv run python -m pydantic_rpc.proto_gen {{module}}

# Start a development server for an example (e.g., just serve greeting)
serve example:
    cd examples && uv run python {{example}}.py

# Run async example with proper event loop handling
async-example name:
    cd examples && uv run python -c "import asyncio; import {{name}}; asyncio.run({{name}}.main())"

# Watch files and run tests on change (requires watchfiles)
watch:
    @echo "Installing watchfiles if not present..."
    @uv pip install watchfiles 2>/dev/null || true
    watchfiles "just test" src/ tests/

# Development mode - format and test on file changes
dev:
    @echo "Installing watchfiles if not present..."
    @uv pip install watchfiles 2>/dev/null || true
    watchfiles "just format && just test" src/ tests/

# Run specific example servers
greeting-server:
    cd examples && uv run python greeting.py

# gRPC Testing with buf curl
# Make sure the greeting-server is running first (just greeting-server in another terminal)

# Send a greeting request with default name
greet:
    buf curl --schema examples/greeter.proto \
        --protocol grpc \
        --http2-prior-knowledge \
        --data '{"name": "World"}' \
        http://localhost:50051/greeter.v1.Greeter/SayHello

# Send a greeting request with custom name
greet-name name="Alice":
    buf curl --schema examples/greeter.proto \
        --protocol grpc \
        --http2-prior-knowledge \
        --data '{"name": "{{name}}"}' \
        http://localhost:50051/greeter.v1.Greeter/SayHello

# Send a greeting request using JSON (same as greet but more explicit)
greet-json json='{"name": "World"}':
    buf curl --schema examples/greeter.proto \
        --protocol grpc \
        --http2-prior-knowledge \
        --data '{{json}}' \
        http://localhost:50051/greeter.v1.Greeter/SayHello

# List available services using server reflection
server-list:
    buf curl --protocol grpc \
        --http2-prior-knowledge \
        --list-services \
        http://localhost:50051

# Describe the Greeter service
server-describe:
    buf curl --schema examples/greeter.proto \
        --protocol grpc \
        --http2-prior-knowledge \
        --list-methods \
        http://localhost:50051

# Describe a specific RPC method
server-describe-method:
    buf curl --schema examples/greeter.proto \
        --protocol grpc \
        --http2-prior-knowledge \
        --describe \
        http://localhost:50051/greeter.v1.Greeter/SayHello

# Run Connect RPC ASGI example (default port 8000)
greeting-asgi:
    cd examples && uv run uvicorn greeting_asgi:app --port 8000

# Run Connect RPC WSGI example (default port 3000)
greeting-wsgi:
    cd examples && uv run python greeting_wsgi.py

# Connect RPC Testing with buf curl
# Make sure the greeting-asgi server is running first (just greeting-asgi in another terminal)

# Send a Connect RPC request with default name
connect-greet:
    buf curl --schema examples/greeter.proto \
        --protocol connect \
        --data '{"name": "World"}' \
        http://localhost:8000/greeter.v1.Greeter/SayHello

# Send a Connect RPC request with custom name
connect-greet-name name="Alice":
    buf curl --schema examples/greeter.proto \
        --protocol connect \
        --data '{"name": "{{name}}"}' \
        http://localhost:8000/greeter.v1.Greeter/SayHello

# Send a Connect RPC request using JSON
connect-greet-json json='{"name": "World"}':
    buf curl --schema examples/greeter.proto \
        --protocol connect \
        --data '{{json}}' \
        http://localhost:8000/greeter.v1.Greeter/SayHello

# List Connect RPC methods (Connect doesn't support reflection, so we use schema)
connect-list:
    buf curl --schema examples/greeter.proto \
        --protocol connect \
        --list-methods \
        http://localhost:8000

# Test Connect RPC with curl (shows raw HTTP request/response)
connect-curl name="World":
    curl -X POST http://localhost:8000/greeter.v1.Greeter/SayHello \
        -H "Content-Type: application/json" \
        -d '{"name": "{{name}}"}'

# WSGI Connect RPC Testing (port 3000)
# Make sure the greeting-wsgi server is running first (just greeting-wsgi in another terminal)

# Send a WSGI Connect RPC request with default name
wsgi-greet:
    buf curl --schema examples/greeter.proto \
        --protocol connect \
        --data '{"name": "World"}' \
        http://localhost:3000/greeter.v1.Greeter/SayHello

# Send a WSGI Connect RPC request with custom name
wsgi-greet-name name="Alice":
    buf curl --schema examples/greeter.proto \
        --protocol connect \
        --data '{"name": "{{name}}"}' \
        http://localhost:3000/greeter.v1.Greeter/SayHello

# Test WSGI Connect RPC with curl
wsgi-curl name="World":
    curl -X POST http://localhost:3000/greeter.v1.Greeter/SayHello \
        -H "Content-Type: application/json" \
        -d '{"name": "{{name}}"}'

# Generate and view Connect RPC stubs for an example
connect-gen example:
    cd examples && uv run python -m pydantic_rpc.proto_gen {{example}}
    @echo "Generated protobuf and Connect stubs for {{example}}"

# Run MCP (Model Context Protocol) example
mcp-example:
    cd examples && uv run python mcp_example.py

# Run MCP HTTP example
mcp-http:
    cd examples && uv run python mcp_http_example.py

# Quick test - run tests in parallel for speed
quick-test:
    uv run pytest -n auto 2>/dev/null || uv run pytest

# Install pre-commit hooks (if using pre-commit)
install-hooks:
    @if [ -f .pre-commit-config.yaml ]; then \
        uv pip install pre-commit && \
        pre-commit install; \
        echo "Pre-commit hooks installed"; \
    else \
        echo "No .pre-commit-config.yaml found"; \
    fi

# Update dependencies
update:
    uv sync --upgrade

# Show project info
info:
    @echo "Project: pydantic-rpc"
    @echo "Version: $(grep version pyproject.toml | head -1 | cut -d'"' -f2)"
    @echo "Python: $(uv python find)"
    @echo "Dependencies:"
    @uv pip list

# Run security check on dependencies
security:
    @uv pip install safety 2>/dev/null || true
    uv run safety check

# Create a new test file
new-test name:
    #!/usr/bin/env bash
    echo 'import pytest' > tests/test_{{name}}.py
    echo 'from pydantic_rpc import Message' >> tests/test_{{name}}.py
    echo '' >> tests/test_{{name}}.py
    echo '' >> tests/test_{{name}}.py
    echo 'def test_{{name}}_basic():' >> tests/test_{{name}}.py
    echo '    """Test basic {{name}} functionality."""' >> tests/test_{{name}}.py
    echo '    # TODO: Implement test' >> tests/test_{{name}}.py
    echo '    assert True' >> tests/test_{{name}}.py
    echo '' >> tests/test_{{name}}.py
    echo '' >> tests/test_{{name}}.py
    echo '@pytest.mark.asyncio' >> tests/test_{{name}}.py
    echo 'async def test_{{name}}_async():' >> tests/test_{{name}}.py
    echo '    """Test async {{name}} functionality."""' >> tests/test_{{name}}.py
    echo '    # TODO: Implement async test' >> tests/test_{{name}}.py
    echo '    assert True' >> tests/test_{{name}}.py
    @echo "Created tests/test_{{name}}.py"

# Run type checking with mypy (if available)
typecheck:
    @if command -v mypy &> /dev/null; then \
        uv run mypy src/; \
    else \
        echo "mypy not installed. Install with: uv pip install mypy"; \
    fi

# Shortcuts/Aliases
alias t := test
alias f := format
alias l := lint
alias c := check
alias r := example
alias w := watch
