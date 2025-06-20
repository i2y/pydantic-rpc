from datetime import datetime, timedelta

import pytest

from pydantic_rpc.core import Message, generate_and_compile_proto


class WithTimestamp(Message):
    timestamp: datetime


class WithDuration(Message):
    duration: timedelta


class GreeterWithTimestamp:
    async def say_hello(self, request: WithTimestamp) -> WithTimestamp:
        return WithTimestamp(timestamp=request.timestamp + timedelta(seconds=1))


class GreeterWithDuration:
    async def say_hello(self, request: WithDuration) -> WithDuration:
        return WithDuration(duration=request.duration + timedelta(seconds=1))


@pytest.mark.asyncio
async def test_greeter_with_timestamp():
    generate_and_compile_proto(GreeterWithTimestamp())


@pytest.mark.asyncio
async def test_greeter_with_duration():
    generate_and_compile_proto(GreeterWithDuration())
