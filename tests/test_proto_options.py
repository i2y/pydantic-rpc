"""Tests for protobuf options support."""

from typing import List, Optional
from pydantic_rpc import Message, generate_proto
from pydantic_rpc.decorators import http_option, proto_option


class Book(Message):
    """Book model for testing."""

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
    """Test service with HTTP options."""

    @http_option(method="GET", path="/v1/books/{id}")
    async def get_book(self, request: GetBookRequest) -> Book:
        """Get a book by ID."""
        return Book(id=request.id, title="Test Book", author="Test Author", price=29.99)

    @http_option(
        method="GET",
        path="/v1/books",
        additional_bindings=[{"get": "/v1/authors/{author}/books"}],
    )
    async def list_books(self, request: ListBooksRequest) -> ListBooksResponse:
        """List all books."""
        return ListBooksResponse(books=[], total_count=0)

    @http_option(method="POST", path="/v1/books", body="*")
    async def create_book(self, request: CreateBookRequest) -> Book:
        """Create a new book."""
        return Book(
            id="new-id",
            title=request.title,
            author=request.author,
            isbn=request.isbn,
            price=request.price,
        )

    @http_option(method="PUT", path="/v1/books/{id}", body="*")
    async def update_book(self, request: UpdateBookRequest) -> Book:
        """Update a book."""
        return Book(
            id=request.id,
            title=request.title or "Updated",
            author=request.author or "Updated Author",
            price=request.price or 0.0,
        )

    @http_option(method="DELETE", path="/v1/books/{id}")
    async def delete_book(self, request: DeleteBookRequest) -> None:
        """Delete a book."""
        return None


class SimpleService:
    """Service without options for comparison."""

    async def simple_method(self, request: GetBookRequest) -> Book:
        """Simple method without options."""
        return Book(id=request.id, title="Simple", author="Simple", price=10.0)


class MixedOptionsService:
    """Service with mixed proto options."""

    @http_option(method="POST", path="/v1/auth/login", body="*")
    @proto_option("deprecated", True)
    @proto_option("idempotency_level", "IDEMPOTENT")
    async def login(self, request: GetBookRequest) -> Book:
        """Login method with multiple options."""
        return Book(id=request.id, title="Auth", author="Auth", price=0.0)

    @proto_option("deprecated", False)
    async def new_method(self, request: GetBookRequest) -> Book:
        """Method with only proto options."""
        return Book(id=request.id, title="New", author="New", price=0.0)


def test_http_option_basic():
    """Test basic HTTP option generation."""
    service = BookstoreService()
    proto = generate_proto(service, package_name="bookstore.v1")

    # Check for google/api/annotations.proto import
    assert 'import "google/api/annotations.proto";' in proto

    # Check for GET method with path parameter (PascalCase RPC names)
    assert "rpc GetBook (GetBookRequest) returns (Book) {" in proto
    assert "option (google.api.http) = {" in proto
    assert 'get: "/v1/books/{id}"' in proto

    # Check for POST method with body
    assert "rpc CreateBook (CreateBookRequest) returns (Book) {" in proto
    assert 'post: "/v1/books"' in proto
    assert 'body: "*"' in proto


def test_http_option_additional_bindings():
    """Test HTTP option with additional bindings."""
    service = BookstoreService()
    proto = generate_proto(service, package_name="bookstore.v1")

    # Check for additional bindings (PascalCase RPC names)
    assert "rpc ListBooks (ListBooksRequest) returns (ListBooksResponse) {" in proto
    assert 'get: "/v1/books"' in proto
    assert "additional_bindings {" in proto
    assert 'get: "/v1/authors/{author}/books"' in proto


def test_delete_with_empty_response():
    """Test DELETE method returning None/Empty."""
    service = BookstoreService()
    proto = generate_proto(service, package_name="bookstore.v1")

    # Check for Empty import
    assert 'import "google/protobuf/empty.proto";' in proto

    # Check for DELETE method (PascalCase RPC names)
    assert (
        "rpc DeleteBook (DeleteBookRequest) returns (google.protobuf.Empty) {" in proto
    )
    assert 'delete: "/v1/books/{id}"' in proto


