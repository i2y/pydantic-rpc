# RPC Architecture Patterns with pydantic-rpc

This guide presents common architectural patterns and their implementations using pydantic-rpc, organized by real-world use cases.

## Pattern 1: Simple Microservice

**Use Case:** You're building a standalone microservice that needs to expose RPC endpoints to other services in your infrastructure.

**Scenario:** A recommendation service that other services call to get product recommendations.

### Implementation A: Pure gRPC Service

Choose this when your clients are other backend services that can speak gRPC.

```python
# recommendation_service.py
from pydantic_rpc import AsyncIOServer, Message
from typing import List
import asyncio

class ProductRequest(Message):
    user_id: str
    category: str
    limit: int = 10

class Product(Message):
    id: str
    name: str
    price: float
    score: float  # recommendation score

class RecommendationResponse(Message):
    products: List[Product]
    generated_at: str

class RecommendationService:
    async def get_recommendations(self, request: ProductRequest) -> RecommendationResponse:
        # ML model inference here
        products = await self.ml_model.predict(
            user_id=request.user_id,
            category=request.category
        )
        return RecommendationResponse(
            products=products[:request.limit],
            generated_at=datetime.now().isoformat()
        )
    
    async def get_trending(self, request: Message) -> RecommendationResponse:
        # Get trending products
        products = await self.cache.get_trending()
        return RecommendationResponse(products=products)

# Deploy as a Kubernetes service
if __name__ == "__main__":
    server = AsyncIOServer()
    asyncio.run(server.run(RecommendationService()))  # Default port is 50051
```

**Deployment:**
```yaml
# kubernetes/recommendation-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: recommendation-service
spec:
  ports:
    - port: 50051
      targetPort: 50051
      protocol: TCP
  selector:
    app: recommendation-service
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: recommendation-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: recommendation-service
  template:
    spec:
      containers:
      - name: service
        image: recommendation-service:latest
        ports:
        - containerPort: 50051
```

### Implementation B: Connect RPC Service

Choose this when you need broader client compatibility (web apps, mobile apps, curl debugging).

```python
# recommendation_service_connect.py
from pydantic_rpc import ASGIApp, Message
from typing import List
import uvicorn

class RecommendationService:
    # Same service implementation as above
    async def get_recommendations(self, request: ProductRequest) -> RecommendationResponse:
        # Implementation
        pass

app = ASGIApp()
app.mount(RecommendationService())

# Can be deployed behind any HTTP load balancer
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

**Client Usage:**
```javascript
// Web frontend can call directly
// Note: URL includes package name (recommendation.v1)
const response = await fetch('https://api.company.com/recommendation.v1.RecommendationService/GetRecommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: '123', category: 'electronics' })
});
const recommendations = await response.json();
```

## Pattern 2: API Gateway / Backend for Frontend (BFF)

**Use Case:** You have multiple backend services and need a unified API for your frontend applications.

**Scenario:** An e-commerce platform where the mobile app needs data from user service, product service, and order service in a single API call.

### Implementation: FastAPI Gateway with Multiple Backends

```python
# api_gateway.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from typing import List, Optional
import grpc
import httpx
import asyncio
import redis.asyncio as redis
from datetime import datetime

app = FastAPI(title="E-commerce API Gateway")

# Service clients
class ServiceClients:
    def __init__(self):
        self.redis = redis.Redis(host='redis', port=6379)
        self.http_client = httpx.AsyncClient()
    
    async def get_user(self, user_id: str):
        """Call user service (gRPC)"""
        async with grpc.aio.insecure_channel('user-service:50051') as channel:
            stub = UserServiceStub(channel)
            return await stub.GetUser(UserRequest(id=user_id))
    
    async def get_products(self, product_ids: List[str]):
        """Call product service (Connect RPC)"""
        response = await self.http_client.post(
            'http://product-service:8080/product.v1.ProductService/GetBulkProducts',
            json={'ids': product_ids}
        )
        return response.json()
    
    async def get_inventory(self, product_ids: List[str]):
        """Call inventory service (REST)"""
        response = await self.http_client.get(
            'http://inventory-service:3000/inventory',
            params={'ids': ','.join(product_ids)}
        )
        return response.json()

clients = ServiceClients()

