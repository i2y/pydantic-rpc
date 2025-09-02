#!/usr/bin/env python3
"""Command-line interface for pydantic-rpc with server runtime support."""

import argparse
import sys
import importlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import asyncio

from pydantic_rpc.core import generate_proto, generate_and_compile_proto


def import_service_class(module_path: str, class_name: Optional[str] = None):
    """Import a service class from a module path.

    Args:
        module_path: Python module path (e.g., 'myapp.services.UserService')
        class_name: Optional class name if not included in module_path

    Returns:
        The service class
    """
    # Add current directory to Python path FIRST, before parsing
    current_dir = os.getcwd()
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    if "." in module_path and not class_name:
        # Try to extract class name from module path
        parts = module_path.split(".")
        potential_class = parts[-1]
        # Check if the last part starts with uppercase (likely a class)
        if potential_class[0].isupper():
            module_path = ".".join(parts[:-1])
            class_name = potential_class

    if not class_name:
        raise ValueError(
            "Class name must be provided either in module_path or as separate argument"
        )

    try:
        module = importlib.import_module(module_path)
        service_class = getattr(module, class_name)
        return service_class
    except ImportError as e:
        raise ImportError(f"Failed to import module '{module_path}': {e}")
    except AttributeError:
        raise AttributeError(
            f"Class '{class_name}' not found in module '{module_path}'"
        )


def cmd_generate(args):
    """Generate protobuf file from a service class."""
    try:
        # Import the service class
        service_class = import_service_class(args.service, args.class_name)

        # Create an instance of the service
        service_instance = service_class()

        # Generate proto content
        proto_content = generate_proto(service_instance, args.package or "")

        # Determine output file
        if args.output:
            output_path = Path(args.output)
            if output_path.is_dir():
                # If output is a directory, create file with service name
                proto_filename = f"{service_class.__name__.lower()}.proto"
                output_file = output_path / proto_filename
            else:
                # Use the provided file path
                output_file = output_path
        else:
            # Default to current directory
            proto_filename = f"{service_class.__name__.lower()}.proto"
            output_file = Path.cwd() / proto_filename

        # Ensure parent directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Write the proto file
        with open(output_file, "w") as f:
            f.write(proto_content)

        print(f"✓ Generated protobuf file: {output_file}")

        # Optionally compile the proto file
        if args.compile:
            print("Compiling protobuf file...")
            pb2_grpc, pb2 = generate_and_compile_proto(
                service_instance, args.package or "", existing_proto_path=output_file
            )
            if pb2_grpc and pb2:
                print(
                    f"✓ Compiled protobuf modules: {output_file.stem}_pb2.py, {output_file.stem}_pb2_grpc.py"
                )
            else:
                print("✗ Failed to compile protobuf file")
                return 1

        return 0

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        return 1


def create_asgi_wrapper(
    service_module: str, service_class_name: str, package_name: str = ""
) -> str:
    """Create a Python module that instantiates and exports an ASGI app."""
    return f"""
# Auto-generated ASGI wrapper for pydantic-rpc
import sys
import os
sys.path.insert(0, os.getcwd())

from {service_module} import {service_class_name}
from pydantic_rpc import ASGIApp

# Create service instance
service = {service_class_name}()

# Create ASGI app
app = ASGIApp(package_name="{package_name}")

# Mount the service (this triggers proto generation)
app.mount(service)
"""


def create_wsgi_wrapper(
    service_module: str, service_class_name: str, package_name: str = ""
) -> str:
    """Create a Python module that instantiates and exports a WSGI app."""
    return f"""
# Auto-generated WSGI wrapper for pydantic-rpc
import sys
import os
sys.path.insert(0, os.getcwd())

from {service_module} import {service_class_name}
from pydantic_rpc import WSGIApp

# Create service instance
service = {service_class_name}()

# Create WSGI app
application = WSGIApp(package_name="{package_name}")

# Mount the service (this triggers proto generation)
application.mount(service)
"""


def run_asgi_server(
    service_module: str, service_class_name: str, port: int, package_name: str = ""
):
    """Run an ASGI server with hypercorn."""
    # Create a temporary file with the ASGI wrapper
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        wrapper_code = create_asgi_wrapper(
            service_module, service_class_name, package_name
        )
        f.write(wrapper_code)
        wrapper_path = f.name

    try:
        # Get the module name from the temp file
        wrapper_module = Path(wrapper_path).stem

        print(f"✓ Starting ASGI server with Hypercorn on port {port}...")
        print(f"  Service: {service_class_name}")
        print(f"  HTTP: http://localhost:{port}")
        print(f"  Connect RPC endpoint: http://localhost:{port}/{service_class_name}/")
        print("\nPress Ctrl+C to stop the server\n")

        # Run hypercorn
        cmd = [
            sys.executable,
            "-m",
            "hypercorn",
            f"{wrapper_module}:app",
            "--bind",
            f"0.0.0.0:{port}",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
        ]

        # Set PYTHONPATH to include the temp file directory
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{Path(wrapper_path).parent}:{env.get('PYTHONPATH', '')}"

        proc = subprocess.Popen(cmd, env=env)
        proc.wait()

    finally:
        # Clean up temp file
        if os.path.exists(wrapper_path):
            os.unlink(wrapper_path)


