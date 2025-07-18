import datetime
import enum
import os
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Union, Optional, List, Dict, Any
from unittest.mock import patch

import pytest
from google.protobuf import timestamp_pb2, duration_pb2
from pydantic import BaseModel

# Import the functions we want to test
from src.pydantic_rpc.core import (
    primitiveProtoValueToPythonValue,
    timestamp_to_python,
    python_to_timestamp,
    duration_to_python,
    python_to_duration,
    generate_converter,
    python_value_to_proto_value,
    is_enum_type,
    is_union_type,
    flatten_union,
    protobuf_type_mapping,
    comment_out,
    indent_lines,
    generate_enum_definition,
    is_stream_type,
    is_generic_alias,
    get_request_arg_type,
    get_rpc_methods,
    is_skip_generation,
    get_proto_path,
)


class SampleEnum(enum.Enum):
    VALUE_A = 1
    VALUE_B = 2


class SampleMessage(BaseModel):
    name: str
    value: int


class SampleService:
    def simple_method(self, request: SampleMessage) -> SampleMessage:
        return request

    def method_with_context(
        self, request: SampleMessage, context: Any
    ) -> SampleMessage:
        _ = context
        return request

    def _private_method(self):
        pass


class TestBasicConversions:
    """Test basic type conversion functions."""

    def test_primitive_proto_value_to_python_value(self):
        """Test that primitive values are returned as-is."""
        assert primitiveProtoValueToPythonValue(42) == 42
        assert primitiveProtoValueToPythonValue("hello") == "hello"
        assert primitiveProtoValueToPythonValue(True) is True
        assert primitiveProtoValueToPythonValue(3.14) == 3.14
        assert primitiveProtoValueToPythonValue(b"bytes") == b"bytes"
        assert primitiveProtoValueToPythonValue(None) is None

    def test_timestamp_to_python(self):
        """Test converting protobuf Timestamp to datetime."""
        # Create a protobuf timestamp
        ts = timestamp_pb2.Timestamp()
        test_dt = datetime.datetime(
            2023, 5, 15, 10, 30, 45, tzinfo=datetime.timezone.utc
        )
        ts.FromDatetime(test_dt)

        # Convert to Python datetime
        result = timestamp_to_python(ts)
        assert isinstance(result, datetime.datetime)
        # Compare as naive datetimes since ToDatetime() returns naive datetime
        assert result.replace(tzinfo=None) == test_dt.replace(tzinfo=None)

    def test_python_to_timestamp(self):
        """Test converting datetime to protobuf Timestamp."""
        test_dt = datetime.datetime(
            2023, 5, 15, 10, 30, 45, tzinfo=datetime.timezone.utc
        )

        result = python_to_timestamp(test_dt)
        assert isinstance(result, timestamp_pb2.Timestamp)

        # Convert back to verify
        converted_back = result.ToDatetime()
        # Compare as naive datetimes since ToDatetime() returns naive datetime
        assert converted_back.replace(tzinfo=None) == test_dt.replace(tzinfo=None)

    def test_duration_to_python(self):
        """Test converting protobuf Duration to timedelta."""
        # Create a protobuf duration
        dur = duration_pb2.Duration()
        test_td = datetime.timedelta(hours=2, minutes=30, seconds=45)
        dur.FromTimedelta(test_td)

        # Convert to Python timedelta
        result = duration_to_python(dur)
        assert isinstance(result, datetime.timedelta)
        assert result == test_td

    def test_python_to_duration(self):
        """Test converting timedelta to protobuf Duration."""
        test_td = datetime.timedelta(hours=2, minutes=30, seconds=45)

        result = python_to_duration(test_td)
        assert isinstance(result, duration_pb2.Duration)

        # Convert back to verify
        converted_back = result.ToTimedelta()
        assert converted_back == test_td