# Aggregated endpoints for mobile app
@app.get("/mobile/home/{user_id}")
async def get_mobile_home(user_id: str, background_tasks: BackgroundTasks):
    """Single endpoint that aggregates data from multiple services"""
    
    # Parallel calls to multiple services
    user_task = clients.get_user(user_id)
    trending_task = clients.http_client.post(
        'http://recommendation-service:8080/recommendation.v1.RecommendationService/GetTrending',
        json={}
    )
    
    # Wait for all results
    user, trending = await asyncio.gather(user_task, trending_task)
    
    # Get inventory for trending products
    product_ids = [p['id'] for p in trending.json()['products']]
    inventory = await clients.get_inventory(product_ids)
    
    # Background task to log user activity
    background_tasks.add_task(log_user_activity, user_id, "home_view")
    
    # Combine and transform data for mobile app
    return {
        "user": {
            "name": user.name,
            "membership_level": user.membership_level
        },
        "trending_products": [
            {
                **product,
                "in_stock": inventory.get(product['id'], {}).get('available', 0) > 0
            }
            for product in trending.json()['products']
        ],
        "generated_at": datetime.now().isoformat()
    }

@app.post("/mobile/checkout")
async def mobile_checkout(order: OrderRequest):
    """Orchestrate checkout across multiple services"""
    
    # 1. Validate inventory
    inventory = await clients.get_inventory(order.product_ids)
    for product_id in order.product_ids:
        if inventory[product_id]['available'] <= 0:
            raise HTTPException(400, f"Product {product_id} out of stock")
    
    # 2. Process payment
    payment_result = await clients.process_payment(order.payment_info)
    
    # 3. Create order
    order_result = await clients.create_order(order)
    
    # 4. Update inventory
    await clients.update_inventory(order.product_ids)
    
    return {
        "order_id": order_result.id,
        "status": "confirmed",
        "estimated_delivery": order_result.estimated_delivery
    }

# Health check that verifies all backend services
@app.get("/health")
async def health_check():
    checks = {
        "api_gateway": "healthy",
        "user_service": "unknown",
        "product_service": "unknown",
        "inventory_service": "unknown"
    }
    
    # Check each backend service
    try:
        await clients.get_user("health-check")
        checks["user_service"] = "healthy"
    except:
        checks["user_service"] = "unhealthy"
    
    # ... check other services
    
    overall_health = "healthy" if all(v == "healthy" for v in checks.values()) else "degraded"
    return {"status": overall_health, "services": checks}
```

## Pattern 3: Hybrid Public/Internal API

**Use Case:** You need to expose some endpoints publicly (with rate limiting, auth) while keeping others internal.

**Scenario:** A SaaS platform where customers access via REST API but internal services use gRPC.

### Implementation: Dual Protocol Service

**⚠️ Important Note about Connect RPC URL Paths:**

When using Connect RPC with pydantic-rpc's ASGIApp, the generated endpoint URLs include the package name. For example:
- Method `process_partner` in class `PartnerConnectService`
- Becomes endpoint: `/partnerconnect.v1.PartnerConnectService/ProcessPartner`
- Full URL: `http://localhost:8000/partner/partnerconnect.v1.PartnerConnectService/ProcessPartner`

This is because pydantic-rpc generates proto files with package names (e.g., `partnerconnect.v1`) and uses connecpy for Connect RPC implementation.

