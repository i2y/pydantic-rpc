import asyncio
import datetime
import enum
import importlib.util
import inspect
import os
import signal
import sys
import time
import types
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent import futures
from posixpath import basename
from typing import (
    Any,
    Type,
    TypeAlias,
    Union,
    cast,
    get_args,
    get_origin,
)
from pathlib import Path

import annotated_types
import grpc
import grpc_tools
from grpc_tools import protoc
from connecpy.asgi import ConnecpyASGIApp as ConnecpyASGI
from connecpy.errors import Errors
from connecpy.wsgi import ConnecpyWSGIApp as ConnecpyWSGI

# Protobuf Python modules for Timestamp, Duration (requires protobuf / grpcio)
from google.protobuf import duration_pb2, timestamp_pb2
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection
from pydantic import BaseModel, ValidationError
from sonora.asgi import grpcASGI
from sonora.wsgi import grpcWSGI
from grpc_health.v1.health import HealthServicer

###############################################################################
# 1. Message definitions & converter extensions
#    (datetime.datetime <-> google.protobuf.Timestamp)
#    (datetime.timedelta <-> google.protobuf.Duration)
###############################################################################


Message: TypeAlias = BaseModel


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


def generate_converter(annotation: Type[Any] | None) -> Callable[[Any], Any]:
    """
    Returns a converter function to convert protobuf types to Python types.
    This is used primarily when handling incoming requests.
    """
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
        return generate_message_converter(annotation)

    # For union types or other unsupported cases, just return the value as-is.
    return primitiveProtoValueToPythonValue


def generate_message_converter(arg_type: Type[Message]) -> Callable[[Any], Message]:
    """Return a converter function for protobuf -> Python Message."""

    fields = arg_type.model_fields
    converters = {
        field: generate_converter(field_type.annotation)  # type: ignore
        for field, field_type in fields.items()
    }

    def converter(request: Any) -> Message:
        rdict = {}
        for field in fields.keys():
            rdict[field] = converters[field](getattr(request, field))
        return arg_type(**rdict)

    return converter


def python_value_to_proto_value(field_type: Type[Any], value: Any) -> Any:
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
        converter = generate_message_converter(arg_type)
        response_type = sig.return_annotation
        param_count = len(sig.parameters)

        if param_count == 1:

            def stub_method(
                self: object,
                request: Any,
                context: Any,
                *,
                original: Callable[..., Message] = method,
            ) -> Any:
                _ = self
                try:
                    arg = converter(request)
                    resp_obj = original(arg)
                    return convert_python_message_to_proto(
                        resp_obj, response_type, pb2_module
                    )
                except ValidationError as e:
                    return context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
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
                    arg = converter(request)
                    resp_obj = original(arg, context)
                    return convert_python_message_to_proto(
                        resp_obj, response_type, pb2_module
                    )
                except ValidationError as e:
                    return context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
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
        method: Callable[..., AsyncIterator[Message] | Awaitable[Message]],
    ) -> Callable[[object, Any, Any], Any]:
        sig = inspect.signature(method)
        arg_type = get_request_arg_type(sig)
        converter = generate_message_converter(arg_type)
        response_type = sig.return_annotation
        size_of_parameters = len(sig.parameters)

        if is_stream_type(response_type):
            method = cast(Callable[..., AsyncIterator[Message]], method)
            item_type = get_args(response_type)[0]
            match size_of_parameters:
                case 1:

                    async def stub_method_stream1(
                        self: object,
                        request: Any,
                        context: Any,
                        method: Callable[..., AsyncIterator[Message]] = method,
                    ) -> AsyncIterator[Any]:
                        _ = self
                        try:
                            arg = converter(request)
                            async for resp_obj in method(arg):
                                yield convert_python_message_to_proto(
                                    resp_obj, item_type, pb2_module
                                )
                        except ValidationError as e:
                            await context.abort(
                                grpc.StatusCode.INVALID_ARGUMENT, str(e)
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                    return stub_method_stream1
                case 2:

                    async def stub_method_stream2(
                        self: object,
                        request: Any,
                        context: Any,
                        method: Callable[..., AsyncIterator[Message]] = method,
                    ) -> AsyncIterator[Any]:
                        _ = self
                        try:
                            arg = converter(request)
                            async for resp_obj in method(arg, context):
                                yield convert_python_message_to_proto(
                                    resp_obj, item_type, pb2_module
                                )
                        except ValidationError as e:
                            await context.abort(
                                grpc.StatusCode.INVALID_ARGUMENT, str(e)
                            )
                        except Exception as e:
                            await context.abort(grpc.StatusCode.INTERNAL, str(e))

                    return stub_method_stream2
                case _:
                    raise Exception("Method must have exactly one or two parameters")

        match size_of_parameters:
            case 1:
                method = cast(Callable[..., Awaitable[Message]], method)

                async def stub_method1(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Awaitable[Message]] = method,
                ) -> Any:
                    _ = self
                    try:
                        arg = converter(request)
                        resp_obj = await method(arg)
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                    except ValidationError as e:
                        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
                    except Exception as e:
                        await context.abort(grpc.StatusCode.INTERNAL, str(e))

                return stub_method1

            case 2:
                method = cast(Callable[..., Awaitable[Message]], method)

                async def stub_method2(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Awaitable[Message]] = method,
                ) -> Any:
                    _ = self
                    try:
                        arg = converter(request)
                        resp_obj = await method(arg, context)
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                    except ValidationError as e:
                        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
                    except Exception as e:
                        await context.abort(grpc.StatusCode.INTERNAL, str(e))

                return stub_method2

            case _:
                raise Exception("Method must have exactly one or two parameters")

    for method_name, method in get_rpc_methods(obj):
        if method.__name__.startswith("_"):
            continue

        a_method = implement_stub_method(method)
        setattr(ConcreteServiceClass, method_name, a_method)

    return ConcreteServiceClass