class TestConverterGeneration:
    """Test converter generation functions."""

    def test_generate_converter_primitives(self):
        """Test converter generation for primitive types."""
        for ptype in (int, str, bool, bytes, float):
            converter = generate_converter(ptype)
            assert converter is primitiveProtoValueToPythonValue

    def test_generate_converter_enum(self):
        """Test converter generation for enum types."""
        converter = generate_converter(SampleEnum)

        # Test conversion
        result = converter(SampleEnum.VALUE_A)
        assert result == SampleEnum.VALUE_A

    def test_generate_converter_datetime(self):
        """Test converter generation for datetime."""
        converter = generate_converter(datetime.datetime)

        # Create a timestamp to convert
        ts = timestamp_pb2.Timestamp()
        test_dt = datetime.datetime(
            2023, 5, 15, 10, 30, 45, tzinfo=datetime.timezone.utc
        )
        ts.FromDatetime(test_dt)

        result = converter(ts)
        assert isinstance(result, datetime.datetime)
        # Compare as naive datetimes since ToDatetime() returns naive datetime
        assert result.replace(tzinfo=None) == test_dt.replace(tzinfo=None)

    def test_generate_converter_timedelta(self):
        """Test converter generation for timedelta."""
        converter = generate_converter(datetime.timedelta)

        # Create a duration to convert
        dur = duration_pb2.Duration()
        test_td = datetime.timedelta(hours=1, minutes=30)
        dur.FromTimedelta(test_td)

        result = converter(dur)
        assert isinstance(result, datetime.timedelta)
        assert result == test_td

    def test_generate_converter_list(self):
        """Test converter generation for list types."""
        converter = generate_converter(List[int])

        # Test conversion
        result = converter([1, 2, 3])
        assert result == [1, 2, 3]

    def test_generate_converter_dict(self):
        """Test converter generation for dict types."""
        converter = generate_converter(Dict[str, int])

        # Test conversion
        result = converter({"a": 1, "b": 2})
        assert result == {"a": 1, "b": 2}


class TestTypeChecking:
    """Test type checking utility functions."""

    def test_is_enum_type(self):
        """Test enum type detection."""
        assert is_enum_type(SampleEnum) is True
        assert is_enum_type(int) is False
        assert is_enum_type(str) is False
        assert is_enum_type(SampleMessage) is False

    def test_is_union_type(self):
        """Test union type detection."""
        assert is_union_type(Union[str, int]) is True
        assert is_union_type(Optional[str]) is True  # Optional is Union[T, None]
        assert is_union_type(str) is False
        assert is_union_type(int) is False

        # Test Python 3.10+ UnionType if available
        if sys.version_info >= (3, 10):
            union_type = str | int
            assert is_union_type(union_type) is True

    def test_flatten_union(self):
        """Test union flattening."""
        # Simple union
        result = flatten_union(Union[str, int])
        assert set(result) == {str, int}

        # Optional (Union with None)
        result = flatten_union(Optional[str])
        assert set(result) == {str, type(None)}

        # Nested unions
        result = flatten_union(Union[str, Union[int, float]])
        assert set(result) == {str, int, float}

        # Non-union type
        result = flatten_union(str)
        assert result == [str]

        # None type
        result = flatten_union(type(None))
        assert result == [type(None)]

    def test_is_stream_type(self):
        """Test stream type detection."""
        assert is_stream_type(AsyncIterator[str]) is True
        assert is_stream_type(str) is False
        assert is_stream_type(List[str]) is False

    def test_is_generic_alias(self):
        """Test generic alias detection."""
        assert is_generic_alias(List[str]) is True
        assert is_generic_alias(Dict[str, int]) is True
        assert is_generic_alias(Optional[str]) is True
        assert is_generic_alias(str) is False
        assert is_generic_alias(int) is False


