"""Type conversion utilities for MCP integration."""

import datetime
import enum
import inspect
from collections.abc import AsyncIterator
from typing import Any, Callable, Type, Union, get_args, get_origin

from pydantic import BaseModel


def is_streaming_return(return_type: Type) -> bool:
    """Check if the return type is a streaming response (AsyncIterator)."""
    origin = get_origin(return_type)
    return origin is AsyncIterator


def python_type_to_json_type(python_type: Type) -> dict[str, Any]:
    """Convert Python type to JSON Schema type."""
    if python_type == int:
        return {"type": "integer"}
    elif python_type == float:
        return {"type": "number"}
    elif python_type == str:
        return {"type": "string"}
    elif python_type == bool:
        return {"type": "boolean"}
    elif python_type == bytes:
        return {"type": "string", "format": "byte"}
    elif python_type == datetime.datetime:
        return {"type": "string", "format": "date-time"}
    elif python_type == datetime.timedelta:
        return {"type": "string", "format": "duration"}
    elif get_origin(python_type) is list:
        item_type = get_args(python_type)[0]
        return {
            "type": "array",
            "items": python_type_to_json_type(item_type)
        }
    elif get_origin(python_type) is dict:
        key_type, value_type = get_args(python_type)
        return {
            "type": "object",
            "additionalProperties": python_type_to_json_type(value_type)
        }
    elif inspect.isclass(python_type) and issubclass(python_type, enum.Enum):
        return {
            "type": "string",
            "enum": [e.value for e in python_type]
        }
    elif inspect.isclass(python_type) and issubclass(python_type, BaseModel):
        # For Pydantic models, use their built-in schema generation
        return python_type.model_json_schema()
    elif get_origin(python_type) is Union:
        # Handle Union types as oneOf
        union_args = get_args(python_type)
        # Filter out NoneType if present
        non_none_types = [t for t in union_args if t is not type(None)]
        if len(non_none_types) == 1:
            # Optional type
            schema = python_type_to_json_type(non_none_types[0])
            schema["nullable"] = True
            return schema
        else:
            return {
                "oneOf": [python_type_to_json_type(t) for t in non_none_types]
            }
    else:
        # Default to object type for unknown types
        return {"type": "object"}


def extract_method_info(method: Callable) -> dict[str, Any]:
    """Extract method information for MCP tool definition."""
    sig = inspect.signature(method)
    doc = inspect.getdoc(method) or ""
    
    # Get parameter types (skip 'self' for instance methods)
    params = list(sig.parameters.values())
    if params and params[0].name in ('self', 'cls'):
        params = params[1:]
    
    # Extract input type
    input_type = None
    if params:
        input_type = params[0].annotation
    
    # Extract return type
    return_type = sig.return_annotation
    
    # Build parameter schema
    parameters_schema = {}
    if input_type and input_type != inspect._empty:
        if inspect.isclass(input_type) and issubclass(input_type, BaseModel):
            # Use Pydantic's built-in schema generation
            parameters_schema = input_type.model_json_schema()
        else:
            parameters_schema = python_type_to_json_type(input_type)
    
    # Build response schema
    response_schema = {}
    if return_type and return_type != inspect._empty:
        if is_streaming_return(return_type):
            # For streaming responses, extract the inner type
            inner_type = get_args(return_type)[0]
            response_schema = {
                "type": "object",
                "properties": {
                    "stream": {
                        "type": "array",
                        "items": python_type_to_json_type(inner_type)
                    }
                }
            }
        elif inspect.isclass(return_type) and issubclass(return_type, BaseModel):
            response_schema = return_type.model_json_schema()
        else:
            response_schema = python_type_to_json_type(return_type)
    
    return {
        "description": doc,
        "parameters": parameters_schema,
        "response": response_schema,
        "is_streaming": is_streaming_return(return_type)
    }
