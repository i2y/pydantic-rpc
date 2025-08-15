from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class FooResponse(_message.Message):
    __slots__ = ("name", "age", "d")
    class DEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    AGE_FIELD_NUMBER: _ClassVar[int]
    D_FIELD_NUMBER: _ClassVar[int]
    name: str
    age: int
    d: _containers.ScalarMap[str, str]
    def __init__(self, name: _Optional[str] = ..., age: _Optional[int] = ..., d: _Optional[_Mapping[str, str]] = ...) -> None: ...

class FooRequest(_message.Message):
    __slots__ = ("name", "age", "d")
    class DEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    AGE_FIELD_NUMBER: _ClassVar[int]
    D_FIELD_NUMBER: _ClassVar[int]
    name: str
    age: int
    d: _containers.ScalarMap[str, str]
    def __init__(self, name: _Optional[str] = ..., age: _Optional[int] = ..., d: _Optional[_Mapping[str, str]] = ...) -> None: ...
