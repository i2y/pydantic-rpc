import annotated_types
import asyncio
import datetime
import enum
import grpc
import grpc_tools
import importlib.util
import inspect
import os
import signal
import sys
import time
import types
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from concurrent import futures
from connectrpc.code import Code as Errors
from connectrpc.errors import ConnectError

# Protobuf Python modules for Timestamp, Duration (requires protobuf / grpcio)
from google.protobuf import duration_pb2, timestamp_pb2, empty_pb2
from grpc import ServicerContext
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_health.v1.health import HealthServicer
from grpc_reflection.v1alpha import reflection
from grpc_tools import protoc
from pathlib import Path
from posixpath import basename
from pydantic import BaseModel, ValidationError
from typing import (
    Any,
    Optional,
    TypeAlias,
    get_args,
    get_origin,
    cast,
    TypeGuard,
    Union,
    Tuple,
)
from concurrent.futures import Executor

from .decorators import (
    get_method_options,
    has_http_option,
    get_error_handlers,
    invoke_error_handler,
)
from .tls import GrpcTLSConfig

###############################################################################
# 1. Message definitions & converter extensions
#    (datetime.datetime <-> google.protobuf.Timestamp)
#    (datetime.timedelta <-> google.protobuf.Duration)
###############################################################################


Message: TypeAlias = BaseModel

# Cache for serializer checks
_has_serializers_cache: dict[type[Message], bool] = {}
_has_field_serializers_cache: dict[type[Message], set[str]] = {}


# Serializer strategy configuration
class SerializerStrategy(enum.Enum):
    """Strategy for applying Pydantic serializers."""

    NONE = "none"  # No serializers applied
    SHALLOW = "shallow"  # Only top-level serializers
    DEEP = "deep"  # Nested serializers too (default)


# Get strategy from environment variable
_SERIALIZER_STRATEGY = SerializerStrategy(
    os.getenv("PYDANTIC_RPC_SERIALIZER_STRATEGY", "deep").lower()
)


def has_serializers(msg_type: type[Message]) -> bool:
    """Check if a Message type has any serializers (cached for performance)."""
    if msg_type not in _has_serializers_cache:
        # Check for both field and model serializers
        has_field = bool(getattr(msg_type, "__pydantic_serializer__", None))
        has_model = bool(
            getattr(msg_type, "model_dump", None) and msg_type != BaseModel
        )
        _has_serializers_cache[msg_type] = has_field or has_model
    return _has_serializers_cache[msg_type]


def get_field_serializers(msg_type: type[Message]) -> set[str]:
    """Get the set of fields that have serializers (cached for performance)."""
    if msg_type not in _has_field_serializers_cache:
        fields_with_serializers = set()
        # Check model_fields_set or similar for fields with serializers
        if hasattr(msg_type, "__pydantic_decorators__"):
            decorators = msg_type.__pydantic_decorators__
            if hasattr(decorators, "field_serializers"):
                fields_with_serializers = set(decorators.field_serializers.keys())
        _has_field_serializers_cache[msg_type] = fields_with_serializers
    return _has_field_serializers_cache[msg_type]


def is_none_type(annotation: Any) -> TypeGuard[type[None] | None]:
    """Check if annotation represents None/NoneType (handles both None and type(None))."""
    return annotation is None or annotation is type(None)


def primitiveProtoValueToPythonValue(value: Any):
    # Returns the value as-is (primitive type).
    return value


def timestamp_to_python(ts: timestamp_pb2.Timestamp) -> datetime.datetime:  # type: ignore
    """Convert a protobuf Timestamp to a Python datetime object."""
    return ts.ToDatetime()


def python_to_timestamp(dt: datetime.datetime) -> timestamp_pb2.Timestamp:  # type: ignore
    """Convert a Python datetime object to a protobuf Timestamp."""
    ts = timestamp_pb2.Timestamp()  # type: ignore
    ts.FromDatetime(dt)
    return ts


def duration_to_python(d: duration_pb2.Duration) -> datetime.timedelta:  # type: ignore
    """Convert a protobuf Duration to a Python timedelta object."""
    return d.ToTimedelta()


def python_to_duration(td: datetime.timedelta) -> duration_pb2.Duration:  # type: ignore
    """Convert a Python timedelta object to a protobuf Duration."""
    d = duration_pb2.Duration()  # type: ignore
    d.FromTimedelta(td)
    return d


def generate_converter(annotation: type[Any] | None) -> Callable[[Any], Any]:
    """
    Returns a converter function to convert protobuf types to Python types.
    This is used primarily when handling incoming requests.
    """
    # For NoneType (Empty messages)
    if is_none_type(annotation):

        def empty_converter(value: empty_pb2.Empty):  # type: ignore
            _ = value
            return None

        return empty_converter

    # For primitive types
    if annotation in (int, str, bool, bytes, float):
        return primitiveProtoValueToPythonValue

    # For enum types
    if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):

        def enum_converter(value: enum.Enum):
            return annotation(value)

        return enum_converter

    # For datetime
    if annotation == datetime.datetime:

        def ts_converter(value: timestamp_pb2.Timestamp):  # type: ignore
            return value.ToDatetime()

        return ts_converter

    # For timedelta
    if annotation == datetime.timedelta:

        def dur_converter(value: duration_pb2.Duration):  # type: ignore
            return value.ToTimedelta()

        return dur_converter

    origin = get_origin(annotation)
    if origin is not None:
        # For seq types
        if origin in (list, tuple):
            item_converter = generate_converter(get_args(annotation)[0])

            def seq_converter(value: list[Any] | tuple[Any, ...]):
                return [item_converter(v) for v in value]

            return seq_converter

        # For dict types
        if origin is dict:
            key_converter = generate_converter(get_args(annotation)[0])
            value_converter = generate_converter(get_args(annotation)[1])

            def dict_converter(value: dict[Any, Any]):
                return {key_converter(k): value_converter(v) for k, v in value.items()}

            return dict_converter

    # For Message classes
    if inspect.isclass(annotation) and issubclass(annotation, Message):
        # Check if it's an empty message class
        if not annotation.model_fields:

            def empty_message_converter(value: empty_pb2.Empty):  # type: ignore
                _ = value
                return annotation()  # Return instance of the empty message class

            return empty_message_converter
        return generate_message_converter(annotation)

    # For union types or other unsupported cases, just return the value as-is.
    return primitiveProtoValueToPythonValue


def generate_message_converter(
    arg_type: type[Message] | type[None] | None,
) -> Callable[[Any], Message | None]:
    """Return a converter function for protobuf -> Python Message."""

    # Handle NoneType (Empty messages)
    if is_none_type(arg_type):

        def empty_converter(request: Any) -> None:
            _ = request
            return None

        return empty_converter

    arg_type = cast("type[Message]", arg_type)
    fields = arg_type.model_fields

    # Handle empty message classes (no fields)
    if not fields:

        def empty_message_converter(request: Any) -> Message:
            _ = request  # The incoming request will be google.protobuf.Empty
            return arg_type()  # Return an instance of the empty message class

        return empty_message_converter
    converters = {
        field: generate_converter(field_type.annotation)  # type: ignore
        for field, field_type in fields.items()
    }

    def converter(request: Any) -> Message:
        rdict = {}
        for field_name, field_info in fields.items():
            field_type = field_info.annotation

            # Check if this is a union type
            if field_type is not None and is_union_type(field_type):
                union_args = flatten_union(field_type)
                has_none = type(None) in union_args
                non_none_args = [arg for arg in union_args if arg is not type(None)]

                if has_none and len(non_none_args) == 1:
                    # This is Optional[T] - check if protobuf field is set
                    try:
                        if hasattr(request, "HasField") and request.HasField(
                            field_name
                        ):
                            rdict[field_name] = converters[field_name](
                                getattr(request, field_name)
                            )
                        else:
                            # Field not set in protobuf, set to None for Optional fields
                            rdict[field_name] = None
                    except ValueError:
                        # HasField doesn't work for this field type (e.g., repeated fields)
                        # Fall back to regular conversion
                        rdict[field_name] = converters[field_name](
                            getattr(request, field_name)
                        )
                elif len(non_none_args) > 1:
                    # This is a oneof field (Union[str, int] etc.)
                    # Check which oneof field is set
                    try:
                        which_field = request.WhichOneof(field_name)
                        if which_field:
                            # Extract the value from the set oneof field
                            proto_value = getattr(request, which_field)

                            # Determine the Python type from the oneof field name
                            # e.g., "value_string" -> str, "value_int32" -> int
                            for union_arg in non_none_args:
                                proto_typename = protobuf_type_mapping(union_arg)
                                if (
                                    proto_typename
                                    and which_field
                                    == f"{field_name}_{proto_typename.replace('.', '_')}"
                                ):
                                    # Convert using the specific type converter
                                    type_converter = generate_converter(union_arg)
                                    rdict[field_name] = type_converter(proto_value)
                                    break
                    except (AttributeError, ValueError):
                        # WhichOneof failed, try fallback
                        # This shouldn't happen for properly generated oneof fields
                        pass
                else:
                    # Union with only None type (shouldn't happen)
                    pass
            else:
                # For non-union fields, convert normally
                rdict[field_name] = converters[field_name](getattr(request, field_name))

        # Use model_validate to support @model_validator
        try:
            return arg_type.model_validate(rdict)
        except AttributeError:
            # Fallback for older Pydantic versions or if model_validate doesn't exist
            return arg_type(**rdict)

    return converter


def handle_validation_error_sync(
    exc: ValidationError,
    method: Callable,
    context: Any,
    request: Any = None,
    is_grpc: bool = True,
) -> Any:
    """
    Handle ValidationError with custom error handlers or default behavior (sync version).

    Args:
        exc: The ValidationError that was raised
        method: The RPC method being called
        context: The gRPC or Connect context
        request: Optional raw request data
        is_grpc: True for gRPC, False for Connect RPC

    Returns:
        Result of context.abort() call
    """
    error_handlers = get_error_handlers(method)

    if error_handlers:
        # Check if there's a handler for ValidationError
        for handler_config in error_handlers:
            if isinstance(exc, handler_config["exception_type"]):
                if handler_config["handler"]:
                    # Custom handler function
                    try:
                        msg, _details = invoke_error_handler(
                            handler_config["handler"], exc, request
                        )
                    except Exception:
                        # Handler failed, fall back to default
                        msg = str(exc)
                else:
                    # No custom handler, use default message
                    msg = str(exc)

                # Use the configured status code
                if is_grpc:
                    status_code = handler_config["status_code"]
                    return context.abort(status_code, msg)
                else:
                    status_code = handler_config["connect_code"]
                    raise ConnectError(code=status_code, message=msg)

    # No handler found, use default behavior
    if is_grpc:
        return context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    else:
        raise ConnectError(code=Errors.INVALID_ARGUMENT, message=str(exc))


