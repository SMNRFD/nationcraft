#!/usr/bin/env python3
"""Real end-to-end test: starts the actual NationCraft API + a mock Telegram
Bot API server + the real aiogram bot, then exercises the full /register and
/login flows by pushing updates to the mock Telegram server and verifying
the bot's replies.

This is a TRUE end-to-end test — no mocks of the bot, no mocks of the API.
The only mock is the Telegram Bot API server (because we can't reach the
real api.telegram.org from a test environment, and even if we could, we
couldn't push updates to it).

Topology:
  ┌─────────────────┐         ┌──────────────────────┐
  │  Test Driver    │────────▶│  Mock Telegram API   │
  │  (this script)  │         │  (FastAPI, port 8081)│
  └─────────────────┘         └──────────┬───────────┘
                                         │ getUpdates / sendMessage
                                         ▼
                               ┌──────────────────────┐
                               │  Real aiogram Bot    │
                               │  (subprocess)        │
                               └──────────┬───────────┘
                                          │ httpx POST /auth/*
                                          ▼
                               ┌──────────────────────┐
                               │  Real FastAPI API    │
                               │  (subprocess, 8000)  │
                               │  + SQLite DB         │
                               └──────────────────────┘

Run:
    python scripts/e2e_real_bot_test.py

Exits 0 on success, 1 on any failure.
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_ROOT / "nationcraft_e2e_real.db"
SECRET = "e2e-real-" + "a3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4"

API_PORT = 8090
MOCK_TELEGRAM_PORT = 8081
BOT_TOKEN = "1234567890:fake-token-for-e2e-testing"


def _log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def _clean_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        p = DB_FILE.with_name(DB_FILE.name + suffix)
        if p.exists():
            try:
                p.unlink()
            except PermissionError:
                pass


def _make_api_env() -> dict[str, str]:
    """Build the env for the API subprocess.

    NOTE: We do NOT use --local here because --local overrides DATABASE_URL
    back to nationcraft.db. We set env vars directly so we can use a
    separate DB file for the test.
    """
    env = os.environ.copy()
    env.update(
        DATABASE_URL=f"sqlite+aiosqlite:///{DB_FILE.name}",
        REDIS_URL="",
        SECRET_KEY=SECRET,
        TELEGRAM_BOT_TOKEN="",   # API subprocess doesn't run the bot
        ENV="development",
        LOG_LEVEL="WARNING",
        LOG_FORMAT="json",
        API_HOST="127.0.0.1",
        API_PORT=str(API_PORT),
        API_BASE_URL=f"http://127.0.0.1:{API_PORT}",
    )
    return env


def _make_bot_env() -> dict[str, str]:
    """Build the env for the bot subprocess.

    The bot connects to the mock Telegram server instead of the real
    api.telegram.org. This is the key piece — the bot doesn't know it's
    not talking to the real Telegram.
    """
    env = os.environ.copy()
    env.update(
        DATABASE_URL=f"sqlite+aiosqlite:///{DB_FILE.name}",
        REDIS_URL="",
        SECRET_KEY=SECRET,
        TELEGRAM_BOT_TOKEN=BOT_TOKEN,
        TELEGRAM_API_BASE=f"http://127.0.0.1:{MOCK_TELEGRAM_PORT}",
        TELEGRAM_PROXY="",
        TELEGRAM_REQUEST_TIMEOUT="10",
        ENV="development",
        LOG_LEVEL="WARNING",
        LOG_FORMAT="json",
        API_BASE_URL=f"http://127.0.0.1:{API_PORT}",
        # Avoid the Docker-hostname validator complaining.
        POSTGRES_HOST="127.0.0.1",
    )
    return env


def _make_mock_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(LOG_LEVEL="WARNING")
    return env


async def _wait_for(url: str, timeout: float = 20.0, label: str = "service") -> bool:
    """Poll a URL until it returns 200 or timeout expires."""
    deadline = time.perf_counter() + timeout
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.perf_counter() < deadline:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return True
            except Exception:
                await asyncio.sleep(0.3)
    _log(f"  ✗ {label} did not come up at {url} within {timeout}s")
    return False


async def _push_command(client: httpx.AsyncClient, chat_id: int, user_id: int, command: str, args: str = "", username: str = "e2e_tester") -> dict:
    """Push a /command update to the mock Telegram server."""
    r = await client.post(
        f"http://127.0.0.1:{MOCK_TELEGRAM_PORT}/test/push_command",
        json={
            "chat_id": chat_id,
            "user_id": user_id,
            "command": command,
            "args": args,
            "username": username,
            "first_name": "E2E Tester",
            "language_code": "en",
        },
        timeout=5.0,
    )
    r.raise_for_status()
    return r.json()


async def _push_message(client: httpx.AsyncClient, chat_id: int, user_id: int, text: str, username: str = "e2e_tester") -> dict:
    """Push a plain-text message update to the mock Telegram server."""
    r = await client.post(
        f"http://127.0.0.1:{MOCK_TELEGRAM_PORT}/test/push_message",
        json={
            "chat_id": chat_id,
            "user_id": user_id,
            "text": text,
            "username": username,
            "first_name": "E2E Tester",
            "language_code": "en",
        },
        timeout=5.0,
    )
    r.raise_for_status()
    return r.json()


async def _get_sent_messages(client: httpx.AsyncClient, chat_id: int) -> list[dict]:
    """Fetch all messages the bot sent to a given chat via sendMessage."""
    r = await client.get(
        f"http://127.0.0.1:{MOCK_TELEGRAM_PORT}/test/sent_messages/{chat_id}",
        timeout=5.0,
    )
    r.raise_for_status()
    return r.json()["messages"]


async def _reset_mock(client: httpx.AsyncClient) -> None:
    """Clear all state on the mock Telegram server."""
    r = await client.post(f"http://127.0.0.1:{MOCK_TELEGRAM_PORT}/test/reset", timeout=5.0)
    r.raise_for_status()


async def _wait_for_reply(
    client: httpx.AsyncClient,
    chat_id: int,
    *,
    match: str | None = None,
    timeout: float = 15.0,
    min_count: int = 1,
) -> list[dict]:
    """Wait until the bot has sent at least ``min_count`` messages to
    ``chat_id``. If ``match`` is provided, wait until at least one message
    contains that substring (case-insensitive).
    """
    deadline = time.perf_counter() + timeout
    last_seen: list[dict] = []
    while time.perf_counter() < deadline:
        msgs = await _get_sent_messages(client, chat_id)
        last_seen = msgs
        if len(msgs) >= min_count:
            if match is None:
                return msgs
            for m in msgs:
                if match.lower() in (m.get("text") or "").lower():
                    return msgs
        await asyncio.sleep(0.5)
    raise AssertionError(
        f"timed out waiting for bot reply (chat={chat_id}, match={match!r}, "
        f"min_count={min_count}). Last saw {len(last_seen)} message(s): "
        f"{[m.get('text', '')[:80] for m in last_seen]}"
    )


async def _register_via_api(client: httpx.AsyncClient, telegram_id: int, password: str, username: str) -> dict:
    """Register a player directly via the API (bypassing the bot)."""
    r = await client.post(
        f"http://127.0.0.1:{API_PORT}/auth/register",
        json={"telegram_id": telegram_id, "password": password, "username": username, "locale": "en"},
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()["data"]


async def main() -> int:
    _clean_db()

    # ---- Start the mock Telegram server ----
    _log("Starting mock Telegram Bot API server...")
    mock_proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "mock_telegram_server.py"),
         "--port", str(MOCK_TELEGRAM_PORT), "--token", BOT_TOKEN],
        cwd=str(PROJECT_ROOT),
        env=_make_mock_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        if not await _wait_for(f"http://127.0.0.1:{MOCK_TELEGRAM_PORT}/test/health", label="mock telegram"):
            out = mock_proc.stdout.read().decode() if mock_proc.stdout else ""
            _log("Mock Telegram server failed to start. Output:\n" + out[-2000:])
            return 1
        _log("  ✓ Mock Telegram server is up")

        # ---- initdb ----
        _log("Running initdb...")
        initdb_proc = subprocess.run(
            [sys.executable, "main.py", "--initdb"],
            cwd=str(PROJECT_ROOT), env=_make_api_env(),
            capture_output=True, timeout=60,
        )
        if initdb_proc.returncode != 0:
            _log("initdb failed:\n" + initdb_proc.stderr.decode()[-2000:])
            return 1
        _log("  ✓ Database initialized")

        # ---- Start the API ----
        _log("Starting API server...")
        api_proc = subprocess.Popen(
            [sys.executable, "main.py", "--only", "api"],
            cwd=str(PROJECT_ROOT), env=_make_api_env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            if not await _wait_for(f"http://127.0.0.1:{API_PORT}/health", label="api"):
                out = api_proc.stdout.read().decode() if api_proc.stdout else ""
                _log("API failed to start. Output:\n" + out[-2000:])
                return 1
            _log("  ✓ API server is up")

            # ---- Start the bot ----
            _log("Starting bot (connecting to mock Telegram server)...")
            bot_proc = subprocess.Popen(
                [sys.executable, "main.py", "--only", "bot"],
                cwd=str(PROJECT_ROOT), env=_make_bot_env(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            try:
                # Wait for the bot to start polling by checking getMe stat.
                async with httpx.AsyncClient(timeout=3.0) as poll_client:
                    bot_up = False
                    deadline = time.perf_counter() + 15
                    while time.perf_counter() < deadline:
                        try:
                            r = await poll_client.get(f"http://127.0.0.1:{MOCK_TELEGRAM_PORT}/test/stats")
                            stats = r.json()["stats"]
                            if stats.get("getMe", 0) >= 1:
                                bot_up = True
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(0.5)
                    if not bot_up:
                        out = bot_proc.stdout.read().decode() if bot_proc.stdout else ""
                        _log("Bot did not call getMe within 15s. Output:\n" + out[-2000:])
                        return 1
                _log("  ✓ Bot is polling the mock Telegram server")

                # ===== TEST SCENARIOS =====
                async with httpx.AsyncClient(timeout=10.0) as client:
                    CHAT_ID = 11111
                    USER_ID = 847898161

                    # ---- Scenario 1: /start → welcome message ----
                    _log("Test 1: /start command...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "start")
                    msgs = await _wait_for_reply(client, CHAT_ID, match="welcome", timeout=10.0)
                    assert any("welcome" in m["text"].lower() or "register" in m["text"].lower() for m in msgs), \
                        f"expected welcome/register message, got: {[m['text'][:80] for m in msgs]}"
                    _log("  ✓ /start returned a welcome message")

                    # ---- Scenario 2: /register → asks for password ----
                    _log("Test 2: /register command (fresh user)...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "register")
                    msgs = await _wait_for_reply(client, CHAT_ID, match="password", timeout=10.0)
                    assert any("password" in m["text"].lower() for m in msgs), \
                        f"expected 'password' prompt, got: {[m['text'][:80] for m in msgs]}"
                    _log("  ✓ /register prompted for password")

                    # ---- Scenario 3: send password → /auth/register called ----
                    _log("Test 3: send password (registration)...")
                    await _reset_mock(client)
                    # First push /register to enter the FSM state.
                    await _push_command(client, CHAT_ID, USER_ID, "register")
                    await _wait_for_reply(client, CHAT_ID, match="password", timeout=10.0)
                    # Now push the password.
                    await _push_message(client, CHAT_ID, USER_ID, "TestPass1234")
                    msgs = await _wait_for_reply(client, CHAT_ID, match="saved", timeout=15.0)
                    assert any("saved" in m["text"].lower() or "welcome" in m["text"].lower() for m in msgs), \
                        f"expected success message, got: {[m['text'][:80] for m in msgs]}"
                    _log("  ✓ Registration succeeded — bot replied with success")

                    # Verify the player was actually created in the DB via the API.
                    r = await client.get(
                        f"http://127.0.0.1:{API_PORT}/auth/me",
                        # We can't easily get the bot's token here, so just verify the
                        # player exists by attempting a login.
                    )
                    # Login directly via the API to verify.
                    r = await client.post(
                        f"http://127.0.0.1:{API_PORT}/auth/login",
                        json={"telegram_id": USER_ID, "password": "TestPass1234"},
                        timeout=10.0,
                    )
                    assert r.status_code == 200, f"login after register failed: {r.status_code} {r.text}"
                    _log("  ✓ Player was created in the DB (login works)")

                    # ---- Scenario 4: /register again → "already registered" ----
                    _log("Test 4: /register again (already registered)...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "register")
                    # The bot now has a token cached from the previous registration.
                    # It should say "already registered" without asking for a password.
                    msgs = await _wait_for_reply(client, CHAT_ID, match="already", timeout=10.0)
                    assert any("already" in m["text"].lower() for m in msgs), \
                        f"expected 'already registered', got: {[m['text'][:80] for m in msgs]}"
                    _log("  ✓ Bot recognized existing user (already registered)")

                    # ---- Scenario 5: /login → asks for password ----
                    _log("Test 5: /login command...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "login")
                    msgs = await _wait_for_reply(client, CHAT_ID, match="password", timeout=10.0)
                    assert any("password" in m["text"].lower() for m in msgs), \
                        f"expected password prompt, got: {[m['text'][:80] for m in msgs]}"
                    _log("  ✓ /login prompted for password")

                    # ---- Scenario 6: send correct password → login success ----
                    _log("Test 6: send correct password (login)...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "login")
                    await _wait_for_reply(client, CHAT_ID, match="password", timeout=10.0)
                    await _push_message(client, CHAT_ID, USER_ID, "TestPass1234")
                    msgs = await _wait_for_reply(client, CHAT_ID, match="logged", timeout=15.0)
                    assert any("logged" in m["text"].lower() or "success" in m["text"].lower() for m in msgs), \
                        f"expected login success, got: {[m['text'][:80] for m in msgs]}"
                    _log("  ✓ Login succeeded — bot replied with success")

                    # ---- Scenario 7: /status → shows diagnostic info ----
                    _log("Test 7: /status command...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "status")
                    msgs = await _wait_for_reply(client, CHAT_ID, match="Bot status", timeout=10.0)
                    assert any("bot status" in m["text"].lower() for m in msgs), \
                        f"expected status message, got: {[m['text'][:80] for m in msgs]}"
                    # The status message should show API status as ok.
                    assert any("api status: ok" in m["text"].lower() for m in msgs), \
                        f"expected API status ok, got: {[m['text'][:200] for m in msgs]}"
                    _log("  ✓ /status shows API status ok")

                    # ---- Scenario 8: /help → shows help text ----
                    _log("Test 8: /help command...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "help")
                    msgs = await _wait_for_reply(client, CHAT_ID, timeout=10.0)
                    assert len(msgs) >= 1, "expected at least one reply for /help"
                    _log("  ✓ /help returned a reply")

                    # ---- Scenario 9: /cancel → clears state ----
                    _log("Test 9: /cancel command...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "cancel")
                    msgs = await _wait_for_reply(client, CHAT_ID, timeout=10.0)
                    assert len(msgs) >= 1, "expected at least one reply for /cancel"
                    _log("  ✓ /cancel returned a reply")

                    # ---- Scenario 10: Wrong password → login failed ----
                    _log("Test 10: wrong password (login should fail)...")
                    await _reset_mock(client)
                    await _push_command(client, CHAT_ID, USER_ID, "login")
                    await _wait_for_reply(client, CHAT_ID, match="password", timeout=10.0)
                    await _push_message(client, CHAT_ID, USER_ID, "WrongPassword99")
                    msgs = await _wait_for_reply(client, CHAT_ID, match="failed", timeout=15.0)
                    assert any("failed" in m["text"].lower() or "invalid" in m["text"].lower() for m in msgs), \
                        f"expected login failed message, got: {[m['text'][:80] for m in msgs]}"
                    _log("  ✓ Wrong password correctly rejected")

                print()
                print("=" * 70)
                print("  ALL 10 E2E TESTS PASSED")
                print("=" * 70)
                return 0
            finally:
                _log("Stopping bot...")
                bot_proc.send_signal(signal.SIGINT)
                try:
                    bot_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    bot_proc.kill()
                    bot_proc.wait()
        finally:
            _log("Stopping API...")
            api_proc.send_signal(signal.SIGINT)
            try:
                api_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                api_proc.kill()
                api_proc.wait()
    finally:
        _log("Stopping mock Telegram server...")
        mock_proc.send_signal(signal.SIGINT)
        try:
            mock_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock_proc.kill()
            mock_proc.wait()
        _clean_db()

    return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