def test_service_without_options():
    """Test service without any options."""
    service = SimpleService()
    proto = generate_proto(service, package_name="simple.v1")

    # Should not have google/api/annotations.proto import
    assert 'import "google/api/annotations.proto";' not in proto

    # Should have simple RPC definition without options block (PascalCase RPC names)
    assert "rpc SimpleMethod (GetBookRequest) returns (Book);" in proto
    assert "option (google.api.http)" not in proto


def test_mixed_proto_options():
    """Test service with mixed proto options."""
    service = MixedOptionsService()
    proto = generate_proto(service, package_name="mixed.v1")

    # Check for google/api/annotations.proto import (due to login method)
    assert 'import "google/api/annotations.proto";' in proto

    # Check for HTTP option and other proto options in login method (PascalCase RPC names)
    assert "rpc Login (GetBookRequest) returns (Book) {" in proto
    assert "option (google.api.http) = {" in proto
    assert 'post: "/v1/auth/login"' in proto
    assert 'body: "*"' in proto
    assert "option deprecated = true;" in proto
    assert "option idempotency_level = IDEMPOTENT;" in proto

    # Check for method with only proto options (PascalCase RPC names)
    assert "rpc NewMethod (GetBookRequest) returns (Book) {" in proto
    assert "option deprecated = false;" in proto


def test_proto_generation_structure():
    """Test overall proto file structure."""
    service = BookstoreService()
    proto = generate_proto(service, package_name="bookstore.v1")

    # Check basic structure
    assert 'syntax = "proto3";' in proto
    assert "package bookstore.v1;" in proto
    assert "service BookstoreService {" in proto

    # Check message definitions
    assert "message Book {" in proto
    assert "message GetBookRequest {" in proto
    assert "message ListBooksRequest {" in proto
    assert "message ListBooksResponse {" in proto
    assert "message CreateBookRequest {" in proto
    assert "message UpdateBookRequest {" in proto
    assert "message DeleteBookRequest {" in proto

    # Check field definitions
    assert "string id = 1;" in proto
    assert "string title = 2;" in proto
    assert "optional string isbn = 4;" in proto
    assert "float price = 5;" in proto
    assert "repeated Book books = 1;" in proto
    assert "int32 total_count = 2;" in proto


def test_all_http_methods():
    """Test all supported HTTP methods."""

    class AllMethodsService:
        @http_option(method="GET", path="/v1/resource/{id}")
        async def get_method(self, request: GetBookRequest) -> Book:
            return Book(id="1", title="", author="", price=0)

        @http_option(method="POST", path="/v1/resource", body="*")
        async def post_method(self, request: CreateBookRequest) -> Book:
            return Book(id="1", title="", author="", price=0)

        @http_option(method="PUT", path="/v1/resource/{id}", body="*")
        async def put_method(self, request: UpdateBookRequest) -> Book:
            return Book(id="1", title="", author="", price=0)

        @http_option(method="DELETE", path="/v1/resource/{id}")
        async def delete_method(self, request: DeleteBookRequest) -> None:
            return None

        @http_option(method="PATCH", path="/v1/resource/{id}", body="*")
        async def patch_method(self, request: UpdateBookRequest) -> Book:
            return Book(id="1", title="", author="", price=0)

    service = AllMethodsService()
    proto = generate_proto(service, package_name="allmethods.v1")

    # Check all HTTP methods are present
    assert 'get: "/v1/resource/{id}"' in proto
    assert 'post: "/v1/resource"' in proto
    assert 'put: "/v1/resource/{id}"' in proto
    assert 'delete: "/v1/resource/{id}"' in proto
    assert 'patch: "/v1/resource/{id}"' in proto
