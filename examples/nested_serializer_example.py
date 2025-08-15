"""Example demonstrating nested Message serializers with pydantic-rpc."""

import asyncio
import os
from pydantic import field_serializer
from pydantic_rpc import AsyncIOServer, Message


# Set serializer strategy (optional, defaults to 'deep')
# os.environ['PYDANTIC_RPC_SERIALIZER_STRATEGY'] = 'deep'


class Address(Message):
    """Address with custom field serializers."""

    street: str
    city: str
    country: str

    @field_serializer("city")
    def serialize_city(self, city: str) -> str:
        """Convert city to uppercase."""
        return city.upper()

    @field_serializer("country")
    def serialize_country(self, country: str) -> str:
        """Convert country to uppercase."""
        return country.upper()


class Person(Message):
    """Person with nested Address."""

    name: str
    email: str
    age: int
    home_address: Address
    work_address: Address | None = None

    @field_serializer("name")
    def serialize_name(self, name: str) -> str:
        """Capitalize name properly."""
        return name.title()

    @field_serializer("email")
    def serialize_email(self, email: str) -> str:
        """Normalize email to lowercase."""
        return email.lower()


class Company(Message):
    """Company with employees."""

    name: str
    employees: list[Person]
    headquarters: Address

    @field_serializer("name")
    def serialize_company_name(self, name: str) -> str:
        """Convert company name to uppercase."""
        return name.upper()


class CompanyRequest(Message):
    """Request to create a company."""

    company_name: str
    headquarters_city: str
    headquarters_country: str
    employee_count: int


class CompanyResponse(Message):
    """Response with created company."""

    company: Company
    message: str


class CompanyService:
    """Service demonstrating nested serializers."""

    async def create_company(self, request: CompanyRequest) -> CompanyResponse:
        """Create a company with nested serializers applied."""

        # Create headquarters
        headquarters = Address(
            street="123 main street",
            city=request.headquarters_city,
            country=request.headquarters_country,
        )

        # Create employees with addresses
        employees = []
        for i in range(request.employee_count):
            home_addr = Address(
                street=f"{100 + i} residential ave", city="san francisco", country="usa"
            )

            work_addr = None
            if i % 2 == 0:  # Some employees have work addresses
                work_addr = Address(
                    street=f"{200 + i} business blvd", city="new york", country="usa"
                )

            person = Person(
                name=f"employee {i}",
                email=f"EMPLOYEE{i}@EXAMPLE.COM",  # Will be lowercased
                age=25 + i,
                home_address=home_addr,
                work_address=work_addr,
            )
            employees.append(person)

        # Create company
        company = Company(
            name=request.company_name, employees=employees, headquarters=headquarters
        )

        # When this is converted to protobuf:
        # - Company name will be UPPERCASE
        # - Employee names will be Title Case
        # - Employee emails will be lowercase
        # - All city names will be UPPERCASE
        # - All country codes will be UPPERCASE
        # This happens recursively through all nested Messages!

        return CompanyResponse(
            company=company,
            message=f"Created {request.company_name} with {request.employee_count} employees",
        )

    async def get_demo_company(self) -> Company:
        """Get a demo company to show serializers in action."""
        addr = Address(street="456 demo lane", city="seattle", country="usa")

        person = Person(
            name="john doe", email="JOHN.DOE@EXAMPLE.COM", age=30, home_address=addr
        )

        return Company(name="demo corp", employees=[person], headquarters=addr)


async def main():
    """Run the example service."""
    server = AsyncIOServer()

    port = 50051
    server.set_port(port)

    print(f"Starting gRPC server on port {port}")
    print("\nNested Serializer Example")
    print("=" * 50)
    print("This example demonstrates:")
    print("  - Nested Message serializers (Address within Person)")
    print("  - List of Messages with serializers")
    print("  - Optional nested Messages")
    print("  - Multiple levels of nesting")
    print()
    print("Serializer Strategy:")
    strategy = os.getenv("PYDANTIC_RPC_SERIALIZER_STRATEGY", "deep")
    print(f"  Current: {strategy}")
    print("  Options: deep (default), shallow, none")
    print()
    print("Available methods:")
    print("  - create_company: Create a company with employees")
    print("  - get_demo_company: Get a demo company")
    print()
    print("All serializers will be applied based on the strategy:")
    print("  - DEEP: All nested serializers applied")
    print("  - SHALLOW: Only top-level serializers")
    print("  - NONE: No serializers applied")
    print("=" * 50)

    await server.run(CompanyService())


if __name__ == "__main__":
    asyncio.run(main())
