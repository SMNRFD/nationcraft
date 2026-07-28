"""End-to-end smoke test: start the API in a subprocess and exercise the
auth + refresh flow against the real HTTP server.

NOTE: We don't use the `--local` flag because it overrides DATABASE_URL
back to `nationcraft.db` regardless of env vars. Instead we set the env
vars explicitly so we can use a separate DB file for the test.
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx


PROJECT_ROOT = Path("/home/z/my-project/nationcraft")
DB_FILE = PROJECT_ROOT / "nationcraft_e2e.db"
SECRET = "a3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4"


def _clean_db():
    """Remove the DB file and its WAL/SHM sidecars."""
    for suffix in ("", "-wal", "-shm"):
        p = DB_FILE.with_name(DB_FILE.name + suffix)
        if p.exists():
            try:
                p.unlink()
            except PermissionError:
                pass


async def _wait_for_api(client, timeout=15):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            r = await client.get("/health")
            if r.status_code == 200:
                return True
        except Exception:
            await asyncio.sleep(0.2)
    return False


def _make_env():
    """Build the env for the API subprocess. We do NOT use --local here
    because --local overrides DATABASE_URL back to nationcraft.db.
    """
    env = os.environ.copy()
    env.update(
        DATABASE_URL=f"sqlite+aiosqlite:///{DB_FILE.name}",
        REDIS_URL="redis://localhost:6379/0",
        SECRET_KEY=SECRET,
        TELEGRAM_BOT_TOKEN="",
        ENV="development",
        LOG_LEVEL="WARNING",
        LOG_FORMAT="json",
        # Override the postgres defaults so the validator doesn't
        # complain about docker-only hostnames.
        POSTGRES_HOST="localhost",
    )
    return env


async def main():
    _clean_db()
    env = _make_env()

    print("→ initdb ...", flush=True)
    subprocess.run(
        [sys.executable, "main.py", "--initdb"],
        cwd=str(PROJECT_ROOT), env=env, check=True, capture_output=True, timeout=30,
    )

    print("→ starting API ...", flush=True)
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--only", "api"],
        cwd=str(PROJECT_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=5.0) as client:
            if not await _wait_for_api(client):
                out = proc.stdout.read().decode() if proc.stdout else ""
                print("API failed to start. Output:")
                print(out[-3000:])
                return 1

            print("✓ API is ready", flush=True)

            # 4. Register a new player
            print("→ register ...", flush=True)
            r = await client.post("/auth/register", json={
                "telegram_id": 123456,
                "password": "testpassword123",
                "username": "e2e_tester",
                "locale": "en",
            })
            assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
            data = r.json()["data"]
            access = data["access_token"]
            refresh = data["refresh_token"]
            print(f"  ✓ registered, player_id={data['player']['id']}")

            # 5. /auth/me with the access token
            print("→ /auth/me ...", flush=True)
            r = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
            assert r.status_code == 200, f"/auth/me failed: {r.status_code} {r.text}"
            print(f"  ✓ /auth/me ok, locale={r.json()['data']['locale']}")

            # 6. Register again — should 409 conflict
            print("→ duplicate register ...", flush=True)
            r = await client.post("/auth/register", json={
                "telegram_id": 123456,
                "password": "differentpassword456",
                "username": "other",
            })
            assert r.status_code == 409, f"expected 409, got {r.status_code}"
            print(f"  ✓ duplicate register returned 409 as expected")

            # 7. Login with wrong password — should 401
            print("→ wrong password login ...", flush=True)
            r = await client.post("/auth/login", json={
                "telegram_id": 123456,
                "password": "wrongpassword999",
            })
            assert r.status_code == 401, f"expected 401, got {r.status_code}"
            print(f"  ✓ wrong login returned 401 as expected")

            # 8. Login with correct password
            print("→ correct login ...", flush=True)
            r = await client.post("/auth/login", json={
                "telegram_id": 123456,
                "password": "testpassword123",
            })
            assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
            new_access = r.json()["data"]["access_token"]
            assert new_access != access, "new login should issue a new access token"
            print(f"  ✓ login ok, new token issued")

            # 9. Refresh the access token
            print("→ refresh ...", flush=True)
            r = await client.post("/auth/refresh", json={"refresh_token": refresh})
            assert r.status_code == 200, f"refresh failed: {r.status_code} {r.text}"
            rotated_access = r.json()["data"]["access_token"]
            rotated_refresh = r.json()["data"]["refresh_token"]
            assert rotated_access != new_access, "refresh should issue a new access token"
            assert rotated_refresh != refresh, "refresh should rotate the refresh token"
            print(f"  ✓ refresh ok, tokens rotated")

            # 10. Old refresh token should now be invalid
            print("→ old refresh rejected ...", flush=True)
            r = await client.post("/auth/refresh", json={"refresh_token": refresh})
            assert r.status_code == 401, f"expected 401, got {r.status_code}"
            print(f"  ✓ old refresh rejected as expected")

            # 11. Use the rotated access token on /auth/me
            print("→ /auth/me with rotated token ...", flush=True)
            r = await client.get("/auth/me", headers={"Authorization": f"Bearer {rotated_access}"})
            assert r.status_code == 200, f"/auth/me with rotated failed: {r.status_code} {r.text}"
            print(f"  ✓ /auth/me ok with rotated token")

            # 12. /health/ready — should report DB ok, Redis error (no Redis)
            print("→ /health/ready ...", flush=True)
            r = await client.get("/health/ready")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "degraded"  # Redis is down
            assert body["checks"]["db"] == "ok"
            print(f"  ✓ /health/ready: db=ok, redis=down (degraded)")

            # 13. /worlds (authenticated) — should return at least 1 world seeded by initdb
            print("→ /worlds (auth) ...", flush=True)
            r = await client.get("/worlds", headers={"Authorization": f"Bearer {rotated_access}"})
            assert r.status_code == 200, f"/worlds failed: {r.status_code} {r.text}"
            worlds = r.json()["data"]
            assert len(worlds) >= 1, f"expected at least 1 world, got {len(worlds)}"
            print(f"  ✓ /worlds ok, {len(worlds)} world(s) available")

            print()
            print("=" * 60)
            print("ALL E2E CHECKS PASSED")
            print("=" * 60)
            return 0
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _clean_db()


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