```python
# hybrid_service_fixed.py
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic_rpc import ASGIApp, Message
from pydantic import BaseModel
from typing import Optional
import uvicorn
import time
from datetime import datetime

# Shared business logic
class DataProcessor:
    def __init__(self):
        self.request_count = 0
    
    async def process_data(self, data_payload: DataPayload) -> ProcessResult:
        """Core business logic used by both APIs"""
        import asyncio
        self.request_count += 1
        await asyncio.sleep(0.1)  # Simulate processing
        
        # Parse the content
        import json
        try:
            content = json.loads(data_payload.content)
            processed = f"Processed: {content}"
        except:
            processed = f"Processed: {data_payload.content}"
        
        return ProcessResult(
            processed_content=processed,
            timestamp=datetime.now().isoformat(),
            request_number=self.request_count
        )

# Models
class DataPayload(Message):
    """Wrapper for data payload"""
    content: str  # JSON string
    metadata: Optional[str] = None

class ProcessRequest(Message):
    data: DataPayload
    priority: Optional[str] = "normal"

class ProcessResult(Message):
    """Result wrapper"""
    processed_content: str
    timestamp: str
    request_number: int

class ProcessResponse(Message):
    result: ProcessResult
    processing_time_ms: float
    protocol: str

# Public REST API (with auth, rate limiting, etc.)
app = FastAPI(title="Public API")
security = HTTPBearer()
processor = DataProcessor()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    if token != "demo-token":
        raise HTTPException(403, "Invalid token")
    return "demo-user"

class PublicProcessRequest(BaseModel):
    data: dict  # REST can use dict directly
    priority: Optional[str] = "normal"

@app.post("/api/v1/process")
async def process_public(
    request: PublicProcessRequest,
    user_id: str = Depends(verify_token)
):
    """Public endpoint with authentication"""
    import json
    start = time.time()
    
    # Convert dict to DataPayload for internal processing
    data_payload = DataPayload(
        content=json.dumps(request.data),
        metadata=request.priority
    )
    result = await processor.process_data(data_payload)
    
    return {
        "result": {
            "processed_content": result.processed_content,
            "timestamp": result.timestamp,
            "request_number": result.request_number
        },
        "processing_time_ms": (time.time() - start) * 1000,
        "protocol": "REST",
        "user": user_id
    }

# Connect RPC for partner integrations (middle ground)
class PartnerConnectService:
    def __init__(self, processor: DataProcessor):
        self.processor = processor
    
    async def ProcessPartner(self, request: ProcessRequest) -> ProcessResponse:
        """Partner endpoint - method name must be PascalCase for Connect RPC"""
        start = time.time()
        result = await self.processor.process_data(request.data)
        return ProcessResponse(
            result=result,
            processing_time_ms=(time.time() - start) * 1000,
            protocol="Connect-RPC"
        )

# Mount Connect RPC for partners into FastAPI
partner_service = PartnerConnectService(processor)
partner_app = ASGIApp()
partner_app.mount(partner_service)
app.mount("/partner", partner_app)

# Note: gRPC cannot run in the same process with FastAPI
# It requires a separate process on a different port (e.g., 50051)
# 
# IMPORTANT: Connect RPC endpoints include package name in URL path
# Example: /partner/partnerconnect.v1.PartnerConnectService/ProcessPartner
#          not just /partner/PartnerConnectService/ProcessPartner

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Testing the Hybrid Service:**

```bash
# Test REST endpoint with auth
curl -X POST http://localhost:8000/api/v1/process \
  -H "Authorization: Bearer demo-token" \
  -H "Content-Type: application/json" \
  -d '{"data": {"message": "Hello from REST"}, "priority": "high"}'

# Test Connect RPC endpoint (note the package name in URL)
curl -X POST http://localhost:8000/partner/partnerconnect.v1.PartnerConnectService/ProcessPartner \
  -H "Content-Type: application/json" \
  -d '{"data": {"content": "{\"message\": \"Hello from Connect RPC\"}", "metadata": "test"}, "priority": "normal"}'

# Get service stats
curl http://localhost:8000/api/v1/stats
```

## Pattern 4: Event-Driven Architecture with RPC

**Use Case:** Combining event streaming (Kafka/RabbitMQ) with RPC for command/query separation.

**Scenario:** Order processing system where commands are sent via RPC but events are published to message queue.

### Implementation: CQRS Pattern

```python
# order_command_service.py
from pydantic_rpc import ASGIApp, Message
from typing import Optional
import aiokafka
import uvicorn
from datetime import datetime

class CreateOrderCommand(Message):
    user_id: str
    items: List[dict]
    shipping_address: dict

class OrderCreatedEvent(Message):
    order_id: str
    user_id: str
    items: List[dict]
    created_at: str
    event_version: int = 1

class OrderCommandService:
    def __init__(self):
        self.kafka_producer = None
    
    async def startup(self):
        self.kafka_producer = aiokafka.AIOKafkaProducer(
            bootstrap_servers='kafka:9092',
            value_serializer=lambda v: json.dumps(v).encode()
        )
        await self.kafka_producer.start()
    
    async def create_order(self, command: CreateOrderCommand) -> Message:
        """Command: Create a new order"""
        # 1. Validate command
        if not command.items:
            raise ValueError("Order must have at least one item")
        
        # 2. Generate order ID
        order_id = generate_uuid()
        
        # 3. Store in event store
        event = OrderCreatedEvent(
            order_id=order_id,
            user_id=command.user_id,
            items=command.items,
            created_at=datetime.now().isoformat()
        )
        
        # 4. Publish event
        await self.kafka_producer.send(
            'order-events',
            event.model_dump()
        )
        
        # 5. Return command result
        return Message.model_validate({
            "order_id": order_id,
            "status": "accepted"
        })
    
    async def cancel_order(self, request: Message) -> Message:
        """Command: Cancel an order"""
        order_id = request.model_dump()["order_id"]
        
        # Publish cancellation event
        await self.kafka_producer.send(
            'order-events',
            {
                "event_type": "OrderCancelled",
                "order_id": order_id,
                "cancelled_at": datetime.now().isoformat()
            }
        )
        
        return Message.model_validate({"status": "cancelled"})

