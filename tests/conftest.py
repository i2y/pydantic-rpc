"""pytest configuration for pydantic-rpc tests."""

import os
import sys

# Add the Go bin directory to PATH for protoc-gen-connecpy
go_bin = os.path.expanduser("~/go/bin")
if os.path.exists(go_bin):
    os.environ["PATH"] = f"{go_bin}:{os.environ.get('PATH', '')}"

# Ensure the src directory is in the Python path
src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)