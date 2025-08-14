"""Tests for nested Message serializer support."""

import types
from pydantic import field_serializer
from pydantic_rpc import Message
from pydantic_rpc.core import (
    convert_python_message_to_proto,
    SerializerStrategy,
    _SERIALIZER_STRATEGY,
)


class Address(Message):
    """Address with serializers."""

    street: str
    city: str
    country: str

    @field_serializer("city")
    def serialize_city(self, city: str) -> str:
        """Uppercase city name."""
        return city.upper()

    @field_serializer("country")
    def serialize_country(self, country: str) -> str:
        """Uppercase country code."""
        return country.upper()


class Person(Message):
    """Person with nested Address."""

    name: str
    age: int
    address: Address

    @field_serializer("name")
    def serialize_name(self, name: str) -> str:
        """Capitalize name."""
        return name.title()


class Company(Message):
    """Company with list of people."""

    name: str
    employees: list[Person]

    @field_serializer("name")
    def serialize_company_name(self, name: str) -> str:
        """Uppercase company name."""
        return name.upper()


class ComplexNested(Message):
    """Complex nested structure."""

    data: dict[str, Address]
    people: list[Person]
    primary_company: Company | None = None


def create_mock_pb2_module():
    """Create a mock pb2 module for testing."""
    pb2_module = types.ModuleType("test_pb2")

    # Mock protobuf classes
    class MockProto:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    # Register all message types
    for msg_type in [Address, Person, Company, ComplexNested]:
        setattr(pb2_module, msg_type.__name__, MockProto)

    return pb2_module


def test_nested_message_serializers_deep():
    """Test that nested Message serializers are applied with DEEP strategy."""
    # Create test data
    address = Address(street="123 main st", city="new york", country="usa")
    person = Person(name="john doe", age=30, address=address)

    pb2_module = create_mock_pb2_module()

    # Convert with DEEP strategy (default)
    proto_msg = convert_python_message_to_proto(person, Person, pb2_module)

    # Top-level serializer should be applied
    assert proto_msg.name == "John Doe"  # Title case from Person serializer

    # Nested Address serializers should also be applied
    assert proto_msg.address.city == "NEW YORK"  # Uppercase from Address serializer
    assert proto_msg.address.country == "USA"  # Uppercase from Address serializer
    assert proto_msg.address.street == "123 main st"  # No serializer, unchanged


def test_nested_message_serializers_shallow():
    """Test that nested Message serializers are NOT applied with SHALLOW strategy."""
    # Temporarily set SHALLOW strategy
    original_strategy = _SERIALIZER_STRATEGY
    import pydantic_rpc.core

    pydantic_rpc.core._SERIALIZER_STRATEGY = SerializerStrategy.SHALLOW

    try:
        address = Address(street="123 main st", city="new york", country="usa")
        person = Person(name="john doe", age=30, address=address)

        pb2_module = create_mock_pb2_module()
        proto_msg = convert_python_message_to_proto(person, Person, pb2_module)

        # Top-level serializer should be applied
        assert proto_msg.name == "John Doe"  # Title case from Person serializer

        # Nested Address serializers should NOT be applied
        assert proto_msg.address.city == "new york"  # Original value
        assert proto_msg.address.country == "usa"  # Original value

    finally:
        # Restore original strategy
        pydantic_rpc.core._SERIALIZER_STRATEGY = original_strategy


def test_nested_message_serializers_none():
    """Test that no serializers are applied with NONE strategy."""
    # Temporarily set NONE strategy
    original_strategy = _SERIALIZER_STRATEGY
    import pydantic_rpc.core

    pydantic_rpc.core._SERIALIZER_STRATEGY = SerializerStrategy.NONE

    try:
        address = Address(street="123 main st", city="new york", country="usa")
        person = Person(name="john doe", age=30, address=address)

        pb2_module = create_mock_pb2_module()
        proto_msg = convert_python_message_to_proto(person, Person, pb2_module)

        # No serializers should be applied at any level
        assert proto_msg.name == "john doe"  # Original value
        assert proto_msg.address.city == "new york"  # Original value
        assert proto_msg.address.country == "usa"  # Original value

    finally:
        # Restore original strategy
        pydantic_rpc.core._SERIALIZER_STRATEGY = original_strategy


def test_nested_in_list():
    """Test nested Messages in a list with serializers."""
    # Create test data
    addr1 = Address(street="123 main", city="new york", country="usa")
    addr2 = Address(street="456 oak", city="los angeles", country="usa")

    person1 = Person(name="alice smith", age=25, address=addr1)
    person2 = Person(name="bob jones", age=35, address=addr2)

    company = Company(name="acme corp", employees=[person1, person2])

    pb2_module = create_mock_pb2_module()
    proto_msg = convert_python_message_to_proto(company, Company, pb2_module)

    # Company name should be uppercased
    assert proto_msg.name == "ACME CORP"

    # Each person in the list should have serializers applied
    assert len(proto_msg.employees) == 2
    assert proto_msg.employees[0].name == "Alice Smith"
    assert proto_msg.employees[0].address.city == "NEW YORK"
    assert proto_msg.employees[1].name == "Bob Jones"
    assert proto_msg.employees[1].address.city == "LOS ANGELES"