class TestProtobufTypeMapping:
    """Test protobuf type mapping functions."""

    def test_protobuf_type_mapping_primitives(self):
        """Test mapping for primitive types."""
        assert protobuf_type_mapping(int) == "int32"
        assert protobuf_type_mapping(str) == "string"
        assert protobuf_type_mapping(bool) == "bool"
        assert protobuf_type_mapping(bytes) == "bytes"
        assert protobuf_type_mapping(float) == "float"

    def test_protobuf_type_mapping_datetime(self):
        """Test mapping for datetime types."""
        assert protobuf_type_mapping(datetime.datetime) == "google.protobuf.Timestamp"
        assert protobuf_type_mapping(datetime.timedelta) == "google.protobuf.Duration"

    def test_protobuf_type_mapping_enum(self):
        """Test mapping for enum types."""
        assert protobuf_type_mapping(SampleEnum) == "SampleEnum"

    def test_protobuf_type_mapping_message(self):
        """Test mapping for message types."""
        assert protobuf_type_mapping(SampleMessage) == "SampleMessage"

    def test_protobuf_type_mapping_collections(self):
        """Test mapping for collection types."""
        assert protobuf_type_mapping(List[int]) == "repeated int32"
        assert protobuf_type_mapping(List[str]) == "repeated string"

        # Test map types
        map_result = protobuf_type_mapping(Dict[str, int])
        assert map_result == "map<string, int32>"

    def test_protobuf_type_mapping_union(self):
        """Test mapping for union types (should return None)."""
        assert protobuf_type_mapping(Union[str, int]) is None
        assert protobuf_type_mapping(Optional[str]) is None

    def test_protobuf_type_mapping_unknown(self):
        """Test mapping for unknown types."""

        class UnknownType:
            pass

        assert protobuf_type_mapping(UnknownType) is None


class TestProtoGenerationHelpers:
    """Test helper functions for proto generation."""

    def test_comment_out_empty(self):
        """Test commenting out empty strings."""
        assert comment_out("") == tuple()

    def test_comment_out_pydantic_docs(self):
        """Test filtering out pydantic documentation URLs."""
        pydantic_doc = "Usage docs: https://docs.pydantic.dev/2.10/concepts/models/"
        assert comment_out(pydantic_doc) == tuple()

    def test_comment_out_regular_docstring(self):
        """Test commenting out regular docstrings."""
        docstring = "This is a test\nMultiple lines\n\nWith empty line"
        result = comment_out(docstring)
        expected = (
            "// This is a test",
            "// Multiple lines",
            "//",
            "// With empty line",
        )
        assert result == expected

    def test_indent_lines(self):
        """Test line indentation."""
        lines = ["line1", "line2", "line3"]
        result = indent_lines(lines)
        expected = "    line1\n    line2\n    line3"
        assert result == expected

        # Test custom indentation
        result = indent_lines(lines, "  ")
        expected = "  line1\n  line2\n  line3"
        assert result == expected

    def test_generate_enum_definition(self):
        """Test enum definition generation."""
        result = generate_enum_definition(SampleEnum)
        expected_lines = ["enum SampleEnum {", "  VALUE_A = 1;", "  VALUE_B = 2;", "}"]
        assert result == "\n".join(expected_lines)


class TestServiceIntrospection:
    """Test service introspection functions."""

    def test_get_request_arg_type(self):
        """Test getting request argument type from method signature."""
        import inspect

        # Create test functions with proper signatures like the actual use case
        def test_method_one_param(request: SampleMessage) -> SampleMessage:
            return request

        def test_method_two_params(
            request: SampleMessage, context: Any
        ) -> SampleMessage:
            _ = context
            return request

        # Test method with one parameter
        sig = inspect.signature(test_method_one_param)
        result = get_request_arg_type(sig)
        assert result == SampleMessage

        # Test method with two parameters
        sig = inspect.signature(test_method_two_params)
        result = get_request_arg_type(sig)
        assert result == SampleMessage

    def test_get_request_arg_type_invalid(self):
        """Test error handling for invalid method signatures."""
        import inspect

        def invalid_method():
            pass

        def too_many_params(a: int, b: int, c: int):
            _ = a
            _ = b
            _ = c
            pass

        with pytest.raises(
            Exception, match="Method must have exactly one or two parameters"
        ):
            sig = inspect.signature(invalid_method)
            get_request_arg_type(sig)

        with pytest.raises(
            Exception, match="Method must have exactly one or two parameters"
        ):
            sig = inspect.signature(too_many_params)
            get_request_arg_type(sig)

    def test_get_rpc_methods(self):
        """Test extracting RPC methods from service object."""
        service = SampleService()
        methods = get_rpc_methods(service)

        # Should have 2 public methods, converted to PascalCase
        method_names = [name for name, _ in methods]
        assert "SimpleMethod" in method_names
        assert "MethodWithContext" in method_names
        assert "_private_method" not in [name for name, _ in methods]

        # Check methods are callable
        for _, method in methods:
            assert callable(method)


