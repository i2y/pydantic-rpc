"""Decorators for adding protobuf options to RPC methods."""

from typing import Any, Callable, Dict, List, Optional, TypeVar
from functools import wraps

from .options import OptionMetadata, OPTION_METADATA_ATTR


F = TypeVar("F", bound=Callable[..., Any])


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
