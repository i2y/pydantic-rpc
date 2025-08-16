#!/usr/bin/env python3
"""
Fixed example of hybrid service with multiple protocols.
This demonstrates running Connect RPC with FastAPI in a single process.
gRPC would need to run as a separate process.
"""

from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic_rpc import ASGIApp, Message
from pydantic import BaseModel
import uvicorn
import time
from typing import Optional
from datetime import datetime

# ========== Shared Models ==========
class DataPayload(Message):
    """Wrapper for data payload"""
    content: str  # JSON string for simplicity
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
    protocol: str  # Which protocol was used

# ========== Shared Business Logic ==========
class DataProcessor:
    """Core business logic shared by all API layers"""
    
    def __init__(self):
        self.request_count = 0
    
    async def process_data(self, data_payload: DataPayload) -> ProcessResult:
        """Process data - same logic for all protocols"""
        import asyncio
        self.request_count += 1
        await asyncio.sleep(0.1)  # Simulate processing
        
        # Parse the content (in real app, would do actual processing)
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
    
    async def get_stats(self) -> dict:
        """Get processing statistics"""
        return {
            "total_requests": self.request_count,
            "status": "healthy"
        }

# ========== Connect RPC Service (Partners) ==========
class PartnerConnectService:
    """Partner API via Connect RPC - simpler auth"""
    
    def __init__(self, processor: DataProcessor):
        self.processor = processor
    
    async def process_partner(self, request: ProcessRequest) -> ProcessResponse:
        """Partner processing endpoint"""
        # In real app, would validate partner API key from headers
        start = time.time()
        result = await self.processor.process_data(request.data)
        
        return ProcessResponse(
            result=result,
            processing_time_ms=(time.time() - start) * 1000,
            protocol="Connect-RPC"
        )

# ========== FastAPI REST (Public) ==========
app = FastAPI(title="Hybrid Service - Public API")
security = HTTPBearer()

# Create shared processor
processor = DataProcessor()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Simple token verification for demo"""
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
    """Public REST endpoint with authentication"""
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

@app.get("/api/v1/stats")
async def get_stats_public():
    """Public stats endpoint - no auth for demo"""
    stats = await processor.get_stats()
    return stats

@app.get("/")
async def root():
    """Service information"""
    return {
        "service": "Hybrid Service Example",
        "endpoints": {
            "public_rest": {
                "url": "POST /api/v1/process",
                "auth": "Bearer token required",
                "description": "Public REST API"
            },
            "partner_rpc": {
                "url": "POST /partner/partnerconnect.v1.PartnerConnectService/ProcessPartner",
                "auth": "Partner API key (not enforced in demo)",
                "description": "Partner Connect RPC"
            },
            "stats": {
                "url": "GET /api/v1/stats",
                "auth": "None",
                "description": "Service statistics"
            }
        },
        "test_token": "demo-token",
        "note": "gRPC would run on a separate port (e.g., 50051) in production"
    }

# ========== Mount Connect RPC into FastAPI ==========
partner_service = PartnerConnectService(processor)
partner_app = ASGIApp()
partner_app.mount(partner_service)
app.mount("/partner", partner_app)

# ========== Run Server ==========
if __name__ == "__main__":
    print("=" * 60)
    print("Hybrid Service Example (Fixed)")
    print("=" * 60)
    print()
    print("Starting server:")
    print("  - HTTP (public + partner): localhost:8000")
    print()
    print("Test endpoints:")
    print("  - Service info: GET http://localhost:8000/")
    print("  - Public REST: POST http://localhost:8000/api/v1/process")
    print("    Header: Authorization: Bearer demo-token")
    print("  - Partner RPC: POST http://localhost:8000/partner/partnerconnect.v1.PartnerConnectService/ProcessPartner")
    print("  - Stats: GET http://localhost:8000/api/v1/stats")
    print()
    print("=" * 60)
    
    # Run FastAPI with Connect RPC mounted
    uvicorn.run(app, host="0.0.0.0", port=8000)
