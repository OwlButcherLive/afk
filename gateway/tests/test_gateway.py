#!/usr/bin/env python3
"""End-to-end test: REST + WebSocket for the Agent Gateway.

Run from the gateway/ directory:
    cd afk/gateway
    pip install -r requirements.txt
    python -m uvicorn gateway.main:app --host 127.0.0.1 --port 3344 &
    python tests/test_gateway.py
"""

import asyncio
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:3344"

# Create a session once for WS tests
def _create_default_session() -> str:
    """Create a session and return its ID."""
    req = urllib.request.Request(
        f"{BASE}/chat/sessions",
        data=json.dumps({"agent_id": "default"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    return data["id"]


def test_rest():
    print("--- REST tests ---")

    # Health
    resp = urllib.request.urlopen(f"{BASE}/health")
    data = json.loads(resp.read())
    assert data == {"status": "ok"}, f"Health failed: {data}"
    print("  ✅ GET /health")

    # Agents
    resp = urllib.request.urlopen(f"{BASE}/chat/agents")
    data = json.loads(resp.read())
    assert "agents" in data
    assert data["agents"][0]["id"] == "default"
    print("  ✅ GET /chat/agents")

    # History (empty)
    resp = urllib.request.urlopen(f"{BASE}/chat/history?agent=default&limit=10")
    data = json.loads(resp.read())
    assert data == {"messages": []}, f"History not empty: {data}"
    print("  ✅ GET /chat/history (empty)")

    # Agent not found
    try:
        urllib.request.urlopen(f"{BASE}/chat/history?agent=nonexistent")
        assert False, "Should have raised 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
        print("  ✅ GET /chat/history (404 for unknown agent)")

    # Sessions
    resp = urllib.request.urlopen(f"{BASE}/chat/sessions")
    data = json.loads(resp.read())
    assert "sessions" in data
    assert len(data["sessions"]) >= 1
    print("  ✅ GET /chat/sessions")

    # Create session
    sess_id = _create_default_session()
    assert sess_id.startswith("sess_")
    print("  ✅ POST /chat/sessions (created)")

    # Get session by ID
    resp = urllib.request.urlopen(f"{BASE}/chat/sessions/{sess_id}")
    data = json.loads(resp.read())
    assert data["id"] == sess_id
    assert data["agent_id"] == "default"
    print("  ✅ GET /chat/sessions/{id}")

    # History by session (should be empty for new session)
    resp = urllib.request.urlopen(f"{BASE}/chat/history?session={sess_id}&limit=10")
    data = json.loads(resp.read())
    assert data == {"messages": []}, f"Session history not empty: {data}"
    print("  ✅ GET /chat/history?session= (empty)")

    print("  ✅ All REST tests passed")


async def test_ws():
    print("\n--- WebSocket tests ---")
    try:
        import websockets
    except ImportError:
        print("  ⚠️  websockets module not installed, skipping WS tests")
        return

    uri = "ws://127.0.0.1:3344/ws/chat"

    async with websockets.connect(uri) as ws:
        # 1. Initial agent_status
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        event = json.loads(raw)
        assert event["type"] == "agent_status"
        assert event["agent_id"] == "default"
        assert event["status"] == "online"
        print("  ✅ Initial agent_status event")

        # Create a session for WS test
        sess_id = _create_default_session()
        print(f"  📋 Using session: {sess_id}")

        # 2. Send a message with session_id
        await ws.send(json.dumps({
            "type": "message",
            "session_id": sess_id,
            "agent_id": "default",
            "text": "hello"
        }))

        # Collect responses (user echo, typing on, typing off, agent reply)
        events = []
        for _ in range(4):
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            events.append(json.loads(raw))

        # Response 0: user message echo
        assert events[0]["type"] == "message"
        assert events[0]["role"] == "user"
        assert events[0]["text"] == "hello"
        print("  ✅ User message persisted and echoed")

        # Response 1: typing on
        assert events[1]["type"] == "typing"
        assert events[1]["is_typing"] is True
        print("  ✅ Typing indicator sent")

        # Response 2: typing off
        assert events[2]["type"] == "typing"
        assert events[2]["is_typing"] is False
        print("  ✅ Typing stopped")

        # Response 3: agent reply
        assert events[3]["type"] == "message"
        assert events[3]["role"] == "agent"
        assert "Hello" in events[3]["text"]
        print(f"  ✅ Agent reply received: \"{events[3]['text']}\"")

        # 3. Verify history now has 2 messages (via session)
        resp = urllib.request.urlopen(f"{BASE}/chat/history?session={sess_id}&limit=10")
        data = json.loads(resp.read())
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "agent"
        print("  ✅ History updated with 2 messages")

        print("\n  ✅ All WebSocket tests passed")


async def main():
    test_rest()
    await test_ws()
    print("\n✅✅✅ ALL TESTS PASSED ✅✅✅")


if __name__ == "__main__":
    asyncio.run(main())