# Query service (separate deployment)
class OrderQueryService:
    def __init__(self):
        self.redis = None  # Read model
    
    async def get_order(self, request: Message) -> Message:
        """Query: Get order details"""
        order_id = request.model_dump()["order_id"]
        
        # Read from materialized view (Redis)
        order_data = await self.redis.get(f"order:{order_id}")
        if not order_data:
            raise ValueError("Order not found")
        
        return Message.model_validate(json.loads(order_data))
    
    async def list_user_orders(self, request: Message) -> Message:
        """Query: List orders for a user"""
        user_id = request.model_dump()["user_id"]
        
        # Read from materialized view
        order_ids = await self.redis.smembers(f"user_orders:{user_id}")
        orders = []
        for order_id in order_ids:
            order_data = await self.redis.get(f"order:{order_id}")
            if order_data:
                orders.append(json.loads(order_data))
        
        return Message.model_validate({"orders": orders})

# Event processor (separate deployment)
async def process_events():
    """Subscribe to Kafka and update read models"""
    consumer = aiokafka.AIOKafkaConsumer(
        'order-events',
        bootstrap_servers='kafka:9092',
        group_id='order-query-updater'
    )
    await consumer.start()
    
    redis = await aioredis.create_redis_pool('redis://redis')
    
    async for msg in consumer:
        event = json.loads(msg.value)
        
        if event.get('event_type') == 'OrderCreated' or 'order_id' in event:
            # Update read model in Redis
            order_id = event['order_id']
            await redis.set(f"order:{order_id}", json.dumps(event))
            await redis.sadd(f"user_orders:{event['user_id']}", order_id)
```

## Pattern 5: Service Mesh Integration

**Use Case:** Deploying RPC services in a service mesh (Istio/Linkerd) with observability and traffic management.

**Scenario:** Microservices architecture with automatic mTLS, circuit breaking, and distributed tracing.

### Implementation: Service Mesh Ready Deployment

```python
# service_with_telemetry.py
from pydantic_rpc import ASGIApp, Message
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram, generate_latest
import uvicorn
from fastapi import FastAPI
import time

# Setup OpenTelemetry
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)
otlp_exporter = OTLPSpanExporter(endpoint="otel-collector:4317")
span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

# Prometheus metrics
request_count = Counter('rpc_requests_total', 'Total RPC requests', ['method', 'status'])
request_duration = Histogram('rpc_request_duration_seconds', 'RPC request duration', ['method'])

class PaymentRequest(Message):
    amount: float
    currency: str
    user_id: str

class PaymentResponse(Message):
    transaction_id: str
    status: str
    processed_at: str

class PaymentService:
    async def process_payment(self, request: PaymentRequest) -> PaymentResponse:
        with tracer.start_as_current_span("process_payment") as span:
            start_time = time.time()
            
            # Add span attributes
            span.set_attribute("payment.amount", request.amount)
            span.set_attribute("payment.currency", request.currency)
            span.set_attribute("user.id", request.user_id)
            
            try:
                # Simulate payment processing
                with tracer.start_as_current_span("validate_payment"):
                    await self.validate_payment(request)
                
                with tracer.start_as_current_span("charge_payment"):
                    transaction_id = await self.charge_payment(request)
                
                # Record metrics
                request_count.labels(method="process_payment", status="success").inc()
                request_duration.labels(method="process_payment").observe(time.time() - start_time)
                
                return PaymentResponse(
                    transaction_id=transaction_id,
                    status="completed",
                    processed_at=datetime.now().isoformat()
                )
            
            except Exception as e:
                span.record_exception(e)
                request_count.labels(method="process_payment", status="error").inc()
                raise

# Combine RPC with metrics endpoint
app = FastAPI()

# Mount RPC service
rpc_app = ASGIApp()
rpc_app.mount(PaymentService())
app.mount("/", rpc_app)

# Metrics endpoint for Prometheus
@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")

# Health check for Kubernetes
@app.get("/healthz")
async def health():
    return {"status": "healthy"}