def test_nested_in_dict():
    """Test nested Messages in a dict with serializers."""
    # Create test data
    home_addr = Address(street="123 home", city="boston", country="usa")
    work_addr = Address(street="456 work", city="cambridge", country="usa")

    complex_msg = ComplexNested(
        data={"home": home_addr, "work": work_addr},
        people=[],
        primary_company=None,
    )

    pb2_module = create_mock_pb2_module()
    proto_msg = convert_python_message_to_proto(complex_msg, ComplexNested, pb2_module)

    # Dict values should have serializers applied
    assert proto_msg.data["home"].city == "BOSTON"
    assert proto_msg.data["home"].country == "USA"
    assert proto_msg.data["work"].city == "CAMBRIDGE"
    assert proto_msg.data["work"].country == "USA"


def test_circular_reference_handling():
    """Test that circular references are handled properly."""

    class Node(Message):
        """Node with potential circular reference."""

        value: str
        child: "Node | None" = None

        @field_serializer("value")
        def serialize_value(self, value: str) -> str:
            return value.upper()

    # Create circular reference
    node1 = Node(value="first")
    node2 = Node(value="second")
    node1.child = node2
    node2.child = node1  # Circular!

    pb2_module = types.ModuleType("test_pb2")

    class MockProto:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    setattr(pb2_module, "Node", MockProto)

    # This should not cause infinite recursion
    proto_msg = convert_python_message_to_proto(node1, Node, pb2_module)

    # Note: When there's a circular reference, model_dump() fails with ValueError
    # so we fall back to direct attribute access (no serializers applied)
    # This is expected behavior to prevent infinite recursion
    assert proto_msg.value == "first"  # No serializer due to circular ref fallback
    assert (
        proto_msg.child.value == "second"
    )  # No serializer due to circular ref fallback
    # Circular reference should return empty proto
    assert (
        not hasattr(proto_msg.child.child, "value")
        or proto_msg.child.child.value is None
    )


def test_deeply_nested_messages():
    """Test deeply nested message structures."""

    class Level3(Message):
        data: str

        @field_serializer("data")
        def serialize_data(self, data: str) -> str:
            return f"L3:{data.upper()}"

    class Level2(Message):
        value: str
        nested: Level3

        @field_serializer("value")
        def serialize_value(self, value: str) -> str:
            return f"L2:{value.upper()}"

    class Level1(Message):
        name: str
        nested: Level2

        @field_serializer("name")
        def serialize_name(self, name: str) -> str:
            return f"L1:{name.upper()}"

    # Create deeply nested structure
    l3 = Level3(data="deep")
    l2 = Level2(value="middle", nested=l3)
    l1 = Level1(name="top", nested=l2)

    pb2_module = types.ModuleType("test_pb2")

    class MockProto:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    for cls in [Level1, Level2, Level3]:
        setattr(pb2_module, cls.__name__, MockProto)

    proto_msg = convert_python_message_to_proto(l1, Level1, pb2_module)

    # All levels should have serializers applied
    assert proto_msg.name == "L1:TOP"
    assert proto_msg.nested.value == "L2:MIDDLE"
    assert proto_msg.nested.nested.data == "L3:DEEP"


def test_optional_nested_message():
    """Test optional nested Messages with serializers."""
    # Test with None
    company_no_primary = ComplexNested(data={}, people=[], primary_company=None)

    pb2_module = create_mock_pb2_module()
    proto_msg = convert_python_message_to_proto(
        company_no_primary, ComplexNested, pb2_module
    )

    # Should handle None gracefully
    assert (
        not hasattr(proto_msg, "primary_company") or proto_msg.primary_company is None
    )

    # Test with value
    company = Company(name="test co", employees=[])
    complex_with_company = ComplexNested(data={}, people=[], primary_company=company)

    proto_msg2 = convert_python_message_to_proto(
        complex_with_company, ComplexNested, pb2_module
    )

    # Company serializer should be applied
    assert proto_msg2.primary_company.name == "TEST CO"


if __name__ == "__main__":
    # Run tests
    test_nested_message_serializers_deep()
    test_nested_message_serializers_shallow()
    test_nested_message_serializers_none()
    test_nested_in_list()
    test_nested_in_dict()
    test_circular_reference_handling()
    test_deeply_nested_messages()
    test_optional_nested_message()