async def handle_validation_error_async(
    exc: ValidationError,
    method: Callable,
    context: Any,
    request: Any = None,
    is_grpc: bool = True,
) -> Any:
    """
    Handle ValidationError with custom error handlers or default behavior (async version).

    Args:
        exc: The ValidationError that was raised
        method: The RPC method being called
        context: The gRPC or Connect context
        request: Optional raw request data
        is_grpc: True for gRPC, False for Connect RPC

    Returns:
        Result of context.abort() call
    """
    error_handlers = get_error_handlers(method)

    if error_handlers:
        # Check if there's a handler for ValidationError
        for handler_config in error_handlers:
            if isinstance(exc, handler_config["exception_type"]):
                # Found a matching handler
                if handler_config["handler"]:
                    # Custom handler function
                    try:
                        msg, _details = invoke_error_handler(
                            handler_config["handler"], exc, request
                        )
                    except Exception:
                        # Handler failed, fall back to default
                        msg = str(exc)
                else:
                    # No custom handler, use default message
                    msg = str(exc)

                # Use the configured status code
                if is_grpc:
                    status_code = handler_config["status_code"]
                    await context.abort(status_code, msg)
                    return
                else:
                    status_code = handler_config["connect_code"]
                    raise ConnectError(code=status_code, message=msg)

    # No handler found, use default behavior
    if is_grpc:
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
    else:
        raise ConnectError(code=Errors.INVALID_ARGUMENT, message=str(exc))


def python_value_to_proto_value(field_type: type[Any], value: Any) -> Any:
    """
    Converts Python values to protobuf values.
    Used primarily when constructing a response object.
    """
    # datetime.datetime -> Timestamp
    if field_type == datetime.datetime:
        return python_to_timestamp(value)

    # datetime.timedelta -> Duration
    if field_type == datetime.timedelta:
        return python_to_duration(value)

    # Default behavior: return the value as-is.
    return value


###############################################################################
# 2. Stub implementation
###############################################################################