def connect_obj_with_stub_connecpy(
    connecpy_module: Any, pb2_module: Any, obj: object
) -> type:
    """
    Connect a Python service object to a Connecpy stub.
    """
    service_class = obj.__class__
    stub_class_name = service_class.__name__
    stub_class = getattr(connecpy_module, stub_class_name)

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
            case 1:

                def stub_method1(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Message] = method,
                ) -> Any:
                    _ = self
                    try:
                        arg = converter(request)
                        resp_obj = method(arg)
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                    except ValidationError as e:
                        return context.abort(Errors.InvalidArgument, str(e))
                    except Exception as e:
                        return context.abort(Errors.Internal, str(e))

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
                        arg = converter(request)
                        resp_obj = method(arg, context)
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                    except ValidationError as e:
                        return context.abort(Errors.InvalidArgument, str(e))
                    except Exception as e:
                        return context.abort(Errors.Internal, str(e))

                return stub_method2

            case _:
                raise Exception("Method must have exactly one or two parameters")

    for method_name, method in get_rpc_methods(obj):
        if method.__name__.startswith("_"):
            continue
        a_method = implement_stub_method(method)
        setattr(ConcreteServiceClass, method_name, a_method)

    return ConcreteServiceClass


def connect_obj_with_stub_async_connecpy(
    connecpy_module: Any, pb2_module: Any, obj: object
) -> type:
    """
    Connect a Python service object to a Connecpy stub for async methods.
    """
    service_class = obj.__class__
    stub_class_name = service_class.__name__
    stub_class = getattr(connecpy_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        pass

    def implement_stub_method(
        method: Callable[..., Awaitable[Message]],
    ) -> Callable[[object, Any, Any], Any]:
        sig = inspect.signature(method)
        arg_type = get_request_arg_type(sig)
        converter = generate_message_converter(arg_type)
        response_type = sig.return_annotation
        size_of_parameters = len(sig.parameters)

        match size_of_parameters:
            case 1:

                async def stub_method1(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Awaitable[Message]] = method,
                ) -> Any:
                    _ = self
                    try:
                        arg = converter(request)
                        resp_obj = await method(arg)
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                    except ValidationError as e:
                        await context.abort(Errors.InvalidArgument, str(e))
                    except Exception as e:
                        await context.abort(Errors.Internal, str(e))

                return stub_method1

            case 2:

                async def stub_method2(
                    self: object,
                    request: Any,
                    context: Any,
                    method: Callable[..., Awaitable[Message]] = method,
                ) -> Any:
                    _ = self
                    try:
                        arg = converter(request)
                        resp_obj = await method(arg, context)
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                    except ValidationError as e:
                        await context.abort(Errors.InvalidArgument, str(e))
                    except Exception as e:
                        await context.abort(Errors.Internal, str(e))

                return stub_method2

            case _:
                raise Exception("Method must have exactly one or two parameters")

    for method_name, method in get_rpc_methods(obj):
        if method.__name__.startswith("_"):
            continue
        if not asyncio.iscoroutinefunction(method):
            raise Exception("Method must be async", method_name)
        a_method = implement_stub_method(method)
        setattr(ConcreteServiceClass, method_name, a_method)

    return ConcreteServiceClass


