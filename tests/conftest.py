"""pytest configuration for pydantic-rpc tests."""

import sys
import os
import tempfile

tests_path = os.path.dirname(__file__)
if tests_path not in sys.path:
    sys.path.insert(0, tests_path)

os.environ["PYDANTIC_RPC_PROTO_PATH"] = str(tempfile.mkdtemp())

# Add the Go bin directory to PATH for protoc-gen-connecpy
go_bin = os.path.expanduser("~/go/bin")
if os.path.exists(go_bin):
    os.environ["PATH"] = f"{go_bin}:{os.environ.get('PATH', '')}"

# Ensure the src directory is in the Python path
src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
