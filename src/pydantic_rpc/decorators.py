"""Decorators for adding protobuf options to RPC methods."""

from typing import Any, Callable, Dict, List, Optional, TypeVar, Type
from functools import wraps
import inspect
import grpc
from connectrpc.code import Code as ConnectErrors

from .options import OptionMetadata, OPTION_METADATA_ATTR


F = TypeVar("F", bound=Callable[..., Any])
ERROR_HANDLER_ATTR = "__pydantic_rpc_error_handlers__"


def http_option(
    method: str,
    path: str,
    body: Optional[str] = None,
    response_body: Optional[str] = None,
    additional_bindings: Optional[List[Dict[str, Any]]] = None,
) -> Callable[[F], F]:
    """
    Decorator to add google.api.http option to an RPC method.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        path: URL path template (e.g., "/v1/books/{id}")
        body: Request body mapping (e.g., "*" for entire body)
        response_body: Response body mapping (specific field to return)
        additional_bindings: List of additional HTTP bindings

    Example:
        @http_option(method="GET", path="/v1/books/{id}")
        async def get_book(self, request: GetBookRequest) -> Book:
            ...
    """

    def decorator(func: F) -> F:
        # Get or create option metadata
        if not hasattr(func, OPTION_METADATA_ATTR):
            setattr(func, OPTION_METADATA_ATTR, OptionMetadata())

        metadata: OptionMetadata = getattr(func, OPTION_METADATA_ATTR)

        # Set HTTP option
        metadata.set_http_option(
            method=method,
            path=path,
            body=body,
            response_body=response_body,
            additional_bindings=additional_bindings,
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Preserve the metadata on the wrapper
        setattr(wrapper, OPTION_METADATA_ATTR, metadata)

        return wrapper  # type: ignore

    return decorator


def proto_option(name: str, value: Any) -> Callable[[F], F]:
    """
    Decorator to add a generic protobuf option to an RPC method.

    Args:
        name: Option name (e.g., "deprecated", "idempotency_level")
        value: Option value

    Example:
        @proto_option("deprecated", True)
        @proto_option("idempotency_level", "IDEMPOTENT")
        async def old_method(self, request: Request) -> Response:
            ...
    """

    def decorator(func: F) -> F:
        # Get or create option metadata
        if not hasattr(func, OPTION_METADATA_ATTR):
            setattr(func, OPTION_METADATA_ATTR, OptionMetadata())

        metadata: OptionMetadata = getattr(func, OPTION_METADATA_ATTR)

        # Add proto option
        metadata.add_proto_option(name=name, value=value)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Preserve the metadata on the wrapper
        setattr(wrapper, OPTION_METADATA_ATTR, metadata)

        return wrapper  # type: ignore

    return decorator


def get_method_options(method: Callable) -> Optional[OptionMetadata]:
    """
    Get option metadata from a method.

    Args:
        method: The method to get options from

    Returns:
        OptionMetadata if present, None otherwise
    """
    return getattr(method, OPTION_METADATA_ATTR, None)


def has_http_option(method: Callable) -> bool:
    """
    Check if a method has an HTTP option.

    Args:
        method: The method to check

    Returns:
        True if the method has an HTTP option, False otherwise
    """
    metadata = get_method_options(method)
    return metadata is not None and metadata.http_option is not None


def has_proto_options(method: Callable) -> bool:
    """
    Check if a method has any proto options.

    Args:
        method: The method to check

    Returns:
        True if the method has proto options, False otherwise
    """
    metadata = get_method_options(method)
    return metadata is not None and len(metadata.proto_options) > 0


def error_handler(
    exception_type: Type[Exception],
    status_code: Optional[grpc.StatusCode] = None,
    connect_code: Optional[ConnectErrors] = None,
    handler: Optional[
        Callable[[Exception], tuple[str, Any]]
        | Callable[[Exception, Any], tuple[str, Any]]
    ] = None,
) -> Callable[[F], F]:
    """
    Decorator to add automatic error handling to an RPC method.

    Args:
        exception_type: The type of exception to handle
        status_code: The gRPC status code to return (for gRPC services)
        connect_code: The Connect error code to return (for Connect services)
        handler: Optional custom handler function that returns (message, details).
                Can accept either (exception) or (exception, request_data) as parameters.

    Example:
        @error_handler(ValidationError, status_code=grpc.StatusCode.INVALID_ARGUMENT)
        @error_handler(KeyError, status_code=grpc.StatusCode.NOT_FOUND)
        async def get_user(self, request: GetUserRequest) -> User:
            ...

        # With custom handler that accesses request data
        def validation_handler(exc: ValidationError, request_data: Any) -> tuple[str, dict]:
            return f"Validation failed for {request_data}", {"errors": exc.errors()}

        @error_handler(ValidationError, handler=validation_handler)
        async def create_user(self, request: CreateUserRequest) -> User:
            ...
    """

    def decorator(func: F) -> F:
        # Get or create error handlers list
        if not hasattr(func, ERROR_HANDLER_ATTR):
            setattr(func, ERROR_HANDLER_ATTR, [])

        handlers = getattr(func, ERROR_HANDLER_ATTR)

        # Add this handler to the list
        handlers.append(
            {
                "exception_type": exception_type,
                "status_code": status_code or grpc.StatusCode.INTERNAL,
                "connect_code": connect_code or ConnectErrors.INTERNAL,
                "handler": handler,
            }
        )

        # Set the error handlers directly on the function
        # No need for a wrapper - we're just storing metadata
        setattr(func, ERROR_HANDLER_ATTR, handlers)

        return func  # type: ignore

    return decorator


def get_error_handlers(method: Callable) -> Optional[List[Dict[str, Any]]]:
    """
    Get error handlers from a method.

    Args:
        method: The method to get error handlers from

    Returns:
        List of error handler configurations if present, None otherwise
    """
    return getattr(method, ERROR_HANDLER_ATTR, None)


def invoke_error_handler(
    handler_func: Callable, exception: Exception, request_data: Any = None
) -> tuple[str, Any]:
    """
    Invoke an error handler function with appropriate parameters based on its signature.

    Args:
        handler_func: The error handler function to invoke
        exception: The exception that was raised
        request_data: Optional request data (raw protobuf request)

    Returns:
        Tuple of (error_message, error_details)
    """
    sig = inspect.signature(handler_func)
    param_count = len(sig.parameters)

    if param_count == 1:
        # Handler only accepts exception
        return handler_func(exception)
    elif param_count == 2:
        # Handler accepts exception and request_data
        return handler_func(exception, request_data)
    else:
        # Invalid signature, fall back to exception only
        return handler_func(exception)