def python_value_to_proto_oneof(
    field_name: str, field_type: Type[Any], value: Any, pb2_module: Any
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
    converted_value = python_value_to_proto(actual_type, value, pb2_module)
    return oneof_field_name, converted_value


def convert_python_message_to_proto(
    py_msg: Message, msg_type: Type[Message], pb2_module: Any
) -> object:
    """
    Convert a Python Pydantic Message instance to a protobuf message instance.
    Used for constructing a response.
    """
    field_dict = {}
    for name, field_info in msg_type.model_fields.items():
        value = getattr(py_msg, name)
        if value is None:
            continue

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
                ) = python_value_to_proto_oneof(name, field_type, value, pb2_module)
                field_dict[oneof_field_name] = converted_value
                continue

        # For regular and Optional fields that have a value.
        if field_type is not None:
            field_dict[name] = python_value_to_proto(field_type, value, pb2_module)

    # Retrieve the appropriate protobuf class dynamically
    proto_class = getattr(pb2_module, msg_type.__name__)
    return proto_class(**field_dict)


def python_value_to_proto(field_type: Type[Any], value: Any, pb2_module: Any) -> Any:
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
        inner_type = get_args(field_type)[0]  # type: ignore
        return [python_value_to_proto(inner_type, v, pb2_module) for v in value]

    # If dict
    if origin is dict:
        key_type, val_type = get_args(field_type)  # type: ignore
        return {
            python_value_to_proto(key_type, k, pb2_module): python_value_to_proto(
                val_type, v, pb2_module
            )
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
            return python_value_to_proto(non_none_args[0], value, pb2_module)
        return None  # Should not be reached if value is not None

    # If Message
    if inspect.isclass(field_type) and issubclass(field_type, Message):
        return convert_python_message_to_proto(value, field_type, pb2_module)

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
    elif field_type is type(None):
        return [field_type]
    else:
        return [field_type]


def protobuf_type_mapping(python_type: Any) -> str | None:
    """
    Map a Python type to a protobuf type name/class.
    Includes support for Timestamp and Duration.
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
    index = 1

    for field_name, field_info in pydantic_fields.items():
        field_type = field_info.annotation
        if field_type is None:
            raise Exception(f"Field {field_name} has no type annotation.")

        is_optional = False
        # Handle Union types, which may be Optional or a oneof.
        if is_union_type(field_type):
            union_args = flatten_union(field_type)
            none_type = type(None)

            if none_type in union_args:
                is_optional = True
                union_args = [arg for arg in union_args if arg is not none_type]

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

        if is_enum_type(field_type):
            if field_type not in done_enums:
                refs.append(field_type)
        elif inspect.isclass(field_type) and issubclass(field_type, Message):
            if field_type not in done_messages:
                refs.append(field_type)

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
                            "//   minimum length of " + str(metadata_item.min_len)
                        )
                    case annotated_types.MaxLen:
                        fields.append(
                            "//   maximum length of " + str(metadata_item.max_len)
                        )
                    case _:
                        fields.append("//   " + str(metadata_item))

        field_definition = f"{proto_typename} {field_name} = {index};"
        if is_optional:
            field_definition = f"optional {field_definition}"

        fields.append(field_definition)
        index += 1

    msg_def = f"message {message_type.__name__} {{\n{indent_lines(fields)}\n}}"
    return msg_def, refs


def is_stream_type(annotation: Any) -> bool:
    return get_origin(annotation) is AsyncIterator


def is_generic_alias(annotation: Any) -> bool:
    return get_origin(annotation) is not None


def generate_proto(obj: object, package_name: str = "") -> str:
    """
    Generate a .proto definition from a service class.
    Automatically handles Timestamp and Duration usage.
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

    def check_and_set_well_known_types(py_type: Any):
        nonlocal uses_timestamp, uses_duration
        if py_type == datetime.datetime:
            uses_timestamp = True
        if py_type == datetime.timedelta:
            uses_duration = True

    for method_name, method in get_rpc_methods(obj):
        if method.__name__.startswith("_"):
            continue

        method_sig = inspect.signature(method)
        request_type = get_request_arg_type(method_sig)
        response_type = method_sig.return_annotation

        # Recursively generate message definitions
        message_types = [request_type, response_type]
        while message_types:
            mt = message_types.pop()
            if mt in done_messages:
                continue
            done_messages.add(mt)

            if is_stream_type(mt):
                item_type = get_args(mt)[0]
                message_types.append(item_type)
                continue

            for _, field_info in mt.model_fields.items():
                t = field_info.annotation
                if is_union_type(t):
                    for sub_t in flatten_union(t):
                        check_and_set_well_known_types(sub_t)
                else:
                    check_and_set_well_known_types(t)

            msg_def, refs = generate_message_definition(mt, done_enums, done_messages)
            mt_doc = inspect.getdoc(mt)
            if mt_doc:
                for comment_line in comment_out(mt_doc):
                    all_type_definitions.append(comment_line)

            all_type_definitions.append(msg_def)
            all_type_definitions.append("")

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

        if is_stream_type(response_type):
            item_type = get_args(response_type)[0]
            rpc_definitions.append(
                f"rpc {method_name} ({request_type.__name__}) returns (stream {item_type.__name__});"
            )
        else:
            rpc_definitions.append(
                f"rpc {method_name} ({request_type.__name__}) returns ({response_type.__name__});"
            )

    if not package_name:
        if service_name.endswith("Service"):
            package_name = service_name[: -len("Service")]
        else:
            package_name = service_name
        package_name = package_name.lower() + ".v1"

    imports: list[str] = []
    if uses_timestamp:
        imports.append('import "google/protobuf/timestamp.proto";')
    if uses_duration:
        imports.append('import "google/protobuf/duration.proto";')

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
    try:
        rel_input = str(proto_path.relative_to(out_dir.parent.parent))
        root_dir = out_dir.parent.parent
    except ValueError:
        rel_input = proto_path.name
        root_dir = out_dir
    args = [
        f"-I{str(root_dir)}",
        f"-I{well_known_path}",
        f"--grpc_python_out={out_str}",
        rel_input,
    ]
    current_dir = os.getcwd()
    os.chdir(str(root_dir))
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


def generate_connecpy_code(proto_path: Path) -> types.ModuleType | None:
    """
    Run protoc with the Connecpy plugin to generate Python Connecpy code from proto_path.
    Writes foo_connecpy.py next to proto_path, then imports and returns that module.
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
    try:
        rel_input = str(proto_path.relative_to(out_dir.parent.parent))
        root_dir = out_dir.parent.parent
    except ValueError:
        rel_input = proto_path.name
        root_dir = out_dir
    args = [
        f"-I{str(root_dir)}",
        f"-I{well_known_path}",
        f"--connecpy_out={out_str}",
        rel_input,
    ]
    current_dir = os.getcwd()
    os.chdir(str(root_dir))
    try:
        if protoc.main(args) != 0:
            return None
    finally:
        os.chdir(current_dir)

    # 4) Locate the generated file
    base_name = proto_path.stem  # "foo"
    generated_filename = f"{base_name}_connecpy.py"  # "foo_connecpy.py"
    generated_filepath = out_dir / generated_filename

    # 5) Add out_dir to sys.path so we can import by filename
    if out_str not in sys.path:
        sys.path.append(out_str)

    # 6) Load and return the module
    spec = importlib.util.spec_from_file_location(
        base_name + "_connecpy", str(generated_filepath)
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
    try:
        rel_input = str(proto_path.relative_to(out_dir.parent.parent))
        root_dir = out_dir.parent.parent
    except ValueError:
        rel_input = proto_path.name
        root_dir = out_dir
    args = [
        f"-I{str(root_dir)}",
        f"-I{well_known_path}",
        f"--python_out={out_str}",
        f"--pyi_out={out_str}",
        rel_input,
    ]

    current_dir = os.getcwd()
    os.chdir(str(root_dir))
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
    """Return the type annotation of the first parameter (request) of a method."""
    num_of_params = len(sig.parameters)
    if not (num_of_params == 1 or num_of_params == 2):
        raise Exception("Method must have exactly one or two parameters")
    return tuple(sig.parameters.values())[0].annotation


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


def generate_and_compile_proto(
    obj: object,
    package_name: str = "",
    existing_proto_path: Path | None = None,
) -> tuple[Any, Any] | None:
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


def generate_and_compile_proto_using_connecpy(
    obj: object,
    package_name: str = "",
    existing_proto_path: Path | None = None,
) -> tuple[Any, Any]:
    if is_skip_generation():
        import importlib

        pb2_module = None
        connecpy_module = None

        try:
            pb2_module = importlib.import_module(
                f"{obj.__class__.__name__.lower()}_pb2"
            )
        except ImportError:
            pass

        try:
            connecpy_module = importlib.import_module(
                f"{obj.__class__.__name__.lower()}_connecpy"
            )
        except ImportError:
            pass

        if connecpy_module is not None and pb2_module is not None:
            return connecpy_module, pb2_module

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

    gen_connecpy = generate_connecpy_code(proto_file_path)
    if gen_connecpy is None:
        raise Exception("Generating Connecpy code")
    return gen_connecpy, gen_pb


###############################################################################
# 4. Server Implementations
###############################################################################


class Server:
    """A simple gRPC server that uses ThreadPoolExecutor for concurrency."""

    def __init__(self, max_workers: int = 8, *interceptors: Any) -> None:
        self._server: grpc.Server = grpc.server(
            futures.ThreadPoolExecutor(max_workers), interceptors=interceptors
        )
        self._service_names: list[str] = []
        self._package_name: str = ""
        self._port: int = 50051

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

        self._server.add_insecure_port(f"[::]:{self._port}")
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

    def __init__(self, *interceptors: grpc.ServerInterceptor) -> None:
        self._server: grpc.aio.Server = grpc.aio.server(interceptors=interceptors)
        self._service_names: list[str] = []
        self._package_name: str = ""
        self._port: int = 50051

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

        _ = self._server.add_insecure_port(f"[::]:{self._port}")
        await self._server.start()

        shutdown_event = asyncio.Event()

        def shutdown(signum: signal.Signals, frame: Any):
            _ = signum
            _ = frame
            print("Received shutdown signal...")
            shutdown_event.set()

        for s in [signal.SIGTERM, signal.SIGINT]:
            _ = signal.signal(s, shutdown)  # pyright:ignore[reportArgumentType]

        print("gRPC server is running...")
        _ = await shutdown_event.wait()
        await self._server.stop(10)
        print("gRPC server shutdown.")


class WSGIApp:
    """
    A WSGI-compatible application that can serve gRPC via sonora's grpcWSGI.
    Useful for embedding gRPC within an existing WSGI stack.
    """

    def __init__(self, app: Any):
        self._app: grpcWSGI = grpcWSGI(app)
        self._service_names: list[str] = []
        self._package_name: str = ""

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
            service_impl, self._app
        )
        full_service_name = pb2_module.DESCRIPTOR.services_by_name[
            service_name
        ].full_name
        self._service_names.append(full_service_name)

    def mount_objs(self, *objs: object):
        """Mount multiple service objects into this WSGI app."""
        for obj in objs:
            self.mount(obj, self._package_name)

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[[str, list[tuple[str, str]]], None],
    ) -> Any:
        """WSGI entry point."""
        return self._app(environ, start_response)


class ASGIApp:
    """
    An ASGI-compatible application that can serve gRPC via sonora's grpcASGI.
    Useful for embedding gRPC within an existing ASGI stack.
    """

    def __init__(self, app: Any):
        self._app: grpcASGI = grpcASGI(app)
        self._service_names: list[str] = []
        self._package_name: str = ""

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the async service implementation."""
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
            service_impl, self._app
        )
        full_service_name = pb2_module.DESCRIPTOR.services_by_name[
            service_name
        ].full_name
        self._service_names.append(full_service_name)

    def mount_objs(self, *objs: object):
        """Mount multiple service objects into this ASGI app."""
        for obj in objs:
            self.mount(obj, self._package_name)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> Any:
        """ASGI entry point."""
        _ = await self._app(scope, receive, send)