def connect_obj_with_stub(
    pb2_grpc_module: Any, pb2_module: Any, service_obj: object
) -> type:
    """
    Connect a Python service object to a gRPC stub, generating server methods.
    Returns a subclass of the generated Servicer stub with concrete implementations.
    """
    service_class = service_obj.__class__
    stub_class_name = service_class.__name__ + "Servicer"
    stub_class = getattr(pb2_grpc_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        """Dynamically generated servicer class with stub methods implemented."""

        pass

    def implement_stub_method(
        method: Callable[..., Message],
    ) -> Callable[[object, Any, Any], Any]:
        """
        Wraps a user-defined method (self, *args) -> R into a gRPC stub signature:
        (self, request_proto, context) -> response_proto
        """
        sig = inspect.signature(method)
        arg_type = get_request_arg_type(sig)
        response_type = sig.return_annotation
        param_count = len(sig.parameters)
        converter = generate_message_converter(arg_type)

        if param_count == 0 or param_count == 1:

            def stub_method(
                self: object,
                request: Any,
                context: Any,
                *,
                original: Callable[..., Message] = method,
            ) -> Any:
                _ = self
                try:
                    if param_count == 0:
                        # Method takes no parameters
                        resp_obj = original()
                    elif is_none_type(arg_type):
                        resp_obj = original(None)  # Fixed: pass None instead of no args
                    else:
                        arg = converter(request)
                        resp_obj = original(arg)

                    if is_none_type(response_type):
                        return empty_pb2.Empty()  # type: ignore
                    elif (
                        inspect.isclass(response_type)
                        and issubclass(response_type, Message)
                        and not response_type.model_fields
                    ):
                        # Empty message class
                        return empty_pb2.Empty()  # type: ignore
                    else:
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                except ValidationError as e:
                    return handle_validation_error_sync(
                        e, original, context, request, is_grpc=True
                    )
                except Exception as e:
                    return context.abort(grpc.StatusCode.INTERNAL, str(e))

        elif param_count == 2:

            def stub_method(
                self: object,
                request: Any,
                context: Any,
                *,
                original: Callable[..., Message] = method,
            ) -> Any:
                _ = self
                try:
                    if is_none_type(arg_type):
                        resp_obj = original(
                            None, context
                        )  # Fixed: pass None instead of Empty
                    else:
                        arg = converter(request)
                        resp_obj = original(arg, context)

                    if is_none_type(response_type):
                        return empty_pb2.Empty()  # type: ignore
                    elif (
                        inspect.isclass(response_type)
                        and issubclass(response_type, Message)
                        and not response_type.model_fields
                    ):
                        # Empty message class
                        return empty_pb2.Empty()  # type: ignore
                    else:
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                except ValidationError as e:
                    return handle_validation_error_sync(
                        e, original, context, request, is_grpc=True
                    )
                except Exception as e:
                    return context.abort(grpc.StatusCode.INTERNAL, str(e))

        else:
            raise TypeError(
                f"Method '{method.__name__}' must have exactly 1 or 2 parameters, got {param_count}"
            )

        return stub_method

    # Attach all RPC methods from service_obj to the concrete servicer
    for method_name, method in get_rpc_methods(service_obj):
        if method_name.startswith("_"):
            continue
        setattr(ConcreteServiceClass, method_name, implement_stub_method(method))

    return ConcreteServiceClass


def connect_obj_with_stub_async(
    pb2_grpc_module: Any, pb2_module: Any, obj: object
) -> type:
    """
    Connect a Python service object to a gRPC stub for async methods.
    """
    service_class = obj.__class__
    stub_class_name = service_class.__name__ + "Servicer"
    stub_class = getattr(pb2_grpc_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        pass

    def implement_stub_method(
        method: Callable[..., Any],
    ) -> Callable[[object, Any, Any], Any]:
        sig = inspect.signature(method)
        input_type = get_request_arg_type(sig)
        is_input_stream = is_stream_type(input_type)
        response_type = sig.return_annotation
        is_output_stream = is_stream_type(response_type)
        size_of_parameters = len(sig.parameters)

        if size_of_parameters not in (0, 1, 2):
            raise TypeError(
                f"Method '{method.__name__}' must have 0, 1 or 2 parameters, got {size_of_parameters}"
            )

        if is_input_stream:
            input_item_type = get_args(input_type)[0]
            item_converter = generate_message_converter(input_item_type)

            async def convert_iterator(
                proto_iter: AsyncIterator[Any],
            ) -> AsyncIterator[Message]:
                async for proto in proto_iter:
                    result = item_converter(proto)
                    if result is None:
                        raise TypeError(
                            f"Unexpected None result from converter for type {input_item_type}"
                        )
                    yield result

            if is_output_stream:
                # stream-stream
                output_item_type = get_args(response_type)[0]

                if size_of_parameters == 1:

                    async def stub_method(
                        self: object,
                        request_iterator: AsyncIterator[Any],
                        context: Any,
                    ) -> AsyncIterator[Any]:
                        _ = self
                        try:
                            arg_iter = convert_iterator(request_iterator)
                            async for resp_obj in method(arg_iter):
                                yield convert_python_message_to_proto(
                                    resp_obj, output_item_type, pb2_module
                                )
                        except ValidationError as e:
                            await handle_validation_error_async(
                                e, method, context, None, is_grpc=True
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                else:  # size_of_parameters == 2

                    async def stub_method(
                        self: object,
                        request_iterator: AsyncIterator[Any],
                        context: Any,
                    ) -> AsyncIterator[Any]:
                        _ = self
                        try:
                            arg_iter = convert_iterator(request_iterator)
                            async for resp_obj in method(arg_iter, context):
                                yield convert_python_message_to_proto(
                                    resp_obj, output_item_type, pb2_module
                                )
                        except ValidationError as e:
                            await handle_validation_error_async(
                                e, method, context, None, is_grpc=True
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                return stub_method

            else:
                # stream-unary
                if size_of_parameters == 1:

                    async def stub_method(
                        self: object,
                        request_iterator: AsyncIterator[Any],
                        context: Any,
                    ) -> Any:
                        _ = self
                        try:
                            arg_iter = convert_iterator(request_iterator)
                            resp_obj = await method(arg_iter)
                            return convert_python_message_to_proto(
                                resp_obj, response_type, pb2_module
                            )
                        except ValidationError as e:
                            await handle_validation_error_async(
                                e, method, context, None, is_grpc=True
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                else:  # size_of_parameters == 2

                    async def stub_method(
                        self: object,
                        request_iterator: AsyncIterator[Any],
                        context: Any,
                    ) -> Any:
                        _ = self
                        try:
                            arg_iter = convert_iterator(request_iterator)
                            resp_obj = await method(arg_iter, context)
                            return convert_python_message_to_proto(
                                resp_obj, response_type, pb2_module
                            )
                        except ValidationError as e:
                            await handle_validation_error_async(
                                e, method, context, None, is_grpc=True
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                return stub_method

        else:
            # unary input
            converter = generate_message_converter(input_type)

            if is_output_stream:
                # unary-stream
                output_item_type = get_args(response_type)[0]

                if size_of_parameters == 1:

                    async def stub_method(
                        self: object,
                        request: Any,
                        context: Any,
                    ) -> AsyncIterator[Any]:
                        _ = self
                        try:
                            arg = converter(request)
                            async for resp_obj in method(arg):
                                yield convert_python_message_to_proto(
                                    resp_obj, output_item_type, pb2_module
                                )
                        except ValidationError as e:
                            await handle_validation_error_async(
                                e, method, context, request, is_grpc=True
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                else:  # size_of_parameters == 2

                    async def stub_method(
                        self: object,
                        request: Any,
                        context: Any,
                    ) -> AsyncIterator[Any]:
                        _ = self
                        try:
                            arg = converter(request)
                            async for resp_obj in method(arg, context):
                                yield convert_python_message_to_proto(
                                    resp_obj, output_item_type, pb2_module
                                )
                        except ValidationError as e:
                            await handle_validation_error_async(
                                e, method, context, request, is_grpc=True
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                return stub_method

            else:
                # unary-unary
                if size_of_parameters == 0 or size_of_parameters == 1:

                    async def stub_method(
                        self: object,
                        request: Any,
                        context: Any,
                    ) -> Any:
                        _ = self
                        try:
                            if size_of_parameters == 0:
                                # Method takes no parameters
                                resp_obj = await method()
                            elif is_none_type(input_type):
                                resp_obj = await method(None)
                            else:
                                arg = converter(request)
                                resp_obj = await method(arg)

                            if is_none_type(response_type):
                                return empty_pb2.Empty()  # type: ignore
                            elif (
                                inspect.isclass(response_type)
                                and issubclass(response_type, Message)
                                and not response_type.model_fields
                            ):
                                # Empty message class
                                return empty_pb2.Empty()  # type: ignore
                            else:
                                return convert_python_message_to_proto(
                                    resp_obj, response_type, pb2_module
                                )
                        except ValidationError as e:
                            await handle_validation_error_async(
                                e, method, context, request, is_grpc=True
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                else:  # size_of_parameters == 2

                    async def stub_method(
                        self: object,
                        request: Any,
                        context: Any,
                    ) -> Any:
                        _ = self
                        try:
                            if is_none_type(input_type):
                                resp_obj = await method(None, context)
                            else:
                                arg = converter(request)
                                resp_obj = await method(arg, context)

                            if is_none_type(response_type):
                                return empty_pb2.Empty()  # type: ignore
                            elif (
                                inspect.isclass(response_type)
                                and issubclass(response_type, Message)
                                and not response_type.model_fields
                            ):
                                # Empty message class
                                return empty_pb2.Empty()  # type: ignore
                            else:
                                return convert_python_message_to_proto(
                                    resp_obj, response_type, pb2_module
                                )
                        except ValidationError as e:
                            await handle_validation_error_async(
                                e, method, context, request, is_grpc=True
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                return stub_method

    for method_name, method in get_rpc_methods(obj):
        if method.__name__.startswith("_"):
            continue

        a_method = implement_stub_method(method)
        setattr(ConcreteServiceClass, method_name, a_method)

    return ConcreteServiceClass


def connect_obj_with_stub_connect_python(
    connect_python_module: Any, pb2_module: Any, obj: object
) -> type:
    """
    Connect a Python service object to a Connect Python stub.
    """
    service_class = obj.__class__
    stub_class_name = service_class.__name__
    stub_class = getattr(connect_python_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        pass

    def implement_stub_method(
        method: Callable[..., Message],
    ) -> Callable[[object, Any, Any], Any]:
        sig = inspect.signature(method)
        arg_type = get_request_arg_type(sig)
        converter = generate_message_converter(arg_type)
        response_type = sig.return_annotation
        size_of_parameters = len(sig.parameters)

        match size_of_parameters:
            case 0:
                # Method with no parameters (empty request)
                def stub_method0(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Message] = method,
                ) -> Any:
                    _ = self
                    try:
                        resp_obj = method()

                        if is_none_type(response_type):
                            return empty_pb2.Empty()  # type: ignore
                        else:
                            return convert_python_message_to_proto(
                                resp_obj, response_type, pb2_module
                            )
                    except ValidationError as e:
                        return handle_validation_error_sync(
                            e, method, context, request, is_grpc=False
                        )
                    except Exception as e:
                        raise ConnectError(code=Errors.INTERNAL, message=str(e))

                return stub_method0

            case 1:

                def stub_method1(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Message] = method,
                ) -> Any:
                    _ = self
                    try:
                        if is_none_type(arg_type):
                            resp_obj = method(None)
                        else:
                            arg = converter(request)
                            resp_obj = method(arg)

                        if is_none_type(response_type):
                            return empty_pb2.Empty()  # type: ignore
                        else:
                            return convert_python_message_to_proto(
                                resp_obj, response_type, pb2_module
                            )
                    except ValidationError as e:
                        return handle_validation_error_sync(
                            e, method, context, request, is_grpc=False
                        )
                    except Exception as e:
                        raise ConnectError(code=Errors.INTERNAL, message=str(e))

                return stub_method1

            case 2:

                def stub_method2(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Message] = method,
                ) -> Any:
                    _ = self
                    try:
                        if is_none_type(arg_type):
                            resp_obj = method(None, context)
                        else:
                            arg = converter(request)
                            resp_obj = method(arg, context)

                        if is_none_type(response_type):
                            return empty_pb2.Empty()  # type: ignore
                        else:
                            return convert_python_message_to_proto(
                                resp_obj, response_type, pb2_module
                            )
                    except ValidationError as e:
                        return handle_validation_error_sync(
                            e, method, context, request, is_grpc=False
                        )
                    except Exception as e:
                        raise ConnectError(code=Errors.INTERNAL, message=str(e))

                return stub_method2

            case _:
                raise Exception("Method must have 0, 1, or 2 parameters")

    for method_name, method in get_rpc_methods(obj):
        if method.__name__.startswith("_"):
            continue
        a_method = implement_stub_method(method)
        # Use the original snake_case method name for Connecpy v2.2.0 compatibility
        setattr(ConcreteServiceClass, method.__name__, a_method)

    return ConcreteServiceClass


def connect_obj_with_stub_async_connect_python(
    connect_python_module: Any, pb2_module: Any, obj: object
) -> type:
    """
    Connect a Python service object to a Connect Python stub for async methods with streaming support.
    """
    service_class = obj.__class__
    stub_class_name = service_class.__name__
    stub_class = getattr(connect_python_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        pass

    def implement_stub_method(
        method: Callable[..., Any],
    ) -> Callable[[object, Any, Any], Any]:
        sig = inspect.signature(method)
        input_type = get_request_arg_type(sig)
        is_input_stream = is_stream_type(input_type)
        response_type = sig.return_annotation
        is_output_stream = is_stream_type(response_type)
        size_of_parameters = len(sig.parameters)

        match size_of_parameters:
            case 0:
                # Method with no parameters (empty request)
                async def stub_method0(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Awaitable[Message]] = method,
                ) -> Any:
                    _ = self
                    try:
                        resp_obj = await method()

                        if is_none_type(response_type):
                            return empty_pb2.Empty()  # type: ignore
                        else:
                            return convert_python_message_to_proto(
                                resp_obj, response_type, pb2_module
                            )
                    except ValidationError as e:
                        await handle_validation_error_async(
                            e, method, context, request, is_grpc=False
                        )
                    except Exception as e:
                        raise ConnectError(code=Errors.INTERNAL, message=str(e))

                return stub_method0

            case 1 | 2:
                if is_input_stream:
                    # Client streaming or bidirectional streaming
                    input_item_type = get_args(input_type)[0]
                    item_converter = generate_message_converter(input_item_type)

                    async def convert_iterator(
                        proto_iter: AsyncIterator[Any],
                    ) -> AsyncIterator[Message]:
                        async for proto in proto_iter:
                            result = item_converter(proto)
                            if result is None:
                                raise TypeError(
                                    f"Unexpected None result from converter for type {input_item_type}"
                                )
                            yield result

                    if is_output_stream:
                        # Bidirectional streaming
                        output_item_type = get_args(response_type)[0]

                        if size_of_parameters == 1:

                            async def stub_method(
                                self: object,
                                request_iterator: AsyncIterator[Any],
                                context: Any,
                            ) -> AsyncIterator[Any]:
                                _ = self
                                try:
                                    arg_iter = convert_iterator(request_iterator)
                                    async for resp_obj in method(arg_iter):
                                        yield convert_python_message_to_proto(
                                            resp_obj, output_item_type, pb2_module
                                        )
                                except ValidationError as e:
                                    await handle_validation_error_async(
                                        e, method, context, None, is_grpc=False
                                    )
                                except Exception as e:
                                    raise ConnectError(
                                        code=Errors.INTERNAL, message=str(e)
                                    )
                        else:  # size_of_parameters == 2

                            async def stub_method(
                                self: object,
                                request_iterator: AsyncIterator[Any],
                                context: Any,
                            ) -> AsyncIterator[Any]:
                                _ = self
                                try:
                                    arg_iter = convert_iterator(request_iterator)
                                    async for resp_obj in method(arg_iter, context):
                                        yield convert_python_message_to_proto(
                                            resp_obj, output_item_type, pb2_module
                                        )
                                except ValidationError as e:
                                    await handle_validation_error_async(
                                        e, method, context, None, is_grpc=False
                                    )
                                except Exception as e:
                                    raise ConnectError(
                                        code=Errors.INTERNAL, message=str(e)
                                    )

                        return stub_method
                    else:
                        # Client streaming
                        if size_of_parameters == 1:

                            async def stub_method(
                                self: object,
                                request_iterator: AsyncIterator[Any],
                                context: Any,
                            ) -> Any:
                                _ = self
                                try:
                                    arg_iter = convert_iterator(request_iterator)
                                    resp_obj = await method(arg_iter)
                                    if is_none_type(response_type):
                                        return empty_pb2.Empty()  # type: ignore
                                    return convert_python_message_to_proto(
                                        resp_obj, response_type, pb2_module
                                    )
                                except ValidationError as e:
                                    await handle_validation_error_async(
                                        e, method, context, None, is_grpc=False
                                    )
                                except Exception as e:
                                    raise ConnectError(
                                        code=Errors.INTERNAL, message=str(e)
                                    )
                        else:  # size_of_parameters == 2

                            async def stub_method(
                                self: object,
                                request_iterator: AsyncIterator[Any],
                                context: Any,
                            ) -> Any:
                                _ = self
                                try:
                                    arg_iter = convert_iterator(request_iterator)
                                    resp_obj = await method(arg_iter, context)
                                    if is_none_type(response_type):
                                        return empty_pb2.Empty()  # type: ignore
                                    return convert_python_message_to_proto(
                                        resp_obj, response_type, pb2_module
                                    )
                                except ValidationError as e:
                                    await handle_validation_error_async(
                                        e, method, context, None, is_grpc=False
                                    )
                                except Exception as e:
                                    raise ConnectError(
                                        code=Errors.INTERNAL, message=str(e)
                                    )

                        return stub_method
                else:
                    # Unary request
                    converter = generate_message_converter(input_type)

                    if is_output_stream:
                        # Server streaming
                        output_item_type = get_args(response_type)[0]

                        if size_of_parameters == 1:

                            async def stub_method(
                                self: object,
                                request: Any,
                                context: Any,
                            ) -> AsyncIterator[Any]:
                                _ = self
                                try:
                                    if is_none_type(input_type):
                                        arg = None
                                    else:
                                        arg = converter(request)
                                    async for resp_obj in method(arg):
                                        yield convert_python_message_to_proto(
                                            resp_obj, output_item_type, pb2_module
                                        )
                                except ValidationError as e:
                                    await handle_validation_error_async(
                                        e, method, context, request, is_grpc=False
                                    )
                                except Exception as e:
                                    raise ConnectError(
                                        code=Errors.INTERNAL, message=str(e)
                                    )
                        else:  # size_of_parameters == 2

                            async def stub_method(
                                self: object,
                                request: Any,
                                context: Any,
                            ) -> AsyncIterator[Any]:
                                _ = self
                                try:
                                    if is_none_type(input_type):
                                        arg = None
                                    else:
                                        arg = converter(request)
                                    async for resp_obj in method(arg, context):
                                        yield convert_python_message_to_proto(
                                            resp_obj, output_item_type, pb2_module
                                        )
                                except ValidationError as e:
                                    await handle_validation_error_async(
                                        e, method, context, request, is_grpc=False
                                    )
                                except Exception as e:
                                    raise ConnectError(
                                        code=Errors.INTERNAL, message=str(e)
                                    )

                        return stub_method
                    else:
                        # Unary RPC
                        if size_of_parameters == 1:

                            async def stub_method(
                                self: object,
                                request: Any,
                                context: Any,
                            ) -> Any:
                                _ = self
                                try:
                                    if is_none_type(input_type):
                                        resp_obj = await method(None)
                                    else:
                                        arg = converter(request)
                                        resp_obj = await method(arg)

                                    if is_none_type(response_type):
                                        return empty_pb2.Empty()  # type: ignore
                                    else:
                                        return convert_python_message_to_proto(
                                            resp_obj, response_type, pb2_module
                                        )
                                except ValidationError as e:
                                    await handle_validation_error_async(
                                        e, method, context, request, is_grpc=False
                                    )
                                except Exception as e:
                                    raise ConnectError(
                                        code=Errors.INTERNAL, message=str(e)
                                    )
                        else:  # size_of_parameters == 2

                            async def stub_method(
                                self: object,
                                request: Any,
                                context: Any,
                            ) -> Any:
                                _ = self
                                try:
                                    if is_none_type(input_type):
                                        resp_obj = await method(None, context)
                                    else:
                                        arg = converter(request)
                                        resp_obj = await method(arg, context)

                                    if is_none_type(response_type):
                                        return empty_pb2.Empty()  # type: ignore
                                    else:
                                        return convert_python_message_to_proto(
                                            resp_obj, response_type, pb2_module
                                        )
                                except ValidationError as e:
                                    await handle_validation_error_async(
                                        e, method, context, request, is_grpc=False
                                    )
                                except Exception as e:
                                    raise ConnectError(
                                        code=Errors.INTERNAL, message=str(e)
                                    )

                        return stub_method

            case _:
                raise Exception("Method must have 0, 1, or 2 parameters")

    for method_name, method in get_rpc_methods(obj):
        if method.__name__.startswith("_"):
            continue
        # Check for async generator functions for streaming support
        if not (
            asyncio.iscoroutinefunction(method) or inspect.isasyncgenfunction(method)
        ):
            raise Exception(f"Method {method_name} must be async or async generator")
        a_method = implement_stub_method(method)
        # Use the original snake_case method name for Connecpy v2.2.0 compatibility
        setattr(ConcreteServiceClass, method.__name__, a_method)

    return ConcreteServiceClass


def python_value_to_proto_oneof(
    field_name: str,
    field_type: type[Any],
    value: Any,
    pb2_module: Any,
    _visited: set[int] | None = None,
    _depth: int = 0,
) -> tuple[str, Any]:
    """
    Converts a Python value from a Union type to a protobuf oneof field.
    Returns the field name to set and the converted value.
    """
    union_args = [arg for arg in flatten_union(field_type) if arg is not type(None)]

    # Find which subtype in the Union matches the value's type.
    actual_type = None
    for sub_type in union_args:
        origin = get_origin(sub_type)
        type_to_check = origin or sub_type
        try:
            if isinstance(value, type_to_check):
                actual_type = sub_type
                break
        except TypeError:
            # This can happen if `sub_type` is not a class, e.g. a generic alias
            if isinstance(value, type_to_check):
                actual_type = sub_type
                break

    if actual_type is None:
        raise TypeError(f"Value of type {type(value)} not found in union {field_type}")

    proto_typename = protobuf_type_mapping(actual_type)
    if proto_typename is None:
        raise TypeError(f"Unsupported type in oneof: {actual_type}")

    oneof_field_name = f"{field_name}_{proto_typename.replace('.', '_')}"
    converted_value = python_value_to_proto(
        actual_type, value, pb2_module, _visited, _depth
    )
    return oneof_field_name, converted_value


def convert_python_message_to_proto(
    py_msg: Message,
    msg_type: type[Message],
    pb2_module: Any,
    _visited: set[int] | None = None,
    _depth: int = 0,
) -> object:
    """Convert a Python Pydantic Message instance to a protobuf message instance. Used for constructing a response.

    Args:
        py_msg: The Pydantic Message instance to convert
        msg_type: The type of the Message
        pb2_module: The protobuf module
        _visited: Internal set to track visited objects for circular reference detection
        _depth: Current recursion depth for strategy control
    """
    # Handle empty message classes
    if not msg_type.model_fields:
        # Return google.protobuf.Empty instance
        return empty_pb2.Empty()

    # Initialize visited set for circular reference detection
    if _visited is None:
        _visited = set()

    # Check for circular references
    obj_id = id(py_msg)
    if obj_id in _visited:
        # Return empty proto to avoid infinite recursion
        proto_class = getattr(pb2_module, msg_type.__name__)
        return proto_class()
    _visited.add(obj_id)

    # Determine if we should apply serializers based on strategy
    apply_serializers = False
    if _SERIALIZER_STRATEGY == SerializerStrategy.DEEP:
        apply_serializers = True  # Always apply at any depth
    elif _SERIALIZER_STRATEGY == SerializerStrategy.SHALLOW:
        apply_serializers = _depth == 0  # Only at top level
    # SerializerStrategy.NONE: never apply

    # Only use model_dump if there are serializers and strategy allows
    serialized_data = None
    if apply_serializers and has_serializers(msg_type):
        try:
            serialized_data = py_msg.model_dump(mode="python")
        except Exception:
            # Fallback to the old approach if model_dump fails
            serialized_data = None

    field_dict = {}
    for name, field_info in msg_type.model_fields.items():
        field_type = field_info.annotation

        # Check if this field type contains Message types
        contains_message = False
        if field_type:
            if inspect.isclass(field_type) and issubclass(field_type, Message):
                contains_message = True
            elif is_union_type(field_type):
                # Check if any of the union args are Messages
                for arg in flatten_union(field_type):
                    if arg and inspect.isclass(arg) and issubclass(arg, Message):
                        contains_message = True
                        break
            else:
                # Check for list/dict of Messages
                origin = get_origin(field_type)
                if origin in (list, tuple):
                    inner_type = (
                        get_args(field_type)[0] if get_args(field_type) else None
                    )
                    if (
                        inner_type
                        and inspect.isclass(inner_type)
                        and issubclass(inner_type, Message)
                    ):
                        contains_message = True
                elif origin is dict:
                    args = get_args(field_type)
                    if len(args) >= 2:
                        val_type = args[1]
                        if inspect.isclass(val_type) and issubclass(val_type, Message):
                            contains_message = True

        # Get the value
        value = getattr(py_msg, name)
        if value is None:
            continue

        # For Message types, recursively apply serialization
        if contains_message and not is_union_type(field_type):
            # Direct Message field
            if inspect.isclass(field_type) and issubclass(field_type, Message):
                # Recursively convert nested Message with serializers
                field_dict[name] = convert_python_message_to_proto(
                    value, field_type, pb2_module, _visited, _depth + 1
                )
                continue

        # Use serialized data for non-Message types to respect custom serializers
        if (
            serialized_data is not None
            and name in serialized_data
            and not contains_message
        ):
            value = serialized_data[name]

        field_type = field_info.annotation

        # Handle oneof fields, which are represented as Unions.
        if field_type is not None and is_union_type(field_type):
            union_args = [
                arg for arg in flatten_union(field_type) if arg is not type(None)
            ]
            if len(union_args) > 1:
                # It's a oneof field. We need to determine the concrete type and
                # the corresponding protobuf field name.
                (
                    oneof_field_name,
                    converted_value,
                ) = python_value_to_proto_oneof(
                    name, field_type, value, pb2_module, _visited, _depth
                )
                field_dict[oneof_field_name] = converted_value
                continue

        # For regular and Optional fields that have a value.
        if field_type is not None:
            field_dict[name] = python_value_to_proto(
                field_type, value, pb2_module, _visited, _depth
            )

    # Remove from visited set when done
    _visited.discard(obj_id)

    # Retrieve the appropriate protobuf class dynamically
    proto_class = getattr(pb2_module, msg_type.__name__)
    return proto_class(**field_dict)


def python_value_to_proto(
    field_type: type[Any],
    value: Any,
    pb2_module: Any,
    _visited: set[int] | None = None,
    _depth: int = 0,
) -> Any:
    """
    Perform Python->protobuf type conversion for each field value.
    """
    import datetime
    import inspect

    # If datetime
    if field_type == datetime.datetime:
        return python_to_timestamp(value)

    # If timedelta
    if field_type == datetime.timedelta:
        return python_to_duration(value)

    # If enum
    if inspect.isclass(field_type) and issubclass(field_type, enum.Enum):
        return value.value  # proto3 enum is an int

    origin = get_origin(field_type)
    # If seq
    if origin in (list, tuple):
        inner_type = get_args(field_type)[0]
        # Handle list of Messages
        if inspect.isclass(inner_type) and issubclass(inner_type, Message):
            return [
                convert_python_message_to_proto(
                    v, inner_type, pb2_module, _visited, _depth + 1
                )
                for v in value
            ]
        return [
            python_value_to_proto(inner_type, v, pb2_module, _visited, _depth)
            for v in value
        ]

    # If dict
    if origin is dict:
        key_type, val_type = get_args(field_type)
        # Handle dict with Message values
        if inspect.isclass(val_type) and issubclass(val_type, Message):
            return {
                python_value_to_proto(
                    key_type, k, pb2_module, _visited, _depth
                ): convert_python_message_to_proto(
                    v, val_type, pb2_module, _visited, _depth + 1
                )
                for k, v in value.items()
            }
        return {
            python_value_to_proto(
                key_type, k, pb2_module, _visited, _depth
            ): python_value_to_proto(val_type, v, pb2_module, _visited, _depth)
            for k, v in value.items()
        }

    # If union -> oneof. This path is now only for Optional[T] where value is not None.
    if is_union_type(field_type):
        # The value is not None, so we need to find the actual type.
        non_none_args = [
            arg for arg in flatten_union(field_type) if arg is not type(None)
        ]
        if non_none_args:
            # Assuming it's an Optional[T], so there's one type left.
            return python_value_to_proto(
                non_none_args[0], value, pb2_module, _visited, _depth
            )
        return None  # Should not be reached if value is not None

    # If Message
    if inspect.isclass(field_type) and issubclass(field_type, Message):
        return convert_python_message_to_proto(
            value, field_type, pb2_module, _visited, _depth + 1
        )

    # If primitive
    return value


###############################################################################
# 3. Generating proto files (datetime->Timestamp, timedelta->Duration)
###############################################################################


def is_enum_type(python_type: Any) -> bool:
    """Return True if the given Python type is an enum."""
    return inspect.isclass(python_type) and issubclass(python_type, enum.Enum)


def is_union_type(python_type: Any) -> bool:
    """
    Check if a given Python type is a Union type (including Python 3.10's UnionType).
    """
    if get_origin(python_type) is Union:
        return True
    if sys.version_info >= (3, 10):
        import types

        if isinstance(python_type, types.UnionType):
            return True
    return False


def flatten_union(field_type: Any) -> list[Any]:
    """Recursively flatten nested Unions into a single list of types."""
    if is_union_type(field_type):
        results = []
        for arg in get_args(field_type):
            results.extend(flatten_union(arg))
        return results
    elif is_none_type(field_type):
        return [field_type]
    else:
        return [field_type]


def protobuf_type_mapping(python_type: Any) -> str | None:
    """
    Map a Python type to a protobuf type name/class.
    Includes support for Timestamp, Duration, and Empty.
    """
    import datetime

    mapping = {
        int: "int32",
        str: "string",
        bool: "bool",
        bytes: "bytes",
        float: "float",
    }

    if python_type == datetime.datetime:
        return "google.protobuf.Timestamp"

    if python_type == datetime.timedelta:
        return "google.protobuf.Duration"

    if is_none_type(python_type):
        return "google.protobuf.Empty"

    if is_enum_type(python_type):
        return python_type.__name__

    if is_union_type(python_type):
        return None  # Handled separately as oneof

    if hasattr(python_type, "__origin__"):
        if python_type.__origin__ in (list, tuple):
            inner_type = python_type.__args__[0]
            inner_proto_type = protobuf_type_mapping(inner_type)
            if inner_proto_type:
                return f"repeated {inner_proto_type}"
        elif python_type.__origin__ is dict:
            key_type = python_type.__args__[0]
            value_type = python_type.__args__[1]
            key_proto_type = protobuf_type_mapping(key_type)
            value_proto_type = protobuf_type_mapping(value_type)
            if key_proto_type and value_proto_type:
                return f"map<{key_proto_type}, {value_proto_type}>"

    if inspect.isclass(python_type) and issubclass(python_type, Message):
        # Check if it's an empty message
        if not python_type.model_fields:
            return "google.protobuf.Empty"
        return python_type.__name__

    return mapping.get(python_type)


def comment_out(docstr: str) -> tuple[str, ...]:
    """Convert docstrings into commented-out lines in a .proto file."""
    if not docstr:
        return tuple()

    if docstr.startswith("Usage docs: https://docs.pydantic.dev/2.10/concepts/models/"):
        return tuple()

    return tuple("//" if line == "" else f"// {line}" for line in docstr.split("\n"))


def indent_lines(lines: list[str], indentation: str = "    ") -> str:
    """Indent multiple lines with a given indentation string."""
    return "\n".join(indentation + line for line in lines)


def generate_enum_definition(enum_type: Any) -> str:
    """Generate a protobuf enum definition from a Python enum."""
    enum_name = enum_type.__name__
    members: list[str] = []
    for _, member in enum_type.__members__.items():
        members.append(f"  {member.name} = {member.value};")
    enum_def = f"enum {enum_name} {{\n"
    enum_def += "\n".join(members)
    enum_def += "\n}"
    return enum_def


def generate_oneof_definition(
    field_name: str, union_args: list[Any], start_index: int
) -> tuple[list[str], int]:
    """
    Generate a oneof block in protobuf for a union field.
    Returns a tuple of the definition lines and the updated field index.
    """
    lines = []
    lines.append(f"oneof {field_name} {{")
    current = start_index
    for arg_type in union_args:
        proto_typename = protobuf_type_mapping(arg_type)
        if proto_typename is None:
            raise Exception(f"Nested Union not flattened properly: {arg_type}")

        field_alias = f"{field_name}_{proto_typename.replace('.', '_')}"
        lines.append(f"  {proto_typename} {field_alias} = {current};")
        current += 1
    lines.append("}")
    return lines, current


def extract_nested_types(field_type: Any) -> list[Any]:
    """
    Recursively extract all Message and enum types from a field type,
    including those nested within list, dict, and union types.
    """
    extracted_types = []

    if field_type is None or is_none_type(field_type):
        return extracted_types

    # Check if the type itself is an enum or Message
    if is_enum_type(field_type):
        extracted_types.append(field_type)
    elif inspect.isclass(field_type) and issubclass(field_type, Message):
        extracted_types.append(field_type)

    # Handle Union types
    if is_union_type(field_type):
        union_args = flatten_union(field_type)
        for arg in union_args:
            if arg is not type(None):
                extracted_types.extend(extract_nested_types(arg))

    # Handle generic types (list, dict, etc.)
    origin = get_origin(field_type)
    if origin is not None:
        args = get_args(field_type)
        for arg in args:
            extracted_types.extend(extract_nested_types(arg))

    return extracted_types


def generate_message_definition(
    message_type: Any,
    done_enums: set[Any],
    done_messages: set[Any],
) -> tuple[str, list[Any]]:
    """
    Generate a protobuf message definition for a Pydantic-based Message class.
    Also returns any referenced types (enums, messages) that need to be defined.
    """
    fields: list[str] = []
    refs: list[Any] = []
    pydantic_fields = message_type.model_fields

    # Check if this is an empty message and should use google.protobuf.Empty
    if not pydantic_fields:
        # Return a special marker that indicates this should use google.protobuf.Empty
        return "__EMPTY__", []

    index = 1

    for field_name, field_info in pydantic_fields.items():
        field_type = field_info.annotation
        if field_type is None:
            raise Exception(f"Field {field_name} has no type annotation.")

        is_optional = False
        # Handle Union types, which may be Optional or a oneof.
        if is_union_type(field_type):
            union_args = flatten_union(field_type)
            none_type = type(
                None
            )  # Keep this as type(None) since we're working with union args

            if none_type in union_args or None in union_args:
                is_optional = True
                union_args = [arg for arg in union_args if not is_none_type(arg)]

            if len(union_args) == 1:
                # This is an Optional[T]. Treat it as a simple optional field.
                field_type = union_args[0]
            elif len(union_args) > 1:
                # This is a Union of multiple types, so it becomes a `oneof`.
                oneof_lines, new_index = generate_oneof_definition(
                    field_name, union_args, index
                )
                fields.extend(oneof_lines)
                index = new_index

                for utype in union_args:
                    if is_enum_type(utype) and utype not in done_enums:
                        refs.append(utype)
                    elif (
                        inspect.isclass(utype)
                        and issubclass(utype, Message)
                        and utype not in done_messages
                    ):
                        refs.append(utype)
                continue  # Proceed to the next field
            else:
                # This was a field of only `NoneType`, which is not supported.
                continue

        # For regular fields or optional fields that have been unwrapped.
        proto_typename = protobuf_type_mapping(field_type)
        if proto_typename is None:
            raise Exception(f"Type {field_type} is not supported.")

        # Extract all nested Message and enum types recursively
        nested_types = extract_nested_types(field_type)
        for nested_type in nested_types:
            if is_enum_type(nested_type) and nested_type not in done_enums:
                refs.append(nested_type)
            elif (
                inspect.isclass(nested_type)
                and issubclass(nested_type, Message)
                and nested_type not in done_messages
            ):
                refs.append(nested_type)

        if field_info.description:
            fields.append("// " + field_info.description)
        if field_info.metadata:
            fields.append("// Constraint:")
            for metadata_item in field_info.metadata:
                match type(metadata_item):
                    case annotated_types.Ge:
                        fields.append(
                            "//   greater than or equal to " + str(metadata_item.ge)
                        )
                    case annotated_types.Le:
                        fields.append(
                            "//   less than or equal to " + str(metadata_item.le)
                        )
                    case annotated_types.Gt:
                        fields.append("//   greater than " + str(metadata_item.gt))
                    case annotated_types.Lt:
                        fields.append("//   less than " + str(metadata_item.lt))
                    case annotated_types.MultipleOf:
                        fields.append(
                            "//   multiple of " + str(metadata_item.multiple_of)
                        )
                    case annotated_types.Len:
                        fields.append("//   length of " + str(metadata_item.len))
                    case annotated_types.MinLen:
                        fields.append(
                            "//   minimum length of " + str(metadata_item.min_length)
                        )
                    case annotated_types.MaxLen:
                        fields.append(
                            "//   maximum length of " + str(metadata_item.max_length)
                        )
                    case _:
                        fields.append("//   " + str(metadata_item))

        field_definition = f"{proto_typename} {field_name} = {index};"
        if is_optional:
            field_definition = f"optional {field_definition}"

        fields.append(field_definition)
        index += 1

    # Add reserved fields for forward/backward compatibility if specified
    reserved_count = get_reserved_fields_count()
    if reserved_count > 0:
        start_reserved = index
        end_reserved = index + reserved_count - 1
        fields.append("")
        fields.append("// Reserved fields for future compatibility")
        if reserved_count == 1:
            fields.append(f"reserved {start_reserved};")
        else:
            fields.append(f"reserved {start_reserved} to {end_reserved};")

    msg_def = f"message {message_type.__name__} {{\n{indent_lines(fields)}\n}}"
    return msg_def, refs


def is_stream_type(annotation: Any) -> bool:
    return get_origin(annotation) is AsyncIterator


def is_generic_alias(annotation: Any) -> bool:
    return get_origin(annotation) is not None


def format_method_options(method: Any) -> list[str]:
    """
    Format protobuf options for a method.

    Args:
        method: The method to get options from

    Returns:
        List of formatted option strings
    """
    metadata = get_method_options(method)
    if metadata is None:
        return []

    return metadata.to_proto_strings()


def check_uses_http_options(obj: object) -> bool:
    """
    Check if any method in the service uses HTTP options.

    Args:
        obj: Service instance

    Returns:
        True if any method has HTTP options
    """
    for method_name, method in get_rpc_methods(obj):
        if has_http_option(method):
            return True
    return False


def generate_proto(obj: object, package_name: str = "") -> str:
    """
    Generate a .proto definition from a service class.
    Automatically handles Timestamp, Duration, and Empty usage.
    """
    import datetime

    service_class = obj.__class__
    service_name = service_class.__name__
    service_docstr = inspect.getdoc(service_class)
    service_comment = "\n".join(comment_out(service_docstr)) if service_docstr else ""

    rpc_definitions: list[str] = []
    all_type_definitions: list[str] = []
    done_messages: set[Any] = set()
    done_enums: set[Any] = set()

    uses_timestamp = False
    uses_duration = False
    uses_empty = False
    uses_http_options = check_uses_http_options(obj)

    def check_and_set_well_known_types_for_fields(py_type: Any):
        """Check well-known types for field annotations (excludes None/Empty)."""
        nonlocal uses_timestamp, uses_duration
        if py_type == datetime.datetime:
            uses_timestamp = True
        if py_type == datetime.timedelta:
            uses_duration = True
        # Don't check for None here - Optional fields don't use Empty

    for method_name, method in get_rpc_methods(obj):
        if method.__name__.startswith("_"):
            continue

        method_sig = inspect.signature(method)
        request_type = get_request_arg_type(method_sig)
        response_type = method_sig.return_annotation

        # Validate that we don't have AsyncIterator[None] which doesn't make any practical sense
        if is_stream_type(request_type):
            stream_item_type = get_args(request_type)[0]
            if is_none_type(stream_item_type):
                raise TypeError(
                    f"Method '{method_name}' has AsyncIterator[None] as input type, which is not allowed. Streaming Empty messages is meaningless."
                )

        if is_stream_type(response_type):
            stream_item_type = get_args(response_type)[0]
            if is_none_type(stream_item_type):
                raise TypeError(
                    f"Method '{method_name}' has AsyncIterator[None] as return type, which is not allowed. Streaming Empty messages is meaningless."
                )

        # Handle NoneType for request and response
        if is_none_type(request_type):
            uses_empty = True
        if is_none_type(response_type):
            uses_empty = True

        # Recursively generate message definitions
        message_types = []
        if not is_none_type(request_type):
            message_types.append(request_type)
        if not is_none_type(response_type):
            message_types.append(response_type)

        while message_types:
            mt: type[Message] | type[ServicerContext] | None = message_types.pop()
            if mt in done_messages or mt is ServicerContext or mt is None:
                continue
            done_messages.add(mt)

            if is_stream_type(mt):
                item_type = get_args(mt)[0]
                if not is_none_type(item_type):
                    message_types.append(item_type)
                continue

            # Check if mt is actually a Message type
            if not (inspect.isclass(mt) and issubclass(mt, Message)):
                # Not a Message type, skip processing
                continue

            mt = cast(type[Message], mt)

            for _, field_info in mt.model_fields.items():
                t = field_info.annotation
                if is_union_type(t):
                    for sub_t in flatten_union(t):
                        check_and_set_well_known_types_for_fields(
                            sub_t
                        )  # Use the field-specific version
                else:
                    check_and_set_well_known_types_for_fields(
                        t
                    )  # Use the field-specific version

            msg_def, refs = generate_message_definition(mt, done_enums, done_messages)

            # Skip adding definition if it's an empty message (will use google.protobuf.Empty)
            if msg_def != "__EMPTY__":
                mt_doc = inspect.getdoc(mt)
                if mt_doc:
                    for comment_line in comment_out(mt_doc):
                        all_type_definitions.append(comment_line)

                all_type_definitions.append(msg_def)
                all_type_definitions.append("")
            else:
                # Mark that we need google.protobuf.Empty import
                uses_empty = True

            for r in refs:
                if is_enum_type(r) and r not in done_enums:
                    done_enums.add(r)
                    enum_def = generate_enum_definition(r)
                    all_type_definitions.append(enum_def)
                    all_type_definitions.append("")
                elif issubclass(r, Message) and r not in done_messages:
                    message_types.append(r)

        method_docstr = inspect.getdoc(method)
        if method_docstr:
            for comment_line in comment_out(method_docstr):
                rpc_definitions.append(comment_line)

        input_type = request_type
        input_is_stream = is_stream_type(input_type)
        output_is_stream = is_stream_type(response_type)

        if input_is_stream:
            input_msg_type = get_args(input_type)[0]
        else:
            input_msg_type = input_type

        if output_is_stream:
            output_msg_type = get_args(response_type)[0]
        else:
            output_msg_type = response_type

        # Handle NoneType and empty messages by using Empty
        if input_msg_type is None or input_msg_type is ServicerContext:
            input_str = "google.protobuf.Empty"  # No need to check for stream since we validated above
            if input_msg_type is ServicerContext:
                uses_empty = True
        elif (
            inspect.isclass(input_msg_type)
            and issubclass(input_msg_type, Message)
            and not input_msg_type.model_fields
        ):
            # Empty message class
            input_str = "google.protobuf.Empty"
            uses_empty = True
        else:
            input_str = (
                f"stream {input_msg_type.__name__}"
                if input_is_stream
                else input_msg_type.__name__
            )

        if output_msg_type is None or output_msg_type is ServicerContext:
            output_str = "google.protobuf.Empty"  # No need to check for stream since we validated above
            if output_msg_type is ServicerContext:
                uses_empty = True
        elif (
            inspect.isclass(output_msg_type)
            and issubclass(output_msg_type, Message)
            and not output_msg_type.model_fields
        ):
            # Empty message class
            output_str = "google.protobuf.Empty"
            uses_empty = True
        else:
            output_str = (
                f"stream {output_msg_type.__name__}"
                if output_is_stream
                else output_msg_type.__name__
            )

        # Get method options
        method_options = format_method_options(method)

        if method_options:
            # RPC with options - use block format
            rpc_definitions.append(
                f"rpc {method_name} ({input_str}) returns ({output_str}) {{"
            )
            for option_str in method_options:
                # Indent each option line
                for line in option_str.split("\n"):
                    rpc_definitions.append(f"  {line}")
            rpc_definitions.append("}")
        else:
            # RPC without options - use simple format
            rpc_definitions.append(
                f"rpc {method_name} ({input_str}) returns ({output_str});"
            )

    if not package_name:
        if service_name.endswith("Service"):
            package_name = service_name[: -len("Service")]
        else:
            package_name = service_name
        package_name = package_name.lower() + ".v1"

    imports: list[str] = []
    if uses_http_options:
        imports.append('import "google/api/annotations.proto";')
    if uses_timestamp:
        imports.append('import "google/protobuf/timestamp.proto";')
    if uses_duration:
        imports.append('import "google/protobuf/duration.proto";')
    if uses_empty:
        imports.append('import "google/protobuf/empty.proto";')

    import_block = "\n".join(imports)
    if import_block:
        import_block += "\n"

    proto_definition = f"""syntax = "proto3";

package {package_name};

{import_block}{service_comment}
service {service_name} {{
{indent_lines(rpc_definitions)}
}}

{indent_lines(all_type_definitions, "")}
"""
    return proto_definition


def generate_grpc_code(proto_path: Path) -> types.ModuleType | None:
    """
    Run protoc to generate Python gRPC code from proto_path.
    Writes foo_pb2_grpc.py next to proto_path, then imports and returns that module.
    """
    # 1) Ensure the .proto exists
    if not proto_path.is_file():
        raise FileNotFoundError(f"{proto_path!r} does not exist")

    # 2) Determine output directory (same as the .proto's parent)
    proto_path = proto_path.resolve()
    out_dir = proto_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3) Build and run the protoc command
    out_str = str(out_dir)
    well_known_path = os.path.join(os.path.dirname(grpc_tools.__file__), "_proto")
    args = [
        "protoc",  # Dummy program name (required for protoc.main)
        "-I.",
        f"-I{well_known_path}",
        f"--grpc_python_out={out_str}",
        proto_path.name,
    ]

    current_dir = os.getcwd()
    os.chdir(str(out_dir))
    try:
        if protoc.main(args) != 0:
            return None
    finally:
        os.chdir(current_dir)

    # 4) Locate the generated gRPC file
    base_name = proto_path.stem  # "foo"
    generated_filename = f"{base_name}_pb2_grpc.py"  # "foo_pb2_grpc.py"
    generated_filepath = out_dir / generated_filename

    # 5) Add out_dir to sys.path so we can import it
    if out_str not in sys.path:
        sys.path.append(out_str)

    # 6) Load and return the module
    spec = importlib.util.spec_from_file_location(
        base_name + "_pb2_grpc", str(generated_filepath)
    )
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_connect_python_code(proto_path: Path) -> types.ModuleType | None:
    """
    Run protoc with the Connect Python plugin to generate Python Connect code from proto_path.
    Writes foo_connect_python.py next to proto_path, then imports and returns that module.
    """
    # 1) Ensure the .proto exists
    if not proto_path.is_file():
        raise FileNotFoundError(f"{proto_path!r} does not exist")

    # 2) Determine output directory (same as the .proto's parent)
    proto_path = proto_path.resolve()
    out_dir = proto_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3) Build and run the protoc command
    out_str = str(out_dir)
    well_known_path = os.path.join(os.path.dirname(grpc_tools.__file__), "_proto")
    args = [
        "protoc",  # Dummy program name (required for protoc.main)
        "-I.",
        f"-I{well_known_path}",
        f"--connect-python_out={out_str}",
        proto_path.name,
    ]

    current_dir = os.getcwd()
    os.chdir(str(out_dir))
    try:
        if protoc.main(args) != 0:
            return None
    finally:
        os.chdir(current_dir)

    # 4) Locate the generated file
    base_name = proto_path.stem  # "foo"
    generated_filename = f"{base_name}_connect.py"  # "foo_connect.py"
    generated_filepath = out_dir / generated_filename

    # 5) Add out_dir to sys.path so we can import by filename
    if out_str not in sys.path:
        sys.path.append(out_str)

    # 6) Load and return the module
    spec = importlib.util.spec_from_file_location(
        base_name + "_connect", str(generated_filepath)
    )
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_pb_code(proto_path: Path) -> types.ModuleType | None:
    """
    Run protoc to generate Python gRPC code from proto_path.
    Writes foo_pb2.py and foo_pb2.pyi next to proto_path, then imports and returns the pb2 module.
    """
    # 1) Make sure proto_path exists
    if not proto_path.is_file():
        raise FileNotFoundError(f"{proto_path!r} does not exist")

    # 2) Determine output directory (same as proto file)
    proto_path = proto_path.resolve()
    out_dir = proto_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3) Build and run protoc command
    out_str = str(out_dir)
    well_known_path = os.path.join(os.path.dirname(grpc_tools.__file__), "_proto")
    args = [
        "protoc",  # Dummy program name (required for protoc.main)
        "-I.",
        f"-I{well_known_path}",
        f"--python_out={out_str}",
        f"--pyi_out={out_str}",
        proto_path.name,
    ]

    current_dir = os.getcwd()
    os.chdir(str(out_dir))
    try:
        if protoc.main(args) != 0:
            return None
    finally:
        os.chdir(current_dir)

    # 4) Locate generated file
    base_name = proto_path.stem  # e.g. "foo"
    generated_file = out_dir / f"{base_name}_pb2.py"

    # 5) Add to sys.path if needed
    if out_str not in sys.path:
        sys.path.append(out_str)

    # 6) Import it
    spec = importlib.util.spec_from_file_location(
        base_name + "_pb2", str(generated_file)
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_request_arg_type(sig: inspect.Signature) -> Any:
    """Return the type annotation of the first parameter (request) of a method.

    If the method has no parameters, return None (implying an empty request).
    """
    num_of_params = len(sig.parameters)
    if num_of_params == 0:
        # No parameters means empty request
        return None
    elif num_of_params == 1 or num_of_params == 2:
        return tuple(sig.parameters.values())[0].annotation
    else:
        raise Exception("Method must have 0, 1, or 2 parameters")


def get_rpc_methods(obj: object) -> list[tuple[str, Callable[..., Any]]]:
    """
    Retrieve the list of RPC methods from a service object.
    The method name is converted to PascalCase for .proto compatibility.
    """

    def to_pascal_case(name: str) -> str:
        return "".join(part.capitalize() for part in name.split("_"))

    return [
        (to_pascal_case(attr_name), getattr(obj, attr_name))
        for attr_name in dir(obj)
        if inspect.ismethod(getattr(obj, attr_name))
    ]


def is_skip_generation() -> bool:
    """Check if the proto file and code generation should be skipped."""
    return os.getenv("PYDANTIC_RPC_SKIP_GENERATION", "false").lower() == "true"


def get_reserved_fields_count() -> int:
    """Get the number of reserved fields to add to each message from environment variable."""
    try:
        return max(0, int(os.getenv("PYDANTIC_RPC_RESERVED_FIELDS", "0")))
    except ValueError:
        return 0


def generate_and_compile_proto(
    obj: object,
    package_name: str = "",
    existing_proto_path: Path | None = None,
) -> tuple[Any, Any]:
    if is_skip_generation():
        import importlib

        pb2_module = None
        pb2_grpc_module = None

        try:
            pb2_module = importlib.import_module(
                f"{obj.__class__.__name__.lower()}_pb2"
            )
        except ImportError:
            pass

        try:
            pb2_grpc_module = importlib.import_module(
                f"{obj.__class__.__name__.lower()}_pb2_grpc"
            )
        except ImportError:
            pass

        if pb2_grpc_module is not None and pb2_module is not None:
            return pb2_grpc_module, pb2_module

        # If the modules are not found, generate and compile the proto files.

    if existing_proto_path:
        # Use the provided existing proto file (skip generation)
        proto_file_path = existing_proto_path
    else:
        # Generate as before
        klass = obj.__class__
        proto_file = generate_proto(obj, package_name)
        proto_file_name = klass.__name__.lower() + ".proto"
        proto_file_path = get_proto_path(proto_file_name)

        with proto_file_path.open(mode="w", encoding="utf-8") as f:
            _ = f.write(proto_file)

    gen_pb = generate_pb_code(proto_file_path)
    if gen_pb is None:
        raise Exception("Generating pb code")

    gen_grpc = generate_grpc_code(proto_file_path)
    if gen_grpc is None:
        raise Exception("Generating grpc code")
    return gen_grpc, gen_pb


def get_proto_path(proto_filename: str) -> Path:
    # 1. Get raw env var (or default to cwd)
    raw = os.getenv("PYDANTIC_RPC_PROTO_PATH", None)
    base = Path(raw) if raw is not None else Path.cwd()

    # 2. Expand ~ and env-vars, then make absolute
    base = Path(os.path.expandvars(os.path.expanduser(str(base)))).resolve()

    # 3. Ensure it's a directory (or create it)
    if not base.exists():
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise RuntimeError(f"Unable to create directory {base!r}: {e}") from e
    elif not base.is_dir():
        raise NotADirectoryError(f"{base!r} exists but is not a directory")

    # 4. Check writability
    if not os.access(base, os.W_OK):
        raise PermissionError(f"No write permission for directory {base!r}")

    # 5. Return the final file path
    return base / proto_filename


def generate_and_compile_proto_using_connect_python(
    obj: object,
    package_name: str = "",
    existing_proto_path: Path | None = None,
) -> tuple[Any, Any]:
    if is_skip_generation():
        import importlib

        pb2_module = None
        connect_python_module = None

        try:
            pb2_module = importlib.import_module(
                f"{obj.__class__.__name__.lower()}_pb2"
            )
        except ImportError:
            pass

        try:
            connect_python_module = importlib.import_module(
                f"{obj.__class__.__name__.lower()}_connect"
            )
        except ImportError:
            pass

        if connect_python_module is not None and pb2_module is not None:
            return connect_python_module, pb2_module

        # If the modules are not found, generate and compile the proto files.

    if existing_proto_path:
        # Use the provided existing proto file (skip generation)
        proto_file_path = existing_proto_path
    else:
        # Generate as before
        klass = obj.__class__
        proto_file = generate_proto(obj, package_name)
        proto_file_name = klass.__name__.lower() + ".proto"

        proto_file_path = get_proto_path(proto_file_name)
        with proto_file_path.open(mode="w", encoding="utf-8") as f:
            _ = f.write(proto_file)

    gen_pb = generate_pb_code(proto_file_path)
    if gen_pb is None:
        raise Exception("Generating pb code")

    gen_connect_python = generate_connect_python_code(proto_file_path)
    if gen_connect_python is None:
        raise Exception("Generating Connect Python code")
    return gen_connect_python, gen_pb


def is_combined_proto_enabled() -> bool:
    """Check if combined proto file generation is enabled."""
    return os.getenv("PYDANTIC_RPC_COMBINED_PROTO", "false").lower() == "true"


def generate_combined_proto(
    *services: object, package_name: str = "combined.v1"
) -> str:
    """Generate a combined .proto definition from multiple service classes."""
    import datetime

    all_type_definitions: list[str] = []
    all_service_definitions: list[str] = []
    done_messages: set[Any] = set()
    done_enums: set[Any] = set()

    uses_timestamp = False
    uses_duration = False
    uses_empty = False

    def check_and_set_well_known_types_for_fields(py_type: Any):
        """Check well-known types for field annotations (excludes None/Empty)."""
        nonlocal uses_timestamp, uses_duration
        if py_type == datetime.datetime:
            uses_timestamp = True
        if py_type == datetime.timedelta:
            uses_duration = True

    # Process each service
    for service_obj in services:
        service_class = service_obj.__class__
        service_name = service_class.__name__
        service_docstr = inspect.getdoc(service_class)
        service_comment = (
            "\n".join(comment_out(service_docstr)) if service_docstr else ""
        )

        service_rpc_definitions: list[str] = []

        for method_name, method in get_rpc_methods(service_obj):
            if method.__name__.startswith("_"):
                continue

            method_sig = inspect.signature(method)
            request_type = get_request_arg_type(method_sig)
            response_type = method_sig.return_annotation

            # Validate stream types
            if is_stream_type(request_type):
                stream_item_type = get_args(request_type)[0]
                if is_none_type(stream_item_type):
                    raise TypeError(
                        f"Method '{method_name}' has AsyncIterator[None] as input type, which is not allowed."
                    )

            if is_stream_type(response_type):
                stream_item_type = get_args(response_type)[0]
                if is_none_type(stream_item_type):
                    raise TypeError(
                        f"Method '{method_name}' has AsyncIterator[None] as return type, which is not allowed."
                    )

            # Handle NoneType for request and response
            if is_none_type(request_type):
                uses_empty = True
            if is_none_type(response_type):
                uses_empty = True

            # Validate that users aren't using protobuf messages directly
            if hasattr(request_type, "DESCRIPTOR") and not is_none_type(request_type):
                raise TypeError(
                    f"Method '{method_name}' uses protobuf message '{request_type.__name__}' directly. "
                    f"Please use Pydantic Message classes instead, or None/empty Message for empty requests."
                )
            if hasattr(response_type, "DESCRIPTOR") and not is_none_type(response_type):
                raise TypeError(
                    f"Method '{method_name}' uses protobuf message '{response_type.__name__}' directly. "
                    f"Please use Pydantic Message classes instead, or None/empty Message for empty responses."
                )

            # Collect message types for processing
            message_types = []
            if not is_none_type(request_type):
                message_types.append(request_type)
            if not is_none_type(response_type):
                message_types.append(response_type)

            # Process message types
            while message_types:
                mt: type[Message] | type[ServicerContext] | None = message_types.pop()
                if mt in done_messages or mt is ServicerContext or mt is None:
                    continue
                done_messages.add(mt)

                if is_stream_type(mt):
                    item_type = get_args(mt)[0]
                    if not is_none_type(item_type):
                        message_types.append(item_type)
                    continue

                mt = cast(type[Message], mt)

                for _, field_info in mt.model_fields.items():
                    t = field_info.annotation
                    if is_union_type(t):
                        for sub_t in flatten_union(t):
                            check_and_set_well_known_types_for_fields(sub_t)
                    else:
                        check_and_set_well_known_types_for_fields(t)

                msg_def, refs = generate_message_definition(
                    mt, done_enums, done_messages
                )

                # Skip adding definition if it's an empty message (will use google.protobuf.Empty)
                if msg_def != "__EMPTY__":
                    mt_doc = inspect.getdoc(mt)
                    if mt_doc:
                        for comment_line in comment_out(mt_doc):
                            all_type_definitions.append(comment_line)

                    all_type_definitions.append(msg_def)
                    all_type_definitions.append("")
                else:
                    # Mark that we need google.protobuf.Empty import
                    uses_empty = True

                for r in refs:
                    if is_enum_type(r) and r not in done_enums:
                        done_enums.add(r)
                        enum_def = generate_enum_definition(r)
                        all_type_definitions.append(enum_def)
                        all_type_definitions.append("")
                    elif issubclass(r, Message) and r not in done_messages:
                        message_types.append(r)

            # Generate RPC definition
            method_docstr = inspect.getdoc(method)
            if method_docstr:
                for comment_line in comment_out(method_docstr):
                    service_rpc_definitions.append(comment_line)

            input_type = request_type
            input_is_stream = is_stream_type(input_type)
            output_is_stream = is_stream_type(response_type)

            if input_is_stream:
                input_msg_type = get_args(input_type)[0]
            else:
                input_msg_type = input_type

            if output_is_stream:
                output_msg_type = get_args(response_type)[0]
            else:
                output_msg_type = response_type

            # Handle NoneType and empty messages by using Empty
            if input_msg_type is None or input_msg_type is ServicerContext:
                input_str = "google.protobuf.Empty"  # No need to check for stream since we validated above
                if input_msg_type is ServicerContext:
                    uses_empty = True
            elif (
                inspect.isclass(input_msg_type)
                and issubclass(input_msg_type, Message)
                and not input_msg_type.model_fields
            ):
                # Empty message class
                input_str = "google.protobuf.Empty"
                uses_empty = True
            else:
                input_str = (
                    f"stream {input_msg_type.__name__}"
                    if input_is_stream
                    else input_msg_type.__name__
                )

            if output_msg_type is None or output_msg_type is ServicerContext:
                output_str = "google.protobuf.Empty"  # No need to check for stream since we validated above
                if output_msg_type is ServicerContext:
                    uses_empty = True
            elif (
                inspect.isclass(output_msg_type)
                and issubclass(output_msg_type, Message)
                and not output_msg_type.model_fields
            ):
                # Empty message class
                output_str = "google.protobuf.Empty"
                uses_empty = True
            else:
                output_str = (
                    f"stream {output_msg_type.__name__}"
                    if output_is_stream
                    else output_msg_type.__name__
                )

            service_rpc_definitions.append(
                f"rpc {method_name} ({input_str}) returns ({output_str});"
            )

        # Create service definition
        service_def_lines: list[str] = []
        if service_comment:
            service_def_lines.append(service_comment)
        service_def_lines.append(f"service {service_name} {{")
        service_def_lines.extend([f"    {line}" for line in service_rpc_definitions])
        service_def_lines.append("}")
        service_def_lines.append("")

        all_service_definitions.extend(service_def_lines)

    # Build imports
    imports: list[str] = []
    if uses_timestamp:
        imports.append('import "google/protobuf/timestamp.proto";')
    if uses_duration:
        imports.append('import "google/protobuf/duration.proto";')
    if uses_empty:
        imports.append('import "google/protobuf/empty.proto";')

    import_block = "\n".join(imports)
    if import_block:
        import_block += "\n"

    # Combine everything
    service_defs = "\n".join(all_service_definitions)
    type_defs = "\n".join(all_type_definitions)
    proto_definition = f"""syntax = "proto3";

package {package_name};

{import_block}{service_defs}
{type_defs}
"""
    return proto_definition


def get_combined_proto_filename() -> str:
    """Get the combined proto filename."""
    return os.getenv("PYDANTIC_RPC_COMBINED_PROTO_FILENAME", "combined_services.proto")


def generate_combined_descriptor_set(
    *services: object, output_path: Path | None = None
) -> bytes:
    """Generate a combined protobuf descriptor set from multiple services."""
    filename = get_combined_proto_filename()

    if output_path is None:
        output_path = get_proto_path(filename)

    # Generate combined proto file
    combined_proto = generate_combined_proto(*services)
    proto_file_path = get_proto_path(filename)

    with proto_file_path.open(mode="w", encoding="utf-8") as f:
        _ = f.write(combined_proto)

    # Generate descriptor set using protoc
    out_str = str(proto_file_path.parent)
    well_known_path = os.path.join(os.path.dirname(grpc_tools.__file__), "_proto")
    args = [
        "protoc",
        f"-I{out_str}",
        f"-I{well_known_path}",
        f"--descriptor_set_out={output_path}",
        "--include_imports",
        proto_file_path.name,
    ]

    current_dir = os.getcwd()
    os.chdir(out_str)
    try:
        if protoc.main(args) != 0:
            raise RuntimeError("Failed to generate combined descriptor set")
    finally:
        os.chdir(current_dir)

    # Read and return the descriptor set
    with open(output_path, "rb") as f:
        descriptor_data = f.read()

    return descriptor_data


###############################################################################
# 4. Server Implementations
###############################################################################


class Server:
    """A simple gRPC server that uses ThreadPoolExecutor for concurrency."""

    def __init__(
        self,
        service: Optional[object] = None,
        port: int = 50051,
        package_name: str = "",
        max_workers: int = 8,
        tls: Optional["GrpcTLSConfig"] = None,
        interceptors: Optional[Sequence[grpc.ServerInterceptor]] = None,
        handlers: Optional[Sequence[grpc.GenericRpcHandler]] = None,
        options: Optional[Sequence[Tuple[str, Any]]] = None,
        maximum_concurrent_rpcs: Optional[int] = None,
        compression: Optional[grpc.Compression] = None,
    ) -> None:
        self._server: grpc.Server = grpc.server(
            futures.ThreadPoolExecutor(max_workers),
            handlers=handlers,
            interceptors=interceptors,
            options=options,
            maximum_concurrent_rpcs=maximum_concurrent_rpcs,
            compression=compression,
        )
        self._service_names: list[str] = []
        self._package_name: str = package_name
        self._port: int = port
        self._tls_config = tls
        self._initial_service = service

    def set_package_name(self, package_name: str):
        """Set the package name for .proto generation."""
        self._package_name = package_name

    def set_port(self, port: int):
        """Set the port number for the gRPC server."""
        self._port = port

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the service implementation."""
        pb2_grpc_module, pb2_module = generate_and_compile_proto(obj, package_name) or (
            None,
            None,
        )
        self.mount_using_pb2_modules(pb2_grpc_module, pb2_module, obj)

    def mount_using_pb2_modules(
        self, pb2_grpc_module: Any, pb2_module: Any, obj: object
    ):
        """Connect the compiled gRPC modules with the service implementation."""
        concreteServiceClass = connect_obj_with_stub(pb2_grpc_module, pb2_module, obj)
        service_name = obj.__class__.__name__
        service_impl = concreteServiceClass()
        getattr(pb2_grpc_module, f"add_{service_name}Servicer_to_server")(
            service_impl, self._server
        )
        full_service_name = pb2_module.DESCRIPTOR.services_by_name[
            service_name
        ].full_name
        self._service_names.append(full_service_name)

    def run(self, *objs: object):
        """
        Mount multiple services and run the gRPC server with reflection and health check.
        Press Ctrl+C or send SIGTERM to stop.
        """
        # Mount initial service if provided
        if self._initial_service:
            self.mount(self._initial_service, self._package_name)

        # Mount additional services
        for obj in objs:
            self.mount(obj, self._package_name)

        SERVICE_NAMES = (
            health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
            reflection.SERVICE_NAME,
            *self._service_names,
        )
        health_servicer = HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, self._server)
        reflection.enable_server_reflection(SERVICE_NAMES, self._server)

        if self._tls_config:
            # Use secure port with TLS
            credentials = self._tls_config.to_server_credentials()
            self._server.add_secure_port(f"[::]:{self._port}", credentials)
            print(f"gRPC server starting with TLS on port {self._port}...")
        else:
            # Use insecure port
            self._server.add_insecure_port(f"[::]:{self._port}")
            print(f"gRPC server starting on port {self._port}...")

        self._server.start()

        def handle_signal(signum: signal.Signals, frame: Any):
            _ = signum
            _ = frame
            print("Received shutdown signal...")
            self._server.stop(grace=10)
            print("gRPC server shutdown.")
            sys.exit(0)

        _ = signal.signal(signal.SIGINT, handle_signal)  # pyright:ignore[reportArgumentType]
        _ = signal.signal(signal.SIGTERM, handle_signal)  # pyright:ignore[reportArgumentType]

        print("gRPC server is running...")
        while True:
            time.sleep(86400)


class AsyncIOServer:
    """An async gRPC server using asyncio."""

    def __init__(
        self,
        service: Optional[object] = None,
        port: int = 50051,
        package_name: str = "",
        tls: Optional["GrpcTLSConfig"] = None,
        interceptors: Optional[Sequence[grpc.ServerInterceptor]] = None,
        migration_thread_pool: Optional[Executor] = None,
        handlers: Optional[Sequence[grpc.GenericRpcHandler]] = None,
        options: Optional[Sequence[Tuple[str, Any]]] = None,
        maximum_concurrent_rpcs: Optional[int] = None,
        compression: Optional[grpc.Compression] = None,
    ) -> None:
        self._server: grpc.aio.Server = grpc.aio.server(
            migration_thread_pool=migration_thread_pool,
            handlers=handlers,
            interceptors=interceptors,
            options=options,
            maximum_concurrent_rpcs=maximum_concurrent_rpcs,
            compression=compression,
        )
        self._service_names: list[str] = []
        self._package_name: str = package_name
        self._port: int = port
        self._tls_config = tls
        self._initial_service = service

    def set_package_name(self, package_name: str):
        """Set the package name for .proto generation."""
        self._package_name = package_name

    def set_port(self, port: int):
        """Set the port number for the async gRPC server."""
        self._port = port

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the service implementation (async)."""
        pb2_grpc_module, pb2_module = generate_and_compile_proto(obj, package_name) or (
            None,
            None,
        )
        self.mount_using_pb2_modules(pb2_grpc_module, pb2_module, obj)

    def mount_using_pb2_modules(
        self, pb2_grpc_module: Any, pb2_module: Any, obj: object
    ):
        """Connect the compiled gRPC modules with the async service implementation."""
        concreteServiceClass = connect_obj_with_stub_async(
            pb2_grpc_module, pb2_module, obj
        )
        service_name = obj.__class__.__name__
        service_impl = concreteServiceClass()
        getattr(pb2_grpc_module, f"add_{service_name}Servicer_to_server")(
            service_impl, self._server
        )
        full_service_name = pb2_module.DESCRIPTOR.services_by_name[
            service_name
        ].full_name
        self._service_names.append(full_service_name)

    async def run(self, *objs: object):
        """
        Mount multiple async services and run the gRPC server with reflection and health check.
        Press Ctrl+C or send SIGTERM to stop.
        """
        # Mount initial service if provided
        if self._initial_service:
            self.mount(self._initial_service, self._package_name)

        # Mount additional services
        for obj in objs:
            self.mount(obj, self._package_name)

        SERVICE_NAMES = (
            health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
            reflection.SERVICE_NAME,
            *self._service_names,
        )
        health_servicer = HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, self._server)
        reflection.enable_server_reflection(SERVICE_NAMES, self._server)

        if self._tls_config:
            # Use secure port with TLS
            credentials = self._tls_config.to_server_credentials()
            _ = self._server.add_secure_port(f"[::]:{self._port}", credentials)
            print(f"gRPC server starting with TLS on port {self._port}...")
        else:
            # Use insecure port
            _ = self._server.add_insecure_port(f"[::]:{self._port}")
            print(f"gRPC server starting on port {self._port}...")

        await self._server.start()

        shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown(signum: signal.Signals, frame: Any):
            _ = signum
            _ = frame
            print("Received shutdown signal...")
            loop.call_soon_threadsafe(shutdown_event.set)

        for s in [signal.SIGTERM, signal.SIGINT]:
            _ = signal.signal(s, shutdown)  # pyright:ignore[reportArgumentType]

        print("gRPC server is running...")
        _ = await shutdown_event.wait()
        await self._server.stop(10)
        print("gRPC server shutdown.")

    async def stop(self, grace: float = 10.0):
        """Stop the gRPC server gracefully."""
        await self._server.stop(grace)


def get_connect_python_asgi_app_class(connect_python_module: Any, service_name: str):
    """Get the ASGI application class from connect-python module."""
    return getattr(connect_python_module, f"{service_name}ASGIApplication")


def get_connect_python_wsgi_app_class(connect_python_module: Any, service_name: str):
    """Get the WSGI application class from connect-python module."""
    return getattr(connect_python_module, f"{service_name}WSGIApplication")


class ASGIApp:
    """
    An ASGI-compatible application that can serve Connect-RPC via connect-python.
    """

    def __init__(self, service: Optional[object] = None, package_name: str = ""):
        self._services: list[tuple[Any, str]] = []  # List of (app, path) tuples
        self._service_names: list[str] = []
        self._package_name: str = package_name
        self._initial_service = service

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the async service implementation."""
        connect_python_module, pb2_module = (
            generate_and_compile_proto_using_connect_python(obj, package_name)
        )
        self.mount_using_pb2_modules(connect_python_module, pb2_module, obj)

    def mount_using_pb2_modules(
        self, connect_python_module: Any, pb2_module: Any, obj: object
    ):
        """Connect the compiled connect-python and pb2 modules with the async service implementation."""
        concreteServiceClass = connect_obj_with_stub_async_connect_python(
            connect_python_module, pb2_module, obj
        )
        service_name = obj.__class__.__name__
        service_impl = concreteServiceClass()

        # Get the service-specific ASGI application class
        app_class = get_connect_python_asgi_app_class(
            connect_python_module, service_name
        )
        app = app_class(service=service_impl)

        # Store the app and its path for routing
        self._services.append((app, app.path))

        full_service_name = pb2_module.DESCRIPTOR.services_by_name[
            service_name
        ].full_name
        self._service_names.append(full_service_name)

    def mount_objs(self, *objs: object):
        """Mount multiple service objects into this ASGI app."""
        # Mount initial service if provided
        if self._initial_service:
            self.mount(self._initial_service, self._package_name)

        # Mount additional services
        for obj in objs:
            self.mount(obj, self._package_name)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ):
        """ASGI entry point with routing for multiple services."""
        # Mount initial service on first call if not already mounted
        if self._initial_service and not self._services:
            self.mount(self._initial_service, self._package_name)

        if scope["type"] != "http":
            await send({"type": "http.response.start", "status": 404})
            await send({"type": "http.response.body", "body": b"Not Found"})
            return

        path = scope.get("path", "")

        # Route to the appropriate service based on path
        for app, service_path in self._services:
            if path.startswith(service_path):
                return await app(scope, receive, send)

        # If only one service is mounted, use it as default
        if len(self._services) == 1:
            return await self._services[0][0](scope, receive, send)

        # No matching service found
        await send({"type": "http.response.start", "status": 404})
        await send({"type": "http.response.body", "body": b"Not Found"})


class WSGIApp:
    """
    A WSGI-compatible application that can serve Connect-RPC via connect-python.
    """

    def __init__(self, service: Optional[object] = None, package_name: str = ""):
        self._services: list[tuple[Any, str]] = []  # List of (app, path) tuples
        self._service_names: list[str] = []
        self._package_name: str = package_name
        self._initial_service = service

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the sync service implementation."""
        connect_python_module, pb2_module = (
            generate_and_compile_proto_using_connect_python(obj, package_name)
        )
        self.mount_using_pb2_modules(connect_python_module, pb2_module, obj)

    def mount_using_pb2_modules(
        self, connect_python_module: Any, pb2_module: Any, obj: object
    ):
        """Connect the compiled connect-python and pb2 modules with the sync service implementation."""
        concreteServiceClass = connect_obj_with_stub_connect_python(
            connect_python_module, pb2_module, obj
        )
        service_name = obj.__class__.__name__
        service_impl = concreteServiceClass()

        # Get the service-specific WSGI application class
        app_class = get_connect_python_wsgi_app_class(
            connect_python_module, service_name
        )
        app = app_class(service=service_impl)

        # Store the app and its path for routing
        self._services.append((app, app.path))

        full_service_name = pb2_module.DESCRIPTOR.services_by_name[
            service_name
        ].full_name
        self._service_names.append(full_service_name)

    def mount_objs(self, *objs: object):
        """Mount multiple service objects into this WSGI app."""
        # Mount initial service if provided
        if self._initial_service:
            self.mount(self._initial_service, self._package_name)

        # Mount additional services
        for obj in objs:
            self.mount(obj, self._package_name)

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[
            [str, list[tuple[str, str]]], Callable[[bytes], object]
        ],
    ) -> Iterable[bytes]:
        """WSGI entry point with routing for multiple services."""
        # Mount initial service on first call if not already mounted
        if self._initial_service and not self._services:
            self.mount(self._initial_service, self._package_name)

        path = environ.get("PATH_INFO", "")

        # Route to the appropriate service based on path
        for app, service_path in self._services:
            if path.startswith(service_path):
                return app(environ, start_response)

        # If only one service is mounted, use it as default
        if len(self._services) == 1:
            return self._services[0][0](environ, start_response)

        # No matching service found
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Not Found"]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate and compile proto files.")
    _ = parser.add_argument(
        "py_file", type=str, help="The Python file containing the service class."
    )
    _ = parser.add_argument(
        "class_name", type=str, help="The name of the service class."
    )
    args = parser.parse_args()

    module_name = os.path.splitext(basename(args.py_file))[0]
    module = importlib.import_module(module_name)
    klass = getattr(module, args.class_name)
    _ = generate_and_compile_proto(klass())


if __name__ == "__main__":
    main()