class TestEnvironmentUtils:
    """Test environment and file system utilities."""

    def test_is_skip_generation_default(self):
        """Test default behavior of skip generation check."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_skip_generation() is False

    def test_is_skip_generation_true(self):
        """Test skip generation when environment variable is set."""
        with patch.dict(os.environ, {"PYDANTIC_RPC_SKIP_GENERATION": "true"}):
            assert is_skip_generation() is True

        with patch.dict(os.environ, {"PYDANTIC_RPC_SKIP_GENERATION": "True"}):
            assert is_skip_generation() is True

        with patch.dict(os.environ, {"PYDANTIC_RPC_SKIP_GENERATION": "TRUE"}):
            assert is_skip_generation() is True

    def test_is_skip_generation_false(self):
        """Test skip generation when environment variable is false."""
        with patch.dict(os.environ, {"PYDANTIC_RPC_SKIP_GENERATION": "false"}):
            assert is_skip_generation() is False

        with patch.dict(os.environ, {"PYDANTIC_RPC_SKIP_GENERATION": "anything"}):
            assert is_skip_generation() is False

    def test_get_proto_path_default(self):
        """Test getting proto path with default behavior."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_proto_path("test.proto")
            expected = Path.cwd() / "test.proto"
            assert result == expected

    def test_get_proto_path_custom_env(self):
        """Test getting proto path with custom environment variable."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"PYDANTIC_RPC_PROTO_PATH": temp_dir}):
                result = get_proto_path("test.proto")
                expected = (Path(temp_dir) / "test.proto").resolve()
                assert result == expected

    def test_get_proto_path_with_expansion(self):
        """Test proto path with environment variable expansion."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test environment variable expansion
            with patch.dict(
                os.environ,
                {"PYDANTIC_RPC_PROTO_PATH": "$HOME/protos", "HOME": temp_dir},
            ):
                result = get_proto_path("test.proto")
                # The directory might not exist, so just check the path structure
                assert result.name == "test.proto"
                assert "protos" in str(result)

    def test_get_proto_path_creates_directory(self):
        """Test that get_proto_path creates directories if they don't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            new_dir = Path(temp_dir) / "new_subdir"
            with patch.dict(os.environ, {"PYDANTIC_RPC_PROTO_PATH": str(new_dir)}):
                result = get_proto_path("test.proto")
                assert new_dir.exists()
                assert new_dir.is_dir()
                assert result == (new_dir / "test.proto").resolve()

    def test_get_proto_path_not_directory_error(self):
        """Test error when proto path points to a file instead of directory."""
        with tempfile.NamedTemporaryFile() as temp_file:
            with patch.dict(os.environ, {"PYDANTIC_RPC_PROTO_PATH": temp_file.name}):
                with pytest.raises(NotADirectoryError):
                    _ = get_proto_path("test.proto")


class TestPythonValueToProtoValue:
    """Test python_value_to_proto_value function."""

    def test_python_value_to_proto_value_datetime(self):
        """Test converting datetime values."""
        test_dt = datetime.datetime(
            2023, 5, 15, 10, 30, 45, tzinfo=datetime.timezone.utc
        )
        result = python_value_to_proto_value(datetime.datetime, test_dt)

        assert isinstance(result, timestamp_pb2.Timestamp)
        converted_back = result.ToDatetime()
        # Compare as naive datetimes since ToDatetime() returns naive datetime
        assert converted_back.replace(tzinfo=None) == test_dt.replace(tzinfo=None)

    def test_python_value_to_proto_value_timedelta(self):
        """Test converting timedelta values."""
        test_td = datetime.timedelta(hours=2, minutes=30)
        result = python_value_to_proto_value(datetime.timedelta, test_td)

        assert isinstance(result, duration_pb2.Duration)
        converted_back = result.ToTimedelta()
        assert converted_back == test_td

    def test_python_value_to_proto_value_primitive(self):
        """Test converting primitive values (should return as-is)."""
        assert python_value_to_proto_value(int, 42) == 42
        assert python_value_to_proto_value(str, "hello") == "hello"
        assert python_value_to_proto_value(bool, True) is True
        assert python_value_to_proto_value(float, 3.14) == 3.14