def get_connecpy_server_class(connecpy_module: Any, service_name: str):
    return getattr(connecpy_module, f"{service_name}Server")


class ConnecpyASGIApp:
    """
    An ASGI-compatible application that can serve Connect-RPC via Connecpy's ConnecpyASGIApp.
    """

    def __init__(self):
        self._app: ConnecpyASGI = ConnecpyASGI()
        self._service_names: list[str] = []
        self._package_name: str = ""

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the async service implementation."""
        connecpy_module, pb2_module = generate_and_compile_proto_using_connecpy(
            obj, package_name
        )
        self.mount_using_pb2_modules(connecpy_module, pb2_module, obj)

    def mount_using_pb2_modules(
        self, connecpy_module: Any, pb2_module: Any, obj: object
    ):
        """Connect the compiled connecpy and pb2 modules with the async service implementation."""
        concreteServiceClass = connect_obj_with_stub_async_connecpy(
            connecpy_module, pb2_module, obj
        )
        service_name = obj.__class__.__name__
        service_impl = concreteServiceClass()
        connecpy_server = get_connecpy_server_class(connecpy_module, service_name)
        self._app.add_service(connecpy_server(service=service_impl))
        full_service_name = pb2_module.DESCRIPTOR.services_by_name[
            service_name
        ].full_name
        self._service_names.append(full_service_name)

    def mount_objs(self, *objs: object):
        """Mount multiple service objects into this ASGI app."""
        for obj in objs:
            self.mount(obj, self._package_name)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ):
        """ASGI entry point."""
        _ = await self._app(scope, receive, send)


class ConnecpyWSGIApp:
    """
    A WSGI-compatible application that can serve Connect-RPC via Connecpy's ConnecpyWSGIApp.
    """

    def __init__(self):
        self._app: ConnecpyWSGI = ConnecpyWSGI()
        self._service_names: list[str] = []
        self._package_name: str = ""

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the async service implementation."""
        connecpy_module, pb2_module = generate_and_compile_proto_using_connecpy(
            obj, package_name
        )
        self.mount_using_pb2_modules(connecpy_module, pb2_module, obj)

    def mount_using_pb2_modules(
        self, connecpy_module: Any, pb2_module: Any, obj: object
    ):
        """Connect the compiled connecpy and pb2 modules with the async service implementation."""
        concreteServiceClass = connect_obj_with_stub_connecpy(
            connecpy_module, pb2_module, obj
        )
        service_name = obj.__class__.__name__
        service_impl = concreteServiceClass()
        connecpy_server = get_connecpy_server_class(connecpy_module, service_name)
        self._app.add_service(connecpy_server(service=service_impl))
        full_service_name = pb2_module.DESCRIPTOR.services_by_name[
            service_name
        ].full_name
        self._service_names.append(full_service_name)

    def mount_objs(self, *objs: object):
        """Mount multiple service objects into this WSGI app."""
        for obj in objs:
            self.mount(obj, self._package_name)

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[[str, list[tuple[str, str]]], None],
    ) -> Any:
        """WSGI entry point."""
        return self._app(environ, start_response)


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
