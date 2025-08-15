"""Protocol Buffer options support for pydantic-rpc."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HttpBinding(BaseModel):
    """HTTP binding configuration for a single HTTP method."""

    method: str = Field(..., description="HTTP method (get, post, put, delete, patch)")
    path: Optional[str] = Field(None, description="URL path template")
    body: Optional[str] = Field(None, description="Request body mapping")
    response_body: Optional[str] = Field(None, description="Response body mapping")

    def to_proto_dict(self) -> Dict[str, Any]:
        """Convert to protobuf option format."""
        result = {}
        if self.path:
            result[self.method.lower()] = self.path
        if self.body:
            result["body"] = self.body
        if self.response_body:
            result["response_body"] = self.response_body
        return result


class HttpOption(BaseModel):
    """Google API HTTP option configuration."""

    method: str = Field(..., description="Primary HTTP method")
    path: str = Field(..., description="Primary URL path template")
    body: Optional[str] = Field(None, description="Request body mapping")
    response_body: Optional[str] = Field(None, description="Response body mapping")
    additional_bindings: List[Dict[str, Any]] = Field(
        default_factory=list, description="Additional HTTP bindings"
    )

    def to_proto_string(self) -> str:
        """Convert to protobuf option string format."""
        lines = []
        lines.append("option (google.api.http) = {")

        # Primary binding
        lines.append(f'  {self.method.lower()}: "{self.path}"')

        # Body mapping
        if self.body:
            lines.append(f'  body: "{self.body}"')

        # Response body mapping
        if self.response_body:
            lines.append(f'  response_body: "{self.response_body}"')

        # Additional bindings
        for binding in self.additional_bindings:
            lines.append("  additional_bindings {")
            for key, value in binding.items():
                if key == "body":
                    lines.append(f'    {key}: "{value}"')
                else:
                    lines.append(f'    {key}: "{value}"')
            lines.append("  }")

        lines.append("};")
        return "\n".join(lines)


class ProtoOption(BaseModel):
    """Generic protocol buffer option."""

    name: str = Field(..., description="Option name")
    value: Any = Field(..., description="Option value")

    def to_proto_string(self) -> str:
        """Convert to protobuf option string format."""
        if isinstance(self.value, bool):
            value_str = "true" if self.value else "false"
        elif isinstance(self.value, str):
            # Check if it's an enum value (no quotes) or string literal (quotes)
            if self.value.isupper() or "_" in self.value:
                # Likely an enum value
                value_str = self.value
            else:
                value_str = f'"{self.value}"'
        else:
            value_str = str(self.value)

        return f"option {self.name} = {value_str};"


class OptionMetadata(BaseModel):
    """Metadata container for method/service options."""

    http_option: Optional[HttpOption] = None
    proto_options: List[ProtoOption] = Field(default_factory=list)

    def add_proto_option(self, name: str, value: Any) -> None:
        """Add a generic proto option."""
        self.proto_options.append(ProtoOption(name=name, value=value))

    def set_http_option(
        self,
        method: str,
        path: str,
        body: Optional[str] = None,
        response_body: Optional[str] = None,
        additional_bindings: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Set the HTTP option configuration."""
        self.http_option = HttpOption(
            method=method,
            path=path,
            body=body,
            response_body=response_body,
            additional_bindings=additional_bindings or [],
        )

    def to_proto_strings(self) -> List[str]:
        """Convert all options to protobuf strings."""
        result = []

        # Add HTTP option first if present
        if self.http_option:
            result.append(self.http_option.to_proto_string())

        # Add other proto options
        for option in self.proto_options:
            result.append(option.to_proto_string())

        return result


# Option metadata attribute name used on methods
OPTION_METADATA_ATTR = "__pydantic_rpc_options__"