# Readiness check
@app.get("/ready")
async def ready():
    # Check dependencies
    return {"ready": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

**Kubernetes Deployment with Istio:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: payment-service
  labels:
    app: payment-service
spec:
  ports:
    - port: 8080
      name: http-rpc
    - port: 9090
      name: metrics
  selector:
    app: payment-service
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: payment-service
  template:
    metadata:
      labels:
        app: payment-service
      annotations:
        sidecar.istio.io/inject: "true"  # Enable Istio sidecar
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
        prometheus.io/path: "/metrics"
    spec:
      containers:
      - name: service
        image: payment-service:latest
        ports:
        - containerPort: 8080
        - containerPort: 9090
        env:
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://otel-collector:4317"
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
---
# Istio VirtualService for traffic management
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: payment-service
spec:
  hosts:
  - payment-service
  http:
  - match:
    - headers:
        x-version:
          exact: v2
    route:
    - destination:
        host: payment-service
        subset: v2
      weight: 100
  - route:
    - destination:
        host: payment-service
        subset: v1
      weight: 90
    - destination:
        host: payment-service
        subset: v2
      weight: 10  # Canary deployment
```

## Pattern 6: Testing Strategy

**Use Case:** Comprehensive testing of RPC services.

### Implementation: Test Harness

```python
# test_service_integration.py
import pytest
import grpc
import httpx
from unittest.mock import AsyncMock
import asyncio

class TestServiceIntegration:
    @pytest.fixture
    async def grpc_service(self):
        """Fixture for gRPC service"""
        server = AsyncIOServer()
        task = asyncio.create_task(
            server.run(TestService(), port=50052)
        )
        yield "localhost:50052"
        task.cancel()
    
    @pytest.fixture
    async def connect_service(self):
        """Fixture for Connect RPC service"""
        app = ASGIApp()
        app.mount(TestService())
        async with AsyncClient(app=app, base_url="http://test") as client:
            yield client
    
    @pytest.mark.asyncio
    async def test_grpc_endpoint(self, grpc_service):
        async with grpc.aio.insecure_channel(grpc_service) as channel:
            stub = TestServiceStub(channel)
            response = await stub.TestMethod(TestRequest(data="test"))
            assert response.result == "processed"
    
    @pytest.mark.asyncio
    async def test_connect_endpoint(self, connect_service):
        response = await connect_service.post(
            "/TestService/TestMethod",
            json={"data": "test"}
        )
        assert response.status_code == 200
        assert response.json()["result"] == "processed"
    
    @pytest.mark.asyncio
    async def test_load(self, connect_service):
        """Load test with concurrent requests"""
        async def make_request():
            return await connect_service.post(
                "/TestService/TestMethod",
                json={"data": "test"}
            )
        
        # Send 100 concurrent requests
        tasks = [make_request() for _ in range(100)]
        responses = await asyncio.gather(*tasks)
        
        assert all(r.status_code == 200 for r in responses)
```

## Choosing the Right Pattern

| Pattern | When to Use | Key Benefits |
|---------|------------|--------------|
| **Simple Microservice** | Single-purpose services | Easy to deploy and scale |
| **API Gateway/BFF** | Multiple backends, unified frontend API | Single entry point, aggregation |
| **Hybrid Public/Internal** | Different SLAs for different clients | Security isolation, performance optimization |
| **Event-Driven + RPC** | CQRS, event sourcing | Scalability, audit trail |
| **Service Mesh** | Large microservices deployment | Observability, traffic management |

## Key Architectural Decisions

### Protocol Selection
- **gRPC**: Service-to-service, need maximum performance
- **Connect RPC**: Need HTTP/1.1 compatibility, browser access
- **Both**: Different requirements for different clients

### Connect RPC URL Path Considerations
When using pydantic-rpc's ASGIApp for Connect RPC:
- URLs include the generated package name (e.g., `service.v1`)
- Full path format: `/{mount_path}/{package}.v1.{ServiceClass}/{MethodName}`
- Example: `/api/recommendation.v1.RecommendationService/GetRecommendations`
- This follows the standard Connect RPC and gRPC convention of using fully-qualified service names

### Deployment Strategy
- **Single Process**: Simplicity, shared resources
- **Multiple Processes**: Isolation, independent scaling
- **Service Mesh**: Advanced traffic management, observability

### State Management
- **Stateless**: Most RPC services should be stateless
- **Event Sourcing**: When audit trail is required
- **CQRS**: When read/write patterns differ significantly

This architecture-oriented guide should help you choose and implement the right pattern for your specific use case.
