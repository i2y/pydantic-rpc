from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class UserResponse(_message.Message):
    __slots__ = ("message", "user_id")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    message: str
    user_id: int
    def __init__(self, message: _Optional[str] = ..., user_id: _Optional[int] = ...) -> None: ...

class UserRequest(_message.Message):
    __slots__ = ("name", "age", "email")
    NAME_FIELD_NUMBER: _ClassVar[int]
    AGE_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    name: str
    age: int
    email: str
    def __init__(self, name: _Optional[str] = ..., age: _Optional[int] = ..., email: _Optional[str] = ...) -> None: ...
