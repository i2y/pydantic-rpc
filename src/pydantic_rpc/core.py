import annotated_types
import asyncio
import enum
import importlib.util
import inspect
import os
import signal
import sys
import time
import types
import datetime
from concurrent import futures
from posixpath import basename
from typing import (
    Callable,
    Type,
    get_args,
    get_origin,
    Union,
    TypeAlias,
)
from collections.abc import AsyncIterator

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_health.v1.health import HealthServicer
from grpc_reflection.v1alpha import reflection
from grpc_tools import protoc
from pydantic import BaseModel, ValidationError
from sonora.wsgi import grpcWSGI
from sonora.asgi import grpcASGI
from connecpy.asgi import ConnecpyASGIApp as ConnecpyASGI
from connecpy.errors import Errors
from connecpy.wsgi import ConnecpyWSGIApp as ConnecpyWSGI

# Protobuf Python modules for Timestamp, Duration (requires protobuf / grpcio)
from google.protobuf import timestamp_pb2, duration_pb2

###############################################################################
# 1. Message definitions & converter extensions
#    (datetime.datetime <-> google.protobuf.Timestamp)
#    (datetime.timedelta <-> google.protobuf.Duration)
###############################################################################


Message: TypeAlias = BaseModel


def primitiveProtoValueToPythonValue(value):
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


def generate_converter(annotation: Type) -> Callable:
    """
    Returns a converter function to convert protobuf types to Python types.
    This is used primarily when handling incoming requests.
    """
    # For primitive types
    if annotation in (int, str, bool, bytes, float):
        return primitiveProtoValueToPythonValue

    # For enum types
    if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):

        def enum_converter(value):
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

            def seq_converter(value):
                return [item_converter(v) for v in value]

            return seq_converter

        # For dict types
        if origin is dict:
            key_converter = generate_converter(get_args(annotation)[0])
            value_converter = generate_converter(get_args(annotation)[1])

            def dict_converter(value):
                return {key_converter(k): value_converter(v) for k, v in value.items()}

            return dict_converter

    # For Message classes
    if inspect.isclass(annotation) and issubclass(annotation, Message):
        return generate_message_converter(annotation)

    # For union types or other unsupported cases, just return the value as-is.
    return primitiveProtoValueToPythonValue


def generate_message_converter(arg_type: Type[Message]) -> Callable:
    """Return a converter function for protobuf -> Python Message."""
    if arg_type is None or not issubclass(arg_type, Message):
        raise TypeError("Request arg must be subclass of Message")

    fields = arg_type.model_fields
    converters = {
        field: generate_converter(field_type.annotation)  # type: ignore
        for field, field_type in fields.items()
    }

    def converter(request):
        rdict = {}
        for field in fields.keys():
            rdict[field] = converters[field](getattr(request, field))
        return arg_type(**rdict)

    return converter


def python_value_to_proto_value(field_type: Type, value):
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


