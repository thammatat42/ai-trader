"""End-to-end smoke test for Epic 1 auth endpoints."""
import asyncio
import httpx

BASE = "http://127.0.0.1:8000/api/v1"


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        # 1. Health
        r = await c.get("/health")
        print(f"[1] GET /health => {r.status_code}")

        # 2. Register first user (admin-first logic)
        r = await c.post("/auth/register", json={
            "email": "admin@test.com",
            "password": "Admin123!",
            "full_name": "Admin User",
        })
        print(f"[2] POST /auth/register (1st) => {r.status_code} role={r.json().get('role', r.json())}")

        # 3. Login
        r = await c.post("/auth/login", json={
            "email": "admin@test.com",
            "password": "Admin123!",
        })
        print(f"[3] POST /auth/login => {r.status_code}")
        tokens = r.json()
        access = tokens["access_token"]
        refresh = tokens["refresh_token"]
        h = {"Authorization": f"Bearer {access}"}

        # 4. GET /users/me
        r = await c.get("/users/me", headers=h)
        me = r.json()
        print(f"[4] GET /users/me => {r.status_code} email={me.get('email')} role={me.get('role')}")

        # 5. PUT /users/me
        r = await c.put("/users/me", headers=h, json={"full_name": "Admin Updated"})
        print(f"[5] PUT /users/me => {r.status_code} name={r.json().get('full_name')}")

        # 6. Register second user (should be trader)
        r = await c.post("/auth/register", json={
            "email": "trader@test.com",
            "password": "Trader123!",
            "full_name": "Trader User",
        })
        print(f"[6] POST /auth/register (2nd) => {r.status_code} role={r.json().get('role', r.json())}")

        # 7. GET /users (admin list)
        r = await c.get("/users", headers=h)
        print(f"[7] GET /users (admin) => {r.status_code} count={len(r.json())}")

        # 8. Login as trader
        r = await c.post("/auth/login", json={
            "email": "trader@test.com",
            "password": "Trader123!",
        })
        trader_tokens = r.json()
        th = {"Authorization": f"Bearer {trader_tokens['access_token']}"}

        # 9. Trader cannot list all users (RBAC)
        r = await c.get("/users", headers=th)
        print(f"[8] GET /users (trader, expect 403) => {r.status_code}")

        # 10. Create API key
        r = await c.post("/api-keys", headers=h, json={"name": "test-key"})
        print(f"[9] POST /api-keys => {r.status_code} prefix={r.json().get('key_prefix')}")
        api_key_id = r.json().get("id")
        full_key = r.json().get("full_key")

        # 11. List API keys
        r = await c.get("/api-keys", headers=h)
        print(f"[10] GET /api-keys => {r.status_code} count={len(r.json())}")

        # 12. Auth via API key
        r = await c.get("/users/me", headers={"X-API-Key": full_key})
        print(f"[11] GET /users/me (API key) => {r.status_code} email={r.json().get('email', r.json())}")

        # 13. Revoke API key
        r = await c.delete(f"/api-keys/{api_key_id}", headers=h)
        print(f"[12] DELETE /api-keys/{api_key_id} => {r.status_code}")

        # 14. Refresh token
        r = await c.post("/auth/refresh", json={"refresh_token": refresh})
        print(f"[13] POST /auth/refresh => {r.status_code}")
        new_access = r.json().get("access_token", "")
        new_h = {"Authorization": f"Bearer {new_access}"}

        # 15. Logout
        r = await c.post("/auth/logout", headers=new_h)
        print(f"[14] POST /auth/logout => {r.status_code}")

        # 16. Token blocked after logout
        r = await c.get("/users/me", headers=new_h)
        print(f"[15] GET /users/me (after logout, expect 401) => {r.status_code}")

        # Rate-limit headers check
        r = await c.get("/health")
        rl_headers = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower()}
        print(f"[16] Rate-limit headers: {rl_headers}")

    print("\n=== ALL TESTS COMPLETE ===")


if __name__ == "__main__":
    asyncio.run(main())
