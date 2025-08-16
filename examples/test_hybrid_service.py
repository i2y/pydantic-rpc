#!/usr/bin/env python3
"""
Test client for hybrid service example.
Run this after starting hybrid_service_working.py
"""

import asyncio
import httpx
import json

async def test_all_endpoints():
    async with httpx.AsyncClient() as client:
        print("=" * 60)
        print("Testing Hybrid Service Endpoints")
        print("=" * 60)
        
        # Test service info
        print("\n1. Service Info (GET /):")
        response = await client.get("http://localhost:8000/")
        print(json.dumps(response.json(), indent=2))
        
        # Test public REST API
        print("\n2. Public REST API (requires auth):")
        response = await client.post(
            "http://localhost:8000/api/v1/process",
            json={"data": {"message": "Hello from REST"}, "priority": "high"},
            headers={"Authorization": "Bearer demo-token"}
        )
        print(json.dumps(response.json(), indent=2))
        
        # Test public REST API without auth (should fail)
        print("\n3. Public REST API without auth (should fail):")
        response = await client.post(
            "http://localhost:8000/api/v1/process",
            json={"data": {"message": "No auth"}}
        )
        print(f"Status: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.json()}")
        
        # Test partner Connect RPC
        print("\n4. Partner Connect RPC:")
        response = await client.post(
            "http://localhost:8000/partner/partnerconnect.v1.PartnerConnectService/ProcessPartner",
            json={
                "data": {
                    "content": json.dumps({"message": "Hello from Connect RPC"}),
                    "metadata": "test"
                },
                "priority": "normal"
            }
        )
        print(json.dumps(response.json(), indent=2))
        
        # Test stats endpoint
        print("\n5. Stats endpoint:")
        response = await client.get("http://localhost:8000/api/v1/stats")
        print(json.dumps(response.json(), indent=2))
        
        print("\n" + "=" * 60)
        print("Note: gRPC endpoint (port 50051) requires a gRPC client")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_all_endpoints())