def connect_obj_with_stub(pb2_grpc_module, pb2_module, service_obj: object) -> type:
    """
    Connect a Python service object to a gRPC stub, generating server methods.
    """
    service_class = service_obj.__class__
    stub_class_name = service_class.__name__ + "Servicer"
    stub_class = getattr(pb2_grpc_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        pass

    def implement_stub_method(method):
        # Analyze method signature.
        sig = inspect.signature(method)
        arg_type = get_request_arg_type(sig)
        # Convert request from protobuf to Python.
        converter = generate_message_converter(arg_type)

        response_type = sig.return_annotation
        size_of_parameters = len(sig.parameters)

        match size_of_parameters:
            case 1:

                def stub_method1(self, request, context, method=method):
                    try:
                        # Convert request to Python object
                        arg = converter(request)
                        # Invoke the actual method
                        resp_obj = method(arg)
                        # Convert the returned Python Message to a protobuf message
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                    except ValidationError as e:
                        return context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
                    except Exception as e:
                        return context.abort(grpc.StatusCode.INTERNAL, str(e))

                return stub_method1

            case 2:

                def stub_method2(self, request, context, method=method):
                    try:
                        arg = converter(request)
                        resp_obj = method(arg, context)
                        return convert_python_message_to_proto(
                            resp_obj, response_type, pb2_module
                        )
                    except ValidationError as e:
                        return context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
                    except Exception as e:
                        return context.abort(grpc.StatusCode.INTERNAL, str(e))

                return stub_method2

            case _:
                raise Exception("Method must have exactly one or two parameters")

    for method_name, method in get_rpc_methods(service_obj):
        if method.__name__.startswith("_"):
            continue

        a_method = implement_stub_method(method)
        setattr(ConcreteServiceClass, method_name, a_method)

    return ConcreteServiceClass


def connect_obj_with_stub_async(pb2_grpc_module, pb2_module, obj: object) -> type:
    """
    Connect a Python service object to a gRPC stub for async methods.
    """
    service_class = obj.__class__
    stub_class_name = service_class.__name__ + "Servicer"
    stub_class = getattr(pb2_grpc_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        pass

    def implement_stub_method(method):
        sig = inspect.signature(method)
        arg_type = get_request_arg_type(sig)
        converter = generate_message_converter(arg_type)
        response_type = sig.return_annotation
        size_of_parameters = len(sig.parameters)

        if is_stream_type(response_type):
            item_type = get_args(response_type)[0]
            match size_of_parameters:
                case 1:

                    async def stub_method_stream1(
                        self, request, context, method=method
                    ):
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
                        self, request, context, method=method
                    ):
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

                async def stub_method1(self, request, context, method=method):
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

                async def stub_method2(self, request, context, method=method):
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


def connect_obj_with_stub_connecpy(connecpy_module, pb2_module, obj: object) -> type:
    """
    Connect a Python service object to a Connecpy stub.
    """
    service_class = obj.__class__
    stub_class_name = service_class.__name__
    stub_class = getattr(connecpy_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        pass

    def implement_stub_method(method):
        sig = inspect.signature(method)
        arg_type = get_request_arg_type(sig)
        converter = generate_message_converter(arg_type)
        response_type = sig.return_annotation
        size_of_parameters = len(sig.parameters)

        match size_of_parameters:
            case 1:

                def stub_method1(self, request, context, method=method):
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

                def stub_method2(self, request, context, method=method):
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
    connecpy_module, pb2_module, obj: object
) -> type:
    """
    Connect a Python service object to a Connecpy stub for async methods.
    """
    service_class = obj.__class__
    stub_class_name = service_class.__name__
    stub_class = getattr(connecpy_module, stub_class_name)

    class ConcreteServiceClass(stub_class):
        pass

    def implement_stub_method(method):
        sig = inspect.signature(method)
        arg_type = get_request_arg_type(sig)
        converter = generate_message_converter(arg_type)
        response_type = sig.return_annotation
        size_of_parameters = len(sig.parameters)

        match size_of_parameters:
            case 1:

                async def stub_method1(self, request, context, method=method):
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

                async def stub_method2(self, request, context, method=method):
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


def convert_python_message_to_proto(
    py_msg: Message, msg_type: Type, pb2_module
) -> object:
    """
    Convert a Python Pydantic Message instance to a protobuf message instance.
    Used for constructing a response.
    """
    # Before calling something like pb2_module.AResponseMessage(...),
    # convert each field from Python to proto.
    field_dict = {}
    for name, field_info in msg_type.model_fields.items():
        value = getattr(py_msg, name)
        if value is None:
            field_dict[name] = None
            continue

        field_type = field_info.annotation
        field_dict[name] = python_value_to_proto(field_type, value, pb2_module)

    # Retrieve the appropriate protobuf class dynamically
    proto_class = getattr(pb2_module, msg_type.__name__)
    return proto_class(**field_dict)


def python_value_to_proto(field_type: Type, value, pb2_module):
    """
    Perform Python->protobuf type conversion for each field value.
    """
    import inspect
    import datetime

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

    # If union -> oneof
    if is_union_type(field_type):
        # Flatten union and check which type matches. If matched, return converted value.
        for sub_type in flatten_union(field_type):
            if sub_type == datetime.datetime and isinstance(value, datetime.datetime):
                return python_to_timestamp(value)
            if sub_type == datetime.timedelta and isinstance(value, datetime.timedelta):
                return python_to_duration(value)
            if (
                inspect.isclass(sub_type)
                and issubclass(sub_type, enum.Enum)
                and isinstance(value, enum.Enum)
            ):
                return value.value
            if sub_type in (int, float, str, bool, bytes) and isinstance(
                value, sub_type
            ):
                return value
            if (
                inspect.isclass(sub_type)
                and issubclass(sub_type, Message)
                and isinstance(value, Message)
            ):
                return convert_python_message_to_proto(value, sub_type, pb2_module)
        return None

    # If Message
    if inspect.isclass(field_type) and issubclass(field_type, Message):
        return convert_python_message_to_proto(value, field_type, pb2_module)

    # If primitive
    return value


###############################################################################
# 3. Generating proto files (datetime->Timestamp, timedelta->Duration)
###############################################################################


def is_enum_type(python_type: Type) -> bool:
    """Return True if the given Python type is an enum."""
    return inspect.isclass(python_type) and issubclass(python_type, enum.Enum)


def is_union_type(python_type: Type) -> bool:
    """
    Check if a given Python type is a Union type (including Python 3.10's UnionType).
    """
    if get_origin(python_type) is Union:
        return True
    if sys.version_info >= (3, 10):
        import types

        if type(python_type) is types.UnionType:
            return True
    return False


def flatten_union(field_type: Type) -> list[Type]:
    """Recursively flatten nested Unions into a single list of types."""
    if is_union_type(field_type):
        results = []
        for arg in get_args(field_type):
            results.extend(flatten_union(arg))
        return results
    else:
        return [field_type]


def protobuf_type_mapping(python_type: Type) -> str | type | None:
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
        return python_type  # Will be defined as enum later

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
        return python_type

    return mapping.get(python_type)  # type: ignore


def comment_out(docstr: str) -> tuple[str, ...]:
    """Convert docstrings into commented-out lines in a .proto file."""
    if not docstr:
        return tuple()

    if docstr.startswith("Usage docs: https://docs.pydantic.dev/2.10/concepts/models/"):
        return tuple()

    return tuple("//" if line == "" else f"// {line}" for line in docstr.split("\n"))


def indent_lines(lines, indentation="    "):
    """Indent multiple lines with a given indentation string."""
    return "\n".join(indentation + line for line in lines)


def generate_enum_definition(enum_type: Type[enum.Enum]) -> str:
    """Generate a protobuf enum definition from a Python enum."""
    enum_name = enum_type.__name__
    members = []
    for _, member in enum_type.__members__.items():
        members.append(f"  {member.name} = {member.value};")
    enum_def = f"enum {enum_name} {{\n"
    enum_def += "\n".join(members)
    enum_def += "\n}"
    return enum_def


def generate_oneof_definition(
    field_name: str, union_args: list[Type], start_index: int
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

        # If it's an enum or Message, use the type name.
        if is_enum_type(arg_type):
            proto_typename = arg_type.__name__
        elif inspect.isclass(arg_type) and issubclass(arg_type, Message):
            proto_typename = arg_type.__name__

        field_alias = f"{field_name}_{proto_typename.replace('.', '_')}"
        lines.append(f"  {proto_typename} {field_alias} = {current};")
        current += 1
    lines.append("}")
    return lines, current


def generate_message_definition(
    message_type: Type[Message],
    done_enums: set,
    done_messages: set,
) -> tuple[str, list[type]]:
    """
    Generate a protobuf message definition for a Pydantic-based Message class.
    Also returns any referenced types (enums, messages) that need to be defined.
    """
    fields = []
    refs = []
    pydantic_fields = message_type.model_fields
    index = 1

    for field_name, field_info in pydantic_fields.items():
        field_type = field_info.annotation
        if field_type is None:
            raise Exception(f"Field {field_name} has no type annotation.")

        if is_union_type(field_type):
            union_args = flatten_union(field_type)
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

        else:
            proto_typename = protobuf_type_mapping(field_type)
            if proto_typename is None:
                raise Exception(f"Type {field_type} is not supported.")

            if is_enum_type(field_type):
                proto_typename = field_type.__name__
                if field_type not in done_enums:
                    refs.append(field_type)
            elif inspect.isclass(field_type) and issubclass(field_type, Message):
                proto_typename = field_type.__name__
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

            fields.append(f"{proto_typename} {field_name} = {index};")
            index += 1

    msg_def = f"message {message_type.__name__} {{\n{indent_lines(fields)}\n}}"
    return msg_def, refs


def is_stream_type(annotation: Type) -> bool:
    return get_origin(annotation) is AsyncIterator


def is_generic_alias(annotation: Type) -> bool:
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

    rpc_definitions = []
    all_type_definitions = []
    done_messages = set()
    done_enums = set()

    uses_timestamp = False
    uses_duration = False

    def check_and_set_well_known_types(py_type: Type):
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

    imports = []
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


def generate_grpc_code(proto_file, grpc_python_out) -> types.ModuleType | None:
    """
    Execute the protoc command to generate Python gRPC code from the .proto file.
    Returns a tuple of (pb2_grpc_module, pb2_module) on success, or None if failed.
    """
    command = f"-I. --grpc_python_out={grpc_python_out} {proto_file}"
    exit_code = protoc.main(command.split())
    if exit_code != 0:
        return None

    base = os.path.splitext(proto_file)[0]
    generated_pb2_grpc_file = f"{base}_pb2_grpc.py"

    if grpc_python_out not in sys.path:
        sys.path.append(grpc_python_out)

    spec = importlib.util.spec_from_file_location(
        generated_pb2_grpc_file, os.path.join(grpc_python_out, generated_pb2_grpc_file)
    )
    if spec is None:
        return None
    pb2_grpc_module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        return None
    spec.loader.exec_module(pb2_grpc_module)

    return pb2_grpc_module


def generate_connecpy_code(
    proto_file: str, connecpy_out: str
) -> types.ModuleType | None:
    """
    Execute the protoc command to generate Python Connecpy code from the .proto file.
    Returns a tuple of (connecpy_module, pb2_module) on success, or None if failed.
    """
    command = f"-I. --connecpy_out={connecpy_out} {proto_file}"
    exit_code = protoc.main(command.split())
    if exit_code != 0:
        return None

    base = os.path.splitext(proto_file)[0]
    generated_connecpy_file = f"{base}_connecpy.py"

    if connecpy_out not in sys.path:
        sys.path.append(connecpy_out)

    spec = importlib.util.spec_from_file_location(
        generated_connecpy_file, os.path.join(connecpy_out, generated_connecpy_file)
    )
    if spec is None:
        return None
    connecpy_module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        return None
    spec.loader.exec_module(connecpy_module)

    return connecpy_module


def generate_pb_code(
    proto_file: str, python_out: str, pyi_out: str
) -> types.ModuleType | None:
    """
    Execute the protoc command to generate Python gRPC code from the .proto file.
    Returns a tuple of (pb2_grpc_module, pb2_module) on success, or None if failed.
    """
    command = f"-I. --python_out={python_out} --pyi_out={pyi_out} {proto_file}"
    exit_code = protoc.main(command.split())
    if exit_code != 0:
        return None

    base = os.path.splitext(proto_file)[0]
    generated_pb2_file = f"{base}_pb2.py"

    if python_out not in sys.path:
        sys.path.append(python_out)

    spec = importlib.util.spec_from_file_location(
        generated_pb2_file, os.path.join(python_out, generated_pb2_file)
    )
    if spec is None:
        return None
    pb2_module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        return None
    spec.loader.exec_module(pb2_module)

    return pb2_module


def get_request_arg_type(sig):
    """Return the type annotation of the first parameter (request) of a method."""
    num_of_params = len(sig.parameters)
    if not (num_of_params == 1 or num_of_params == 2):
        raise Exception("Method must have exactly one or two parameters")
    return tuple(sig.parameters.values())[0].annotation


def get_rpc_methods(obj: object) -> list[tuple[str, types.MethodType]]:
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


def generate_and_compile_proto(obj: object, package_name: str = ""):
    if is_skip_generation():
        import importlib

        pb2_module = importlib.import_module(f"{obj.__class__.__name__.lower()}_pb2")
        pb2_grpc_module = importlib.import_module(
            f"{obj.__class__.__name__.lower()}_pb2_grpc"
        )

        if pb2_grpc_module is not None and pb2_module is not None:
            return pb2_grpc_module, pb2_module

        # If the modules are not found, generate and compile the proto files.

    klass = obj.__class__
    proto_file = generate_proto(obj, package_name)
    proto_file_name = klass.__name__.lower() + ".proto"

    with open(proto_file_name, "w", encoding="utf-8") as f:
        f.write(proto_file)

    gen_pb = generate_pb_code(proto_file_name, ".", ".")
    if gen_pb is None:
        raise Exception("Generating pb code")

    gen_grpc = generate_grpc_code(proto_file_name, ".")
    if gen_grpc is None:
        raise Exception("Generating grpc code")
    return gen_grpc, gen_pb


def generate_and_compile_proto_using_connecpy(obj: object, package_name: str = ""):
    if is_skip_generation():
        import importlib

        pb2_module = importlib.import_module(f"{obj.__class__.__name__.lower()}_pb2")
        connecpy_module = importlib.import_module(
            f"{obj.__class__.__name__.lower()}_connecpy"
        )

        if connecpy_module is not None and pb2_module is not None:
            return connecpy_module, pb2_module

        # If the modules are not found, generate and compile the proto files.

    klass = obj.__class__
    proto_file = generate_proto(obj, package_name)
    proto_file_name = klass.__name__.lower() + ".proto"

    with open(proto_file_name, "w", encoding="utf-8") as f:
        f.write(proto_file)

    gen_pb = generate_pb_code(proto_file_name, ".", ".")
    if gen_pb is None:
        raise Exception("Generating pb code")

    gen_connecpy = generate_connecpy_code(proto_file_name, ".")
    if gen_connecpy is None:
        raise Exception("Generating Connecpy code")
    return gen_connecpy, gen_pb


###############################################################################
# 4. Server Implementations
###############################################################################


class Server:
    """A simple gRPC server that uses ThreadPoolExecutor for concurrency."""

    def __init__(self, max_workers: int = 8, *interceptors) -> None:
        self._server = grpc.server(
            futures.ThreadPoolExecutor(max_workers), interceptors=interceptors
        )
        self._service_names = []
        self._package_name = ""
        self._port = 50051

    def set_package_name(self, package_name: str):
        """Set the package name for .proto generation."""
        self._package_name = package_name

    def set_port(self, port: int):
        """Set the port number for the gRPC server."""
        self._port = port

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the service implementation."""
        pb2_grpc_module, pb2_module = generate_and_compile_proto(obj, package_name)
        self.mount_using_pb2_modules(pb2_grpc_module, pb2_module, obj)

    def mount_using_pb2_modules(self, pb2_grpc_module, pb2_module, obj: object):
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

    def run(self, *objs):
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

        def handle_signal(signal, frame):
            print("Received shutdown signal...")
            self._server.stop(grace=10)
            print("gRPC server shutdown.")
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        print("gRPC server is running...")
        while True:
            time.sleep(86400)


class AsyncIOServer:
    """An async gRPC server using asyncio."""

    def __init__(self, *interceptors, port: int = 50051) -> None:
        self._server = grpc.aio.server(interceptors=interceptors)
        self._service_names = []
        self._package_name = ""
        self.set_port(port)

    def set_package_name(self, package_name: str):
        """Set the package name for .proto generation."""
        self._package_name = package_name

    def set_port(self, port: int):
        """Set the port number for the async gRPC server."""
        self._port = port

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the service implementation (async)."""
        pb2_grpc_module, pb2_module = generate_and_compile_proto(obj, package_name)
        self.mount_using_pb2_modules(pb2_grpc_module, pb2_module, obj)

    def mount_using_pb2_modules(self, pb2_grpc_module, pb2_module, obj: object):
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

    async def run(self, *objs):
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

        self._server.add_insecure_port(f"[::]:{self._port}")
        await self._server.start()

        shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown(signum, frame):
            print("Received shutdown signal...")
            loop.call_soon_threadsafe(shutdown_event.set)

        for s in [signal.SIGTERM, signal.SIGINT]:
            signal.signal(s, shutdown)

        print("gRPC server is running...")
        await shutdown_event.wait()
        await self._server.stop(10)
        print("gRPC server shutdown.")


class WSGIApp:
    """
    A WSGI-compatible application that can serve gRPC via sonora's grpcWSGI.
    Useful for embedding gRPC within an existing WSGI stack.
    """

    def __init__(self, app):
        self._app = grpcWSGI(app)
        self._service_names = []
        self._package_name = ""

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the service implementation."""
        pb2_grpc_module, pb2_module = generate_and_compile_proto(obj, package_name)
        self.mount_using_pb2_modules(pb2_grpc_module, pb2_module, obj)

    def mount_using_pb2_modules(self, pb2_grpc_module, pb2_module, obj: object):
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

    def mount_objs(self, *objs):
        """Mount multiple service objects into this WSGI app."""
        for obj in objs:
            self.mount(obj, self._package_name)

    def __call__(self, environ, start_response):
        """WSGI entry point."""
        return self._app(environ, start_response)


class ASGIApp:
    """
    An ASGI-compatible application that can serve gRPC via sonora's grpcASGI.
    Useful for embedding gRPC within an existing ASGI stack.
    """

    def __init__(self, app):
        self._app = grpcASGI(app)
        self._service_names = []
        self._package_name = ""

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the async service implementation."""
        pb2_grpc_module, pb2_module = generate_and_compile_proto(obj, package_name)
        self.mount_using_pb2_modules(pb2_grpc_module, pb2_module, obj)

    def mount_using_pb2_modules(self, pb2_grpc_module, pb2_module, obj: object):
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

    def mount_objs(self, *objs):
        """Mount multiple service objects into this ASGI app."""
        for obj in objs:
            self.mount(obj, self._package_name)

    async def __call__(self, scope, receive, send):
        """ASGI entry point."""
        await self._app(scope, receive, send)


def get_connecpy_server_class(connecpy_module, service_name):
    return getattr(connecpy_module, f"{service_name}Server")


class ConnecpyASGIApp:
    """
    An ASGI-compatible application that can serve Connect-RPC via Connecpy's ConnecpyASGIApp.
    """

    def __init__(self):
        self._app = ConnecpyASGI()
        self._service_names = []
        self._package_name = ""

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the async service implementation."""
        connecpy_module, pb2_module = generate_and_compile_proto_using_connecpy(
            obj, package_name
        )
        self.mount_using_pb2_modules(connecpy_module, pb2_module, obj)

    def mount_using_pb2_modules(self, connecpy_module, pb2_module, obj: object):
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

    def mount_objs(self, *objs):
        """Mount multiple service objects into this ASGI app."""
        for obj in objs:
            self.mount(obj, self._package_name)

    async def __call__(self, scope, receive, send):
        """ASGI entry point."""
        await self._app(scope, receive, send)


class ConnecpyWSGIApp:
    """
    A WSGI-compatible application that can serve Connect-RPC via Connecpy's ConnecpyWSGIApp.
    """

    def __init__(self):
        self._app = ConnecpyWSGI()
        self._service_names = []
        self._package_name = ""

    def mount(self, obj: object, package_name: str = ""):
        """Generate and compile proto files, then mount the async service implementation."""
        connecpy_module, pb2_module = generate_and_compile_proto_using_connecpy(
            obj, package_name
        )
        self.mount_using_pb2_modules(connecpy_module, pb2_module, obj)

    def mount_using_pb2_modules(self, connecpy_module, pb2_module, obj: object):
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

    def mount_objs(self, *objs):
        """Mount multiple service objects into this WSGI app."""
        for obj in objs:
            self.mount(obj, self._package_name)

    def __call__(self, environ, start_response):
        """WSGI entry point."""
        return self._app(environ, start_response)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate and compile proto files.")
    parser.add_argument(
        "py_file", type=str, help="The Python file containing the service class."
    )
    parser.add_argument("class_name", type=str, help="The name of the service class.")
    args = parser.parse_args()

    module_name = os.path.splitext(basename(args.py_file))[0]
    module = importlib.import_module(module_name)
    klass = getattr(module, args.class_name)
    generate_and_compile_proto(klass())


if __name__ == "__main__":
    main()
