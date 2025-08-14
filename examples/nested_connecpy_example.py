"""Connect-RPC example with nested Message serializers."""

from pydantic import field_serializer
from pydantic_rpc import ConnecpyASGIApp, Message


class Address(Message):
    """Address with serializers."""

    street: str
    city: str
    country: str

    @field_serializer("city")
    def serialize_city(self, city: str) -> str:
        return city.upper()

    @field_serializer("country")
    def serialize_country(self, country: str) -> str:
        return country.upper()


class PersonRequest(Message):
    """Request with nested Address."""

    name: str
    age: int
    address: Address

    @field_serializer("name")
    def serialize_name(self, name: str) -> str:
        return name.title()


class PersonResponse(Message):
    """Response with processed person data."""

    greeting: str
    person: PersonRequest  # Reuse the request type


class EmptyRequest(Message):
    """Empty request message."""

    pass


class NestedService:
    """Service demonstrating nested serializers with Connect-RPC."""

    async def process_person(self, request: PersonRequest) -> PersonResponse:
        """Process a person with nested Address.

        All serializers will be applied:
        - Person name will be Title Case
        - Address city will be UPPERCASE
        - Address country will be UPPERCASE
        """
        # Create response - serializers are applied during proto conversion
        greeting = f"Hello {request.name} from {request.address.city}, {request.address.country}!"

        return PersonResponse(
            greeting=greeting,
            person=request,  # Pass through to show serializers applied
        )

    async def create_demo_person(self) -> PersonRequest:
        """Create a demo person to show serializers."""
        addr = Address(street="123 main st", city="san francisco", country="usa")

        return PersonRequest(name="john doe", age=30, address=addr)


# Create ASGI app
app = ConnecpyASGIApp()
app.mount(NestedService())

if __name__ == "__main__":
    import uvicorn

    print("Starting Connect-RPC server with nested serializers")
    print("=" * 50)
    print("Available endpoints:")
    print("  POST /nestedservice.v1.NestedService/ProcessPerson")
    print("  POST /nestedservice.v1.NestedService/CreateDemoPerson")
    print()
    print("Serializers will be applied to nested Messages:")
    print("  - Names -> Title Case")
    print("  - Cities -> UPPERCASE")
    print("  - Countries -> UPPERCASE")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8001)
