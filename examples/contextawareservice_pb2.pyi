from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class ContextResponse(_message.Message):
    __slots__ = ("result", "has_context")
    RESULT_FIELD_NUMBER: _ClassVar[int]
    HAS_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    result: str
    has_context: bool
    def __init__(
        self, result: _Optional[str] = ..., has_context: bool = ...
    ) -> None: ...

class ContextRequest(_message.Message):
    __slots__ = ("operation", "value")
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    operation: str
    value: str
    def __init__(
        self, operation: _Optional[str] = ..., value: _Optional[str] = ...
    ) -> None: ...
