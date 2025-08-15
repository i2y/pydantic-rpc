#!/usr/bin/env python
"""
Example bookstore service with HTTP options for proto generation.

This demonstrates how to use the new protobuf options feature to define
HTTP mappings for your gRPC services.
"""

from typing import List, Optional
from pydantic_rpc import Message, http_option, proto_option, generate_proto


class Book(Message):
    """Book model."""

    id: str
    title: str
    author: str
    isbn: Optional[str] = None
    price: float


class GetBookRequest(Message):
    """Request for getting a book."""

    id: str


class ListBooksRequest(Message):
    """Request for listing books."""

    author: Optional[str] = None
    limit: int = 10
    offset: int = 0


class ListBooksResponse(Message):
    """Response for listing books."""

    books: List[Book]
    total_count: int


class CreateBookRequest(Message):
    """Request for creating a book."""

    title: str
    author: str
    isbn: Optional[str] = None
    price: float


class UpdateBookRequest(Message):
    """Request for updating a book."""

    id: str
    title: Optional[str] = None
    author: Optional[str] = None
    price: Optional[float] = None


class DeleteBookRequest(Message):
    """Request for deleting a book."""

    id: str


class BookstoreService:
    """Bookstore management service with HTTP gateway support."""

    @http_option(method="GET", path="/v1/books/{id}")
    async def get_book(self, request: GetBookRequest) -> Book:
        """Get a book by ID."""
        # Implementation would go here
        return Book(
            id=request.id, title="Example Book", author="Example Author", price=29.99
        )

    @http_option(
        method="GET",
        path="/v1/books",
        additional_bindings=[
            {
                "get": "/v1/authors/{author}/books"
            }  # Alternative path for filtering by author
        ],
    )
    async def list_books(self, request: ListBooksRequest) -> ListBooksResponse:
        """List all books with optional filtering."""
        # Implementation would go here
        books = [
            Book(id="1", title="Python Programming", author="John Doe", price=32.00),
            Book(id="2", title="gRPC in Practice", author="Jane Smith", price=38.00),
        ]
        return ListBooksResponse(books=books, total_count=len(books))

    @http_option(method="POST", path="/v1/books", body="*")
    async def create_book(self, request: CreateBookRequest) -> Book:
        """Create a new book."""
        # Implementation would go here
        return Book(
            id="generated-id",
            title=request.title,
            author=request.author,
            isbn=request.isbn,
            price=request.price,
        )

    @http_option(method="PUT", path="/v1/books/{id}", body="*")
    @proto_option("idempotency_level", "IDEMPOTENT")
    async def update_book(self, request: UpdateBookRequest) -> Book:
        """Update an existing book."""
        # Implementation would go here
        return Book(
            id=request.id,
            title=request.title or "Updated Book",
            author=request.author or "Updated Author",
            price=request.price or 0.0,
        )

    @http_option(method="DELETE", path="/v1/books/{id}")
    async def delete_book(self, request: DeleteBookRequest) -> None:
        """Delete a book by ID."""
        # Implementation would go here
        print(f"Deleting book {request.id}")
        return None


def main():
    """Generate and display the proto definition."""
    service = BookstoreService()
    proto_content = generate_proto(service, package_name="bookstore.v1")

    print("Generated Proto Definition:")
    print("=" * 80)
    print(proto_content)
    print("=" * 80)

    # Optionally save to file
    with open("bookstore.proto", "w") as f:
        f.write(proto_content)
    print("\nProto definition saved to bookstore.proto")

    print("\nThis proto file can now be used with:")
    print("1. gRPC-Gateway to generate an HTTP gateway")
    print("2. Connecpy to generate Connect-RPC compatible code")
    print("3. Standard protoc to generate gRPC client/server code")


if __name__ == "__main__":
    main()