def run_wsgi_server(
    service_module: str, service_class_name: str, port: int, package_name: str = ""
):
    """Run a WSGI server with gunicorn."""
    # Create a temporary file with the WSGI wrapper
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        wrapper_code = create_wsgi_wrapper(
            service_module, service_class_name, package_name
        )
        f.write(wrapper_code)
        wrapper_path = f.name

    try:
        # Get the module name from the temp file
        wrapper_module = Path(wrapper_path).stem

        print(f"✓ Starting WSGI server with Gunicorn on port {port}...")
        print(f"  Service: {service_class_name}")
        print(f"  HTTP: http://localhost:{port}")
        print(f"  Connect RPC endpoint: http://localhost:{port}/{service_class_name}/")
        print("\nPress Ctrl+C to stop the server\n")

        # Run gunicorn
        cmd = [
            sys.executable,
            "-m",
            "gunicorn",
            f"{wrapper_module}:application",
            "--bind",
            f"0.0.0.0:{port}",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
            "--workers",
            str(args.workers) if hasattr(args, "workers") else "1",
        ]

        # Set PYTHONPATH to include the temp file directory
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{Path(wrapper_path).parent}:{env.get('PYTHONPATH', '')}"

        proc = subprocess.Popen(cmd, env=env)
        proc.wait()

    finally:
        # Clean up temp file
        if os.path.exists(wrapper_path):
            os.unlink(wrapper_path)


def cmd_serve(args):
    """Start a server with the specified service."""
    try:
        # Parse module and class name
        if "." in args.service:
            parts = args.service.split(".")
            if parts[-1][0].isupper():
                service_module = ".".join(parts[:-1])
                service_class_name = parts[-1]
            else:
                service_module = args.service
                service_class_name = args.class_name
        else:
            service_module = args.service
            service_class_name = args.class_name

        if not service_class_name:
            raise ValueError("Class name must be provided")

        # Import the service class to validate it exists
        service_class = import_service_class(service_module, service_class_name)

        # Determine server type and run
        if args.asgi:
            # Run ASGI server with hypercorn
            run_asgi_server(
                service_module, service_class_name, args.port, args.package or ""
            )

        elif args.wsgi:
            # Run WSGI server with gunicorn
            run_wsgi_server(
                service_module, service_class_name, args.port, args.package or ""
            )

        else:
            # Default to gRPC server
            from pydantic_rpc import Server, AsyncIOServer

            # Create an instance of the service
            service_instance = service_class()

            # Check if service has async methods
            has_async = any(
                asyncio.iscoroutinefunction(getattr(service_instance, name))
                for name in dir(service_instance)
                if not name.startswith("_")
            )

            if has_async or args.asyncio:
                server = AsyncIOServer(
                    service=service_instance,
                    port=args.port,
                    package_name=args.package or "",
                )
                print(f"✓ Starting AsyncIO gRPC server on port {args.port}...")
                print(f"  Service: {service_class_name}")
                if args.reflection:
                    print("  Reflection: enabled")
                print("\nPress Ctrl+C to stop the server\n")

                loop = asyncio.get_event_loop()
                loop.run_until_complete(server.run())

            else:
                server = Server(
                    service=service_instance,
                    port=args.port,
                    package_name=args.package or "",
                )
                print(f"✓ Starting gRPC server on port {args.port}...")
                print(f"  Service: {service_class_name}")
                if args.reflection:
                    print("  Reflection: enabled")
                print("\nPress Ctrl+C to stop the server\n")

                server.run()

        return 0

    except KeyboardInterrupt:
        print("\n✓ Server stopped")
        return 0
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="pydantic-rpc",
        description="CLI tool for pydantic-rpc: Generate and serve gRPC/Connect services from Pydantic models",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Generate command
    generate_parser = subparsers.add_parser(
        "generate", help="Generate protobuf file from a service class"
    )
    generate_parser.add_argument(
        "service",
        help="Python module path to the service (e.g., myapp.services.UserService)",
    )
    generate_parser.add_argument(
        "--class-name", help="Service class name (if not included in service path)"
    )
    generate_parser.add_argument(
        "--output",
        "-o",
        help="Output file or directory path (default: current directory)",
    )
    generate_parser.add_argument("--package", "-p", help="Protobuf package name")
    generate_parser.add_argument(
        "--compile",
        "-c",
        action="store_true",
        help="Also compile the generated proto file",
    )

    # Serve command
    serve_parser = subparsers.add_parser(
        "serve", help="Start a server with the specified service"
    )
    serve_parser.add_argument(
        "service",
        help="Python module path to the service (e.g., myapp.services.UserService)",
    )
    serve_parser.add_argument(
        "--class-name", help="Service class name (if not included in service path)"
    )
    serve_parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=50051,
        help="Port to listen on (default: 50051)",
    )
    serve_parser.add_argument("--package", help="Protobuf package name")
    serve_parser.add_argument(
        "--reflection",
        "-r",
        action="store_true",
        default=True,
        help="Enable gRPC reflection (default: True)",
    )
    serve_parser.add_argument(
        "--asyncio", action="store_true", help="Force use of AsyncIO server"
    )
    serve_parser.add_argument(
        "--asgi",
        action="store_true",
        help="Run as ASGI app with Hypercorn (Connect RPC over HTTP/2)",
    )
    serve_parser.add_argument(
        "--wsgi",
        action="store_true",
        help="Run as WSGI app with Gunicorn (Connect RPC over HTTP/1.1)",
    )
    serve_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=1,
        help="Number of worker processes for WSGI server (default: 1)",
    )

    global args  # Make args accessible to run_wsgi_server
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "generate":
        return cmd_generate(args)
    elif args.command == "serve":
        return cmd_serve(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
