"""Quick smoke test for Epic 2 endpoints."""
import asyncio
import httpx

async def test():
    async with httpx.AsyncClient(base_url="http://localhost:8000") as c:
        # Login
        r = await c.post("/api/v1/auth/login", json={"email": "admin@test.com", "password": "admin123"})
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # Trades
        r = await c.get("/api/v1/trades", headers=h)
        print(f"GET /trades: {r.status_code}")
        assert r.status_code == 200

        r = await c.get("/api/v1/trades/positions", headers=h)
        print(f"GET /trades/positions: {r.status_code}")
        assert r.status_code == 200

        r = await c.get("/api/v1/trades/history", headers=h)
        print(f"GET /trades/history: {r.status_code}")
        assert r.status_code == 200

        r = await c.get("/api/v1/trades/summary", headers=h)
        print(f"GET /trades/summary: {r.status_code} -> {r.json()}")
        assert r.status_code == 200

        # Platforms
        r = await c.get("/api/v1/platforms", headers=h)
        print(f"GET /platforms: {r.status_code}")
        assert r.status_code == 200

        r = await c.get("/api/v1/platforms/types", headers=h)
        print(f"GET /platforms/types: {r.status_code} -> {r.json()}")
        assert r.status_code == 200

        # Create a test platform
        r = await c.post("/api/v1/platforms", headers=h, json={
            "name": "MT5 Demo",
            "platform_type": "mt5",
            "endpoint_url": "http://10.0.0.1:8000",
            "config_json": {"symbols": ["XAUUSD"], "magic": 888888},
            "market_hours": "forex",
        })
        print(f"POST /platforms: {r.status_code}")
        assert r.status_code == 201
        pid = r.json()["id"]

        # Get single
        r = await c.get(f"/api/v1/platforms/{pid}", headers=h)
        print(f"GET /platforms/{{id}}: {r.status_code}")
        assert r.status_code == 200

        # Update
        r = await c.put(f"/api/v1/platforms/{pid}", headers=h, json={"is_active": True})
        print(f"PUT /platforms/{{id}}: {r.status_code}")
        assert r.status_code == 200

        # Test connection (will fail since no real bridge)
        r = await c.post(f"/api/v1/platforms/{pid}/test", headers=h)
        print(f"POST /platforms/{{id}}/test: {r.status_code} -> connected={r.json().get('connected')}")
        assert r.status_code == 200

        # Delete
        r = await c.delete(f"/api/v1/platforms/{pid}", headers=h)
        print(f"DELETE /platforms/{{id}}: {r.status_code}")
        assert r.status_code == 204

        print("\n=== ALL TESTS PASSED ===")

asyncio.run(test())
