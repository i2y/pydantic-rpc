"""pytest configuration for pydantic-rpc tests."""

import sys
import os
import tempfile
import shutil
import pytest
import uuid
import subprocess
from functools import lru_cache


tests_path = os.path.dirname(__file__)
if tests_path not in sys.path:
    sys.path.insert(0, tests_path)

# Create a temporary directory for proto files
_temp_proto_dir = tempfile.mkdtemp()
os.environ["PYDANTIC_RPC_PROTO_PATH"] = _temp_proto_dir

# Add the Go bin directory to PATH for protoc-gen-connecpy
go_bin = os.path.expanduser("~/go/bin")
if os.path.exists(go_bin):
    os.environ["PATH"] = f"{go_bin}:{os.environ.get('PATH', '')}"

# Ensure the src directory is in the Python path
src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)


@pytest.fixture(autouse=True)
def cleanup_proto_files():
    """Clean up generated proto files after each test."""
    yield  # Run the test

    # Clean up generated files in the proto directory
    proto_dir = os.environ.get("PYDANTIC_RPC_PROTO_PATH", _temp_proto_dir)
    if os.path.exists(proto_dir):
        for filename in os.listdir(proto_dir):
            file_path = os.path.join(proto_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception:
                pass  # Ignore cleanup errors


@pytest.fixture(autouse=True)
def unique_package_name(request: pytest.FixtureRequest) -> str:
    """Generate a unique package name for each test to avoid protobuf conflicts."""
    package_name = f"test_{uuid.uuid4().hex[:8]}.v1"
    # Store in request node so tests can access it
    request.node.unique_package_name = package_name
    return package_name


@lru_cache(maxsize=1)
def should_skip_connecpy_tests() -> bool:
    """Determine if connecpy tests should be skipped based on whether connecpy is installed."""
    if os.getenv("CI"):
        return False

    # Check if Go is installed
    go_path = shutil.which("go")
    if not go_path:
        return True  # Skip if Go is not installed

    # Check if protoc-gen-connecpy is installed in Go bin
    try:
        result = subprocess.run(
            ["go", "env", "GOPATH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
        gopath = result.stdout.strip()
        connecpy_path = os.path.join(gopath, "bin", "protoc-gen-connecpy")
        if not os.path.exists(connecpy_path):
            return True  # Skip if protoc-gen-connecpy is not installed
    except Exception:
        return True  # Skip if any error occurs

    return False  # Do not skip if all requirements are met


def pytest_sessionfinish(session: pytest.Session, exitstatus: pytest.ExitCode) -> None:
    """Clean up the entire temporary directory when the test session ends."""
    _ = session
    _ = exitstatus
    if os.path.exists(_temp_proto_dir):
        try:
            shutil.rmtree(_temp_proto_dir)
        except Exception:
            pass  # Ignore cleanup errors
